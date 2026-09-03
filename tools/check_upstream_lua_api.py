#!/usr/bin/env python3
"""Validate the exact CorsixTH Lua surface used by the Old 3DS adapter.

The check is intentionally literal and fail-closed. A future upstream release
must be reviewed and the contract updated instead of silently accepting API
drift that would surface only after pressing a button on hardware.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence


class ApiContractError(RuntimeError):
    pass


@dataclass(frozen=True)
class MissingLiteral:
    path: str
    literal: str


def load_contract(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ApiContractError(f"cannot read API contract {path}: {exc}") from exc
    if data.get("format") != 1 or not isinstance(data.get("contracts"), list):
        raise ApiContractError("unsupported API contract format")
    return data


def check_upstream(root: Path, contract: dict) -> list[MissingLiteral]:
    root = root.resolve()
    missing: list[MissingLiteral] = []
    for entry in contract["contracts"]:
        relative = entry.get("path")
        literals = entry.get("required_literals")
        if not isinstance(relative, str) or not isinstance(literals, list):
            raise ApiContractError("invalid contract entry")
        source = root / relative
        try:
            text = source.read_text(encoding="utf-8-sig")
        except OSError:
            missing.extend(MissingLiteral(relative, literal) for literal in literals)
            continue
        for literal in literals:
            if not isinstance(literal, str):
                raise ApiContractError("contract literal must be a string")
            if literal not in text:
                missing.append(MissingLiteral(relative, literal))
    return missing


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("upstream", type=Path, help="root of a CorsixTH checkout")
    parser.add_argument(
        "--contract",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "config"
        / "corsixth-lua-api-v0.70.1.json",
    )
    parser.add_argument("--json", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        contract = load_contract(args.contract)
        missing = check_upstream(args.upstream, contract)
    except ApiContractError as exc:
        if args.json:
            print(json.dumps({"ok": False, "error": str(exc)}, indent=2, sort_keys=True))
        else:
            print(f"error: {exc}", file=sys.stderr)
        return 2

    payload = {
        "ok": not missing,
        "tag": contract.get("upstream_tag"),
        "commit": contract.get("upstream_commit"),
        "checked_files": len(contract["contracts"]),
        "missing": [item.__dict__ for item in missing],
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    elif missing:
        for item in missing:
            print(f"missing {item.literal!r} in {item.path}", file=sys.stderr)
    else:
        print(
            f"CorsixTH Lua API contract OK: {payload['checked_files']} files, "
            f"{payload['tag']} ({payload['commit']})"
        )
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
