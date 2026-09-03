"""Build the authoritative deterministic TH3DSR1 package family."""

from __future__ import annotations

import dataclasses
import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Iterable

try:
    from th3ds_assets import build_glyph_atlas, build_language_bundle, build_language_pack, convert_fullscreen_image
    from th3ds_container import (
        AUDIO_ALIGNMENT, PIN_ON_MOUNT, REQUIRED, STREAMABLE, ResourceInput,
        build_bundle_manifest, build_package, inspect_bundle, inspect_package,
        resource_id, source_set_digest,
    )
    from th3ds_resource import ResourceError, atomic_directory, read_stable, safe_relative
    from th3ds_sound import SoundEncoder, build_sound_pack
    from th3ds_sprite import build_sprite_pack
except ModuleNotFoundError:
    from .th3ds_assets import build_glyph_atlas, build_language_bundle, build_language_pack, convert_fullscreen_image
    from .th3ds_container import (
        AUDIO_ALIGNMENT, PIN_ON_MOUNT, REQUIRED, STREAMABLE, ResourceInput,
        build_bundle_manifest, build_package, inspect_bundle, inspect_package,
        resource_id, source_set_digest,
    )
    from .th3ds_resource import ResourceError, atomic_directory, read_stable, safe_relative
    from .th3ds_sound import SoundEncoder, build_sound_pack
    from .th3ds_sprite import build_sprite_pack


@dataclasses.dataclass(frozen=True)
class ImageSpec:
    pixels: str
    palette: str
    pixel_format: str = "rgb565"
    palette_bits: int = 6
    transparent_index: int | None = None


@dataclasses.dataclass(frozen=True)
class Budgets:
    max_output_bytes: int = 256 * 1024 * 1024
    audio_bytes: int = 3 * 1024 * 1024
    sprite_bytes: int = 8 * 1024 * 1024
    texture_bytes: int = 6 * 1024 * 1024
    language_font_bytes: int = 3 * 1024 * 1024
    metadata_bytes: int = 1024 * 1024
    scratch_bytes: int = 1024 * 1024

    def manifest(self) -> dict[str, int]:
        return {
            "audio_bytes": self.audio_bytes,
            "language_font_bytes": self.language_font_bytes,
            "metadata_bytes": self.metadata_bytes,
            "scratch_bytes": self.scratch_bytes,
            "sprite_bytes": self.sprite_bytes,
            "texture_bytes": self.texture_bytes,
        }


def _children(directory: Path) -> dict[str, Path]:
    result: dict[str, Path] = {}
    for child in directory.iterdir():
        key = child.name.casefold()
        if key in result:
            raise ResourceError(f"case-insensitive collision in {directory}: {child.name}")
        result[key] = child
    return result


def find_input(root: Path, relative: str) -> Path:
    current = root
    for part in safe_relative(relative).split("/"):
        if not current.is_dir():
            raise ResourceError(f"input path is missing: {relative}")
        match = _children(current).get(part.casefold())
        if match is None:
            raise ResourceError(f"input path is missing: {relative}")
        current = match
    if not current.is_file() or current.is_symlink():
        raise ResourceError(f"input must be a regular non-symlink file: {relative}")
    return current


def discover_sprite_pairs(source: Path) -> list[tuple[str, Path, Path]]:
    pairs: list[tuple[str, Path, Path]] = []
    for root_name in ("DATA", "QDATA"):
        directory = _children(source).get(root_name.casefold()) if source.is_dir() else None
        if directory is None or not directory.is_dir():
            continue
        for tab in sorted(directory.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not tab.is_file() or tab.is_symlink() or tab.suffix.casefold() != ".tab":
                continue
            siblings = _children(tab.parent)
            dat = siblings.get((tab.stem + ".dat").casefold())
            if dat is None or not dat.is_file() or dat.is_symlink():
                continue
            relative = tab.relative_to(source).with_suffix("").as_posix()
            pairs.append((relative, tab, dat))
    return pairs


def discover_images(source: Path) -> list[ImageSpec]:
    specs: list[ImageSpec] = []
    for root_name in ("DATA", "QDATA"):
        directory = _children(source).get(root_name.casefold()) if source.is_dir() else None
        if directory is None or not directory.is_dir():
            continue
        for dat in sorted(directory.rglob("*"), key=lambda item: item.as_posix().casefold()):
            if not dat.is_file() or dat.is_symlink() or dat.suffix.casefold() != ".dat":
                continue
            if dat.stat().st_size != 640 * 480:
                continue
            palette = _children(dat.parent).get((dat.stem + ".pal").casefold())
            if palette is None or not palette.is_file() or palette.is_symlink():
                continue
            specs.append(ImageSpec(dat.relative_to(source).as_posix(), palette.relative_to(source).as_posix()))
    return specs


def _source_records(root: Path, prefix: str) -> list[tuple[str, bytes]]:
    records: list[tuple[str, bytes]] = []
    folded: set[str] = set()
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix().encode("utf-8")):
        if path.is_symlink():
            raise ResourceError(f"source-set input may not be a symlink: {path}")
        if not path.is_file():
            continue
        relative = safe_relative(PurePosixPath(prefix) / PurePosixPath(path.relative_to(root).as_posix()))
        key = relative.casefold()
        if key in folded:
            raise ResourceError(f"case-insensitive source-set collision: {relative}")
        folded.add(key)
        records.append((relative, read_stable(path)))
    return records


def _toolchain_git() -> str:
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(["git", "rev-parse", "HEAD"], cwd=root, text=True, capture_output=True, check=False)
    value = result.stdout.strip()
    return value if result.returncode == 0 and len(value) == 40 else "0" * 40


def _write_verified(path: Path, data: bytes, *, package: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    with path.open("rb") as handle:
        os.fsync(handle.fileno())
    reread = path.read_bytes()
    if reread != data:
        raise ResourceError(f"atomic staging readback differs: {path.name}")
    (inspect_package if package else inspect_bundle)(reread)


def _group(
    group_id: int, name: str, resources: Iterable[ResourceInput], *,
    required: bool, decoded_ceiling_bytes: int | None = None,
) -> dict[str, object]:
    values = list(resources)
    return {
        "decoded_ceiling_bytes": decoded_ceiling_bytes if decoded_ceiling_bytes is not None else sum(item.decoded_size for item in values),
        "id": group_id,
        "name": name,
        "required": required,
        "resource_ids": sorted(resource_id(item.kind, item.logical_name).hex() for item in values),
    }


def _check_budgets(
    budgets: Budgets, *, sound_entries: Iterable[dict[str, object]],
    sprite_entries: Iterable[dict[str, object]], images: Iterable[bytes], language_font_bytes: int,
) -> dict[str, object]:
    checks: list[tuple[str, int, int]] = []
    for item in sound_entries:
        checks.append((f"audio:{item['name']}", int(item["decoded_size"]), budgets.audio_bytes))
    for item in sprite_entries:
        checks.append((f"sprite:{item['index']}", int(item["decoded_size"]), budgets.sprite_bytes))
        checks.append((f"scratch:sprite:{item['index']}", int(item["decoded_size"]) + int(item["source_size"]), budgets.scratch_bytes))
    for index, data in enumerate(images):
        checks.append((f"texture:{index}", len(data), budgets.texture_bytes))
    checks.append(("language_font", language_font_bytes, budgets.language_font_bytes))
    failures = [f"{name} {actual} > {limit}" for name, actual, limit in checks if actual > limit]
    if failures:
        raise ResourceError("resource budget exceeded: " + "; ".join(failures))
    return {"checks": [{"actual": a, "limit": limit, "name": name, "pass": a <= limit} for name, a, limit in checks], "pass": True}


def build_resource_tree(
    source: Path, output: Path, *, language_dir: Path, selected_language: str = "English",
    image_specs: Iterable[ImageSpec] | None = None, glyph_atlases: Iterable[Path] = (),
    budgets: Budgets = Budgets(), sound_encoder: SoundEncoder | None = None,
) -> dict[str, object]:
    source = source.expanduser().resolve()
    output = output.expanduser().resolve()
    language_dir = language_dir.expanduser().resolve()
    if not source.is_dir():
        raise ResourceError(f"Theme Hospital directory does not exist: {source}")
    source_children = _children(source)
    missing_roots = [name for name in ("DATA", "LEVELS", "QDATA", "SOUND") if name.casefold() not in source_children or not source_children[name.casefold()].is_dir()]
    if missing_roots:
        raise ResourceError("source does not look like a Theme Hospital directory; missing: " + ", ".join(missing_roots))
    try:
        output.relative_to(source)
    except ValueError:
        pass
    else:
        raise ResourceError("output may not be inside the input tree")
    if any(value < 0 for value in dataclasses.asdict(budgets).values()):
        raise ResourceError("resource budgets must be non-negative")

    glyph_paths = sorted((path.expanduser().resolve() for path in glyph_atlases), key=lambda item: item.as_posix())
    source_records = _source_records(source, "game") + _source_records(language_dir, "corsixth/languages")
    for index, metadata_path in enumerate(glyph_paths):
        metadata_bytes = read_stable(metadata_path)
        try:
            image_name = json.loads(metadata_bytes.decode("utf-8"))["image"]
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError) as exc:
            raise ResourceError(f"invalid glyph atlas metadata {metadata_path}") from exc
        source_records.append((f"glyph-input/{index}/{metadata_path.name}", metadata_bytes))
        source_records.append((f"glyph-input/{index}/{Path(image_name).name}", read_stable(metadata_path.parent / image_name)))
    source_hash, source_count, source_bytes = source_set_digest(source_records)

    sound = build_sound_pack(find_input(source, "SOUND/DATA/SOUND-0.DAT"), encoder=sound_encoder)
    core_resources: list[ResourceInput] = [ResourceInput(
        "audio/sound-0", "AUDIO_BANK", sound.data, sound.decoded_size,
        {"cache_pool": "audio", "entry_count": len(sound.entries), "payload_format": "TH3DSND1"},
        group_id=2, flags=REQUIRED | STREAMABLE, alignment=AUDIO_ALIGNMENT,
        decoded_sha256=sound.decoded_sha256,
    )]
    all_sprite_entries: list[dict[str, object]] = []
    for name, tab, dat in discover_sprite_pairs(source):
        sprite = build_sprite_pack(tab, dat)
        all_sprite_entries.extend(sprite.entries)
        core_resources.append(ResourceInput(
            f"sprites/{safe_relative(name).lower()}", "SPRITE_SHEET", sprite.data, sprite.decoded_size,
            {"cache_pool": "sprite", "payload_format": "TH3DSP1", "pixel_bytes": sprite.pixel_bytes, "sprite_count": len(sprite.entries)},
            group_id=3, flags=REQUIRED | STREAMABLE, decoded_sha256=sprite.decoded_sha256,
        ))

    chosen_images = list(discover_images(source) if image_specs is None else image_specs)
    image_outputs: list[bytes] = []
    for spec in sorted(chosen_images, key=lambda item: item.pixels.casefold()):
        image = convert_fullscreen_image(find_input(source, spec.pixels), find_input(source, spec.palette), pixel_format=spec.pixel_format, palette_bits=spec.palette_bits, transparent_index=spec.transparent_index)
        image_outputs.append(image)
        stem = PurePosixPath(safe_relative(spec.pixels)).with_suffix("").as_posix().lower()
        core_resources.append(ResourceInput(
            f"ui/{stem}", "UI_BITMAP", image, len(image),
            {"height": 240, "pixel_format": spec.pixel_format.upper(), "stride": 640, "width": 320},
            group_id=1, flags=REQUIRED | PIN_ON_MOUNT,
        ))

    language = build_language_bundle(language_dir, selected_language, source)
    language_payload = build_language_pack(language)
    language_resources: list[ResourceInput] = [ResourceInput(
        f"language/{language.tag}/closure", "LANGUAGE_BUNDLE", language_payload.data, language_payload.decoded_size,
        {"cache_pool": "language_font", "entry_count": len(language.files), "original_string_ids": list(language.original_ids), "payload_format": "TH3DSLG1", "selected": language.selected, "tag": language.tag},
        group_id=1, flags=REQUIRED | PIN_ON_MOUNT, decoded_sha256=language_payload.decoded_sha256,
    )]
    glyph_bytes = 0
    if len(glyph_paths) > 16:
        raise ResourceError("a language package may contain at most 16 glyph atlas pages")
    for metadata_path in glyph_paths:
        name, mapping, image = build_glyph_atlas(metadata_path)
        atlas_name = f"font/{language.tag}/{safe_relative(name).lower()}/atlas"
        map_name = f"font/{language.tag}/{safe_relative(name).lower()}/map"
        atlas_id = resource_id("FONT_ATLAS", atlas_name)
        language_resources.append(ResourceInput(atlas_name, "FONT_ATLAS", image, len(image), {"height": 256, "pixel_format": "RGBA5551", "width": 256}, group_id=1, flags=REQUIRED | PIN_ON_MOUNT))
        language_resources.append(ResourceInput(map_name, "FONT_MAP", mapping, len(mapping), {"atlas_resource_id": atlas_id.hex(), "encoding": "canonical-json-v1"}, group_id=1, flags=REQUIRED | PIN_ON_MOUNT, dependencies=(atlas_id,)))
        glyph_bytes += len(image) + len(mapping)

    budget_result = _check_budgets(budgets, sound_entries=sound.entries, sprite_entries=all_sprite_entries, images=image_outputs, language_font_bytes=language_payload.decoded_size + glyph_bytes)
    toolchain = {"font_input": "pre-rasterized", "packer_contract": 1, "packer_git": _toolchain_git(), "python": "3", "sprite_compression": "zlib-level-9"}
    core = build_package(
        role="core", name="core", source_set_sha256=source_hash, source_file_count=source_count,
        source_total_bytes=source_bytes, resources=core_resources,
        groups=[_group(1, "boot-menu", (i for i in core_resources if i.group_id == 1), required=True, decoded_ceiling_bytes=budgets.texture_bytes), _group(2, "audio-common", (i for i in core_resources if i.group_id == 2), required=True, decoded_ceiling_bytes=budgets.audio_bytes), _group(3, "sprite-common", (i for i in core_resources if i.group_id == 3), required=True, decoded_ceiling_bytes=budgets.sprite_bytes)],
        budgets=budgets.manifest(), toolchain=toolchain,
    )
    language_package = build_package(
        role="language", name=language.tag, source_set_sha256=source_hash, source_file_count=source_count,
        source_total_bytes=source_bytes, resources=language_resources,
        groups=[_group(1, "selected-language", language_resources, required=True, decoded_ceiling_bytes=budgets.language_font_bytes)], budgets=budgets.manifest(),
        toolchain=toolchain, language={"atlas_pages": len(glyph_paths), "inheritance_mode": "static-selected-closure", "selected": language.selected, "tag": language.tag},
        dependencies=[{"container_sha256": core.container_sha256, "package_id": core.package_id}],
    )
    bundle, bundle_hash = build_bundle_manifest(source_set_sha256=source_hash, selected_language=language.tag, packages=(("core.th3ds", core), (f"lang/{language.tag}.th3ds", language_package)))
    total_output = len(bundle) + len(core.data) + len(language_package.data)
    if total_output > budgets.max_output_bytes:
        raise ResourceError(f"resource budget exceeded: output {total_output} > {budgets.max_output_bytes}")
    for package in (core, language_package):
        metadata_size = int.from_bytes(package.data[0x48:0x50], "little")
        if metadata_size > budgets.metadata_bytes:
            raise ResourceError(f"resource budget exceeded: metadata {metadata_size} > {budgets.metadata_bytes}")

    def produce(root: Path) -> dict[str, object]:
        _write_verified(root / "core.th3ds", core.data, package=True)
        _write_verified(root / "lang" / f"{language.tag}.th3ds", language_package.data, package=True)
        _write_verified(root / "bundle.th3ds.json", bundle, package=False)
        return {
            "budget": budget_result, "bundle_sha256": bundle_hash,
            "format": {"major": 1, "minor": 0, "name": "TH3DSR1"},
            "packages": [{"container_sha256": core.container_sha256, "path": "core.th3ds"}, {"container_sha256": language_package.container_sha256, "path": f"lang/{language.tag}.th3ds"}],
            "resource_count": len(core.resources) + len(language_package.resources),
            "source_set_sha256": source_hash,
        }
    return atomic_directory(output, produce)  # type: ignore[return-value]
