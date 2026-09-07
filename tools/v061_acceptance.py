#!/usr/bin/env python3
"""Generate a fail-closed v0.6.1 PASS/FAIL/NOT_PROVEN ledger."""

from __future__ import annotations

import argparse
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from validate_sd_tree import ValidationError, validate_sd_tree
except ModuleNotFoundError:  # Support imports from the repository root.
    from .validate_sd_tree import ValidationError, validate_sd_tree


DEVICE_IDS = tuple(f"D{number:02d}" for number in range(1, 13))
BOOT_IDENTITY_PREFIX = "acceptance-identity: "
BOOT_IDENTITY_SCHEMA = "corsixth-old3ds-boot-v1"
REQUIRED_STAGES = (
    "S10", "S20", "S30", "S35", "S40", "S45",
    "S50", "S60", "S70", "S80", "S90", "S100",
)


def item(result: str, evidence: Any) -> dict[str, Any]:
    return {"result": result, "evidence": evidence}


def load_json(path: Path | None, label: str) -> tuple[dict[str, Any], str | None]:
    if path is None:
        return {}, f"{label} was not supplied"
    if not path.is_file():
        return {}, f"{label} is missing: {path}"
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        return {}, f"cannot read {label}: {exc}"
    if not isinstance(value, dict):
        return {}, f"{label} must be a JSON object"
    return value, None


def parse_python_unittest_log(path: Path | None) -> tuple[dict[str, Any] | None, str | None]:
    if path is None or not path.is_file():
        return None, f"Python raw test log is missing: {path}"
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return None, f"cannot read Python raw test log: {exc}"
    totals = re.findall(r"^Ran (\d+) tests? in ", text, flags=re.MULTILINE)
    terminal = re.findall(r"^(OK(?: \([^\n]+\))?|FAILED(?: \([^\n]+\))?)$", text, flags=re.MULTILINE)
    if len(totals) != 1 or len(terminal) != 1:
        return None, "Python raw test log has no unique unittest result"
    tests = int(totals[0])
    status = terminal[0]

    def count(name: str) -> int:
        match = re.search(rf"\b{name}=(\d+)\b", status)
        return int(match.group(1)) if match else 0

    failed = count("failures")
    errors = count("errors")
    skipped = count("skipped")
    skip_records = []
    for line in text.splitlines():
        match = re.match(r"^(?P<test>.+?) \.\.\. skipped (?P<reason>.+)$", line)
        if match:
            skip_records.append(
                {"reason": match.group("reason"), "test": match.group("test")}
            )
    if status.startswith("FAILED") and failed == 0 and errors == 0:
        return None, "Python FAILED result omits failure/error counts"
    if skipped != len(skip_records):
        return None, "Python skipped count lacks exact verbose skip records"
    passed = tests - failed - errors - skipped
    if passed < 0:
        return None, "Python raw test counts are internally inconsistent"
    return {
        "tests": tests,
        "passed": passed,
        "failed": failed,
        "errors": errors,
        "skip_records": skip_records,
        "skipped": skipped,
    }, None


def _gate(rows: list[dict[str, Any]]) -> str:
    results = [row["result"] for row in rows]
    if "FAIL" in results:
        return "FAIL"
    return "PASS" if results and all(result == "PASS" for result in results) else "OPEN"


def _iso8601(value: object, label: str) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{label} is missing")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"{label} must include a timezone")
    return parsed


def validate_deploy(
    deploy: dict[str, Any], package: dict[str, Any]
) -> tuple[bool, dict[str, Any]]:
    expected = {
        "binarySha256": package["binary_sha256"],
        "manifestSha256": package["manifest_sha256"],
        "filesVerified": package["file_count"] + 1,
        "bytesVerified": package["total_bytes"],
    }
    mismatches = {
        key: {"expected": value, "actual": deploy.get(key)}
        for key, value in expected.items()
        if deploy.get(key) != value
    }
    required_identity = {
        "deploymentId": deploy.get("deploymentId"),
        "deviceId": deploy.get("deviceId"),
        "deployedAt": deploy.get("deployedAt"),
    }
    try:
        _iso8601(required_identity["deployedAt"], "deployedAt")
    except (TypeError, ValueError) as exc:
        mismatches["deployedAt"] = {"error": str(exc)}
    for key in ("deploymentId", "deviceId"):
        if not isinstance(required_identity[key], str) or not required_identity[key]:
            mismatches[key] = {"error": f"{key} is missing"}
    if deploy.get("ok") is not True:
        mismatches["ok"] = {"expected": True, "actual": deploy.get("ok")}
    return not mismatches, {"expected": expected, "identity": required_identity, "mismatches": mismatches}


def validate_boot(
    path: Path,
    package: dict[str, Any],
    deploy: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    if not path.is_file():
        return False, {"error": f"boot log is missing: {path}"}
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        return False, {"error": "boot log is empty"}
    identity_lines = [line for line in text.splitlines() if line.startswith(BOOT_IDENTITY_PREFIX)]
    if len(identity_lines) != 1:
        return False, {"error": "boot log has no unique candidate/device identity record"}
    try:
        identity = json.loads(identity_lines[0][len(BOOT_IDENTITY_PREFIX):])
    except json.JSONDecodeError as exc:
        return False, {"error": f"boot identity is invalid JSON: {exc}"}
    expected_identity = {
        "schema": BOOT_IDENTITY_SCHEMA,
        "candidate_commit": package["candidate"]["commit"],
        "candidate_tree": package["candidate"]["tree"],
        "binary_sha256": package["binary_sha256"],
        "manifest_sha256": package["manifest_sha256"],
        "deployment_id": deploy.get("deploymentId"),
        "device_id": deploy.get("deviceId"),
    }
    mismatches = {
        key: {"expected": value, "actual": identity.get(key) if isinstance(identity, dict) else None}
        for key, value in expected_identity.items()
        if not isinstance(identity, dict) or identity.get(key) != value
    }
    try:
        boot_started = _iso8601(
            identity.get("boot_started_at") if isinstance(identity, dict) else None,
            "boot_started_at",
        )
        deployed = _iso8601(deploy.get("deployedAt"), "deployedAt")
        if boot_started < deployed:
            mismatches["boot_started_at"] = {
                "error": "boot predates this deployment",
                "actual": identity.get("boot_started_at") if isinstance(identity, dict) else None,
            }
    except (TypeError, ValueError) as exc:
        mismatches["boot_started_at"] = {"error": str(exc)}
    if mismatches:
        return False, {"identity_mismatches": mismatches}

    positions = [text.find(f"stage[{stage}]") for stage in REQUIRED_STAGES]
    missing = [stage for stage, position in zip(REQUIRED_STAGES, positions) if position < 0]
    ordered = positions == sorted(positions) if not missing else False
    complete_position = text.find("runtime: boot complete")
    complete = complete_position > positions[-1] if positions and not missing else False
    if missing or not ordered or not complete:
        return False, {
            "complete_marker": complete,
            "missing_stages": missing,
            "ordered": ordered,
        }
    return True, {"identity": identity, "stages": list(REQUIRED_STAGES)}


def build(args: argparse.Namespace) -> dict[str, Any]:
    host, host_error = load_json(args.host_summary, "host summary")
    deploy, deploy_error = load_json(args.deploy_report, "deploy report")
    budget, budget_error = load_json(args.heap_budget, "heap budget")
    python_log = getattr(args, "python_test_log", None)
    if python_log is None and args.host_summary is not None:
        python_log = args.host_summary.parent / "python-tests.log"
    python_counts, python_error = parse_python_unittest_log(python_log)

    package_report: dict[str, Any] | None = None
    package_error: str | None = None
    try:
        package_report = validate_sd_tree(args.package, require_mode="loose")
    except (OSError, ValidationError) as exc:
        package_error = str(exc)

    matrices = host.get("matrices", []) if not host_error else []
    all_matrices = bool(matrices) and all(
        isinstance(row, dict)
        and isinstance(row.get("ctest_total"), int)
        and row.get("ctest_total", 0) > 0
        and row.get("ctest_failed") == 0
        for row in matrices
    )
    sanitized = any(
        isinstance(row, dict)
        and row.get("name") == "gcc-sanitized"
        and row.get("ctest_total", 0) > 0
        and row.get("ctest_failed") == 0
        for row in matrices
    )
    expected_skips = set(getattr(args, "expected_python_skip", ()) or ())
    observed_skips = {
        row["test"] for row in python_counts.get("skip_records", [])
    } if python_counts else set()
    unexpected_skips = sorted(observed_skips - expected_skips)
    missing_expected_skips = sorted(expected_skips - observed_skips)
    python_consistent = bool(
        python_counts
        and host.get("python_tests") == python_counts["tests"]
        and host.get("python_skipped", 0) == python_counts["skipped"]
    )
    python_pass = bool(
        python_consistent
        and python_counts
        and python_counts["tests"] > 0
        and python_counts["failed"] == 0
        and python_counts["errors"] == 0
        and not unexpected_skips
        and not missing_expected_skips
    )
    python_evidence: dict[str, Any] = {
        "counts": python_counts,
        "error": python_error,
        "expected_skips": sorted(expected_skips),
        "missing_expected_skips": missing_expected_skips,
        "raw_log": str(python_log) if python_log else None,
        "summary_matches_raw": python_consistent,
        "unexpected_skips": unexpected_skips,
    }
    host_items = {
        "H01": item(
            "PASS"
            if not host_error and host.get("actual_upstream_api_checked") is True
            else "FAIL",
            host_error or "pinned integration/API contract",
        ),
        "H02": item(
            "PASS" if not host_error and host.get("cpp_failed") == 0 and host.get("cpp_tests", 0) > 0 else "FAIL",
            {"failed": host.get("cpp_failed"), "tests": host.get("cpp_tests"), "input_error": host_error},
        ),
        "H03": item("PASS" if python_pass else "FAIL", python_evidence),
        "H04": item(
            "PASS" if sanitized and all_matrices else "FAIL",
            {"all_matrices": all_matrices, "sanitized": sanitized},
        ),
        "H05": item(
            "PASS"
            if not host_error and host.get("arm_codegen_checked") is True
            else "FAIL",
            "ARMv6K code generation audit",
        ),
        "H06": item(
            "PASS"
            if not host_error
            and host.get("true_3ds_cross_build_executed") is True
            and not budget_error
            and budget.get("pass") is True
            else "FAIL",
            {
                "cross": host.get("true_3ds_cross_build_executed"),
                "heap": budget.get("valueBytes"),
                "input_error": budget_error or host_error,
            },
        ),
        "H07": item("PASS" if package_report else "FAIL", package_report or {"error": package_error}),
    }

    device = {identifier: item("NOT_PROVEN", "requires current Old 3DS raw evidence") for identifier in DEVICE_IDS}
    deploy_ok = False
    if args.deploy_report is not None:
        if deploy_error or package_report is None:
            device["D01"] = item("FAIL", {"deploy_error": deploy_error, "package_error": package_error})
        else:
            deploy_ok, evidence = validate_deploy(deploy, package_report)
            device["D01"] = item("PASS" if deploy_ok else "FAIL", evidence)

    if args.boot_log is not None:
        if package_report is None or not deploy_ok:
            device["D02"] = item("FAIL", {"error": "boot evidence lacks a validated package/deployment identity"})
        else:
            boot_ok, boot_evidence = validate_boot(args.boot_log, package_report, deploy)
            device["D02"] = item("PASS" if boot_ok else "FAIL", boot_evidence)
            if args.boot_log.is_file():
                boot_text = args.boot_log.read_text(encoding="utf-8", errors="replace")
                probes = (
                    "heap-probe[MAIN MENU]: PASS" in boot_text
                    and "heap-probe[LEVEL READY]: PASS" in boot_text
                )
                device["D10"] = item(
                    "PASS" if boot_ok and probes else "FAIL",
                    "current bound boot log: menu and level probes",
                )
                injected = "failure-injection[native-error]: PASS" in boot_text
                device["D11"] = item(
                    "PASS" if boot_ok and injected else "FAIL",
                    "active native-error injection evidence",
                )

    gate_a = _gate(list(host_items.values()))
    gate_b = _gate([device["D01"]])
    gate_c = _gate(list(device.values()))
    gates = {"A_host_cross": gate_a, "B_install_identity": gate_b, "C_real_device": gate_c}
    if "FAIL" in gates.values():
        release = "FAIL"
    elif all(value == "PASS" for value in gates.values()):
        release = "PASS"
    else:
        release = "NOT_PROVEN"
    return {
        "format": 2,
        "version": "0.6.1",
        "host": host_items,
        "device": device,
        "gates": gates,
        "package": package_report or {"error": package_error},
        "release": release,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host-summary", type=Path, required=True)
    parser.add_argument("--python-test-log", type=Path)
    parser.add_argument(
        "--expected-python-skip",
        action="append",
        default=[],
        help="exact verbose unittest test label allowed to skip; repeatable",
    )
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
    return 0 if result["release"] == "PASS" else 2


if __name__ == "__main__":
    raise SystemExit(main())
