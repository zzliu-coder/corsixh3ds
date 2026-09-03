#!/usr/bin/env python3
"""Generate the v0.6.1 PASS/FAIL/NOT_PROVEN acceptance ledger."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


DEVICE_IDS = tuple(f"D{number:02d}" for number in range(1, 13))


def item(result: str, evidence: str) -> dict[str, str]:
    return {"result": result, "evidence": evidence}


def load_json(path: Path | None) -> dict:
    if path is None or not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def build(args: argparse.Namespace) -> dict:
    host = load_json(args.host_summary)
    deploy = load_json(args.deploy_report)
    budget = load_json(args.heap_budget)
    boot = args.boot_log.read_text(encoding="utf-8", errors="replace") if args.boot_log and args.boot_log.is_file() else ""
    package = args.package
    game_absent = bool(package and package.is_dir() and not (package / "game").exists())

    matrices = host.get("matrices", [])
    all_matrices = bool(matrices) and all(row.get("ctest_failed") == 0 for row in matrices)
    sanitized = any(row.get("name") == "gcc-sanitized" and row.get("ctest_failed") == 0 for row in matrices)
    host_items = {
        "H01": item("PASS" if host.get("actual_upstream_api_checked") else "NOT_PROVEN", "pinned integration/API contract"),
        "H02": item("PASS" if host.get("cpp_failed") == 0 and host.get("cpp_tests", 0) > 0 else "FAIL", f"{host.get('cpp_tests')} C++ tests"),
        "H03": item("PASS" if host.get("python_tests", 0) > 0 else "FAIL", f"{host.get('python_tests')} Python tests; skipped={host.get('python_skipped')}"),
        "H04": item("PASS" if sanitized and all_matrices else "FAIL", "sanitizer and compiler matrices"),
        "H05": item("PASS" if host.get("arm_codegen_checked") else "NOT_PROVEN", "ARMv6K code generation audit"),
        "H06": item("PASS" if host.get("true_3ds_cross_build_executed") and budget.get("pass") else "FAIL", f"cross={host.get('true_3ds_cross_build_executed')} heap={budget.get('valueBytes')}"),
        "H07": item("PASS" if game_absent else "FAIL", "no-game package excludes game/"),
    }

    device = {identifier: item("NOT_PROVEN", "requires current Old 3DS evidence") for identifier in DEVICE_IDS}
    if deploy.get("ok"):
        device["D01"] = item("PASS" if "CorsixTH-3DS.3dsx" in {row.get("path") for row in deploy.get("files", [])} else "FAIL", "transactional FTP readback report")
    required_stages = ("S10", "S20", "S30", "S35", "S40", "S45", "S50", "S60", "S70", "S80", "S90", "S100")
    if boot:
        missing = [stage for stage in required_stages if f"stage[{stage}]" not in boot]
        device["D02"] = item("PASS" if not missing else "FAIL", "missing=" + ",".join(missing))
        probe_ok = "heap-probe[MAIN MENU]: PASS" in boot and "heap-probe[LEVEL READY]: PASS" in boot
        device["D10"] = item("PASS" if probe_ok else "FAIL", "main-menu and level 2 MiB probes")
        fatal_visible = "attempt to call a nil value (field 'mainloop')" not in boot
        device["D11"] = item("PASS" if fatal_visible else "FAIL", "native error reporter log contract")

    gate_a = "PASS" if all(row["result"] == "PASS" for row in host_items.values()) else "OPEN"
    gate_b = "PASS" if deploy.get("ok") and device["D01"]["result"] == "PASS" else "OPEN"
    gate_c = "PASS" if all(row["result"] == "PASS" for row in device.values()) else "OPEN"
    return {
        "format": 1,
        "version": "0.6.1",
        "host": host_items,
        "device": device,
        "gates": {"A_host_cross": gate_a, "B_install_identity": gate_b, "C_real_device": gate_c},
        "release": "PASS" if gate_a == gate_b == gate_c == "PASS" else "NOT_PROVEN",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-summary", type=Path, required=True)
    parser.add_argument("--heap-budget", type=Path, required=True)
    parser.add_argument("--package", type=Path, required=True)
    parser.add_argument("--deploy-report", type=Path)
    parser.add_argument("--boot-log", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = build(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
