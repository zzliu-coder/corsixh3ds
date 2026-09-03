"""Shared deterministic resource-packer primitives."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
import zlib
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable, Iterable


class ResourceError(RuntimeError):
    """Raised when conversion cannot produce a trustworthy resource tree."""


@dataclass(frozen=True)
class ResourceRecord:
    path: str
    kind: str
    packed_size: int
    decoded_size: int
    cache_class: str
    residency_class: str
    crc32: str
    sha256: str

    def as_dict(self) -> dict[str, object]:
        return {
            "cache_class": self.cache_class,
            "crc32": self.crc32,
            "decoded_size": self.decoded_size,
            "kind": self.kind,
            "packed_size": self.packed_size,
            "path": self.path,
            "residency_class": self.residency_class,
            "sha256": self.sha256,
        }


def canonical_json(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
        "utf-8"
    )


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def crc32_hex(data: bytes) -> str:
    return f"{zlib.crc32(data) & 0xFFFFFFFF:08x}"


def safe_relative(value: str | PurePosixPath) -> str:
    text = PurePosixPath(str(value).replace("\\", "/")).as_posix()
    while text.startswith("./"):
        text = text[2:]
    path = PurePosixPath(text)
    if not text or text.startswith("/") or any(part in ("", ".", "..") for part in path.parts):
        raise ResourceError(f"unsafe relative resource path: {value}")
    return text


def read_stable(path: Path, *, expected_sha256: str | None = None) -> bytes:
    """Read once and reject files which changed while being consumed."""

    try:
        before = path.stat()
        if not path.is_file() or path.is_symlink():
            raise ResourceError(f"input must be a regular non-symlink file: {path}")
        data = path.read_bytes()
        after = path.stat()
    except OSError as exc:
        raise ResourceError(f"cannot read input {path}: {exc}") from exc
    identity_before = (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns)
    identity_after = (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
    if identity_before != identity_after or len(data) != before.st_size:
        raise ResourceError(f"input changed while being read: {path}")
    digest = sha256_bytes(data)
    if expected_sha256 is not None and digest != expected_sha256:
        raise ResourceError(f"input changed after discovery: {path}")
    return data


def write_bytes(root: Path, relative: str, data: bytes) -> ResourceRecord:
    relative = safe_relative(relative)
    destination = root / PurePosixPath(relative)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    return ResourceRecord(
        path=relative,
        kind="blob",
        packed_size=len(data),
        decoded_size=len(data),
        cache_class="direct",
        residency_class="streamed",
        crc32=crc32_hex(data),
        sha256=sha256_bytes(data),
    )


def record_for(
    path: str,
    data: bytes,
    *,
    kind: str,
    decoded_size: int,
    cache_class: str,
    residency_class: str,
) -> ResourceRecord:
    return ResourceRecord(
        path=safe_relative(path),
        kind=kind,
        packed_size=len(data),
        decoded_size=decoded_size,
        cache_class=cache_class,
        residency_class=residency_class,
        crc32=crc32_hex(data),
        sha256=sha256_bytes(data),
    )


def atomic_directory(output: Path, producer: Callable[[Path], object]) -> object:
    """Publish a complete new directory; never merge with an existing tree."""

    output = output.expanduser().resolve()
    if output.exists():
        raise ResourceError(f"output already exists; choose a new empty path: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{output.name}.tmp-", dir=output.parent))
    try:
        result = producer(temporary)
        os.replace(temporary, output)
        return result
    except BaseException:
        shutil.rmtree(temporary, ignore_errors=True)
        raise


def tree_digest(records: Iterable[ResourceRecord]) -> str:
    digest = hashlib.sha256()
    for record in sorted(records, key=lambda item: item.path):
        digest.update(record.path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(bytes.fromhex(record.sha256))
    return digest.hexdigest()
