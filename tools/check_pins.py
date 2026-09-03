#!/usr/bin/env python3
"""Validate and query the immutable source manifest used by the 3DS build."""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Sequence

HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
REQUIRED_GIT = ("corsixth", "sdl2", "sdl2_mixer", "lua", "luafilesystem")


class PinError(RuntimeError):
    pass


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PinError(f"cannot read pin manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("format") != 1:
        raise PinError("unsupported pin manifest format")
    for name in REQUIRED_GIT:
        entry = value.get(name)
        if not isinstance(entry, dict):
            raise PinError(f"missing git pin: {name}")
        if not isinstance(entry.get("repository"), str) or not entry["repository"].startswith("https://"):
            raise PinError(f"invalid repository URL for {name}")
        commit = entry.get("commit")
        if not isinstance(commit, str) or HEX40.fullmatch(commit) is None:
            raise PinError(f"invalid 40-character commit for {name}")
    lpeg = value.get("lpeg")
    if not isinstance(lpeg, dict) or not isinstance(lpeg.get("url"), str):
        raise PinError("missing LPeg source pin")
    if not isinstance(lpeg.get("sha256"), str) or HEX64.fullmatch(lpeg["sha256"]) is None:
        raise PinError("invalid LPeg SHA-256")
    devkitpro = value.get("devkitpro")
    if not isinstance(devkitpro, dict) or not devkitpro.get("docker_image"):
        raise PinError("missing devkitPro Docker image pin")
    return value


def lookup(value: Any, dotted_key: str) -> Any:
    current = value
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            raise PinError(f"unknown pin key: {dotted_key}")
        current = current[part]
    return current


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--manifest",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "config/upstream-pins.json",
    )
    parser.add_argument("--get", metavar="DOTTED_KEY")
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        manifest = load_manifest(args.manifest)
        if args.get:
            value = lookup(manifest, args.get)
            if isinstance(value, (dict, list)):
                print(json.dumps(value, ensure_ascii=False, sort_keys=True))
            elif isinstance(value, bool):
                print("true" if value else "false")
            else:
                print(value)
            return 0
        if args.json:
            print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))
        else:
            print("Pinned sources verified")
            for name in REQUIRED_GIT:
                entry = manifest[name]
                print(f"  {name:15s} {entry['commit']}")
            print(f"  {'lpeg':15s} sha256:{manifest['lpeg']['sha256']}")
        return 0
    except PinError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
