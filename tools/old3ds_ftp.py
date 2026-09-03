#!/usr/bin/env python3
"""Verified, recoverable deployment of a complete CorsixTH SD package over FTPD."""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import io
import json
import posixpath
import socket
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath


PUBLISHED = "/3ds/corsixth"
STAGING = "/3ds/.corsixth-uploading"


class DeployError(RuntimeError):
    pass


@dataclass(frozen=True)
class FileEntry:
    path: str
    size: int
    sha256: str


def safe_relative_path(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in ("", ".", "..") for part in path.parts):
        raise DeployError(f"unsafe manifest path: {value!r}")
    return path.as_posix()


def load_manifest(package: Path) -> list[FileEntry]:
    manifest_path = package / "sd-manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise DeployError(f"cannot read package manifest: {exc}") from exc
    if payload.get("root") != "sdmc:/3ds/corsixth" or payload.get("format") != 1:
        raise DeployError("package manifest has an unexpected root or format")
    entries: list[FileEntry] = []
    seen: set[str] = set()
    for raw in payload.get("files", []):
        relative = safe_relative_path(str(raw["path"]))
        if relative in seen or relative == "sd-manifest.json":
            raise DeployError(f"duplicate or reserved manifest path: {relative}")
        seen.add(relative)
        entry = FileEntry(relative, int(raw["size"]), str(raw["sha256"]))
        local = package / relative
        if not local.is_file() or local.stat().st_size != entry.size:
            raise DeployError(f"local package does not match manifest: {relative}")
        entries.append(entry)
    actual = {
        item.relative_to(package).as_posix()
        for item in package.rglob("*")
        if item.is_file() and item.name != ".DS_Store"
    }
    expected = seen | {"sd-manifest.json"}
    if actual != expected:
        missing = sorted(expected - actual)
        extra = sorted(actual - expected)
        raise DeployError(f"package file set mismatch; missing={missing[:5]} extra={extra[:5]}")
    return sorted(entries, key=lambda item: item.path)


def sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


class FtpConnection:
    def __init__(self, host: str, port: int, timeout: float) -> None:
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ftp: ftplib.FTP | None = None

    def __enter__(self) -> ftplib.FTP:
        ftp = ftplib.FTP()
        ftp.connect(self.host, self.port, timeout=self.timeout)
        ftp.login()
        ftp.set_pasv(True)
        self.ftp = ftp
        return ftp

    def __exit__(self, _type, _value, _traceback) -> None:
        if self.ftp is None:
            return
        try:
            self.ftp.quit()
        except (OSError, ftplib.Error):
            self.ftp.close()


def remote_exists(ftp: ftplib.FTP, path: str) -> bool:
    previous = ftp.pwd()
    try:
        ftp.cwd(path)
        return True
    except ftplib.error_perm:
        try:
            ftp.size(path)
            return True
        except ftplib.Error:
            return False
    finally:
        try:
            ftp.cwd(previous)
        except ftplib.Error:
            pass


def list_names(ftp: ftplib.FTP, directory: str) -> list[str]:
    previous = ftp.pwd()
    try:
        ftp.cwd(directory)
        names = ftp.nlst()
        return [posixpath.basename(name.rstrip("/")) for name in names if name not in (".", "..")]
    finally:
        ftp.cwd(previous)


def remove_tree(ftp: ftplib.FTP, directory: str) -> None:
    if directory in ("/", "/3ds", PUBLISHED):
        raise DeployError(f"refusing to remove protected remote path: {directory}")
    if not remote_exists(ftp, directory):
        return
    for name in list_names(ftp, directory):
        child = posixpath.join(directory, name)
        try:
            ftp.delete(child)
        except ftplib.error_perm:
            remove_tree(ftp, child)
    ftp.rmd(directory)


def ensure_directories(ftp: ftplib.FTP, entries: list[FileEntry]) -> None:
    directories = {STAGING}
    for entry in entries:
        parent = PurePosixPath(entry.path).parent
        while parent.as_posix() != ".":
            directories.add(posixpath.join(STAGING, parent.as_posix()))
            parent = parent.parent
    for directory in sorted(directories, key=lambda value: (value.count("/"), value)):
        try:
            ftp.mkd(directory)
        except ftplib.error_perm as exc:
            if not remote_exists(ftp, directory):
                raise DeployError(f"cannot create remote directory {directory}: {exc}") from exc


def upload_one(host: str, port: int, timeout: float, package: Path, entry: FileEntry) -> None:
    remote = posixpath.join(STAGING, entry.path)
    temporary = remote + ".uploading"
    with FtpConnection(host, port, timeout) as ftp:
        try:
            ftp.delete(temporary)
        except ftplib.Error:
            pass
        with (package / entry.path).open("rb") as handle:
            ftp.storbinary(f"STOR {temporary}", handle, blocksize=256 * 1024)
        try:
            ftp.delete(remote)
        except ftplib.Error:
            pass
        ftp.rename(temporary, remote)


def verify_one(host: str, port: int, timeout: float, entry: FileEntry) -> tuple[str, str, int]:
    digest = hashlib.sha256()
    size = 0

    def consume(block: bytes) -> None:
        nonlocal size
        digest.update(block)
        size += len(block)

    with FtpConnection(host, port, timeout) as ftp:
        ftp.retrbinary(f"RETR {posixpath.join(STAGING, entry.path)}", consume, blocksize=256 * 1024)
    return entry.path, digest.hexdigest(), size


def transfer_parallel(label: str, jobs: int, entries: list[FileEntry], worker) -> None:
    completed = 0
    total_bytes = sum(entry.size for entry in entries)
    completed_bytes = 0
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        futures = {executor.submit(worker, entry): entry for entry in entries}
        for future in as_completed(futures):
            entry = futures[future]
            future.result()
            completed += 1
            completed_bytes += entry.size
            if completed == len(entries) or completed % 25 == 0:
                print(
                    f"{label} {completed}/{len(entries)} files "
                    f"{completed_bytes}/{total_bytes} bytes",
                    flush=True,
                )


def readback_small(ftp: ftplib.FTP, remote: str) -> bytes:
    output = io.BytesIO()
    ftp.retrbinary(f"RETR {remote}", output.write, blocksize=256 * 1024)
    return output.getvalue()


def deploy(args: argparse.Namespace) -> dict[str, object]:
    package = args.package.expanduser().resolve()
    entries = load_manifest(package)
    manifest_path = package / "sd-manifest.json"
    manifest_hash = sha256_path(manifest_path)
    binary_entry = next((entry for entry in entries if entry.path == "CorsixTH-3DS.3dsx"), None)
    if binary_entry is None:
        raise DeployError("package manifest does not contain CorsixTH-3DS.3dsx")

    started = time.monotonic()
    with FtpConnection(args.host, args.port, args.timeout) as ftp:
        if not remote_exists(ftp, "/3ds"):
            raise DeployError("FTPD target does not expose /3ds")
        remove_tree(ftp, STAGING)
        ensure_directories(ftp, entries)

    transfer_parallel(
        "UPLOAD",
        args.jobs,
        entries,
        lambda entry: upload_one(args.host, args.port, args.timeout, package, entry),
    )
    upload_one(
        args.host,
        args.port,
        args.timeout,
        package,
        FileEntry("sd-manifest.json", manifest_path.stat().st_size, manifest_hash),
    )
    upload_seconds = time.monotonic() - started

    def verify(entry: FileEntry) -> None:
        path, actual_hash, actual_size = verify_one(
            args.host, args.port, args.timeout, entry
        )
        if actual_size != entry.size or actual_hash != entry.sha256:
            raise DeployError(
                f"readback mismatch for {path}: size={actual_size} sha256={actual_hash}"
            )

    transfer_parallel("VERIFY", args.jobs, entries, verify)
    verify(FileEntry("sd-manifest.json", manifest_path.stat().st_size, manifest_hash))
    verify_seconds = time.monotonic() - started - upload_seconds

    backup = None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    with FtpConnection(args.host, args.port, args.timeout) as ftp:
        staged_manifest = readback_small(ftp, f"{STAGING}/sd-manifest.json")
        if hashlib.sha256(staged_manifest).hexdigest() != manifest_hash:
            raise DeployError("staged manifest changed after readback verification")
        if remote_exists(ftp, PUBLISHED):
            backup = f"/3ds/corsixth-backup-{stamp}"
            if remote_exists(ftp, backup):
                raise DeployError(f"backup path already exists: {backup}")
            ftp.rename(PUBLISHED, backup)
        try:
            ftp.rename(STAGING, PUBLISHED)
        except Exception:
            if backup is not None and not remote_exists(ftp, PUBLISHED):
                ftp.rename(backup, PUBLISHED)
            raise
        published_binary = readback_small(ftp, f"{PUBLISHED}/CorsixTH-3DS.3dsx")
        published_manifest = readback_small(ftp, f"{PUBLISHED}/sd-manifest.json")
    binary_hash = hashlib.sha256(published_binary).hexdigest()
    if binary_hash != binary_entry.sha256:
        raise DeployError(f"published binary readback mismatch: {binary_hash}")
    if hashlib.sha256(published_manifest).hexdigest() != manifest_hash:
        raise DeployError("published manifest readback mismatch")

    return {
        "ok": True,
        "host": args.host,
        "port": args.port,
        "package": str(package),
        "published": PUBLISHED,
        "backup": backup,
        "filesVerified": len(entries) + 1,
        "bytesVerified": sum(entry.size for entry in entries) + manifest_path.stat().st_size,
        "binarySha256": binary_hash,
        "manifestSha256": manifest_hash,
        "uploadSeconds": round(upload_seconds, 3),
        "verifySeconds": round(verify_seconds, 3),
        "elapsedSeconds": round(time.monotonic() - started, 3),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path, help="local sd-card/3ds/corsixth directory")
    parser.add_argument("--host", required=True, help="3DS IPv4 address")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--jobs", type=int, default=2, choices=range(1, 5))
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--report", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        report = deploy(args)
    except (DeployError, ftplib.Error, OSError, socket.error) as exc:
        print(f"DEPLOY_FAIL: {exc}", file=sys.stderr)
        return 2
    encoded = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(encoded, encoding="utf-8")
    print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
