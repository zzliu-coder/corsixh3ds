from __future__ import annotations

import concurrent.futures
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
EXACT_STRESS_RUNTIME = sys.version_info[:2] in {(3, 9), (3, 14)}
SERIAL_RUNS = 100 if EXACT_STRESS_RUNTIME else 1
CONCURRENT_RUNS = 100 if EXACT_STRESS_RUNTIME else 20
CONCURRENT_WORKERS = 20


def run_command_case(output: Path, matrix: str, marker: str, exit_code: int):
    return subprocess.run(
        [
            "bash",
            str(ROOT / "scripts" / "run_ci_command.sh"),
            matrix,
            str(output),
            "--",
            "bash",
            "-c",
            'printf "%s\\n" "$1"; exit "$2"',
            "diagnostic-case",
            marker,
            str(exit_code),
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        check=False,
    )


def read_summary_and_log(output: Path):
    summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))
    log_path = output / "command.log"
    content = log_path.read_bytes()
    return summary, log_path, content


FRESH_HEAD = "1" * 40
FRESH_TREE = "2" * 40
FRESH_PARENT = "3" * 40
FRESH_BUNDLE_SHA = "4" * 64
FRESH_BINDINGS = [
    "12345", "2", "fresh-chain-final-seal",
    f"official-fresh-chain-evidence-12345-2-{FRESH_HEAD}",
    FRESH_HEAD, FRESH_TREE, FRESH_PARENT,
    "https://example.invalid/input.tar", FRESH_BUNDLE_SHA,
]


def fresh_command(*arguments: object):
    return subprocess.run(
        ["bash", "-c", 'source "$1"; shift; cth3ds_fresh_evidence "$@"',
         "fresh-test", str(ROOT / "scripts" / "ci_diagnostics.sh"),
         *(str(value) for value in arguments)],
        cwd=ROOT, text=True, capture_output=True, check=False,
    )


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n")


def make_fresh_sources(root: Path):
    session = root / "session"
    envelope = root / "envelope"
    identity = {"commit": FRESH_HEAD, "tree": FRESH_TREE, "parents": [FRESH_PARENT]}
    write_json(envelope / "authority-binding.json",
               {"status": "PASS", "head": FRESH_HEAD, "tree": FRESH_TREE,
                "parents": [FRESH_PARENT]})
    write_json(envelope / "bundle-verification.json",
               {"status": "PASS", "manifest_sha256": "5" * 64,
                "sha256sums_sha256": "6" * 64})
    for name in ("bootstrap-summary.json", "environment-audit.json"):
        write_json(envelope / "environment" / name, {"status": "PASS"})
    for name in ("bundle-sha256-check.log", "install.log", "pip-bootstrap.log",
                 "pip-check.log", "record-normalization.log"):
        path = envelope / "environment" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PASS\n")
    journal = b'{"stage_id":"r4.n10_preflight","dependency_ids":[]}\n'
    for name in ("00-preflight/execution-journal.jsonl",
                 "50-matrix/execution-journal.jsonl"):
        path = session / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(journal)
    write_json(session / "50-matrix/receipt.json",
               {"passed": 60, "case_count": 60, "failed": 0,
                "review_session_id": "review-1", "candidate_identity": identity})
    write_json(session / "80-acceptance/base32/summary.json",
               {"passed": 32, "total": 32, "failed": 0})
    write_json(session / "80-acceptance/r4-additive22/summary.json",
               {"passed": 22, "total": 22, "failed": 0,
                "review_session_id": "review-1"})
    h2 = {"status": "PASS", "independent_process_count": 40,
          "sanitized": {"passed": 20, "total": 20},
          "non_sanitized": {"passed": 20, "total": 20}}
    write_json(session / "90-final-audit/h2-exact20/summary.json", h2)
    for profile in ("sanitized", "non_sanitized"):
        for index in range(1, 21):
            write_json(session / "90-final-audit/h2-exact20" /
                       f"{profile}-{index:02d}.json",
                       {"record": {"profile": profile, "process_index": index,
                        "run_id": f"{profile}-{index}", "exit_code": 0,
                        "exact_red_fact": True}, "observation": {"ok": True}})
    write_json(session / "90-final-audit/observed-dag.json",
               {"review_session_id": "review-1", "node_count": 18,
                "edge_count": 20, "cycle_count": 0})
    write_json(session / "90-final-audit/fresh-chain-result.json",
               {"review_session_id": "review-1", "candidate_identity": identity,
                "facts_checks": {"passed": 18, "total": 18},
                "matrix": {"passed": 60, "total": 60},
                "base_acceptance": {"passed": 32, "total": 32},
                "r4_acceptance": {"passed": 22, "total": 22},
                "composed_acceptance": {"passed": 54, "total": 54},
                "semantic_verify": "PASS", "construction_self_verification": "PASS",
                "independent_review": "NOT_PROVEN"})
    return session, envelope


def reseal_fresh_tree(root: Path) -> None:
    manifest_path = root / "artifact-manifest.json"
    manifest = json.loads(manifest_path.read_text())
    for row in manifest["payloads"]:
        raw = (root / row["path"]).read_bytes()
        row["bytes"] = len(raw)
        row["sha256"] = hashlib.sha256(raw).hexdigest()
    manifest_path.write_text(json.dumps(manifest, sort_keys=True,
                                        separators=(",", ":")) + "\n")
    names = sorted([row["path"] for row in manifest["payloads"]] +
                   ["artifact-manifest.json"])
    (root / "SHA256SUMS").write_text("".join(
        f"{hashlib.sha256((root / name).read_bytes()).hexdigest()}  {name}\n"
        for name in names))


def make_fresh_zip(root: Path, output: Path, extra_rows=()) -> str:
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in root.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(root).as_posix())
        for name, content in extra_rows:
            archive.writestr(name, content)
    return hashlib.sha256(output.read_bytes()).hexdigest()


class CiDiagnosticsTests(unittest.TestCase):
    def assert_log_artifact(self, summary, log_path: Path, content: bytes) -> None:
        self.assertEqual(summary["logs"], [str(log_path)])
        self.assertEqual(summary["log_validation_errors"], [])
        self.assertEqual(
            summary["log_artifacts"],
            [
                {
                    "path": str(log_path),
                    "byte_size": len(content),
                    "sha256": hashlib.sha256(content).hexdigest(),
                }
            ],
        )

    def assert_failure_case(self, output: Path, result, marker: str) -> None:
        self.assertEqual(result.returncode, 23, result.stderr)
        summary, log_path, content = read_summary_and_log(output)
        self.assertEqual(summary["status"], "FAIL")
        self.assertEqual(summary["stage"], "command")
        self.assertEqual(summary["exit_code"], 23)
        self.assertIn("exit", summary["failed_command"])
        self.assertEqual(content, f"{marker}\n".encode())
        self.assert_log_artifact(summary, log_path, content)
        tail_header = result.stderr.index(f"[cth3ds-ci] tail: {log_path}")
        raw_marker = result.stderr.index(marker, tail_header)
        machine_summary = result.stderr.index(
            "[cth3ds-ci] machine summary:", raw_marker
        )
        self.assertLess(tail_header, raw_marker)
        self.assertLess(raw_marker, machine_summary)

    def test_failure_injection_preserves_diagnostics_and_exit_code(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            first_summary = None
            first_identity = None
            for index in range(SERIAL_RUNS):
                output = temporary_root / f"failure-{index}"
                marker = f"bounded failure marker {index}"
                result = run_command_case(
                    output, "injected-failure", marker, 23
                )
                self.assert_failure_case(output, result, marker)
                if index == 0:
                    first_summary = json.loads(
                        (output / "summary.json").read_text(encoding="utf-8")
                    )
                    first_identity = json.loads(
                        (output / "identity.json").read_text(encoding="utf-8")
                    )

            assert first_summary is not None
            assert first_identity is not None
            summary = first_summary
            identity = first_identity
            self.assertEqual(summary["matrix"], "injected-failure")
            self.assertEqual(
                identity["source"]["commit"],
                subprocess.check_output(
                    ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
                ).strip(),
            )
            self.assertEqual(
                identity["source"]["tree"],
                subprocess.check_output(
                    ["git", "rev-parse", "HEAD^{tree}"], cwd=ROOT, text=True
                ).strip(),
            )
            self.assertEqual(
                identity["source"]["parents"],
                subprocess.check_output(
                    ["git", "rev-list", "--parents", "-n", "1", "HEAD"],
                    cwd=ROOT,
                    text=True,
                ).split()[1:],
            )

    def test_success_path_writes_machine_readable_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            for index in range(SERIAL_RUNS):
                output = temporary_root / f"success-{index}"
                marker = f"success marker {index}"
                result = run_command_case(
                    output, "injected-success", marker, 0
                )
                self.assertEqual(result.returncode, 0, result.stderr)
                summary, log_path, content = read_summary_and_log(output)
                self.assertEqual(summary["status"], "PASS")
                self.assertEqual(summary["exit_code"], 0)
                self.assertIsNone(summary["failed_command"])
                self.assertEqual(content, f"{marker}\n".encode())
                self.assert_log_artifact(summary, log_path, content)

    def test_fail_closed_preflight_keeps_summary(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "evidence"
            command = 'source "{}"; source "{}"; ci_diag_init preflight-failure "{}"; ci_diag_step preflight; die "forced preflight failure"'.format(
                ROOT / "scripts" / "common.sh",
                ROOT / "scripts" / "ci_diagnostics.sh",
                output,
            )
            result = subprocess.run(
                ["bash", "-c", command],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(result.returncode, 2, result.stderr)
            summary = json.loads((output / "summary.json").read_text())
            self.assertEqual(summary["status"], "FAIL")
            self.assertEqual(summary["stage"], "preflight")
            self.assertEqual(summary["failed_command"], "forced preflight failure")
            self.assertIn("machine summary:", result.stderr)

            root = Path(temporary) / "not-a-repository"
            root.mkdir()
            non_git_output = Path(temporary) / "non-git-evidence"
            environment = os.environ.copy()
            non_git_command = (
                'set -euo pipefail; CTH3DS_ROOT="$1"; export CTH3DS_ROOT; '
                'source "$2"; ci_diag_init non-git-root "$3"; '
                "printf 'must not execute\\n'"
            )
            non_git_result = subprocess.run(
                [
                    "bash",
                    "-c",
                    non_git_command,
                    "non-git-test",
                    str(root),
                    str(ROOT / "scripts" / "ci_diagnostics.sh"),
                    str(non_git_output),
                ],
                cwd=root,
                env=environment,
                text=True,
                capture_output=True,
                check=False,
            )

            self.assertNotEqual(non_git_result.returncode, 0)
            non_git_summary = json.loads(
                (non_git_output / "summary.json").read_text()
            )
            identity = json.loads((non_git_output / "identity.json").read_text())
            self.assertEqual(non_git_summary["status"], "FAIL")
            self.assertEqual(non_git_summary["stage"], "source-identity")
            self.assertEqual(identity["source"]["status"], "FAIL")
            self.assertNotIn("commit", identity["source"])
            self.assertNotIn("tree", identity["source"])
            self.assertNotIn("dirty", identity["source"])
            self.assertNotIn("must not execute", non_git_result.stdout)

            missing_output = Path(temporary) / "missing-log-evidence"
            missing_log = Path(temporary) / "missing.log"
            missing_command = (
                'source "$1"; ci_diag_init missing-log "$2"; '
                'ci_diag_step validation "$3"; ci_diag_mark_pass'
            )
            missing_result = subprocess.run(
                [
                    "bash",
                    "-c",
                    missing_command,
                    "missing-log-test",
                    str(ROOT / "scripts" / "ci_diagnostics.sh"),
                    str(missing_output),
                    str(missing_log),
                ],
                cwd=ROOT,
                text=True,
                capture_output=True,
                check=False,
            )
            self.assertEqual(missing_result.returncode, 74, missing_result.stderr)
            missing_summary = json.loads(
                (missing_output / "summary.json").read_text(encoding="utf-8")
            )
            self.assertEqual(missing_summary["status"], "FAIL")
            self.assertEqual(missing_summary["exit_code"], 74)
            self.assertTrue(missing_summary["log_validation_errors"])
            self.assertIn("error", missing_summary["log_artifacts"][0])

            concurrent_root = Path(temporary) / "concurrent"

            def execute(index: int):
                output = concurrent_root / str(index)
                marker = f"concurrent raw marker {index}"
                return output, marker, run_command_case(
                    output, "concurrent-failure", marker, 23
                )

            with concurrent.futures.ThreadPoolExecutor(
                max_workers=CONCURRENT_WORKERS
            ) as executor:
                outcomes = list(executor.map(execute, range(CONCURRENT_RUNS)))
            for output, marker, concurrent_result in outcomes:
                self.assert_failure_case(output, concurrent_result, marker)

            # Keep this adversarial Fresh-retention matrix inside an existing
            # unittest method so the public host inventory remains exactly 149 IDs.
            fresh_root = Path(temporary) / "fresh-retention"
            session, envelope = make_fresh_sources(fresh_root)
            sealed = fresh_root / "sealed"
            staged = fresh_command("stage", session, envelope, sealed, "success",
                                   *FRESH_BINDINGS)
            self.assertEqual(staged.returncode, 0, staged.stderr)
            staged_result = json.loads(staged.stdout)
            self.assertEqual(staged_result["entry_count"], 58)
            self.assertEqual(staged_result["payload_count"], 56)
            self.assertEqual(len([p for p in sealed.rglob("*") if p.is_file()]), 58)

            valid = fresh_command("validate", sealed, *FRESH_BINDINGS)
            self.assertEqual(valid.returncode, 0, valid.stderr)

            manifest = json.loads((sealed / "artifact-manifest.json").read_text())
            payload_paths = [row["path"] for row in manifest["payloads"]]
            self.assertEqual(len(payload_paths), 56)
            self.assertEqual(len(set(payload_paths)), 56)
            for index, relative in enumerate(payload_paths):
                with self.subTest(fresh_missing_payload=relative):
                    mutated = fresh_root / f"missing-{index}"
                    shutil.copytree(sealed, mutated)
                    (mutated / relative).unlink()
                    result = fresh_command("validate", mutated, *FRESH_BINDINGS)
                    self.assertEqual(result.returncode, 86, result.stderr)
                    self.assertEqual(json.loads(result.stderr)["code"],
                                     "FRESH_ENTRY_SET_MISMATCH")

            raw_tamper = fresh_root / "raw-tamper"
            shutil.copytree(sealed, raw_tamper)
            target = raw_tamper / "50-matrix/receipt.json"
            target.write_bytes(target.read_bytes() + b" ")
            result = fresh_command("validate", raw_tamper, *FRESH_BINDINGS)
            self.assertEqual(json.loads(result.stderr)["code"],
                             "FRESH_PAYLOAD_DIGEST_MISMATCH")

            def semantic_case(number, relative, change, expected_code):
                mutated = fresh_root / f"semantic-{number}"
                shutil.copytree(sealed, mutated)
                path = mutated / relative
                body = json.loads(path.read_text())
                change(body)
                write_json(path, body)
                reseal_fresh_tree(mutated)
                outcome = fresh_command("validate", mutated, *FRESH_BINDINGS)
                self.assertEqual(outcome.returncode, 86, outcome.stderr)
                self.assertEqual(json.loads(outcome.stderr)["code"], expected_code)

            semantic_rows = [
                ("matrix", "50-matrix/receipt.json",
                 lambda row: row.update(passed=59), "FRESH_MATRIX_COUNT_MISMATCH"),
                ("base", "80-acceptance/base/summary.json",
                 lambda row: row.update(passed=31), "FRESH_BASE_COUNT_MISMATCH"),
                ("r4", "80-acceptance/r4/summary.json",
                 lambda row: row.update(passed=21), "FRESH_R4_COUNT_MISMATCH"),
                ("composed", "90-final-audit/fresh-chain-result.json",
                 lambda row: row["composed_acceptance"].update(passed=53),
                 "FRESH_RESULT_COUNT_MISMATCH"),
                ("h2-summary", "90-final-audit/h2-exact20/summary.json",
                 lambda row: row.update(independent_process_count=39),
                 "FRESH_H2_SUMMARY_MISMATCH"),
                ("h2-record", "90-final-audit/h2-exact20/sanitized-01.json",
                 lambda row: row["record"].update(exact_red_fact=False),
                 "FRESH_H2_RECORD_MISMATCH"),
                ("dag", "90-final-audit/observed-dag.json",
                 lambda row: row.update(edge_count=19), "FRESH_DAG_MISMATCH"),
                ("authority", "authority-binding.json",
                 lambda row: row.update(status="FAIL"),
                 "FRESH_AUTHORITY_BINDING_MISMATCH"),
                ("bundle", "bundle-verification.json",
                 lambda row: row.update(status="FAIL"),
                 "FRESH_BUNDLE_VERIFICATION_MISMATCH"),
                ("review-session", "90-final-audit/fresh-chain-result.json",
                 lambda row: row.update(review_session_id="wrong"),
                 "FRESH_REVIEW_SESSION_MISMATCH"),
            ]
            for number, relative, change, expected_code in semantic_rows:
                with self.subTest(fresh_semantic=number):
                    semantic_case(number, relative, change, expected_code)

            structural_rows = [
                ("extra", lambda root: (root / "extra.txt").write_text("x")),
                ("hidden", lambda root: (root / ".hidden").write_text("x")),
                ("case", lambda root: (root / "AUTHORITY-BINDING.JSON").write_text("x")),
                ("symlink", lambda root: (root / "link").symlink_to("authority-binding.json")),
                ("broken-symlink", lambda root: (root / "broken").symlink_to("absent")),
                ("special", lambda root: os.mkfifo(root / "fifo")),
            ]
            for number, (name, mutate) in enumerate(structural_rows):
                with self.subTest(fresh_structure=name):
                    mutated = fresh_root / f"structure-{number}"
                    shutil.copytree(sealed, mutated)
                    mutate(mutated)
                    outcome = fresh_command("validate", mutated, *FRESH_BINDINGS)
                    self.assertEqual(outcome.returncode, 86, outcome.stderr)
                    self.assertIn(json.loads(outcome.stderr)["code"], {
                        "FRESH_ENTRY_SET_MISMATCH", "FRESH_HIDDEN_ENTRY",
                        "FRESH_CASE_COLLISION", "FRESH_NODE_INVALID",
                        "FRESH_PAYLOAD_DIGEST_MISMATCH"})

            wrong_rows = []
            wrong_run = list(FRESH_BINDINGS)
            wrong_run[0] = "999"
            wrong_run[3] = f"official-fresh-chain-evidence-999-2-{FRESH_HEAD}"
            wrong_rows.append(("run", wrong_run, "FRESH_RUN_BINDING_MISMATCH"))
            wrong_attempt = list(FRESH_BINDINGS)
            wrong_attempt[1] = "3"
            wrong_attempt[3] = f"official-fresh-chain-evidence-12345-3-{FRESH_HEAD}"
            wrong_rows.append(("attempt", wrong_attempt, "FRESH_RUN_BINDING_MISMATCH"))
            wrong_job = list(FRESH_BINDINGS)
            wrong_job[2] = "other-job"
            wrong_rows.append(("job", wrong_job, "FRESH_RUN_BINDING_MISMATCH"))
            wrong_head = list(FRESH_BINDINGS)
            wrong_head[4] = "a" * 40
            wrong_head[3] = f"official-fresh-chain-evidence-12345-2-{'a' * 40}"
            wrong_rows.append(("head", wrong_head, "FRESH_RUN_BINDING_MISMATCH"))
            for position, name, code in (
                    (5, "tree", "FRESH_CANDIDATE_BINDING_MISMATCH"),
                    (6, "parent", "FRESH_CANDIDATE_BINDING_MISMATCH"),
                    (7, "bundle-url", "FRESH_BUNDLE_BINDING_MISMATCH"),
                    (8, "bundle-sha", "FRESH_BUNDLE_BINDING_MISMATCH")):
                values = list(FRESH_BINDINGS)
                values[position] = ("b" * 40 if position in (5, 6) else
                                    ("https://wrong.invalid/input.tar" if position == 7
                                     else "c" * 64))
                wrong_rows.append((name, values, code))
            for name, values, expected_code in wrong_rows:
                with self.subTest(fresh_wrong_binding=name):
                    outcome = fresh_command("validate", sealed, *values)
                    self.assertEqual(outcome.returncode, 86, outcome.stderr)
                    self.assertEqual(json.loads(outcome.stderr)["code"], expected_code)

            invalid_name = list(FRESH_BINDINGS)
            invalid_name[3] = "static-or-colliding-name"
            outcome = fresh_command("validate", sealed, *invalid_name)
            self.assertEqual(json.loads(outcome.stderr)["code"],
                             "FRESH_ARTIFACT_NAME_MISMATCH")

            second_stage = fresh_command("stage", session, envelope, sealed, "success",
                                         *FRESH_BINDINGS)
            self.assertEqual(json.loads(second_stage.stderr)["code"],
                             "FRESH_STAGE_ALREADY_EXISTS")
            divergent = fresh_root / "divergent-session"
            shutil.copytree(session, divergent)
            (divergent / "50-matrix/execution-journal.jsonl").write_text("different\n")
            outcome = fresh_command("stage", divergent, envelope,
                                    fresh_root / "divergent-out", "success",
                                    *FRESH_BINDINGS)
            self.assertEqual(json.loads(outcome.stderr)["code"],
                             "FRESH_JOURNAL_DIVERGENCE")

            failure_package = fresh_root / "failure-package"
            controlled = fresh_command("stage", session, envelope, failure_package,
                                       "failure", *FRESH_BINDINGS)
            self.assertEqual(controlled.returncode, 0, controlled.stderr)
            self.assertEqual(json.loads(controlled.stdout)["status"],
                             "FAILURE_PACKAGE_NON_ACCEPTING")
            outcome = fresh_command("validate", failure_package, *FRESH_BINDINGS)
            self.assertEqual(json.loads(outcome.stderr)["code"],
                             "FRESH_ENTRY_SET_MISMATCH")

            no_space_parent = fresh_root / "not-a-directory"
            no_space_parent.write_text("simulated ENOSPC/storage failure boundary")
            outcome = fresh_command("stage", session, envelope,
                                    no_space_parent / "stage", "success",
                                    *FRESH_BINDINGS)
            self.assertEqual(outcome.returncode, 87, outcome.stderr)
            self.assertEqual(json.loads(outcome.stderr)["code"], "FRESH_IO_FAILURE")

            archive = fresh_root / "fresh.zip"
            transport = make_fresh_zip(sealed, archive)
            outcome = fresh_command("archive", archive, transport, *FRESH_BINDINGS)
            self.assertEqual(outcome.returncode, 0, outcome.stderr)
            outcome = fresh_command("archive", archive, "0" * 64, *FRESH_BINDINGS)
            self.assertEqual(json.loads(outcome.stderr)["code"],
                             "FRESH_TRANSPORT_DIGEST_MISMATCH")
            truncated = fresh_root / "truncated.zip"
            truncated.write_bytes(archive.read_bytes()[:100])
            truncated_sha = hashlib.sha256(truncated.read_bytes()).hexdigest()
            outcome = fresh_command("archive", truncated, truncated_sha, *FRESH_BINDINGS)
            self.assertEqual(json.loads(outcome.stderr)["code"], "FRESH_ARCHIVE_INVALID")
            for name in ("duplicate", "traversal", "absolute", "hidden", "nul"):
                malicious = fresh_root / f"{name}.zip"
                extra_name = {"duplicate": "authority-binding.json",
                              "traversal": "../escape", "absolute": "/absolute",
                              "hidden": ".hidden", "nul": "nul\x00suffix"}[name]
                malicious_sha = make_fresh_zip(sealed, malicious, [(extra_name, b"x")])
                outcome = fresh_command("archive", malicious, malicious_sha,
                                        *FRESH_BINDINGS)
                self.assertEqual(outcome.returncode, 86, outcome.stderr)
                self.assertIn(json.loads(outcome.stderr)["code"], {
                    "FRESH_ARCHIVE_DUPLICATE_ENTRY", "FRESH_PATH_INVALID",
                    "FRESH_HIDDEN_ENTRY", "FRESH_ENTRY_SET_MISMATCH"})

            enforcement_rows = [
                ("failure", "success", "success", "success", "1", "url", 90),
                ("cancelled", "success", "success", "success", "1", "url", 90),
                ("success", "failure", "success", "success", "1", "url", 91),
                ("success", "success", "failure", "success", "1", "url", 92),
                ("success", "success", "success", "failure", "", "", 93),
                ("success", "success", "success", "success", "", "", 93),
            ]
            for row in enforcement_rows:
                with self.subTest(fresh_enforcement=row[0:4]):
                    command = subprocess.run(
                        ["bash", "-c",
                         'source "$1"; shift; cth3ds_enforce_fresh_evidence "$@"',
                         "enforce-test", str(ROOT / "scripts" / "ci_diagnostics.sh"),
                         *(str(value) for value in row[:-1])],
                        cwd=ROOT, text=True, capture_output=True, check=False)
                    self.assertEqual(command.returncode, row[-1], command.stderr)

if __name__ == "__main__":
    unittest.main()
