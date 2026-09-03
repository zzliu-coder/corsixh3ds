#!/usr/bin/env python3
"""Transactional update of CorsixTH runtime files over Old 3DS ftpd.

The proven path for this console is one ordinary STOR data connection per
file. Existing runtime files are retained by an SD-card rename. Game data,
saves, configuration and logs stay in place.
"""

from __future__ import annotations

import argparse
import ftplib
import hashlib
import io
import json
import posixpath
import sys
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from old3ds_ftp import FtpConnection, remote_exists


DEFAULT_FILES = (
    "CorsixTH-3DS.3dsx",
    "CorsixTH.lua",
    "Lua/app.lua",
    "cth3ds-overlay-version.txt",
    "sd-manifest.json",
)
PUBLISHED = "/3ds/corsixth"


class DeltaError(RuntimeError):
    pass


def safe_relative(value: str) -> str:
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(
        part in ("", ".", "..") for part in path.parts
    ):
        raise DeltaError(f"unsafe relative path: {value!r}")
    return path.as_posix()


def digest(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def ensure_directory(ftp: ftplib.FTP, directory: str) -> None:
    current = ""
    for part in PurePosixPath(directory).parts:
        if part == "/":
            current = "/"
            continue
        current = posixpath.join(current, part)
        try:
            ftp.mkd(current)
        except ftplib.error_perm:
            if not remote_exists(ftp, current):
                raise


def exact_size(ftp: ftplib.FTP, path: str) -> int:
    value = ftp.size(path)
    if value is None:
        raise DeltaError(f"FTPD did not report a size for {path}")
    return int(value)


def deploy(args: argparse.Namespace) -> dict[str, object]:
    package = args.package.expanduser().resolve()
    relative_files = tuple(safe_relative(item) for item in args.file)
    if len(set(relative_files)) != len(relative_files):
        raise DeltaError("duplicate file in delta set")

    local_files: dict[str, bytes] = {}
    for relative in relative_files:
        path = package / relative
        if not path.is_file():
            raise DeltaError(f"delta source is missing: {path}")
        local_files[relative] = path.read_bytes()

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    remote_backup = f"/3ds/corsixth-backups/{stamp}"
    args.backup_dir.expanduser().resolve().mkdir(parents=True, exist_ok=True)
    records: list[dict[str, object]] = []
    published: list[tuple[str, str | None]] = []

    with FtpConnection(args.host, args.port, args.timeout) as ftp:
        if not remote_exists(ftp, PUBLISHED):
            raise DeltaError(f"installed CorsixTH directory is missing: {PUBLISHED}")
        ensure_directory(ftp, remote_backup)

        # Stage everything before moving any installed file.
        for relative, payload in local_files.items():
            remote = posixpath.join(PUBLISHED, relative)
            temporary = remote + ".uploading"
            try:
                ftp.delete(temporary)
            except ftplib.error_perm:
                if remote_exists(ftp, temporary):
                    raise
            print(f"UPLOAD {relative} 0/{len(payload)} bytes", flush=True)
            ftp.storbinary(
                f"STOR {temporary}", io.BytesIO(payload), blocksize=256 * 1024
            )
            staged_size = exact_size(ftp, temporary)
            if staged_size != len(payload):
                raise DeltaError(
                    f"staging size mismatch for {relative}: "
                    f"{staged_size}/{len(payload)}"
                )
            print(f"UPLOAD {relative} {staged_size}/{len(payload)} bytes", flush=True)

        try:
            for relative, payload in local_files.items():
                remote = posixpath.join(PUBLISHED, relative)
                temporary = remote + ".uploading"
                rollback = posixpath.join(remote_backup, relative + ".previous")
                ensure_directory(ftp, posixpath.dirname(rollback))
                previous_size = None
                backup_path = None
                if remote_exists(ftp, remote):
                    previous_size = exact_size(ftp, remote)
                    ftp.rename(remote, rollback)
                    backup_path = rollback
                published.append((remote, backup_path))
                ftp.rename(temporary, remote)
                final_size = exact_size(ftp, remote)
                if final_size != len(payload):
                    raise DeltaError(
                        f"published size mismatch for {relative}: "
                        f"{final_size}/{len(payload)}"
                    )
                records.append(
                    {
                        "path": relative,
                        "bytes": final_size,
                        "previousBytes": previous_size,
                        "remoteBackup": backup_path,
                        "expectedSha256": digest(payload),
                        "verification": "ftp-226-and-size",
                    }
                )

            legacy = "/3ds/CorsixTH-3DS.3dsx"
            legacy_moved = None
            if args.disable_legacy and remote_exists(ftp, legacy):
                legacy_moved = posixpath.join(
                    remote_backup, "legacy-root-CorsixTH-3DS.3dsx.disabled"
                )
                ftp.rename(legacy, legacy_moved)
        except Exception:
            for remote, rollback in reversed(published):
                try:
                    if remote_exists(ftp, remote):
                        ftp.delete(remote)
                    if rollback is not None and remote_exists(ftp, rollback):
                        ftp.rename(rollback, remote)
                except ftplib.Error:
                    pass
            raise

    return {
        "ok": True,
        "host": args.host,
        "port": args.port,
        "package": str(package),
        "published": PUBLISHED,
        "remoteRollback": remote_backup,
        "localBackup": None,
        "preserved": ["game", "Saves", "config.txt", "Logs"],
        "files": records,
        "legacyLauncherMoved": legacy_moved,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("package", type=Path)
    parser.add_argument("--host", required=True)
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--timeout", type=float, default=120.0)
    parser.add_argument("--file", action="append", default=list(DEFAULT_FILES))
    parser.add_argument("--backup-dir", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--disable-legacy", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = deploy(args)
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (DeltaError, OSError, ftplib.Error) as error:
        failure = {"ok": False, "error": str(error)}
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(failure, indent=2, sort_keys=True) + "\n")
        print(f"error: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
