#!/usr/bin/env python3
"""Pull the on-device boot log back off the 3DS over FTP.

The runtime writes sdmc:/3ds/corsixth/boot.log unbuffered, so after a freeze
the last line in that file is the last thing that actually executed. Fetching
it turns "it hangs" into a specific stage, which is the difference between a
hardware run that produces a diagnosis and one that produces NOT_PROVEN.

Run FTPD (or any homebrew FTP server) on the console after the CorsixTH run,
then:

    python3 tools/old3ds_fetch_log.py --host 192.168.1.20 --out run/logs
"""

from __future__ import annotations

import argparse
import ftplib
import sys
from pathlib import Path
from typing import Sequence

DEFAULT_REMOTE_FILES = (
    "/3ds/corsixth/boot.log",
    "/3ds/corsixth/config.txt",
    "/3ds/corsixth/cth3ds-overlay-version.txt",
)


class FetchError(RuntimeError):
    pass


def fetch_one(ftp: ftplib.FTP, remote: str, destination: Path) -> int:
    chunks: list[bytes] = []
    try:
        ftp.retrbinary(f"RETR {remote}", chunks.append)
    except ftplib.error_perm as exc:
        raise FetchError(f"{remote}: {exc}") from exc
    payload = b"".join(chunks)
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)
    return len(payload)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", required=True, help="3DS IPv4 address")
    parser.add_argument("--port", type=int, default=5000)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument(
        "--out", type=Path, default=Path("device-logs"), help="local output directory"
    )
    parser.add_argument(
        "--file",
        action="append",
        dest="files",
        help="remote path to fetch (repeatable); defaults to the boot log set",
    )
    parser.add_argument(
        "--tail",
        type=int,
        default=40,
        help="print this many trailing lines of boot.log (0 to disable)",
    )
    args = parser.parse_args(argv)

    remote_files = tuple(args.files) if args.files else DEFAULT_REMOTE_FILES
    failures: list[str] = []
    fetched: list[Path] = []

    try:
        ftp = ftplib.FTP(timeout=args.timeout)
        ftp.connect(args.host, args.port)
        ftp.login()
    except OSError as exc:
        print(f"error: cannot reach {args.host}:{args.port}: {exc}", file=sys.stderr)
        return 2

    try:
        for remote in remote_files:
            destination = args.out / Path(remote).name
            try:
                size = fetch_one(ftp, remote, destination)
            except FetchError as exc:
                failures.append(str(exc))
                continue
            fetched.append(destination)
            print(f"fetched {remote} -> {destination} ({size} bytes)")
    finally:
        try:
            ftp.quit()
        except OSError:
            ftp.close()

    boot_log = args.out / "boot.log"
    if args.tail > 0 and boot_log.is_file():
        lines = boot_log.read_text(encoding="utf-8", errors="replace").splitlines()
        print(f"\n--- last {min(args.tail, len(lines))} lines of boot.log ---")
        for line in lines[-args.tail :]:
            print(line)

    for failure in failures:
        print(f"warning: {failure}", file=sys.stderr)
    if not fetched:
        print("error: nothing was fetched", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
