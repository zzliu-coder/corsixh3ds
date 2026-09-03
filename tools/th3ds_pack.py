#!/usr/bin/env python3
"""Theme Hospital validator plus TH3DSR1 converter and legacy audit archive.

This tool never downloads or redistributes the original game. It consumes a
user-owned Theme Hospital installation and writes a local SD-card staging tree.
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import shutil
import struct
import sys
import tempfile
import zlib
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Iterator, Sequence

try:
    from th3ds_convert import Budgets, ImageSpec, build_resource_tree
    from th3ds_resource import ResourceError
except ModuleNotFoundError:  # Support `import tools.th3ds_pack` from the repository root.
    from .th3ds_convert import Budgets, ImageSpec, build_resource_tree
    from .th3ds_resource import ResourceError

MAGIC = b"CTH3DPK1"
VERSION = 1
HEADER = struct.Struct("<8sIIQQQ")
ENTRY = struct.Struct("<HHIQQ")
MAX_FILES = 200_000
MAX_PATH_BYTES = 4096
REQUIRED_DIRECTORIES = ("DATA", "LEVELS", "QDATA", "SOUND")
# User saves are mutable state and never belong in a package assembled from
# original game media. Keeping SAVE out also prevents a local diagnostic build
# from copying a player's state into distributable package evidence.
OPTIONAL_DIRECTORIES = ("ANIMS", "MUSIC", "INTRO")
SKIPPED_NAMES = {"thumbs.db", ".ds_store"}


class PackError(RuntimeError):
    """Raised for invalid source trees or pack files."""


@dataclasses.dataclass(frozen=True)
class SourceFile:
    relative_path: str
    source_path: Path
    size: int
    sha256: str


@dataclasses.dataclass(frozen=True)
class PackEntry:
    path: str
    flags: int
    checksum: int
    offset: int
    size: int


def _casefold_children(directory: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for child in directory.iterdir():
        key = child.name.casefold()
        if key in result:
            raise PackError(
                f"case-insensitive name collision in {directory}: "
                f"{result[key].name!r} and {child.name!r}"
            )
        result[key] = child
    return result


def _find_directory(source: Path, name: str) -> Path | None:
    candidate = _casefold_children(source).get(name.casefold())
    return candidate if candidate is not None and candidate.is_dir() else None


def _normalize_relative(path: Path | PurePosixPath | str) -> str:
    text = PurePosixPath(str(path).replace("\\", "/")).as_posix()
    while text.startswith("./"):
        text = text[2:]
    if not text or text.startswith("/") or ".." in PurePosixPath(text).parts:
        raise PackError(f"unsafe relative path: {path!s}")
    encoded = text.encode("utf-8")
    if len(encoded) > MAX_PATH_BYTES:
        raise PackError(f"path is too long for the pack format: {text}")
    return text


def validate_source(source: Path) -> dict[str, Path]:
    source = source.expanduser().resolve()
    if not source.is_dir():
        raise PackError(f"source directory does not exist: {source}")
    found: dict[str, Path] = {}
    missing: list[str] = []
    for name in REQUIRED_DIRECTORIES:
        directory = _find_directory(source, name)
        if directory is None:
            missing.append(name)
        else:
            found[name] = directory
    if missing:
        raise PackError(
            "source does not look like a Theme Hospital data directory; "
            f"missing: {', '.join(missing)}"
        )
    for name in OPTIONAL_DIRECTORIES:
        directory = _find_directory(source, name)
        if directory is not None:
            found[name] = directory
    for name in REQUIRED_DIRECTORIES:
        try:
            next(path for path in found[name].rglob("*") if path.is_file())
        except StopIteration as exc:
            raise PackError(f"required directory is empty: {found[name]}") from exc
    return found


def _sha256_file(path: Path, block_size: int = 1024 * 1024) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(block_size)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def collect_files(source: Path) -> list[SourceFile]:
    directories = validate_source(source)
    result: list[SourceFile] = []
    casefolded: dict[str, str] = {}
    for canonical_name in (*REQUIRED_DIRECTORIES, *OPTIONAL_DIRECTORIES):
        directory = directories.get(canonical_name)
        if directory is None:
            continue
        for path in sorted(directory.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if path.is_symlink():
                raise PackError(f"symbolic links are not accepted: {path}")
            if not path.is_file() or path.name.casefold() in SKIPPED_NAMES:
                continue
            relative_inside = path.relative_to(directory)
            relative = _normalize_relative(PurePosixPath(canonical_name) / PurePosixPath(relative_inside.as_posix()))
            folded = relative.casefold()
            previous = casefolded.get(folded)
            if previous is not None:
                raise PackError(
                    "case-insensitive path collision for FAT/SD storage: "
                    f"{previous!r} and {relative!r}"
                )
            casefolded[folded] = relative
            stat = path.stat()
            result.append(
                SourceFile(
                    relative_path=relative,
                    source_path=path,
                    size=stat.st_size,
                    sha256=_sha256_file(path),
                )
            )
    result.sort(key=lambda item: item.relative_path)
    if len(result) > MAX_FILES:
        raise PackError(f"too many files: {len(result)} > {MAX_FILES}")
    return result


def _index_size(files: Sequence[SourceFile]) -> int:
    return sum(ENTRY.size + len(item.relative_path.encode("utf-8")) for item in files)


def build_pack(files: Sequence[SourceFile], output: Path) -> list[PackEntry]:
    files = sorted(files, key=lambda item: item.relative_path)
    output = output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    index_offset = HEADER.size
    data_offset = index_offset + _index_size(files)
    cursor = data_offset
    entries: list[PackEntry] = []
    for item in files:
        checksum = 0
        with item.source_path.open("rb") as handle:
            while True:
                block = handle.read(1024 * 1024)
                if not block:
                    break
                checksum = zlib.crc32(block, checksum)
        entries.append(
            PackEntry(
                path=item.relative_path,
                flags=0,
                checksum=checksum & 0xFFFFFFFF,
                offset=cursor,
                size=item.size,
            )
        )
        cursor += item.size

    temporary = output.with_suffix(output.suffix + ".tmp")
    try:
        with temporary.open("wb") as handle:
            handle.write(
                HEADER.pack(
                    MAGIC,
                    VERSION,
                    len(entries),
                    index_offset,
                    data_offset,
                    0,
                )
            )
            for entry in entries:
                path_bytes = entry.path.encode("utf-8")
                handle.write(
                    ENTRY.pack(
                        len(path_bytes),
                        entry.flags,
                        entry.checksum,
                        entry.offset,
                        entry.size,
                    )
                )
                handle.write(path_bytes)
            for source_file in files:
                with source_file.source_path.open("rb") as source_handle:
                    shutil.copyfileobj(source_handle, handle, 1024 * 1024)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, output)
    finally:
        temporary.unlink(missing_ok=True)
    return entries


def inspect_pack(path: Path, verify: bool = False) -> list[PackEntry]:
    path = path.expanduser().resolve()
    size = path.stat().st_size
    with path.open("rb") as handle:
        header_data = handle.read(HEADER.size)
        if len(header_data) != HEADER.size:
            raise PackError("truncated pack header")
        magic, version, count, index_offset, data_offset, _reserved = HEADER.unpack(header_data)
        if magic != MAGIC or version != VERSION:
            raise PackError("unsupported pack format")
        if count > MAX_FILES or index_offset < HEADER.size or not index_offset <= data_offset <= size:
            raise PackError("invalid pack header values")
        handle.seek(index_offset)
        entries: list[PackEntry] = []
        seen: set[str] = set()
        for _index in range(count):
            raw = handle.read(ENTRY.size)
            if len(raw) != ENTRY.size:
                raise PackError("truncated pack index")
            path_length, flags, checksum, offset, file_size = ENTRY.unpack(raw)
            if path_length == 0 or path_length > MAX_PATH_BYTES:
                raise PackError("invalid packed path length")
            path_bytes = handle.read(path_length)
            if len(path_bytes) != path_length:
                raise PackError("truncated packed path")
            try:
                relative = _normalize_relative(path_bytes.decode("utf-8"))
            except UnicodeDecodeError as exc:
                raise PackError("packed path is not valid UTF-8") from exc
            if relative in seen:
                raise PackError(f"duplicate packed path: {relative}")
            seen.add(relative)
            if offset < data_offset or offset > size or file_size > size - offset:
                raise PackError(f"packed file is out of bounds: {relative}")
            entries.append(PackEntry(relative, flags, checksum, offset, file_size))
        if verify:
            for entry in entries:
                handle.seek(entry.offset)
                remaining = entry.size
                checksum = 0
                while remaining:
                    block = handle.read(min(remaining, 1024 * 1024))
                    if not block:
                        raise PackError(f"truncated packed file: {entry.path}")
                    checksum = zlib.crc32(block, checksum)
                    remaining -= len(block)
                if (checksum & 0xFFFFFFFF) != entry.checksum:
                    raise PackError(f"checksum mismatch: {entry.path}")
        return entries


def _copy_file_atomic(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".tmp")
    try:
        with source.open("rb") as src, temporary.open("wb") as dst:
            shutil.copyfileobj(src, dst, 1024 * 1024)
            dst.flush()
            os.fsync(dst.fileno())
        os.replace(temporary, destination)
    finally:
        temporary.unlink(missing_ok=True)


def stage_sd_tree(
    source: Path,
    output: Path,
    *,
    include_pack: bool = True,
    copy_files: bool = True,
) -> dict[str, object]:
    files = collect_files(source)
    root = output.expanduser().resolve() / "3ds" / "corsixth"
    game_root = root / "game"
    root.mkdir(parents=True, exist_ok=True)
    if copy_files:
        for item in files:
            _copy_file_atomic(item.source_path, game_root / PurePosixPath(item.relative_path))
    entries: list[PackEntry] = []
    if include_pack:
        entries = build_pack(files, root / "theme-hospital.thp")
    config = root / "config.txt"
    if not config.exists():
        config.write_text(
            'theme_hospital_install = "sdmc:/3ds/corsixth/game"\n'
            'width = 640\nheight = 480\nfullscreen = true\n'
            'play_intro = false\nplay_demo = false\ntrack_fps = false\n'
            'ui_scale = 1\ndirect_zoom = false\nscrolling_momentum = false\n'
            'audio = true\nnew_graphics_folder = ""\n',
            encoding="utf-8",
        )
    manifest: dict[str, object] = {
        "format": 1,
        "source": str(source.expanduser().resolve()),
        "file_count": len(files),
        "total_bytes": sum(item.size for item in files),
        "pack_file": "theme-hospital.thp" if include_pack else None,
        "pack_entries": len(entries),
        "runtime_data_path": "game",
        "pack_runtime_mounted": False,
        "pack_purpose": "deterministic audit/archive; runtime reads the loose game tree",
        "files": [
            {
                "path": item.relative_path,
                "size": item.size,
                "sha256": item.sha256,
            }
            for item in files
        ],
    }
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return manifest


def _print_summary(files: Sequence[SourceFile]) -> None:
    print(f"Validated {len(files)} files, {sum(item.size for item in files):,} bytes")
    roots: dict[str, int] = {}
    for item in files:
        root = item.relative_path.split("/", 1)[0]
        roots[root] = roots.get(root, 0) + 1
    for name in sorted(roots):
        print(f"  {name}: {roots[name]} files")


def _parse_image_spec(value: str) -> ImageSpec:
    """Parse PIXELS,PALETTE[,FORMAT[,PALETTE_BITS[,TRANSPARENT_INDEX]]]."""

    parts = [part.strip() for part in value.split(",")]
    if len(parts) < 2 or len(parts) > 5 or not parts[0] or not parts[1]:
        raise argparse.ArgumentTypeError(
            "image spec must be PIXELS,PALETTE[,rgb565|rgba5551[,6|8[,transparent-index]]]"
        )
    try:
        return ImageSpec(
            pixels=parts[0],
            palette=parts[1],
            pixel_format=parts[2] if len(parts) >= 3 and parts[2] else "rgb565",
            palette_bits=int(parts[3]) if len(parts) >= 4 and parts[3] else 6,
            transparent_index=int(parts[4]) if len(parts) >= 5 and parts[4] else None,
        )
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"invalid numeric image option: {exc}") from exc


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate = subparsers.add_parser("validate", help="validate a Theme Hospital data directory")
    validate.add_argument("source", type=Path)

    pack = subparsers.add_parser("pack", help="build a legacy CTH3DPK1 audit-only .thp archive")
    pack.add_argument("source", type=Path)
    pack.add_argument("output", type=Path)

    inspect = subparsers.add_parser("inspect", help="inspect a legacy CTH3DPK1 audit archive")
    inspect.add_argument("pack", type=Path)
    inspect.add_argument("--verify", action="store_true")

    stage = subparsers.add_parser("stage", help="create an SD-card staging tree")
    stage.add_argument("source", type=Path)
    stage.add_argument("output", type=Path)
    stage.add_argument("--no-pack", action="store_true")
    stage.add_argument("--manifest-only", action="store_true")

    convert = subparsers.add_parser(
        "convert", help="build the authoritative deterministic TH3DSR1 package family"
    )
    convert.add_argument("source", type=Path)
    convert.add_argument("output", type=Path)
    convert.add_argument("--language-dir", type=Path, required=True)
    convert.add_argument("--language", default="English")
    convert.add_argument(
        "--image",
        action="append",
        type=_parse_image_spec,
        help="PIXELS,PALETTE[,FORMAT[,PALETTE_BITS[,TRANSPARENT_INDEX]]]; repeatable; default auto-discovers exact 640x480 same-stem pairs",
    )
    convert.add_argument("--glyph-atlas", action="append", type=Path, default=[])
    convert.add_argument("--max-output-bytes", type=int, default=Budgets.max_output_bytes)
    convert.add_argument("--audio-bytes", type=int, default=Budgets.audio_bytes)
    convert.add_argument("--sprite-bytes", type=int, default=Budgets.sprite_bytes)
    convert.add_argument("--texture-bytes", type=int, default=Budgets.texture_bytes)
    convert.add_argument("--language-font-bytes", type=int, default=Budgets.language_font_bytes)
    convert.add_argument("--metadata-bytes", type=int, default=Budgets.metadata_bytes)
    convert.add_argument("--scratch-bytes", type=int, default=Budgets.scratch_bytes)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        if args.command == "validate":
            files = collect_files(args.source)
            _print_summary(files)
        elif args.command == "pack":
            files = collect_files(args.source)
            build_pack(files, args.output)
            inspect_pack(args.output, verify=True)
            _print_summary(files)
            print(f"Wrote {args.output}")
        elif args.command == "inspect":
            entries = inspect_pack(args.pack, verify=args.verify)
            print(f"{len(entries)} files")
            for entry in entries[:20]:
                print(f"  {entry.size:10d}  {entry.path}")
            if len(entries) > 20:
                print(f"  ... {len(entries) - 20} more")
        elif args.command == "stage":
            manifest = stage_sd_tree(
                args.source,
                args.output,
                include_pack=not args.no_pack,
                copy_files=not args.manifest_only,
            )
            print(
                f"Staged {manifest['file_count']} files / "
                f"{manifest['total_bytes']:,} bytes under "
                f"{args.output / '3ds' / 'corsixth'}"
            )
        elif args.command == "convert":
            if min(
                args.max_output_bytes,
                args.audio_bytes,
                args.sprite_bytes,
                args.texture_bytes,
                args.language_font_bytes,
                args.metadata_bytes,
                args.scratch_bytes,
            ) < 0:
                raise PackError("resource budgets must be non-negative")
            manifest = build_resource_tree(
                args.source,
                args.output,
                language_dir=args.language_dir,
                selected_language=args.language,
                image_specs=args.image,
                glyph_atlases=args.glyph_atlas,
                budgets=Budgets(
                    max_output_bytes=args.max_output_bytes,
                    audio_bytes=args.audio_bytes,
                    sprite_bytes=args.sprite_bytes,
                    texture_bytes=args.texture_bytes,
                    language_font_bytes=args.language_font_bytes,
                    metadata_bytes=args.metadata_bytes,
                    scratch_bytes=args.scratch_bytes,
                ),
            )
            print(
                f"Converted {manifest['resource_count']} resources to {args.output}; "
                f"bundle sha256 {manifest['bundle_sha256']}"
            )
        else:  # pragma: no cover - argparse guarantees a command
            parser.error("unknown command")
    except (OSError, PackError, ResourceError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
