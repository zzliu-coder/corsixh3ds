#!/usr/bin/env python3
"""Build deterministic source and VM-evidence archives."""
from __future__ import annotations

import argparse
import hashlib
import os
import stat
import zipfile
from pathlib import Path
from typing import Iterable, Sequence


EXCLUDED_PARTS = {
    ".git",
    ".idea",
    ".vscode",
    "dist",
    "external",
    "local-devkitpro",
    "local-portlibs",
    "pacman-cache",
    "work",
    "__pycache__",
}
EXCLUDED_PREFIXES = ("build-",)
# A fixed date safely in the past keeps archives reproducible without making
# extracted sources newer than the build system clock, which would cause CMake
# to rebuild build.ninja indefinitely. ZIP timestamps cannot represent dates
# before 1980.
FIXED_TIME = (2020, 1, 1, 0, 0, 0)


def is_excluded(relative: Path) -> bool:
    return any(
        part in EXCLUDED_PARTS or part.startswith(EXCLUDED_PREFIXES)
        for part in relative.parts
    )


def source_files(root: Path) -> Iterable[Path]:
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative = path.relative_to(root)
        if is_excluded(relative) or relative.parts[:2] == ("artifacts", "verification"):
            continue
        yield path


def evidence_files(root: Path) -> Iterable[Path]:
    candidates = [root / "artifacts" / "verification", root / "artifacts" / "preview"]
    for directory in candidates:
        if directory.is_dir():
            yield from sorted(path for path in directory.rglob("*") if path.is_file())
    for relative in ("README.md", "docs/VM_VERIFICATION.md", "docs/HARDWARE_TEST_PLAN.md"):
        path = root / relative
        if path.is_file():
            yield path


def write_zip(output: Path, root: Path, prefix: str, files: Iterable[Path]) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for path in files:
            relative = path.relative_to(root).as_posix()
            info = zipfile.ZipInfo(f"{prefix}/{relative}", FIXED_TIME)
            mode = path.stat().st_mode
            permissions = 0o755 if mode & stat.S_IXUSR else 0o644
            info.external_attr = (permissions & 0xFFFF) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = args.root.resolve()
    output = args.output.resolve()
    version = (root / "VERSION").read_text(encoding="utf-8").strip()
    if not version:
        raise SystemExit("VERSION is empty")
    stem = f"corsixth-3ds-old3ds-v{version}"
    source = output / f"{stem}-source.zip"
    evidence = output / f"{stem}-vm-evidence.zip"
    write_zip(source, root, stem, source_files(root))
    write_zip(evidence, root, f"{stem}-vm-evidence", evidence_files(root))
    checksums = output / "SHA256SUMS.txt"
    checksums.write_text(
        "".join(f"{sha256(path)}  {path.name}\n" for path in (source, evidence)),
        encoding="utf-8",
    )
    for path in (source, evidence, checksums):
        print(f"{path} ({path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
