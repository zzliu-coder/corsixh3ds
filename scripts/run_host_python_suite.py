#!/usr/bin/env python3
"""Candidate-bound, manifest-driven host Python test runner.

This is the sole discovery, selection, execution, and accounting boundary for
the host Python suite.  Its verdict is derived from recorded unittest events;
callers cannot supply counts or a status.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import subprocess
import sys
import traceback
import unittest
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


SCHEMA = "cth3ds.host-python-suite-result/v1"
MANIFEST_SCHEMA = "cth3ds.host-python-suite-manifest/v1"


def canonical(value: Any) -> bytes:
    return (json.dumps(value, indent=2, sort_keys=True) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: pathlib.Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def ids_sha256(ids: Iterable[str]) -> str:
    return sha256_bytes(("\n".join(sorted(ids)) + "\n").encode("utf-8"))


def git(repo: pathlib.Path, *args: str) -> str:
    result = subprocess.run(
        ["/usr/bin/git", "-C", str(repo), *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env={"PATH": "/usr/bin:/bin", "LC_ALL": "C", "TZ": "UTC"},
    )
    if result.returncode:
        raise RuntimeError(
            "git %s failed: %s"
            % (" ".join(args), result.stderr.decode(errors="replace").strip())
        )
    return result.stdout.decode("utf-8", errors="strict").strip()


def flatten(suite: unittest.TestSuite) -> Iterable[unittest.TestCase]:
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from flatten(item)
        else:
            yield item


def discover(repo: pathlib.Path) -> Tuple[List[str], Dict[str, unittest.TestCase]]:
    tools = str(repo / "tools")
    if tools not in sys.path:
        sys.path.insert(0, tools)
    previous = pathlib.Path.cwd()
    try:
        os.chdir(str(repo))
        suite = unittest.defaultTestLoader.discover(
            str(repo / "tests"), pattern="test_*.py"
        )
    finally:
        os.chdir(str(previous))
    tests = list(flatten(suite))
    ids = [test.id() for test in tests]
    mapping: Dict[str, unittest.TestCase] = {}
    for test_id, test in zip(ids, tests):
        if test_id in mapping:
            raise RuntimeError("duplicate discovered test ID: %s" % test_id)
        mapping[test_id] = test
    return sorted(ids), mapping


def load_manifest(path: pathlib.Path) -> Mapping[str, Any]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    if value.get("schema") != MANIFEST_SCHEMA:
        raise RuntimeError("manifest schema mismatch")
    baseline = value.get("baseline")
    selected = value.get("test_ids")
    if not isinstance(baseline, dict) or not isinstance(selected, list) or not all(
        isinstance(item, str) and item for item in selected
    ):
        raise RuntimeError("manifest test IDs malformed")
    if len(selected) != len(set(selected)):
        raise RuntimeError("manifest contains duplicate test IDs")
    if selected != sorted(selected):
        raise RuntimeError("manifest test IDs are not sorted")
    baseline_ids = baseline.get("test_ids")
    if not isinstance(baseline_ids, list) or baseline_ids != sorted(baseline_ids):
        raise RuntimeError("manifest baseline IDs malformed")
    if len(baseline_ids) != len(set(baseline_ids)):
        raise RuntimeError("manifest baseline contains duplicate IDs")
    if baseline.get("count") != len(baseline_ids):
        raise RuntimeError("manifest baseline count mismatch")
    if baseline.get("sorted_ids_sha256") != ids_sha256(baseline_ids):
        raise RuntimeError("manifest baseline hash mismatch")
    if not set(baseline_ids).issubset(selected):
        raise RuntimeError("manifest deletes a frozen baseline ID")
    if value.get("selected_count") != len(selected):
        raise RuntimeError("manifest selected count mismatch")
    if value.get("selected_sorted_ids_sha256") != ids_sha256(selected):
        raise RuntimeError("manifest selected hash mismatch")
    allowed = value.get("allowed_skip_reason_prefixes", [])
    if not isinstance(allowed, list) or not all(isinstance(item, str) for item in allowed):
        raise RuntimeError("manifest skip policy malformed")
    return value


def fixture_prefix(test_id: str) -> Optional[str]:
    if test_id.startswith("setUpClass (") or test_id.startswith("tearDownClass ("):
        return test_id.split("(", 1)[1].rstrip(")") + "."
    if test_id.startswith("setUpModule (") or test_id.startswith("tearDownModule ("):
        return test_id.split("(", 1)[1].rstrip(")") + "."
    return None


class RecordingResult(unittest.TextTestResult):
    def __init__(self, *args: Any, selected_ids: Sequence[str], **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.selected_ids = tuple(selected_ids)
        self.outcomes: Dict[str, Dict[str, Any]] = {}
        self.synthetic_events: List[Dict[str, str]] = []

    def _targets(self, test: Any) -> List[str]:
        test_id = test.id()
        if test_id in self.selected_ids:
            return [test_id]
        prefix = fixture_prefix(test_id)
        targets = [item for item in self.selected_ids if prefix and item.startswith(prefix)]
        if not targets:
            self.synthetic_events.append({"id": test_id, "event": "unmapped-fixture"})
        return targets

    def _record(self, test: Any, outcome: str, detail: Optional[str] = None) -> None:
        for test_id in self._targets(test):
            row: Dict[str, Any] = {"id": test_id, "outcome": outcome}
            if detail:
                row["detail"] = detail
            self.outcomes[test_id] = row

    def addSuccess(self, test: Any) -> None:
        super().addSuccess(test)
        self._record(test, "passed")

    def addFailure(self, test: Any, err: Any) -> None:
        super().addFailure(test, err)
        self._record(test, "failed", self._exc_info_to_string(err, test))

    def addError(self, test: Any, err: Any) -> None:
        super().addError(test, err)
        self._record(test, "errors", self._exc_info_to_string(err, test))

    def addSkip(self, test: Any, reason: str) -> None:
        super().addSkip(test, reason)
        self._record(test, "skipped", reason)

    def addExpectedFailure(self, test: Any, err: Any) -> None:
        super().addExpectedFailure(test, err)
        self._record(test, "failed", "expected failure is forbidden")

    def addUnexpectedSuccess(self, test: Any) -> None:
        super().addUnexpectedSuccess(test)
        self._record(test, "failed", "unexpected success is forbidden")


class RecordingRunner(unittest.TextTestRunner):
    resultclass = RecordingResult

    def __init__(self, *args: Any, selected_ids: Sequence[str], **kwargs: Any) -> None:
        self.selected_ids = tuple(selected_ids)
        super().__init__(*args, **kwargs)

    def _makeResult(self) -> RecordingResult:
        return self.resultclass(
            self.stream,
            self.descriptions,
            self.verbosity,
            selected_ids=self.selected_ids,
        )


def execute(repo: pathlib.Path, manifest_path: pathlib.Path) -> Dict[str, Any]:
    manifest = load_manifest(manifest_path)
    selected_ids = list(manifest["test_ids"])
    discovered_ids, discovered = discover(repo)
    missing = sorted(set(selected_ids) - set(discovered_ids))
    extra = sorted(set(discovered_ids) - set(selected_ids))
    duplicate: List[str] = []
    outcomes: Dict[str, Dict[str, Any]] = {}
    synthetic_events: List[Dict[str, str]] = []
    if not missing and not extra:
        suite = unittest.TestSuite([discovered[test_id] for test_id in selected_ids])
        previous = pathlib.Path.cwd()
        try:
            os.chdir(str(repo))
            result = RecordingRunner(
                stream=sys.stderr, verbosity=2, selected_ids=selected_ids
            ).run(suite)
        finally:
            os.chdir(str(previous))
        outcomes = result.outcomes
        synthetic_events = result.synthetic_events
    unstarted = sorted(set(selected_ids) - set(outcomes))
    rows = [outcomes[test_id] for test_id in selected_ids if test_id in outcomes]
    totals = {
        name: sum(row["outcome"] == name for row in rows)
        for name in ("passed", "failed", "errors", "skipped")
    }
    totals["selected"] = len(selected_ids)
    totals["accounted"] = sum(totals[name] for name in ("passed", "failed", "errors", "skipped"))
    allowed = tuple(manifest.get("allowed_skip_reason_prefixes", []))
    unexpected_skips = [
        row for row in rows
        if row["outcome"] == "skipped"
        and not any(row.get("detail", "").startswith(prefix) for prefix in allowed)
    ]
    failures = bool(
        missing or extra or duplicate or unstarted or synthetic_events
        or totals["failed"] or totals["errors"]
        or totals["accounted"] != totals["selected"] or unexpected_skips
    )
    executable = pathlib.Path(sys.executable).absolute()
    implementation = executable.resolve(strict=True)
    head = git(repo, "rev-parse", "HEAD^{commit}")
    tree = git(repo, "rev-parse", "HEAD^{tree}")
    parents = git(repo, "rev-list", "--parents", "-n", "1", "HEAD").split()[1:]
    tracked_dirty = bool(git(repo, "status", "--porcelain=v1", "--untracked-files=no"))
    if tracked_dirty:
        failures = True
    return {
        "schema": SCHEMA,
        "verdict": "FAIL" if failures else "PASS",
        "candidate": {
            "repository": str(repo), "commit": head, "tree": tree,
            "parents": parents, "tracked_worktree_clean": not tracked_dirty,
        },
        "interpreter": {
            "executable": str(executable),
            "implementation_realpath": str(implementation),
            "implementation_sha256": sha256_file(implementation),
            "version": sys.version,
            "implementation": sys.implementation.name,
            "cache_tag": sys.implementation.cache_tag,
        },
        "manifest": {
            "path": str(manifest_path), "sha256": sha256_file(manifest_path),
            "baseline_count": manifest["baseline"]["count"],
            "baseline_sorted_ids_sha256": manifest["baseline"]["sorted_ids_sha256"],
        },
        "discovery": {
            "count": len(discovered_ids), "unique": len(set(discovered_ids)),
            "sorted_ids_sha256": ids_sha256(discovered_ids),
        },
        "selection": {
            "count": len(selected_ids), "unique": len(set(selected_ids)),
            "sorted_ids_sha256": ids_sha256(selected_ids),
        },
        "execution": {
            "count": len(rows), "sorted_ids_sha256": ids_sha256(row["id"] for row in rows),
            "outcomes": rows, "totals": totals,
        },
        "mismatches": {
            "missing_ids": missing, "extra_ids": extra, "duplicate_ids": duplicate,
            "unstarted_ids": unstarted, "synthetic_events": synthetic_events,
            "unexpected_skips": unexpected_skips,
        },
    }


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(allow_abbrev=False)
    result.add_argument("--repo", type=pathlib.Path)
    result.add_argument("--manifest", type=pathlib.Path)
    result.add_argument("--output", type=pathlib.Path, required=True)
    return result


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parser().parse_args(argv)
    root = pathlib.Path(__file__).resolve().parents[1]
    repo = (args.repo or root).resolve(strict=True)
    manifest = (args.manifest or repo / "tests/host-python-suite.json").resolve(strict=True)
    output = args.output.absolute()
    try:
        payload = execute(repo, manifest)
    except Exception as error:
        payload = {
            "schema": SCHEMA, "verdict": "FAIL",
            "runner_error": "%s: %s" % (type(error).__name__, error),
            "traceback": traceback.format_exc(),
        }
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(canonical(payload))
    temporary.replace(output)
    print("HOST_PYTHON_SUITE_RECEIPT=" + json.dumps(payload, sort_keys=True, separators=(",", ":")))
    return 0 if payload.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
