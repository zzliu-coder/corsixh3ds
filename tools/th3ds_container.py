"""Authoritative TH3DSR1 package and bundle writer/inspector.

The runtime loader is deliberately outside this module.  This host-side code
owns the byte layout, deterministic identifiers, integrity fields and strict
validation used by synthetic fixtures and future runtime implementations.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import re
import struct
from pathlib import PurePosixPath
from typing import Iterable, Mapping, Sequence

try:
    from th3ds_resource import ResourceError, canonical_json, safe_relative, sha256_bytes
except ModuleNotFoundError:
    from .th3ds_resource import ResourceError, canonical_json, safe_relative, sha256_bytes


MAGIC = b"TH3DSR1\0"
VERSION_MAJOR = 1
VERSION_MINOR = 0
HEADER_SIZE = 256
INDEX_ENTRY_SIZE = 128
DEFAULT_ALIGNMENT = 64
AUDIO_ALIGNMENT = 4096
ENDIAN_TAG = 0x01020304
RUNTIME_ABI = 1
MAX_RESOURCES = 65_535
MAX_STORED_BYTES = 64 * 1024 * 1024
MAX_METADATA_BYTES = 1024 * 1024

PACKAGE_ROLES = {"core": 1, "language": 2, "level": 3}
RESOURCE_KINDS = {
    "AUDIO_BANK": 1,
    "LANGUAGE_BUNDLE": 2,
    "SPRITE_SHEET": 3,
    "UI_BITMAP": 4,
    "FONT_ATLAS": 5,
    "FONT_MAP": 6,
    "PALETTE": 7,
    "OPAQUE_BLOB": 255,
}
RESOURCE_KIND_NAMES = {value: key for key, value in RESOURCE_KINDS.items()}
CODECS = {"NONE": 0, "ZLIB": 1, "DSP_ADPCM": 2}
KNOWN_FLAGS = 0x7
REQUIRED = 0x1
PIN_ON_MOUNT = 0x2
STREAMABLE = 0x4
BUNDLE_PATH_RE = re.compile(r"[a-z0-9._/-]+\Z")
HEX_32_RE = re.compile(r"[0-9a-f]{32}\Z")
HEX_64_RE = re.compile(r"[0-9a-f]{64}\Z")

# resource_id, kind, codec, flags, group_id, alignment_log2, reserved,
# data_offset, stored_size, decoded_size, meta_offset, meta_size,
# dependency_count, reserved, stored_sha256, decoded_sha256
INDEX_ENTRY = struct.Struct("<16sHHIIB3xQIIQIHH32s32s")
assert INDEX_ENTRY.size == INDEX_ENTRY_SIZE


def align_up(value: int, alignment: int) -> int:
    if alignment <= 0 or alignment & (alignment - 1):
        raise ResourceError(f"alignment must be a positive power of two: {alignment}")
    return (value + alignment - 1) & -alignment


def resource_id(kind_name: str, logical_name: str) -> bytes:
    if kind_name not in RESOURCE_KINDS:
        raise ResourceError(f"unknown resource kind: {kind_name}")
    canonical = safe_relative(logical_name)
    digest = hashlib.sha256()
    digest.update(b"th3ds-resource-id-v1\0")
    digest.update(kind_name.encode("ascii"))
    digest.update(b"\0")
    digest.update(canonical.encode("utf-8"))
    return digest.digest()[:16]


def package_id(role: str, name: str, source_set_sha256: str, runtime_abi: int = RUNTIME_ABI) -> bytes:
    if role not in PACKAGE_ROLES:
        raise ResourceError(f"unknown package role: {role}")
    if len(source_set_sha256) != 64:
        raise ResourceError("source-set SHA-256 must contain 64 hexadecimal characters")
    try:
        source_digest = bytes.fromhex(source_set_sha256)
    except ValueError as exc:
        raise ResourceError("source-set SHA-256 is not hexadecimal") from exc
    digest = hashlib.sha256()
    digest.update(b"th3ds-package-id-v1\0")
    digest.update(role.encode("ascii"))
    digest.update(b"\0")
    digest.update(name.encode("utf-8"))
    digest.update(b"\0")
    digest.update(source_digest)
    digest.update(struct.pack("<I", runtime_abi))
    return digest.digest()[:16]


def source_set_digest(records: Iterable[tuple[str, bytes]]) -> tuple[str, int, int]:
    normalized: dict[str, bytes] = {}
    for name, data in records:
        canonical = safe_relative(name)
        if canonical in normalized:
            raise ResourceError(f"duplicate source-set path: {canonical}")
        normalized[canonical] = data
    digest = hashlib.sha256()
    total = 0
    for name in sorted(normalized, key=lambda item: item.encode("utf-8")):
        encoded = name.encode("utf-8")
        if len(encoded) > 0xFFFF:
            raise ResourceError(f"source-set path is too long: {name}")
        data = normalized[name]
        digest.update(struct.pack("<H", len(encoded)))
        digest.update(encoded)
        digest.update(struct.pack("<Q", len(data)))
        digest.update(hashlib.sha256(data).digest())
        total += len(data)
    return digest.hexdigest(), len(normalized), total


@dataclasses.dataclass(frozen=True)
class ResourceInput:
    logical_name: str
    kind: str
    data: bytes
    decoded_size: int
    metadata: Mapping[str, object]
    group_id: int = 1
    flags: int = REQUIRED
    alignment: int = DEFAULT_ALIGNMENT
    codec: str = "NONE"
    dependencies: tuple[bytes, ...] = ()
    decoded_sha256: str | None = None


@dataclasses.dataclass(frozen=True)
class ResourceDescriptor:
    resource_id: str
    logical_name: str
    kind: str
    data_offset: int
    stored_size: int
    decoded_size: int
    meta_offset: int
    meta_size: int
    alignment: int
    stored_sha256: str
    decoded_sha256: str


@dataclasses.dataclass(frozen=True)
class BuiltPackage:
    data: bytes
    manifest: Mapping[str, object]
    package_id: str
    container_sha256: str
    catalog_sha256: str
    payload_sha256: str
    resources: tuple[ResourceDescriptor, ...]


def _validate_manifest_value(value: object) -> None:
    if isinstance(value, float):
        raise ResourceError("TH3DS canonical JSON forbids floating-point values")
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ResourceError("TH3DS canonical JSON object keys must be strings")
            _validate_manifest_value(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _validate_manifest_value(item)


def _manifest_bytes(value: Mapping[str, object]) -> bytes:
    _validate_manifest_value(value)
    return canonical_json(value)


def _container_hash(data: bytes) -> str:
    mutable = bytearray(data)
    mutable[0xA8:0xC8] = bytes(32)
    return hashlib.sha256(mutable).hexdigest()


def build_package(
    *,
    role: str,
    name: str,
    source_set_sha256: str,
    source_file_count: int,
    source_total_bytes: int,
    resources: Sequence[ResourceInput],
    groups: Sequence[Mapping[str, object]],
    budgets: Mapping[str, int],
    toolchain: Mapping[str, object],
    language: Mapping[str, object] | None = None,
    level: Mapping[str, object] | None = None,
    dependencies: Sequence[Mapping[str, object]] = (),
    required_feature_bits: int = 0,
) -> BuiltPackage:
    if role not in PACKAGE_ROLES:
        raise ResourceError(f"unknown package role: {role}")
    if not resources or len(resources) > MAX_RESOURCES:
        raise ResourceError("TH3DS package must contain 1..65535 resources")
    package_identifier = package_id(role, name, source_set_sha256)

    prepared: list[tuple[bytes, ResourceInput, bytes, str, str]] = []
    seen_ids: set[bytes] = set()
    for item in resources:
        identifier = resource_id(item.kind, item.logical_name)
        if identifier in seen_ids:
            raise ResourceError(f"resource ID collision: {item.logical_name}")
        seen_ids.add(identifier)
        if item.codec not in CODECS:
            raise ResourceError(f"unknown resource codec: {item.codec}")
        if item.flags & ~KNOWN_FLAGS:
            raise ResourceError(f"unknown resource flags: 0x{item.flags:x}")
        if item.group_id < 0 or item.group_id > 0xFFFFFFFF:
            raise ResourceError(f"invalid group id for {item.logical_name}")
        if item.decoded_size < 0 or item.decoded_size > MAX_STORED_BYTES:
            raise ResourceError(f"decoded resource exceeds v1 limit: {item.logical_name}")
        if len(item.data) > MAX_STORED_BYTES:
            raise ResourceError(f"stored resource exceeds v1 limit: {item.logical_name}")
        if item.alignment not in (DEFAULT_ALIGNMENT, AUDIO_ALIGNMENT):
            raise ResourceError(f"unsupported v1 alignment for {item.logical_name}: {item.alignment}")
        metadata = b"".join(item.dependencies) + _manifest_bytes(dict(item.metadata))
        if any(len(value) != 16 for value in item.dependencies):
            raise ResourceError(f"dependency IDs must be 16 bytes: {item.logical_name}")
        if len(metadata) > MAX_METADATA_BYTES:
            raise ResourceError(f"resource metadata exceeds v1 limit: {item.logical_name}")
        stored_hash = sha256_bytes(item.data)
        decoded_hash = item.decoded_sha256 or stored_hash
        if len(decoded_hash) != 64:
            raise ResourceError(f"decoded SHA-256 is invalid: {item.logical_name}")
        prepared.append((identifier, item, metadata, stored_hash, decoded_hash))
    prepared.sort(key=lambda value: value[0])

    metadata_region = bytearray()
    metadata_layout: dict[bytes, tuple[int, int]] = {}
    for identifier, _item, metadata, _stored_hash, _decoded_hash in prepared:
        metadata_layout[identifier] = (len(metadata_region), len(metadata))
        metadata_region.extend(metadata)

    placeholder_hash = "0" * 64
    package_manifest: dict[str, object] = {
        "budgets": dict(budgets),
        "catalog": {
            "catalog_sha256": placeholder_hash,
            "payload_sha256": placeholder_hash,
            "resource_count": len(prepared),
        },
        "dependencies": list(dependencies),
        "format": {"major": VERSION_MAJOR, "minor": VERSION_MINOR},
        "groups": list(groups),
        "language": language,
        "level": level,
        "package": {"id": package_identifier.hex(), "name": name, "role": role},
        "provenance": {"contains_user_game_data": True, "redistributable": False},
        "runtime_abi": {"max": RUNTIME_ABI, "min": RUNTIME_ABI},
        "source": {
            "file_count": source_file_count,
            "set_sha256": source_set_sha256,
            "total_bytes": source_total_bytes,
        },
        "toolchain": dict(toolchain),
    }
    manifest = _manifest_bytes(package_manifest)
    manifest_offset = HEADER_SIZE
    index_offset = align_up(manifest_offset + len(manifest), DEFAULT_ALIGNMENT)
    index_size = len(prepared) * INDEX_ENTRY_SIZE
    metadata_offset = align_up(index_offset + index_size, DEFAULT_ALIGNMENT)
    data_offset = align_up(metadata_offset + len(metadata_region), DEFAULT_ALIGNMENT)

    data_region = bytearray()
    data_layout: dict[bytes, int] = {}
    for identifier, item, _metadata, _stored_hash, _decoded_hash in prepared:
        absolute = data_offset + len(data_region)
        aligned = align_up(absolute, item.alignment)
        data_region.extend(bytes(aligned - absolute))
        data_layout[identifier] = aligned
        data_region.extend(item.data)

    def make_index() -> bytes:
        result = bytearray()
        for identifier, item, metadata, stored_hash, decoded_hash in prepared:
            meta_relative, meta_size = metadata_layout[identifier]
            result.extend(
                INDEX_ENTRY.pack(
                    identifier,
                    RESOURCE_KINDS[item.kind],
                    CODECS[item.codec],
                    item.flags,
                    item.group_id,
                    item.alignment.bit_length() - 1,
                    data_layout[identifier],
                    len(item.data),
                    item.decoded_size,
                    meta_relative,
                    meta_size,
                    len(item.dependencies),
                    0,
                    bytes.fromhex(stored_hash),
                    bytes.fromhex(decoded_hash),
                )
            )
        return bytes(result)

    index = make_index()
    catalog_hash = hashlib.sha256(index + metadata_region).hexdigest()
    payload_hash = hashlib.sha256(data_region).hexdigest()
    package_manifest["catalog"] = {
        "catalog_sha256": catalog_hash,
        "payload_sha256": payload_hash,
        "resource_count": len(prepared),
    }
    manifest = _manifest_bytes(package_manifest)
    if index_offset != align_up(manifest_offset + len(manifest), DEFAULT_ALIGNMENT):
        raise ResourceError("internal error: manifest hash replacement changed its encoded size")

    output = bytearray(data_offset + len(data_region))
    output[manifest_offset : manifest_offset + len(manifest)] = manifest
    output[index_offset : index_offset + len(index)] = index
    output[metadata_offset : metadata_offset + len(metadata_region)] = metadata_region
    output[data_offset : data_offset + len(data_region)] = data_region

    struct.pack_into("<8sHHHH", output, 0x00, MAGIC, HEADER_SIZE, VERSION_MAJOR, VERSION_MINOR, 0)
    struct.pack_into("<IIII", output, 0x10, ENDIAN_TAG, DEFAULT_ALIGNMENT, PACKAGE_ROLES[role], INDEX_ENTRY_SIZE)
    struct.pack_into("<QQ", output, 0x20, manifest_offset, len(manifest))
    struct.pack_into("<QI", output, 0x30, index_offset, len(prepared))
    struct.pack_into("<I", output, 0x3C, 0)
    struct.pack_into("<QQ", output, 0x40, metadata_offset, len(metadata_region))
    struct.pack_into("<QQ", output, 0x50, data_offset, len(data_region))
    struct.pack_into("<Q", output, 0x60, 0)
    output[0x68:0x88] = bytes.fromhex(catalog_hash)
    output[0x88:0xA8] = bytes.fromhex(payload_hash)
    output[0xA8:0xC8] = bytes(32)
    output[0xC8:0xE8] = bytes.fromhex(source_set_sha256)
    struct.pack_into("<II", output, 0xE8, RUNTIME_ABI, required_feature_bits)
    output[0xF0:0x100] = bytes(16)
    container_hash = _container_hash(bytes(output))
    output[0xA8:0xC8] = bytes.fromhex(container_hash)

    descriptors = tuple(
        ResourceDescriptor(
            resource_id=identifier.hex(),
            logical_name=item.logical_name,
            kind=item.kind,
            data_offset=data_layout[identifier],
            stored_size=len(item.data),
            decoded_size=item.decoded_size,
            meta_offset=metadata_layout[identifier][0],
            meta_size=metadata_layout[identifier][1],
            alignment=item.alignment,
            stored_sha256=stored_hash,
            decoded_sha256=decoded_hash,
        )
        for identifier, item, _metadata, stored_hash, decoded_hash in prepared
    )
    return BuiltPackage(
        data=bytes(output),
        manifest=package_manifest,
        package_id=package_identifier.hex(),
        container_sha256=container_hash,
        catalog_sha256=catalog_hash,
        payload_sha256=payload_hash,
        resources=descriptors,
    )


def inspect_package(data: bytes, *, verify: bool = True) -> Mapping[str, object]:
    if len(data) < HEADER_SIZE:
        raise ResourceError("TH3DS package has a truncated header")
    magic, header_size, major, minor, header_flags = struct.unpack_from("<8sHHHH", data, 0)
    endian, alignment, role, entry_size = struct.unpack_from("<IIII", data, 0x10)
    manifest_offset, manifest_size = struct.unpack_from("<QQ", data, 0x20)
    index_offset, count = struct.unpack_from("<QI", data, 0x30)
    reserved_0 = struct.unpack_from("<I", data, 0x3C)[0]
    metadata_offset, metadata_size = struct.unpack_from("<QQ", data, 0x40)
    data_offset, data_size = struct.unpack_from("<QQ", data, 0x50)
    build_epoch = struct.unpack_from("<Q", data, 0x60)[0]
    required_abi, feature_bits = struct.unpack_from("<II", data, 0xE8)
    if magic != MAGIC or header_size != HEADER_SIZE or (major, minor) != (1, 0):
        raise ResourceError("unsupported TH3DS package format")
    if header_flags or reserved_0 or build_epoch or any(data[0xF0:0x100]):
        raise ResourceError("TH3DS package has non-zero reserved header fields")
    if endian != ENDIAN_TAG or alignment != DEFAULT_ALIGNMENT or entry_size != INDEX_ENTRY_SIZE:
        raise ResourceError("TH3DS package has incompatible endian/alignment/index fields")
    if role not in PACKAGE_ROLES.values() or count == 0 or count > MAX_RESOURCES:
        raise ResourceError("TH3DS package has invalid role/resource count")
    if required_abi != RUNTIME_ABI or feature_bits != 0:
        raise ResourceError("TH3DS package requires an unsupported runtime feature")
    regions = [
        (manifest_offset, manifest_size, "manifest"),
        (index_offset, count * INDEX_ENTRY_SIZE, "index"),
        (metadata_offset, metadata_size, "metadata"),
        (data_offset, data_size, "data"),
    ]
    previous_end = HEADER_SIZE
    for offset, size, label in regions:
        if offset % DEFAULT_ALIGNMENT or offset < previous_end or size > len(data) - offset:
            raise ResourceError(f"TH3DS {label} region is out of bounds, overlapping or unaligned")
        if any(data[previous_end:offset]):
            raise ResourceError(f"TH3DS padding before {label} is non-zero")
        previous_end = offset + size
    if previous_end != len(data):
        raise ResourceError("TH3DS file has trailing bytes outside the data region")
    try:
        manifest = json.loads(data[manifest_offset : manifest_offset + manifest_size].decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResourceError("TH3DS package manifest is not valid canonical JSON") from exc
    if not isinstance(manifest, dict) or _manifest_bytes(manifest) != data[manifest_offset : manifest_offset + manifest_size]:
        raise ResourceError("TH3DS package manifest is not canonically encoded")
    package_manifest = manifest.get("package")
    source_manifest = manifest.get("source")
    abi_manifest = manifest.get("runtime_abi")
    catalog_manifest = manifest.get("catalog")
    if manifest.get("format") != {"major": VERSION_MAJOR, "minor": VERSION_MINOR}:
        raise ResourceError("TH3DS package manifest has an unsupported format version")
    if not all(isinstance(value, dict) for value in (package_manifest, source_manifest, abi_manifest, catalog_manifest)):
        raise ResourceError("TH3DS package manifest is missing a required object")
    role_name = next(name for name, value in PACKAGE_ROLES.items() if value == role)
    package_name = package_manifest.get("name")
    package_hex = package_manifest.get("id")
    source_hex = source_manifest.get("set_sha256")
    if package_manifest.get("role") != role_name or not isinstance(package_name, str):
        raise ResourceError("TH3DS manifest/header package role mismatch")
    if not isinstance(source_hex, str) or not HEX_64_RE.fullmatch(source_hex) or bytes.fromhex(source_hex) != data[0xC8:0xE8]:
        raise ResourceError("TH3DS manifest/header source-set hash mismatch")
    expected_package_id = package_id(role_name, package_name, source_hex).hex()
    if not isinstance(package_hex, str) or not HEX_32_RE.fullmatch(package_hex) or package_hex != expected_package_id:
        raise ResourceError("TH3DS package ID is invalid")
    if abi_manifest != {"max": RUNTIME_ABI, "min": RUNTIME_ABI}:
        raise ResourceError("TH3DS package manifest has an unsupported runtime ABI")
    if catalog_manifest.get("resource_count") != count:
        raise ResourceError("TH3DS manifest/header resource count mismatch")

    entries: list[dict[str, object]] = []
    previous_id = b""
    intervals: list[tuple[int, int]] = []
    index_end = index_offset + count * INDEX_ENTRY_SIZE
    for offset in range(index_offset, index_end, INDEX_ENTRY_SIZE):
        unpacked = INDEX_ENTRY.unpack_from(data, offset)
        (
            identifier,
            kind,
            codec,
            flags,
            group_id,
            alignment_log2,
            resource_offset,
            stored_size,
            decoded_size,
            meta_relative,
            meta_size,
            dependency_count,
            entry_reserved,
            stored_hash,
            decoded_hash,
        ) = unpacked
        if previous_id and identifier <= previous_id:
            raise ResourceError("TH3DS resource index is duplicate or out of order")
        previous_id = identifier
        if kind not in RESOURCE_KIND_NAMES or codec not in CODECS.values() or flags & ~KNOWN_FLAGS:
            raise ResourceError("TH3DS resource index contains an unknown required value")
        resource_alignment = 1 << alignment_log2
        if resource_alignment not in (DEFAULT_ALIGNMENT, AUDIO_ALIGNMENT):
            raise ResourceError("TH3DS resource has unsupported alignment")
        if resource_offset % resource_alignment or resource_offset < data_offset:
            raise ResourceError("TH3DS resource offset is invalid")
        if stored_size > data_offset + data_size - resource_offset:
            raise ResourceError("TH3DS resource payload is out of bounds")
        if meta_relative > metadata_size or meta_size > metadata_size - meta_relative:
            raise ResourceError("TH3DS resource metadata is out of bounds")
        if dependency_count * 16 > meta_size or entry_reserved:
            raise ResourceError("TH3DS resource dependency metadata is invalid")
        metadata = data[
            metadata_offset + meta_relative + dependency_count * 16 :
            metadata_offset + meta_relative + meta_size
        ]
        try:
            metadata_value = json.loads(metadata.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ResourceError("TH3DS resource metadata is not valid canonical JSON") from exc
        if not isinstance(metadata_value, dict) or _manifest_bytes(metadata_value) != metadata:
            raise ResourceError("TH3DS resource metadata is not canonically encoded")
        payload = data[resource_offset : resource_offset + stored_size]
        if verify and hashlib.sha256(payload).digest() != stored_hash:
            raise ResourceError("TH3DS stored resource SHA-256 mismatch")
        intervals.append((resource_offset, resource_offset + stored_size))
        entries.append(
            {
                "codec": codec,
                "decoded_sha256": decoded_hash.hex(),
                "decoded_size": decoded_size,
                "flags": flags,
                "group_id": group_id,
                "kind": RESOURCE_KIND_NAMES[kind],
                "resource_id": identifier.hex(),
                "stored_sha256": stored_hash.hex(),
                "stored_size": stored_size,
            }
        )
    cursor = data_offset
    for start, end in sorted(intervals):
        if start < cursor:
            raise ResourceError("TH3DS resource payloads overlap")
        if any(data[cursor:start]):
            raise ResourceError("TH3DS inter-resource padding is non-zero")
        cursor = end
    if any(data[cursor : data_offset + data_size]):
        raise ResourceError("TH3DS trailing data padding is non-zero")
    if verify:
        expected_catalog = data[0x68:0x88]
        expected_payload = data[0x88:0xA8]
        expected_container = data[0xA8:0xC8]
        catalog = data[index_offset:index_end] + data[metadata_offset : metadata_offset + metadata_size]
        payload = data[data_offset : data_offset + data_size]
        if hashlib.sha256(catalog).digest() != expected_catalog:
            raise ResourceError("TH3DS catalog SHA-256 mismatch")
        if hashlib.sha256(payload).digest() != expected_payload:
            raise ResourceError("TH3DS payload SHA-256 mismatch")
        if _container_hash(data) != expected_container.hex():
            raise ResourceError("TH3DS container SHA-256 mismatch")
        if catalog_manifest.get("catalog_sha256") != expected_catalog.hex():
            raise ResourceError("TH3DS manifest/header catalog hash mismatch")
        if catalog_manifest.get("payload_sha256") != expected_payload.hex():
            raise ResourceError("TH3DS manifest/header payload hash mismatch")
    return {"entries": entries, "manifest": manifest}


def build_bundle_manifest(
    *,
    source_set_sha256: str,
    selected_language: str,
    packages: Sequence[tuple[str, BuiltPackage]],
    start_level: str | None = None,
    fallback_language: str | None = None,
) -> tuple[bytes, str]:
    rows = []
    for path, package in sorted(packages, key=lambda item: item[0]):
        canonical = safe_relative(path)
        if not BUNDLE_PATH_RE.fullmatch(canonical):
            raise ResourceError(f"bundle package path must use lowercase safe ASCII: {canonical}")
        role = package.manifest["package"]["role"]  # type: ignore[index]
        rows.append(
            {
                "container_sha256": package.container_sha256,
                "package_id": package.package_id,
                "path": canonical,
                "role": role,
                "size": len(package.data),
            }
        )
    value: dict[str, object] = {
        "bundle_sha256": "0" * 64,
        "fallback_language": fallback_language,
        "format": {"major": VERSION_MAJOR, "minor": VERSION_MINOR},
        "packages": rows,
        "runtime_abi": RUNTIME_ABI,
        "selected_language": selected_language,
        "source_set_sha256": source_set_sha256,
        "start_level": start_level,
    }
    zeroed = _manifest_bytes(value)
    digest = hashlib.sha256(zeroed).hexdigest()
    value["bundle_sha256"] = digest
    encoded = _manifest_bytes(value)
    return encoded, digest


def inspect_bundle(data: bytes) -> Mapping[str, object]:
    try:
        value = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ResourceError("bundle manifest is not valid UTF-8 JSON") from exc
    if not isinstance(value, dict) or _manifest_bytes(value) != data:
        raise ResourceError("bundle manifest is not canonically encoded")
    digest = value.get("bundle_sha256")
    if not isinstance(digest, str) or not HEX_64_RE.fullmatch(digest):
        raise ResourceError("bundle manifest has an invalid bundle hash")
    zeroed = dict(value)
    zeroed["bundle_sha256"] = "0" * 64
    if hashlib.sha256(_manifest_bytes(zeroed)).hexdigest() != digest:
        raise ResourceError("bundle manifest SHA-256 mismatch")
    if value.get("format") != {"major": VERSION_MAJOR, "minor": VERSION_MINOR}:
        raise ResourceError("bundle manifest has an unsupported format version")
    if value.get("runtime_abi") != RUNTIME_ABI:
        raise ResourceError("bundle manifest has an unsupported runtime ABI")
    source_hex = value.get("source_set_sha256")
    selected_language = value.get("selected_language")
    fallback_language = value.get("fallback_language")
    if not isinstance(source_hex, str) or not HEX_64_RE.fullmatch(source_hex):
        raise ResourceError("bundle manifest has an invalid source-set hash")
    if not isinstance(selected_language, str) or not selected_language:
        raise ResourceError("bundle manifest has an invalid selected language")
    if fallback_language is not None and (not isinstance(fallback_language, str) or not fallback_language):
        raise ResourceError("bundle manifest has an invalid fallback language")
    packages = value.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ResourceError("bundle manifest contains no packages")
    paths: set[str] = set()
    identifiers: set[str] = set()
    previous_path = ""
    for item in packages:
        if not isinstance(item, dict):
            raise ResourceError("bundle package entry is not an object")
        path = item.get("path")
        identifier = item.get("package_id")
        if (
            not isinstance(path, str)
            or safe_relative(path) != path
            or not BUNDLE_PATH_RE.fullmatch(path)
        ):
            raise ResourceError("bundle package path is invalid")
        if previous_path and path <= previous_path:
            raise ResourceError("bundle package paths are duplicate or out of order")
        previous_path = path
        container_hex = item.get("container_sha256")
        if (
            not isinstance(identifier, str)
            or not HEX_32_RE.fullmatch(identifier)
            or identifier in identifiers
            or not isinstance(container_hex, str)
            or not HEX_64_RE.fullmatch(container_hex)
            or item.get("role") not in PACKAGE_ROLES
            or not isinstance(item.get("size"), int)
            or item["size"] <= 0
        ):
            raise ResourceError("bundle package entry has an invalid field")
        if path in paths:
            raise ResourceError("bundle contains a duplicate path or package ID")
        paths.add(path)
        identifiers.add(identifier)
    return value
