#!/usr/bin/env python3
"""Create and validate the fail-closed CorsixTH Old 3DS boot contract.

The validator only accepts a complete, hash-bound SD application directory. A
TH3DS tree is product-candidate eligible; a loose tree is an explicitly
diagnostic baseline and can never become product ready through this contract.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import stat
import struct
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Mapping, Sequence

try:
    from th3ds_container import inspect_bundle, inspect_package
    from th3ds_resource import ResourceError
except ModuleNotFoundError:  # Support imports from the repository root.
    from .th3ds_container import inspect_bundle, inspect_package
    from .th3ds_resource import ResourceError


ROOT_URI = "sdmc:/3ds/corsixth"
CONTRACT_SCHEMA = "corsixth-old3ds-boot-contract-v1"
CONTRACT_NAME = "boot-contract.json"
MANIFEST_NAME = "sd-manifest.json"
ENTRYPOINT = "CorsixTH-3DS.3dsx"
HEX_40 = re.compile(r"^[0-9a-f]{40}$")
HEX_64 = re.compile(r"^[0-9a-f]{64}$")
COMMON_REQUIRED_FILES = (
    ENTRYPOINT,
    "CorsixTH.lua",
    "config.txt",
    "cth3ds-overlay-version.txt",
)
COMMON_REQUIRED_DIRECTORIES = ("Bitmap", "Campaigns", "Graphics", "Levels", "Lua")
USER_DATA_ROOTS = ("save", "saves", "screenshots")
TH3DS_FORBIDDEN = (
    "game",
    "manifest.json",
    "theme-hospital.thp",
    "HOSPITAL.EXE",
    "HOSP95.EXE",
    "HOSPITAL.CFG",
)
LOOSE_FORBIDDEN = ("resources", "game/SAVE", "game/save")


class ValidationError(RuntimeError):
    """Raised when an SD tree cannot satisfy the boot contract."""


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}


def _safe_relative(value: object) -> str:
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValidationError(f"invalid relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        raise ValidationError(f"unsafe relative path: {value!r}")
    canonical = path.as_posix()
    if canonical != value:
        raise ValidationError(f"non-canonical relative path: {value!r}")
    return canonical


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _regular_file(root: Path, relative: str, *, nonempty: bool = False) -> Path:
    path = root / PurePosixPath(relative)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValidationError(f"required file is missing: {relative}") from exc
    if not stat.S_ISREG(metadata.st_mode):
        raise ValidationError(f"path is not a regular file: {relative}")
    current = path.parent
    while current != root:
        if current.is_symlink():
            raise ValidationError(f"file traverses a symbolic link: {relative}")
        current = current.parent
    if nonempty and metadata.st_size <= 0:
        raise ValidationError(f"required file is empty: {relative}")
    return path


def _record(root: Path, relative: str, *, nonempty: bool = False) -> FileRecord:
    path = _regular_file(root, relative, nonempty=nonempty)
    return FileRecord(relative, path.stat().st_size, sha256_path(path))


def _load_json(path: Path, label: str) -> dict[str, object]:
    try:
        raw = path.read_text(encoding="utf-8")
        value = json.loads(raw)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValidationError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValidationError(f"{label} must be a JSON object")
    return value


def _load_records(value: object, label: str) -> dict[str, FileRecord]:
    if not isinstance(value, list) or not value:
        raise ValidationError(f"{label} must be a non-empty array")
    result: dict[str, FileRecord] = {}
    for raw in value:
        if not isinstance(raw, dict):
            raise ValidationError(f"{label} contains a non-object entry")
        relative = _safe_relative(raw.get("path"))
        size = raw.get("size")
        digest = raw.get("sha256")
        if (
            relative in result
            or not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
            or not isinstance(digest, str)
            or not HEX_64.fullmatch(digest)
        ):
            raise ValidationError(f"{label} contains an invalid entry for {relative}")
        result[relative] = FileRecord(relative, size, digest)
    return result


def _verify_record(root: Path, expected: FileRecord, *, nonempty: bool = False) -> None:
    actual = _record(root, expected.path, nonempty=nonempty)
    if actual.size != expected.size or actual.sha256 != expected.sha256:
        raise ValidationError(
            f"file identity mismatch: {expected.path}; "
            f"size={actual.size} sha256={actual.sha256}"
        )


def _validate_3dsx(path: Path) -> None:
    data = path.read_bytes()
    if len(data) < 0x20 or data[:4] != b"3DSX":
        raise ValidationError("entrypoint is not a 3DSX binary")
    header_size = struct.unpack_from("<H", data, 4)[0]
    relocation_header_size = struct.unpack_from("<H", data, 6)[0]
    if (
        header_size < 0x20
        or header_size > len(data)
        or header_size % 4
        or relocation_header_size < 4
        or relocation_header_size % 4
    ):
        raise ValidationError("entrypoint has an invalid 3DSX header")


def _validate_candidate(value: object) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValidationError("candidate identity must be an object")
    commit = value.get("commit")
    tree = value.get("tree")
    if not isinstance(commit, str) or not HEX_40.fullmatch(commit):
        raise ValidationError("candidate commit is invalid")
    if not isinstance(tree, str) or not HEX_40.fullmatch(tree):
        raise ValidationError("candidate tree is invalid")
    return {"commit": commit, "tree": tree}


def _require_populated_directory(root: Path, relative: str) -> None:
    path = root / PurePosixPath(relative)
    try:
        metadata = path.lstat()
    except OSError as exc:
        raise ValidationError(f"required directory is missing: {relative}") from exc
    if not stat.S_ISDIR(metadata.st_mode) or path.is_symlink():
        raise ValidationError(f"path is not a real directory: {relative}")
    if not any(child.is_file() and not child.is_symlink() for child in path.rglob("*")):
        raise ValidationError(f"required directory is empty: {relative}")


def _check_forbidden(root: Path, forbidden: Sequence[str], user_roots: Sequence[str]) -> None:
    for relative in (*forbidden, *user_roots):
        if (root / PurePosixPath(relative)).exists() or (root / PurePosixPath(relative)).is_symlink():
            raise ValidationError(f"forbidden package path exists: {relative}")


def _bundle_records(root: Path) -> tuple[FileRecord, list[FileRecord], Mapping[str, object]]:
    bundle_relative = "resources/bundle.th3ds.json"
    bundle_path = _regular_file(root, bundle_relative, nonempty=True)
    try:
        bundle = inspect_bundle(bundle_path.read_bytes())
    except (OSError, ResourceError) as exc:
        raise ValidationError(f"invalid TH3DS bundle: {exc}") from exc
    package_rows = bundle.get("packages")
    assert isinstance(package_rows, list)  # inspect_bundle enforces this.
    records: list[FileRecord] = []
    roles: list[str] = []
    declared_paths: set[str] = set()
    for raw in package_rows:
        assert isinstance(raw, dict)
        relative = _safe_relative(f"resources/{raw['path']}")
        path = _regular_file(root, relative, nonempty=True)
        package_bytes = path.read_bytes()
        try:
            package = inspect_package(package_bytes, verify=True)
        except ResourceError as exc:
            raise ValidationError(f"invalid TH3DS package {relative}: {exc}") from exc
        record = _record(root, relative, nonempty=True)
        package_manifest = package.get("manifest")
        package_identity = package_manifest.get("package") if isinstance(package_manifest, dict) else None
        if (
            record.size != raw["size"]
            or package_bytes[0xA8:0xC8].hex() != raw["container_sha256"]
            or not isinstance(package_identity, dict)
            or package_identity.get("id") != raw["package_id"]
            or package_identity.get("role") != raw["role"]
        ):
            raise ValidationError(f"TH3DS package does not match bundle: {relative}")
        records.append(record)
        roles.append(str(raw["role"]))
        declared_paths.add(relative)
    if roles.count("core") != 1 or "language" not in roles:
        raise ValidationError("TH3DS bundle must declare one core and at least one language package")
    selected = bundle.get("selected_language")
    if f"resources/lang/{selected}.th3ds" not in declared_paths:
        raise ValidationError("selected language package is not declared by the bundle")
    actual_packages = {
        path.relative_to(root).as_posix()
        for path in (root / "resources").rglob("*.th3ds")
        if path.is_file()
    }
    if actual_packages != declared_paths:
        raise ValidationError(
            "TH3DS package family mismatch; "
            f"missing={sorted(declared_paths - actual_packages)} "
            f"extra={sorted(actual_packages - declared_paths)}"
        )
    return _record(root, bundle_relative, nonempty=True), records, bundle


def _contract_required(root: Path, asset_mode: str) -> tuple[list[FileRecord], list[str], list[str]]:
    required_files = [_record(root, path, nonempty=True) for path in COMMON_REQUIRED_FILES]
    directories = list(COMMON_REQUIRED_DIRECTORIES)
    if asset_mode == "th3ds":
        bundle_record, package_records, _bundle = _bundle_records(root)
        required_files.extend([bundle_record, *package_records])
        directories.append("resources")
        forbidden = list(TH3DS_FORBIDDEN)
    elif asset_mode == "loose":
        directories.extend(f"game/{name}" for name in ("DATA", "LEVELS", "QDATA", "SOUND"))
        for name in ("Lua/languages/english.lua", "Lua/languages/original_strings.lua",
                     "game/DATA/LANG-0.DAT", "game/SOUND/DATA/SOUND-0.DAT", "loose-assets.json"):
            required_files.append(_record(root,name,nonempty=True))
        assets = json.loads((root/"loose-assets.json").read_text(encoding="utf-8"))
        if assets.get("language") != "English" or assets.get("device") != "NOT_PROVEN":
            raise ValidationError("loose assets require English and explicit device NOT_PROVEN")
        actual_languages={path.name for path in (root/"Lua/languages").glob("*.lua")}
        if actual_languages != {"english.lua","original_strings.lua"}:
            raise ValidationError("loose language closure must contain only English and original strings")
        forbidden = list(LOOSE_FORBIDDEN)
    else:
        raise ValidationError(f"unsupported asset mode: {asset_mode!r}")
    for relative in directories:
        _require_populated_directory(root, relative)
    _check_forbidden(root, forbidden, USER_DATA_ROOTS)
    return sorted(required_files, key=lambda row: row.path), directories, forbidden


def write_boot_contract(
    root: Path, *, asset_mode: str, candidate_commit: str, candidate_tree: str
) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValidationError("SD application root must be a real directory")
    candidate = _validate_candidate({"commit": candidate_commit, "tree": candidate_tree})
    required_files, directories, forbidden = _contract_required(root, asset_mode)
    contract: dict[str, object] = {
        "asset_mode": asset_mode,
        "candidate": candidate,
        "entrypoint": _record(root, ENTRYPOINT, nonempty=True).as_dict(),
        "format": 1,
        "product_ready_eligible": asset_mode == "loose",
        "required_directories": sorted(directories),
        "required_files": [record.as_dict() for record in required_files],
        "root": ROOT_URI,
        "runtime": {
            "config": "config.txt",
            "loose_game_root": "game" if asset_mode == "loose" else None,
            "resource_bundle": "resources/bundle.th3ds.json" if asset_mode == "th3ds" else None,
        },
        "schema": CONTRACT_SCHEMA,
        "user_data_roots": list(USER_DATA_ROOTS),
        "forbidden_paths": sorted(forbidden),
    }
    (root / CONTRACT_NAME).write_text(
        json.dumps(contract, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return contract


def write_sd_manifest(root: Path) -> dict[str, object]:
    root = root.resolve()
    contract = _load_json(_regular_file(root, CONTRACT_NAME, nonempty=True), "boot contract")
    asset_mode = contract.get("asset_mode")
    candidate = _validate_candidate(contract.get("candidate"))
    files = []
    for path in sorted(root.rglob("*")):
        if path == root / MANIFEST_NAME:
            continue
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValidationError(f"symbolic links are forbidden: {relative}")
        if path.is_file():
            files.append(_record(root, relative).as_dict())
        elif not path.is_dir():
            raise ValidationError(f"non-regular package node is forbidden: {relative}")
    if not files:
        raise ValidationError("SD application tree contains no files")
    manifest: dict[str, object] = {
        "asset_mode": asset_mode,
        "boot_contract": _record(root, CONTRACT_NAME, nonempty=True).as_dict(),
        "candidate": candidate,
        "files": files,
        "format": 1,
        "root": ROOT_URI,
    }
    (root / MANIFEST_NAME).write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def validate_sd_tree(root: Path, *, require_mode: str | None = None) -> dict[str, object]:
    root = root.resolve()
    if not root.is_dir() or root.is_symlink():
        raise ValidationError("SD application root must be a real, non-empty directory")
    contract_path = _regular_file(root, CONTRACT_NAME, nonempty=True)
    manifest_path = _regular_file(root, MANIFEST_NAME, nonempty=True)
    contract = _load_json(contract_path, "boot contract")
    manifest = _load_json(manifest_path, "SD manifest")
    if contract.get("schema") != CONTRACT_SCHEMA or contract.get("format") != 1:
        raise ValidationError("boot contract schema or format is unsupported")
    if contract.get("root") != ROOT_URI or manifest.get("root") != ROOT_URI or manifest.get("format") != 1:
        raise ValidationError("boot contract or manifest root/format is invalid")
    mode = contract.get("asset_mode")
    if mode not in ("th3ds", "loose") or manifest.get("asset_mode") != mode:
        raise ValidationError("asset mode is missing, invalid, or inconsistent")
    if require_mode is not None and mode != require_mode:
        raise ValidationError(f"asset mode {mode!r} does not satisfy required mode {require_mode!r}")
    expected_product_eligible = mode == "loose"
    if contract.get("product_ready_eligible") is not expected_product_eligible:
        raise ValidationError("product-ready eligibility does not match asset mode")
    candidate = _validate_candidate(contract.get("candidate"))
    if _validate_candidate(manifest.get("candidate")) != candidate:
        raise ValidationError("manifest candidate identity does not match boot contract")

    contract_record_raw = manifest.get("boot_contract")
    contract_records = _load_records([contract_record_raw], "boot_contract")
    contract_record = contract_records.get(CONTRACT_NAME)
    if contract_record is None:
        raise ValidationError("manifest does not link boot-contract.json")
    _verify_record(root, contract_record, nonempty=True)

    manifest_records = _load_records(manifest.get("files"), "manifest files")
    if MANIFEST_NAME in manifest_records:
        raise ValidationError("manifest cannot include itself")
    actual_files: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if path.is_symlink():
            raise ValidationError(f"symbolic links are forbidden: {relative}")
        metadata = path.lstat()
        if stat.S_ISREG(metadata.st_mode):
            actual_files.add(relative)
        elif not stat.S_ISDIR(metadata.st_mode):
            raise ValidationError(f"non-regular package node is forbidden: {relative}")
    expected_files = set(manifest_records) | {MANIFEST_NAME}
    if actual_files != expected_files:
        raise ValidationError(
            "manifest file set mismatch; "
            f"missing={sorted(expected_files - actual_files)} "
            f"extra={sorted(actual_files - expected_files)}"
        )
    for record in manifest_records.values():
        _verify_record(root, record)

    required_records = _load_records(contract.get("required_files"), "required_files")
    expected_required, expected_directories, expected_forbidden = _contract_required(root, str(mode))
    expected_required_map = {record.path: record for record in expected_required}
    if required_records != expected_required_map:
        raise ValidationError("boot contract required file identities are incomplete or stale")
    if contract.get("required_directories") != sorted(expected_directories):
        raise ValidationError("boot contract required directories are incomplete")
    if contract.get("forbidden_paths") != sorted(expected_forbidden):
        raise ValidationError("boot contract forbidden paths are incomplete")
    if contract.get("user_data_roots") != list(USER_DATA_ROOTS):
        raise ValidationError("boot contract user-data separation is invalid")
    runtime = contract.get("runtime")
    if not isinstance(runtime, dict):
        raise ValidationError("runtime contract is missing")
    expected_runtime = {
        "config": "config.txt",
        "loose_game_root": "game" if mode == "loose" else None,
        "resource_bundle": "resources/bundle.th3ds.json" if mode == "th3ds" else None,
    }
    if runtime != expected_runtime:
        raise ValidationError("runtime paths do not match the declared asset mode")
    entrypoint_records = _load_records([contract.get("entrypoint")], "entrypoint")
    entrypoint = entrypoint_records.get(ENTRYPOINT)
    if entrypoint is None or required_records.get(ENTRYPOINT) != entrypoint:
        raise ValidationError("3DSX entrypoint identity is not linked to required files")
    _verify_record(root, entrypoint, nonempty=True)
    _validate_3dsx(root / ENTRYPOINT)
    return {
        "asset_mode": mode,
        "binary_sha256": entrypoint.sha256,
        "candidate": candidate,
        "file_count": len(manifest_records),
        "manifest_sha256": sha256_path(manifest_path),
        "product_ready_eligible": expected_product_eligible,
        "result": "PASS",
        "total_bytes": sum(record.size for record in manifest_records.values())
        + manifest_path.stat().st_size,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create-contract")
    create.add_argument("root", type=Path)
    create.add_argument("--asset-mode", choices=("th3ds", "loose"), required=True)
    create.add_argument("--candidate-commit", required=True)
    create.add_argument("--candidate-tree", required=True)
    manifest = subparsers.add_parser("write-manifest")
    manifest.add_argument("root", type=Path)
    validate = subparsers.add_parser("validate")
    validate.add_argument("root", type=Path)
    validate.add_argument("--require-mode", choices=("th3ds", "loose"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "create-contract":
            result = write_boot_contract(
                args.root,
                asset_mode=args.asset_mode,
                candidate_commit=args.candidate_commit,
                candidate_tree=args.candidate_tree,
            )
        elif args.command == "write-manifest":
            result = write_sd_manifest(args.root)
        else:
            result = validate_sd_tree(args.root, require_mode=args.require_mode)
    except (OSError, ValidationError) as exc:
        print(f"SD_TREE_FAIL: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
