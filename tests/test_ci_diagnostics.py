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
FRESH_ENVELOPE = [
    "authority-binding.json",
    "bundle-verification.json",
    "environment/bootstrap-summary.json",
    "environment/bundle-sha256-check.log",
    "environment/environment-audit.json",
    "environment/install.log",
    "environment/pip-bootstrap.log",
    "environment/pip-check.log",
    "environment/record-normalization.log",
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
    # Complete synthetic rows and observations follow the frozen case definitions.
    # R4 evidence shapes are minimized from the retained, passing public specimen.
    session, envelope = root / "session", root / "envelope"
    sid, invocation = "review-1", "7" * 64
    identity = {"commit": FRESH_HEAD, "tree": FRESH_TREE, "first_parent": FRESH_PARENT}
    role_paths = {
        "frozen_matrix": "authority/frozen/c3-acceptance-matrix.json",
        "base_acceptance_cases": "authority/frozen/c3-r3-acceptance-cases.json",
        "r4_acceptance_cases": "authority/frozen/c3-r4-acceptance-cases.json",
        "execution_dag": "authority/frozen/execution-dag.json",
        "candidate_transport": "candidate/candidate.bundle", "source_archive": "authority/frozen/CorsixTH.tar.gz",
        "cross_dependencies": "dependencies/host", "public_ci_environment": "ci",
        "old3ds_toolchain": "toolchains/old3ds/toolchain.tar",
        "python_runtime_3_9_25": "runtimes/linux-x86_64/python-3.9.25/runtime.tar",
        "python_runtime_3_14_6": "runtimes/linux-x86_64/python-3.14.6/runtime.tar",
        "python_wheelhouse_3_9_25": "wheelhouse/linux-x86_64/python-3.9.25",
        "python_wheelhouse_3_14_6": "wheelhouse/linux-x86_64/python-3.14.6",
    }
    frozen_digests = {
        "frozen_matrix": "8b7cf0d8e3b3702e9aa3c32aff9d1ed3e363ceab52699539251975a61985060f",
        "base_acceptance_cases": "45f7bda680a10c159e70ce15b9389eb7cafc419001af542583fdd5353d319d7f",
        "r4_acceptance_cases": "a4a7160e0dc762599d13a4df721d0d156e2daeea6ce6b8b4226c16f3a4d5dc64",
        "execution_dag": "e5339faa3d173e8c11f157980b206447987f75727c841cdd2afc0cc5e875df76",
    }
    bundle = {"status": "PASS", "manifest_sha256": "5" * 64, "sha256sums_sha256": "6" * 64,
              "roles": sorted(role_paths)}
    write_json(envelope / "authority-binding.json",
               {"status": "PASS", "head": FRESH_HEAD, "tree": FRESH_TREE, "parents": [FRESH_PARENT]})
    write_json(envelope / "bundle-verification.json", bundle)
    for name in ("bootstrap-summary.json", "environment-audit.json"):
        write_json(envelope / "environment" / name, {"status": "PASS"})
    for name in ("bundle-sha256-check.log", "install.log", "pip-bootstrap.log",
                 "pip-check.log", "record-normalization.log"):
        path = envelope / "environment" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("PASS\n")
    matrix_codes = json.loads(r'''["PRODUCER_VERDICT_FORBIDDEN","SCHEMA_REQUIRED_FIELD_MISSING","H2_DERIVED_OR_MISLABELED_FIELD_FORBIDDEN","JSON_NONFINITE_NUMBER","JSON_DUPLICATE_KEY","MALFORMED_CANDIDATE_IDENTITY","CANDIDATE_IDENTITY_MISMATCH","CANDIDATE_FINGERPRINT_MISMATCH","PRODUCT_FINGERPRINT_MISMATCH","CANDIDATE_DIRTY","DIFF_OUTSIDE_ALLOWLIST","UPSTREAM_ARCHIVE_HASH_MISMATCH","SYMLINK_ESCAPE","STREAM_TRUNCATED","TOOL_HASH_MISMATCH","OBSERVATION_REPLAY","TIME_ORDER_INVALID","SANITIZER_PRODUCT_FAILURE","SANITIZER_INSTRUMENTATION_UNPROVEN",null,"EXTRA_ROOT_OR_BUILD","NESTED_UNKNOWN_FIELD","UNBOUND_EXTERNAL_STREAM","DUPLICATE_BUILD_ROLE","MISSING_BUILD_ROLE","DUPLICATE_TOOL_ROLE","EXTRA_TOOL_ROLE","MISSING_TOOL_ROLE","DUPLICATE_ARTIFACT_ROLE","EXTRA_ORPHAN_ARTIFACT","UPSTREAM_TREE_MANIFEST_MISSING","DUPLICATE_INVOCATION_ROLE","EXTRA_INVOCATION_ROLE","MISSING_INVOCATION_ROLE","STREAM_ROLE_SWAP","INTEGRATED_SOURCE_TREE_TAMPERED","DANGLING_ARTIFACT_REFERENCE","DUPLICATE_CANONICAL_OWNER_SLOT","SYMLINK_COMPONENT","PATH_IDENTITY_CHANGED","CONSUMER_HASH_MISMATCH","POLICY_HASH_MISMATCH","SCHEMA_HASH_MISMATCH","ORACLE_HASH_MISMATCH","CTEST_STREAM_UNPROVEN","SIMULATOR_OUTPUT_UNPROVEN","UPSTREAM_SOURCE_TREE_EXPANDED","CONSUMER_NOT_SEALED","POLICY_NOT_SEALED","SCHEMA_NOT_SEALED","ORACLE_NOT_SEALED","RH10_TRACKED_OUTER_MANIFEST_MISSING","RH10_FRESH_OUTER_MANIFEST_HASH_MISMATCH","RH10_OUTER_PROVENANCE_FALSE","ARGV_MISMATCH","CWD_MISMATCH","ENVIRONMENT_MISMATCH","TERMINATION_FIELDS_INCONSISTENT","OBSERVATION_STDOUT_MISMATCH","FINAL_CHECKSUM_MISMATCH"]''')
    base_codes = json.loads(r'''[null,"MATRIX_RECEIPT_MISSING","MATRIX_EXECUTION_COUNT_MISMATCH","MATRIX_CASE_FAILED","MATRIX_CASE_SET_INCOMPLETE","MATRIX_CASE_SET_INCOMPLETE","RECEIPT_RUN_ID_MISMATCH","RECEIPT_CANDIDATE_MISMATCH","RECEIPT_POLICY_MISMATCH","RECEIPT_CANONICAL_RUN_MISMATCH","MATRIX_HASH_MISMATCH","RUNNER_HASH_MISMATCH","MATRIX_SUMMARY_DIGEST_MISMATCH","MATRIX_CASE_SET_DIGEST_MISMATCH","MATRIX_CASE_OUTPUT_MISMATCH","PROTOCOL_GATE_SET_MISMATCH","PROTOCOL_GATE_SET_MISMATCH","MANIFEST_CANDIDATE_BINDING_MISMATCH","RESULT_CANDIDATE_BINDING_MISMATCH","RESULT_MANIFEST_BINDING_MISMATCH","PRODUCT_VERDICT_MISMATCH","PRODUCT_FAILURE_CODE_MISMATCH","FINAL_REVIEW_INCONSISTENT","FINAL_RESULT_DERIVATION_MISMATCH","EXPECTED_MATRIX_RECEIPT_DIGEST_REQUIRED","MATRIX_RECEIPT_DIGEST_MISMATCH","EXPECTED_SEAL_DIGEST_REQUIRED","SEAL_ROOT_DIGEST_MISMATCH","SEAL_ROOT_DIGEST_MISMATCH","MATRIX_BYTES_MISSING","POLICY_BINDING_MISMATCH","RECEIPT_REQUIRED_FIELD_MISSING"]''')
    r4_codes = json.loads(r'''["SESSION_ROOT_EMPTY","SESSION_ROOT_NOT_EMPTY","CANONICAL_SEAL_RESERVED_EMPTY","NO_PRIOR_RUN_REFERENCE","CLOSURE_FIXTURE_VALID","CLOSURE_FIXTURE_RUN_ID_MISMATCH","CLOSURE_FIXTURE_CANDIDATE_MISMATCH","CLOSURE_FIXTURE_POLICY_MISMATCH","CLOSURE_FIXTURE_FACTS_MISMATCH","CLOSURE_FIXTURE_FINAL_ACCEPT_FORBIDDEN","CLOSURE_FIXTURE_REVIEW_SESSION_MISMATCH","CONSUMER_NOT_SEALED","POLICY_NOT_SEALED","SCHEMA_NOT_SEALED","ORACLE_NOT_SEALED","FINAL_CHECKSUM_MISMATCH","MATRIX_CASE_FAILED","FINAL_ACCEPTANCE_FIXTURE_FORBIDDEN","EXECUTION_ORDER_IDENTICAL","INPUT_OUTPUT_OVERLAP","CANONICAL_SEAL_RESERVED_EMPTY","EXECUTION_DAG_ACYCLIC"]''')
    dependencies = json.loads(r'''{"r4.n00_preflight":[],"r4.n10_policy":["r4.n00_preflight"],"r4.n20_produce":["r4.n10_policy"],"r4.n30_derive":["r4.n20_produce"],"r4.n35_seal_empty":["r4.n30_derive"],"r4.n40_fixture":["r4.n30_derive","r4.n35_seal_empty"],"r4.n41_fixture_anchor":["r4.n40_fixture"],"r4.n42_fixture_verify":["r4.n41_fixture_anchor"],"r4.n50_closure_cases":["r4.n42_fixture_verify"],"r4.n50_other_cases":["r4.n30_derive"],"r4.n51_receipt":["r4.n50_closure_cases","r4.n50_other_cases"],"r4.n52_receipt_anchor":["r4.n51_receipt"],"r4.n60_finalize":["r4.n52_receipt_anchor","r4.n41_fixture_anchor"],"r4.n61_final_anchor":["r4.n60_finalize"],"r4.n70_semantic_verify":["r4.n61_final_anchor"],"r4.n80_base_acceptance":["r4.n70_semantic_verify"],"r4.n81_cycle_acceptance":["r4.n80_base_acceptance"],"r4.n90_final_audit":["r4.n81_cycle_acceptance"]}''')
    matrix_rows, base_rows, journal = [], [], []
    def invocation_row(name, deps, exit_code=0, stdout=None, stderr=None):
        return {"stage_id": name, "dependency_ids": deps, "exit_code": exit_code,
                "stdout_sha256": stdout or "8" * 64, "stderr_sha256": stderr or "9" * 64,
                "started_at": "2026-09-05T00:00:00Z", "ended_at": "2026-09-05T00:00:00Z",
                "verified_invocation_sha256": invocation}
    for name, deps in dependencies.items():
        journal.append(invocation_row(name, deps))
    for index, code in enumerate(matrix_codes, 1):
        values = {"exit": 0 if index == 20 else 2, "failure_code": code,
                  "gate": "PASS" if index == 20 else ("FAIL" if index in (18, 54) else "NOT_PROVEN"),
                  "product": "FAIL" if index in (18, 20, 54) else "NOT_PROVEN",
                  "review": "ACCEPT_C3_EVIDENCE_PROTOCOL" if index == 20 else "REJECT_C3_EVIDENCE_PROTOCOL"}
        row = {"id": f"E{index:02d}", "pass": True, "stdout_sha256": "8" * 64, "stderr_sha256": "9" * 64}
        for key, value in values.items():
            row["expected_" + key] = row["actual_" + key] = value
        matrix_rows.append(row)
        journal.append(invocation_row("r4.n50_matrix.case." + row["id"], ["r4.n30_derive"], values["exit"]))
    for index, code in enumerate(base_codes, 1):
        base_rows.append({"id": f"R3P{index:02d}", "pass": True, "expected_exit": 0 if index == 1 else 2,
                          "actual_exit": 0 if index == 1 else 2, "expected_failure_code": code, "actual_failure_code": code})
    receipt = {"passed": 60, "case_count": 60, "failed": 0, "cases": matrix_rows,
               "review_session_id": sid, "candidate_identity": identity, "verified_invocation_sha256": invocation,
               "created_at": "2026-09-05T00:00:00Z"}
    encode = lambda value: (json.dumps(value,sort_keys=True,separators=(",",":")) + "\n").encode()
    receipt["matrix_sha256"] = "8b7cf0d8e3b3702e9aa3c32aff9d1ed3e363ceab52699539251975a61985060f"
    receipt["matrix"] = {"definition_sha256": receipt["matrix_sha256"], "passed": 60, "total": 60, "failed": 0}
    receipt["closure_fixture"] = {"sha256s_sha256": "a"*64, "consumed_once": True, "final_acceptance_eligible": False}
    receipt["case_set_sha256"] = hashlib.sha256(encode({"schema":"cth3ds.runtime-core-matrix-case-set/v1","cases":matrix_rows})).hexdigest()
    matrix_summary = {k:v for k,v in receipt.items() if k not in ("created_at","case_count")}
    matrix_summary.update(schema="cth3ds.runtime-core-c3-matrix-result/v2",total=60)
    receipt["summary_sha256"] = hashlib.sha256(encode(matrix_summary)).hexdigest()
    write_json(session / "50-matrix/receipt.json", receipt)
    write_json(session / "80-acceptance/base32/summary.json",
               {"passed": 32, "total": 32, "failed": 0, "cases": base_rows})
    r4_evidence = json.loads(r'''[
  {
    "bundle_manifest_sha256": "44b56a6b19d2f758f0a51a2be39f205d01829bf52174078265dfcedd79002b85",
    "candidate_transport": {
      "head": "1111111111111111111111111111111111111111"
    },
    "initial_entry_count": 0,
    "preflight_rehash": {
      "manifest_sha256": "5555555555555555555555555555555555555555555555555555555555555555",
      "sha256sums_sha256": "6666666666666666666666666666666666666666666666666666666666666666",
      "checked": []
    },
    "review_session_id": "f4350194c0eb4a698b9f201dbeb13511",
    "verified_invocation_sha256": "e288534ff8fe73662e876276d8448d211f4b717527f246c5a313222f71c6972a"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "SESSION_ROOT_NOT_EMPTY",
    "stderr_sha256": "b459bb646ce8d62b569ded740e6657c7a7581c0c6b136ca09094e56c44b56016",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  [
    {
      "entry_count": 0,
      "is_symlink": false,
      "label": "after_derive",
      "observed_at": "2026-09-05T00:16:46.075186Z"
    },
    {
      "entry_count": 0,
      "is_symlink": false,
      "label": "after_fixture",
      "observed_at": "2026-09-05T00:16:47.055674Z"
    },
    {
      "entry_count": 0,
      "is_symlink": false,
      "label": "after_matrix_receipt",
      "observed_at": "2026-09-05T00:19:29.369317Z"
    }
  ],
  {
    "canonical_seal_writer": "finalizer",
    "initial_entry_count": 0,
    "review_session_id": "f4350194c0eb4a698b9f201dbeb13511"
  },
  {
    "actual_exit": 0,
    "actual_failure_code": null,
    "stderr_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    "stdout_sha256": "f6af803429774f8fe666fb9272dea7fd1777f680400cbda7dfd94c6d7608c4ea"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "CLOSURE_FIXTURE_RUN_ID_MISMATCH",
    "stderr_sha256": "75e5cb71a7ee47764e5b77d2a4363aeececb6f36af3ccd3c4b87e0e71930c322",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "CLOSURE_FIXTURE_CANDIDATE_MISMATCH",
    "stderr_sha256": "5e5977464e1a87b678324144de6fdfc7a7777b84b325ce3137be26f069f4e9b4",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "CLOSURE_FIXTURE_POLICY_MISMATCH",
    "stderr_sha256": "b47155e18e200fdae05e550cbf1864809c217ddea83e8cb801688c7142ed6f60",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "CLOSURE_FIXTURE_FACTS_MISMATCH",
    "stderr_sha256": "6281f893e97514130dfcbdaaebe96f4c32d2ad35326acd98c0787a2c1fa376f0",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "CLOSURE_FIXTURE_FINAL_ACCEPT_FORBIDDEN",
    "stderr_sha256": "88f824f59c67a654ff3f67d1e5e8dc1f7d5de0205e5bde693e0e625f10612b13",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "CLOSURE_FIXTURE_ALREADY_CONSUMED",
    "stderr_sha256": "9438ca22d89bcbe13b4a30f5cccbbdf2c3d62b12381b0eb65ba62b7b7a6db9ff",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "CONSUMER_NOT_SEALED",
    "actual_gate": "NOT_PROVEN",
    "actual_product": "NOT_PROVEN",
    "actual_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "expected_exit": 2,
    "expected_failure_code": "CONSUMER_NOT_SEALED",
    "expected_gate": "NOT_PROVEN",
    "expected_product": "NOT_PROVEN",
    "expected_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "id": "E48",
    "mutation_sha256": "42c6c55c895c1cccff3689df467817e49d479c95d163b95e1836b69325d7ccf4",
    "pass": true,
    "stderr_sha256": "4a128bb4cb5216f6f44b851da2c7d0311bb6338cfdd75a4c7b3505af55c7dd50",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "POLICY_NOT_SEALED",
    "actual_gate": "NOT_PROVEN",
    "actual_product": "NOT_PROVEN",
    "actual_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "expected_exit": 2,
    "expected_failure_code": "POLICY_NOT_SEALED",
    "expected_gate": "NOT_PROVEN",
    "expected_product": "NOT_PROVEN",
    "expected_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "id": "E49",
    "mutation_sha256": "37d2f22f3351b1b37203b671c986ea787810fb985a061aab65c46a45cebd948e",
    "pass": true,
    "stderr_sha256": "e2109a7469a10e6bb8c30bd1c3e24465d48e5b415cf83a182f9bda7915e94e50",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "SCHEMA_NOT_SEALED",
    "actual_gate": "NOT_PROVEN",
    "actual_product": "NOT_PROVEN",
    "actual_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "expected_exit": 2,
    "expected_failure_code": "SCHEMA_NOT_SEALED",
    "expected_gate": "NOT_PROVEN",
    "expected_product": "NOT_PROVEN",
    "expected_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "id": "E50",
    "mutation_sha256": "c627f817feeff453936d6083f5154586ba201b0cd901ed679a35226d9579e72a",
    "pass": true,
    "stderr_sha256": "05b73fb32afba1e15c9fdd0e4958e546d534370eca526ebf272a4f3ae8f5111a",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "ORACLE_NOT_SEALED",
    "actual_gate": "NOT_PROVEN",
    "actual_product": "NOT_PROVEN",
    "actual_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "expected_exit": 2,
    "expected_failure_code": "ORACLE_NOT_SEALED",
    "expected_gate": "NOT_PROVEN",
    "expected_product": "NOT_PROVEN",
    "expected_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "id": "E51",
    "mutation_sha256": "292600a77005673da31a9144e3b4436dad21ebba42d843f96f3b933822e64162",
    "pass": true,
    "stderr_sha256": "64917536781b8cb1b54acb35356ec6a87b348dc653898a9c5e70517df6e2e947",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "FINAL_CHECKSUM_MISMATCH",
    "actual_gate": "NOT_PROVEN",
    "actual_product": "NOT_PROVEN",
    "actual_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "expected_exit": 2,
    "expected_failure_code": "FINAL_CHECKSUM_MISMATCH",
    "expected_gate": "NOT_PROVEN",
    "expected_product": "NOT_PROVEN",
    "expected_review": "REJECT_C3_EVIDENCE_PROTOCOL",
    "id": "E60",
    "mutation_sha256": "f9ce543cf725132a3acd799010e712aa31e7d50b865db5d55336032aa109abf7",
    "pass": true,
    "stderr_sha256": "60d0ddd7314086d822eb995c04798d7a1e3141d656492f8e8d701c42e03e4dfe",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "MATRIX_CASE_FAILED",
    "final_seal_entry_count": 0,
    "stderr_sha256": "cf3e0686a8c5cbf4062d40142501c21c5d01c62033af07827bc383e1e7563c30",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "FINAL_ACCEPTANCE_FIXTURE_FORBIDDEN",
    "stderr_sha256": "e5bcc5adc0da1e39733a3934c03b1e2d22b562b94e13baf499edfe9fcd036945",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "equal": true,
    "normalized_sha256": "cd689184be74ad8ef3c74e4fd90eb3d23aec1ada99a233bbf9d96044227f43de"
  },
  {
    "integration": {
      "actual_exit": 2,
      "actual_failure_code": "INPUT_OUTPUT_OVERLAP",
      "no_stage_started": true,
      "stderr_sha256": "57c3f27af143d3b05ea71579e05219844c172ce2f3b7fe385c11fb3bf2a5a4de",
      "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
      "target_creation_count": 0,
      "target_local_durable_failure_count": 0,
      "target_local_journal_count": 0
    },
    "submatrix": {
      "cases": [
        {
          "actual_code": "INPUT_OUTPUT_OVERLAP",
          "continuation_creation_count": 0,
          "expected_code": "INPUT_OUTPUT_OVERLAP",
          "id": "same",
          "pass": true,
          "separation_status": null,
          "validation_new_node_count": 0
        },
        {
          "actual_code": "INPUT_OUTPUT_OVERLAP",
          "continuation_creation_count": 0,
          "expected_code": "INPUT_OUTPUT_OVERLAP",
          "id": "input-ancestor-output",
          "pass": true,
          "separation_status": null,
          "validation_new_node_count": 0
        },
        {
          "actual_code": "INPUT_OUTPUT_OVERLAP",
          "continuation_creation_count": 0,
          "expected_code": "INPUT_OUTPUT_OVERLAP",
          "id": "output-ancestor-input",
          "pass": true,
          "separation_status": null,
          "validation_new_node_count": 0
        },
        {
          "actual_code": "INPUT_OUTPUT_OVERLAP",
          "continuation_creation_count": 0,
          "expected_code": "INPUT_OUTPUT_OVERLAP",
          "id": "symlink-ancestor",
          "pass": true,
          "separation_status": null,
          "validation_new_node_count": 0
        },
        {
          "actual_code": "INPUT_OUTPUT_OVERLAP",
          "continuation_creation_count": 0,
          "expected_code": "INPUT_OUTPUT_OVERLAP",
          "id": "dot-alias",
          "pass": true,
          "separation_status": null,
          "validation_new_node_count": 0
        },
        {
          "actual_code": "INPUT_OUTPUT_OVERLAP",
          "continuation_creation_count": 0,
          "expected_code": "INPUT_OUTPUT_OVERLAP",
          "id": "dotdot-alias",
          "pass": true,
          "separation_status": null,
          "validation_new_node_count": 0
        },
        {
          "actual_code": "INPUT_OUTPUT_OVERLAP",
          "continuation_creation_count": 0,
          "expected_code": "INPUT_OUTPUT_OVERLAP",
          "id": "trailing-slash",
          "pass": true,
          "separation_status": null,
          "validation_new_node_count": 0
        },
        {
          "actual_code": "PASS",
          "continuation_creation_count": 0,
          "expected_code": "PASS",
          "id": "case-alias",
          "pass": true,
          "separation_status": "PASS",
          "validation_new_node_count": 0
        },
        {
          "actual_code": "INPUT_OUTPUT_OVERLAP",
          "continuation_creation_count": 0,
          "expected_code": "INPUT_OUTPUT_OVERLAP",
          "id": "tmp-private-tmp-alias",
          "pass": true,
          "separation_status": null,
          "validation_new_node_count": 0
        },
        {
          "actual_code": "PASS",
          "continuation_creation_count": 1,
          "expected_code": "PASS",
          "id": "disjoint-continuation",
          "pass": true,
          "separation_status": "PASS",
          "validation_new_node_count": 0
        }
      ],
      "failed": 0,
      "passed": 10,
      "total": 10
    }
  },
  {
    "actual_exit": 2,
    "actual_failure_code": "CANONICAL_SEAL_RESERVED_EMPTY",
    "canonical_seal_entry_count": 0,
    "stderr_sha256": "e661ef703de1a593770e8556465e86ac69665ba5481a10d7eabec4990fbb3b00",
    "stdout_sha256": "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
  },
  {
    "completed_prefix_exact": true,
    "cycle_count": 0,
    "edge_count": 20,
    "final_seal_to_matrix_edge_count": 0,
    "node_count": 18
  }
]''')
    bundle_root = root.absolute() / "input-bundle"
    rehash = {"manifest_sha256": "5" * 64, "sha256sums_sha256": "6" * 64,
              "bundle_root": str(bundle_root),
              "checked": [{"role": role, "bundle_relative_path": path,
                           "sha256_or_tree_digest": frozen_digests.get(role, "b" * 64)}
                          for role, path in sorted(role_paths.items())]}
    r4_evidence[0].update(review_session_id=sid, verified_invocation_sha256=invocation,
                          bundle_manifest_sha256="5" * 64, preflight_rehash=rehash,
                          session_root_realpath=str(session.absolute()), bundle_root_realpath=str(bundle_root),
                          inputs={role: {"bundle_relative_path": path, "readonly": True} for role,path in role_paths.items()},
                          execution_dag={"bundle_relative_path": role_paths["execution_dag"], "sha256": frozen_digests["execution_dag"]},
                          candidate_transport={"head": FRESH_HEAD, "kind": "head-bundle",
                              "source_sha256": "b" * 64, "bundle_sha256": "b" * 64,
                              "source_realpath": str(bundle_root / role_paths["candidate_transport"]),
                              "normalized_repo_realpath": str(session.absolute() / "00-preflight/candidate-detached"),
                              "advertised_refs": [{"name": "HEAD", "oid": FRESH_HEAD}]})
    r4_evidence[3].update(review_session_id=sid)
    r4_codes[10] = r4_evidence[10]["actual_failure_code"]
    for index, matrix_index in enumerate((48,49,50,51,60), 11):
        r4_evidence[index] = matrix_rows[matrix_index - 1]
    write_json(session / "80-acceptance/r4-additive22/summary.json",
               {"passed": 22, "total": 22, "failed": 0, "review_session_id": sid,
                "cases": [{"id": f"R4C{i:02d}", "pass": True, "actual_code": code, "evidence": evidence}
                          for i, (code,evidence) in enumerate(zip(r4_codes,r4_evidence),1)]})
    h2 = {"status": "PASS", "independent_process_count": 40,
          "sanitized": {"passed": 20, "total": 20}, "non_sanitized": {"passed": 20, "total": 20}}
    write_json(session / "90-final-audit/h2-exact20/summary.json", h2)
    for profile in ("sanitized", "non_sanitized"):
        for index in range(1, 21):
            values = {"state_before": "MENU_STABLE", "state_after": "MENU_STABLE",
                      "transition_active_before": False, "transition_active_after": False,
                      "escaped_lease_valid_after": True, "call_result": "E_TEST_PREPARE_ABORT",
                      "fault_point": "after-first-staged-acquire",
                      "pool_bytes_before": [0]*7, "pool_bytes_after": [0,0,64,0,0,0,0],
                      "backend_bytes_before": [0,0], "backend_bytes_after": [64,0]}
            for key, delta in (("entries",1),("leases",1),("allocation_records",1),
                               ("pins",0),("dependencies",0),("mounted_package_count",0)):
                values[key + "_before"] = 1
                values[key + "_after"] = 1 + delta
            record = {"profile": profile, "process_index": index, "run_id": f"{profile}-{index}",
                      "exit_code": 0, "exact_red_fact": True, "logical_pool_delta": 64,
                      "backend_accounted_delta": 64, "stdout_sha256": "8"*64, "stderr_sha256": "9"*64}
            write_json(session / "90-final-audit/h2-exact20" / f"{profile}-{index:02d}.json",
                       {"record": record, "observation": {"run_id": record["run_id"], "observations": values,
                           "schema": "cth3ds.runtime-core-raw-observation/v4", "gate_id": "RH07-H2",
                           "oracle_id": "H2_TRANSITION_CAPABILITY_ROLLBACK", "stage_id": "C3"}})
            h2_journal = invocation_row(f"r4.n90_final_audit.h2_{profile}_{index:02d}", ["r4.n81_cycle_acceptance"])
            build = "20-canonical-run/build_red" if profile == "sanitized" else "90-final-audit/h2-plain-build"
            executable = str(session.absolute() / build / "cth3ds-red-h2-transition-lease-escape")
            h2_journal.update(argv=[executable, "--run-id", record["run_id"], "--fault", "after-first-staged-acquire"],
                              executable_relative_path=executable, executable_sha256=("c" if profile == "sanitized" else "d") * 64,
                              argument_roles=["run-id", "fault"], owner="validation-task", input_role=None, output_root=None)
            journal.append(h2_journal)
    journal_raw = "".join(json.dumps(row,sort_keys=True,separators=(",",":")) + "\n" for row in journal).encode()
    for name in ("00-preflight/execution-journal.jsonl", "50-matrix/execution-journal.jsonl"):
        path = session / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(journal_raw)
    write_json(session / "90-final-audit/observed-dag.json",
               {"review_session_id": sid, "node_count": 18, "edge_count": 20, "cycle_count": 0,
                "nodes": list(dependencies), "edges": sorted([[dep,n] for n,ds in dependencies.items() for dep in ds])})
    write_json(session / "90-final-audit/fresh-chain-result.json",
               {"review_session_id": sid, "candidate_identity": identity, "verified_invocation_sha256": invocation,
                "receipt_sha256": hashlib.sha256((session / "50-matrix/receipt.json").read_bytes()).hexdigest(),
                "input_bundle": {"manifest_sha256": "5"*64, "final_rehash": rehash},
                "fixture_sha256s_sha256": "a"*64,
                "canonical_seal_pre_finalizer_observations": r4_evidence[2],
                "h2_exact20_gate": h2, "facts_checks": {"passed": 18, "total": 18},
                "matrix": {"passed": 60, "total": 60}, "base_acceptance": {"passed": 32, "total": 32},
                "r4_acceptance": {"passed": 22, "total": 22}, "composed_acceptance": {"passed": 54, "total": 54},
                "semantic_verify": "PASS", "construction_self_verification": "PASS", "independent_review": "NOT_PROVEN"})
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
            workflow_text = (ROOT / ".github/workflows/old3ds-validation.yml").read_text()
            self.assertNotIn("source scripts/ci_diagnostics.sh", workflow_text)
            self.assertEqual(workflow_text.count(". scripts/ci_diagnostics.sh"), 4)
            self.assertGreaterEqual(workflow_text.count("shell: bash"), 3)
            self.assertIn("compression-level: 6", workflow_text)
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
            self.assertEqual(manifest["outcome"], "success")
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
                ("manifest-outcome", "artifact-manifest.json",
                 lambda row: row.pop("outcome"), "FRESH_MANIFEST_INVALID"),
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

            # R16-F01/F02: mutate actual rows/observations with valid byte seals.
            raw_rows = [
                ("failed-row", "50-matrix/receipt.json",
                 lambda d: d["cases"][0].update({"pass": False, "actual_exit": 99})),
                ("duplicate-id", "50-matrix/receipt.json",
                 lambda d: d["cases"][0].update(id="E02")),
                ("false-expectation", "50-matrix/receipt.json",
                 lambda d: d["cases"][0].update(actual_exit=99, expected_exit=99)),
                ("base-row", "80-acceptance/base/summary.json",
                 lambda d: d["cases"][0].update(actual_exit=99, expected_exit=99)),
                ("r4-row", "80-acceptance/r4/summary.json",
                 lambda d: d["cases"][0].update(actual_code="WRONG")),
                ("h2-observed", "90-final-audit/h2-exact20/sanitized-01.json",
                 lambda d: d["observation"]["observations"].update(entries_after=1)),
                ("h2-binding", "90-final-audit/h2-exact20/sanitized-01.json",
                 lambda d: d["observation"].update(run_id="wrong")),
                ("dag-edge", "90-final-audit/observed-dag.json",
                 lambda d: d["edges"].append([d["nodes"][-1], d["nodes"][0]])),
                ("receipt-candidate", "50-matrix/receipt.json",
                 lambda d: d["candidate_identity"].update(commit="0"*40)),
                ("result-bundle", "90-final-audit/fresh-chain-result.json",
                 lambda d: d["input_bundle"].update(manifest_sha256="0"*64)),
                ("envelope-bundle", "bundle-verification.json",
                 lambda d: d.update(manifest_sha256="0"*64)),
                ("manifest-bundle", "artifact-manifest.json",
                 lambda d: d["bundle"].update(manifest_sha256="0"*64)),
                ("manifest-time", "artifact-manifest.json",
                 lambda d: d.pop("created_at_utc")),
                ("manifest-non-utc", "artifact-manifest.json",
                 lambda d: d.update(created_at_utc="2026-09-05T00:00:00")),
            ]
            for name, relative, mutate in raw_rows:
                with self.subTest(r18_raw=name):
                    changed = fresh_root / ("r18-" + name)
                    shutil.copytree(sealed, changed)
                    value = json.loads((changed / relative).read_text())
                    mutate(value)
                    write_json(changed / relative, value)
                    reseal_fresh_tree(changed)
                    rejected = fresh_command("validate", changed, *FRESH_BINDINGS)
                    self.assertEqual(rejected.returncode, 86, rejected.stderr)
                    self.assertEqual(json.loads(rejected.stderr)["status"], "FAIL")

            # R24: break source relationships, including synchronized edits.
            # Both public entry points use the same semantic checks; do not add
            # discoverable test IDs or special-case the five reported examples.
            def source_case(label, mutate, accept=False):
                changed = fresh_root / ("source-" + label)
                shutil.copytree(sealed, changed)
                documents = {p.relative_to(changed).as_posix(): json.loads(p.read_text())
                             for p in changed.rglob("*.json")}
                journal_path = changed / "00-preflight/execution-journal.jsonl"
                journal = [json.loads(line) for line in journal_path.read_text().splitlines()]
                mutate(documents, journal)
                for name, body in documents.items():
                    write_json(changed / name, body)
                journal_path.write_text("".join(json.dumps(j, sort_keys=True, separators=(",", ":")) + "\n" for j in journal))
                reseal_fresh_tree(changed)
                zipped = fresh_root / ("source-" + label + ".zip")
                with zipfile.ZipFile(zipped, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                    for path in sorted(changed.rglob("*")):
                        if path.is_file():
                            archive.write(path, path.relative_to(changed).as_posix())
                source = fresh_root / ("source-input-" + label)
                mapping = json.loads((changed / "artifact-manifest.json").read_text())
                for row in mapping["payloads"]:
                    owner = "envelope" if row["path"] in FRESH_ENVELOPE else "session"
                    dest = source / owner / row["source"]
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    dest.write_bytes((changed / row["path"]).read_bytes())
                (source / "session/50-matrix/execution-journal.jsonl").write_bytes(journal_path.read_bytes())
                operations = [
                    ("archive", zipped, hashlib.sha256(zipped.read_bytes()).hexdigest(), *FRESH_BINDINGS),
                    ("stage", source / "session", source / "envelope", source / "staged", "success", *FRESH_BINDINGS),
                ]
                for args in operations:
                    with self.subTest(r24_source=label, entry=args[0], accept=accept):
                        result = fresh_command(*args)
                        self.assertEqual(result.returncode, 0 if accept else 86, result.stdout + result.stderr)
                        if not accept:
                            self.assertEqual(json.loads(result.stderr)["status"], "FAIL")
                            self.assertNotIn("Traceback", result.stderr)
                shutil.rmtree(changed)
                shutil.rmtree(source)
                zipped.unlink()

            def h2_change(profile, index, change):
                def apply(documents, journal):
                    doc = documents[f"90-final-audit/h2-exact20/{profile}-{index:02d}.json"]
                    row = next(j for j in journal if j["stage_id"] == f"r4.n90_final_audit.h2_{profile}_{index:02d}")
                    change(doc["record"], doc["observation"], row)
                return apply

            def shift_slot(observation, key, slot, other):
                values = observation["observations"]
                delta = values[key + "_after"][slot] - values[key + "_before"][slot]
                values[key + "_after"][slot] -= delta
                values[key + "_after"][other] += delta

            h2_changes = [
                ("paired-id", lambda r, o, j: (r.update(run_id="detached"), o.update(run_id="detached"))),
                ("journal-id", lambda r, o, j: j["argv"].__setitem__(2, "detached")),
                ("duplicate-source-id", lambda r, o, j: (r.update(run_id=r["profile"] + "-2"), o.update(run_id=r["run_id"]), j["argv"].__setitem__(2, r["run_id"]))),
                ("wrong-process-index", lambda r, o, j: r.update(process_index=2)),
                ("fault-pair", lambda r, o, j: (j["argv"].__setitem__(4, "other-fault"), o["observations"].update(fault_point="other-fault"))),
                ("executable-pair", lambda r, o, j: (j["argv"].__setitem__(0, "/other/build_red/cth3ds-red-h2-transition-lease-escape"), j.update(executable_relative_path=j["argv"][0]))),
                ("argv-extra", lambda r, o, j: j["argv"].extend(["--run-id", r["run_id"]])),
                ("argument-role", lambda r, o, j: j.update(argument_roles=["fault", "run-id"])),
                ("owner", lambda r, o, j: j.update(owner="other-task")),
                ("executable-hash", lambda r, o, j: j.update(executable_sha256="0" * 64)),
                ("observation-role", lambda r, o, j: o.update(gate_id="other-gate")),
                ("pool-slot", lambda r, o, j: shift_slot(o, "pool_bytes", 2, 0)),
                ("backend-slot", lambda r, o, j: shift_slot(o, "backend_bytes", 0, 1)),
                ("pool-record-pair", lambda r, o, j: (o["observations"]["pool_bytes_after"].__setitem__(2, 32), r.update(logical_pool_delta=32))),
                ("backend-record-pair", lambda r, o, j: (o["observations"]["backend_bytes_after"].__setitem__(0, 32), r.update(backend_accounted_delta=32))),
            ]
            for profile in ("sanitized", "non_sanitized"):
                for index in (1, 20):
                    for label, change in h2_changes:
                        source_case(f"{profile}-{index}-{label}", h2_change(profile, index, change))
                    source_case(f"{profile}-{index}-unselected-slot", h2_change(profile, index,
                        lambda r, o, j: o["observations"]["pool_bytes_after"].__setitem__(0, 17)), accept=True)

            def bundle_change(change):
                def apply(documents, journal):
                    evidence = documents["80-acceptance/r4/summary.json"]["cases"][0]["evidence"]
                    final = documents["90-final-audit/fresh-chain-result.json"]["input_bundle"]["final_rehash"]
                    change(evidence, final, documents["bundle-verification.json"])
                return apply

            for role in sorted(json.loads((envelope / "bundle-verification.json").read_text())["roles"]):
                def remove(e, f, b, role=role):
                    e["preflight_rehash"]["checked"] = [r for r in e["preflight_rehash"]["checked"] if r["role"] != role]
                    f["checked"] = [r for r in f["checked"] if r["role"] != role]
                source_case("missing-role-" + role, bundle_change(remove))
                def wrong_path(e, f, b, role=role):
                    for rehash in (e["preflight_rehash"], f):
                        next(r for r in rehash["checked"] if r["role"] == role)["bundle_relative_path"] = "wrong/role-path"
                source_case("path-role-" + role, bundle_change(wrong_path))

            def change_digest(e, f, role, value):
                for rehash in (e["preflight_rehash"], f):
                    next(r for r in rehash["checked"] if r["role"] == role)["sha256_or_tree_digest"] = value

            def swap_role_paths(e, f, b):
                for rehash in (e["preflight_rehash"], f):
                    left, right = rehash["checked"][:2]
                    left["bundle_relative_path"], right["bundle_relative_path"] = right["bundle_relative_path"], left["bundle_relative_path"]

            bundle_changes = [
                ("empty-pair", lambda e, f, b: (e["preflight_rehash"].update(checked=[]), f.update(checked=[]))),
                ("all-sets-empty", lambda e, f, b: (e["preflight_rehash"].update(checked=[]), f.update(checked=[]), b.update(roles=[]), e.update(inputs={}))),
                ("duplicate-pair", lambda e, f, b: (e["preflight_rehash"]["checked"].append(e["preflight_rehash"]["checked"][0]), f["checked"].append(f["checked"][0]))),
                ("envelope-duplicate", lambda e, f, b: b["roles"].append(b["roles"][0])),
                ("extra-pair", lambda e, f, b: (e["preflight_rehash"]["checked"].append({"role":"extra", "bundle_relative_path":"extra", "sha256_or_tree_digest":"0"*64}), f["checked"].append({"role":"extra", "bundle_relative_path":"extra", "sha256_or_tree_digest":"0"*64}))),
                ("path-swap", swap_role_paths),
                ("preflight-digest", lambda e, f, b: e["preflight_rehash"]["checked"][1].update(sha256_or_tree_digest="0"*64)),
                ("transport-pair", lambda e, f, b: e["candidate_transport"].update(bundle_sha256="0"*64, source_sha256="0"*64)),
                ("transport-role-reverse", lambda e, f, b: change_digest(e, f, "candidate_transport", "0"*64)),
                ("transport-source", lambda e, f, b: e["candidate_transport"].update(source_realpath="/wrong/candidate.bundle")),
                ("transport-kind", lambda e, f, b: e["candidate_transport"].update(kind="detached-repo")),
                ("transport-ref", lambda e, f, b: e["candidate_transport"].update(advertised_refs=[{"name":"other", "oid":FRESH_HEAD}])),
                ("transport-output", lambda e, f, b: e["candidate_transport"].update(normalized_repo_realpath="/wrong/candidate-detached")),
                ("DAG-path", lambda e, f, b: e["execution_dag"].update(bundle_relative_path="wrong/dag.json")),
                ("DAG-all-digests", lambda e, f, b: (change_digest(e, f, "execution_dag", "0"*64), e["execution_dag"].update(sha256="0"*64))),
                ("input-readonly", lambda e, f, b: e["inputs"]["candidate_transport"].update(readonly=False)),
                ("input-role", lambda e, f, b: e["inputs"].pop("cross_dependencies")),
                ("rehash-root", lambda e, f, b: f.update(bundle_root="/wrong")),
            ]
            for role in ("frozen_matrix", "base_acceptance_cases", "r4_acceptance_cases", "execution_dag"):
                source_case("frozen-digest-" + role, bundle_change(lambda e, f, b, role=role: change_digest(e, f, role, "0"*64)))
            for label, change in bundle_changes:
                source_case(label, bundle_change(change))

            def relocate(documents, journal):
                e = documents["80-acceptance/r4/summary.json"]["cases"][0]["evidence"]
                prior_session, prior_bundle = e["session_root_realpath"], e["bundle_root_realpath"]
                e["session_root_realpath"], e["bundle_root_realpath"] = "/relocated/session", "/relocated/input"
                e["candidate_transport"]["normalized_repo_realpath"] = e["candidate_transport"]["normalized_repo_realpath"].replace(prior_session, e["session_root_realpath"])
                e["candidate_transport"]["source_realpath"] = e["candidate_transport"]["source_realpath"].replace(prior_bundle, e["bundle_root_realpath"])
                e["preflight_rehash"]["bundle_root"] = e["bundle_root_realpath"]
                documents["90-final-audit/fresh-chain-result.json"]["input_bundle"]["final_rehash"]["bundle_root"] = e["bundle_root_realpath"]
                for j in journal:
                    if j["stage_id"].startswith("r4.n90_final_audit.h2_"):
                        j["argv"][0] = j["argv"][0].replace(prior_session, e["session_root_realpath"])
                        j["executable_relative_path"] = j["argv"][0]
            source_case("relocated-complete-source", relocate, accept=True)

            # R16-F05: check top-level and nested shapes before any dereference,
            # arithmetic, set membership, or sorting.
            shape_targets = [
                ("artifact-manifest.json", ()),
                ("artifact-manifest.json", ("bundle",)),
                ("artifact-manifest.json", ("payloads", 0, "path")),
                ("artifact-manifest.json", ("payloads", 0, "bytes")),
                ("50-matrix/receipt.json", ("cases",)),
                ("50-matrix/receipt.json", ("cases", 0)),
                ("80-acceptance/r4/summary.json", ("cases", 0, "evidence")),
                ("90-final-audit/fresh-chain-result.json", ("input_bundle",)),
                ("90-final-audit/fresh-chain-result.json", ("matrix",)),
                ("90-final-audit/h2-exact20/sanitized-01.json", ("record", "run_id")),
                ("90-final-audit/h2-exact20/sanitized-01.json", ("observation", "observations")),
                ("90-final-audit/h2-exact20/sanitized-01.json", ("observation", "observations", "pool_bytes_after")),
                ("90-final-audit/observed-dag.json", ("nodes", 0)),
                ("90-final-audit/observed-dag.json", ("edges", 0)),
            ]
            for target_index, (relative, keys) in enumerate(shape_targets):
                for value_index, bad_value in enumerate((None, [], {}, True, 1, "wrong")):
                    with self.subTest(r18_shape=(relative, keys, bad_value)):
                        changed = fresh_root / f"shape-{target_index}-{value_index}"
                        shutil.copytree(sealed, changed)
                        body = json.loads((changed / relative).read_text())
                        if keys:
                            destination = body
                            for key in keys[:-1]:
                                destination = destination[key]
                            destination[keys[-1]] = bad_value
                        else:
                            body = bad_value
                        write_json(changed / relative, body)
                        if relative != "artifact-manifest.json":
                            reseal_fresh_tree(changed)
                        rejected = fresh_command("validate", changed, *FRESH_BINDINGS)
                        self.assertEqual(rejected.returncode, 86, rejected.stderr)
                        self.assertEqual(json.loads(rejected.stderr)["status"], "FAIL")
                        self.assertNotIn("Traceback", rejected.stderr)

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
            failure = json.loads((failure_package / "failure.json").read_text())
            self.assertEqual(failure["outcome"], "failure")
            self.assertEqual(failure["payload_count"], 10)
            self.assertEqual(
                {row["path"] for row in failure["payloads"]},
                set(FRESH_ENVELOPE) | {"00-preflight/execution-journal.jsonl"})
            for row in failure["payloads"]:
                raw = (failure_package / row["path"]).read_bytes()
                self.assertEqual(row["bytes"], len(raw))
                self.assertEqual(row["sha256"], hashlib.sha256(raw).hexdigest())
            outcome = fresh_command("validate", failure_package, *FRESH_BINDINGS)
            self.assertEqual(json.loads(outcome.stderr)["code"],
                             "FRESH_ENTRY_SET_MISMATCH")

            timeout_package = fresh_root / "timeout-package"
            timeout = fresh_command("stage", session, envelope, timeout_package,
                                    "timed_out", *FRESH_BINDINGS)
            self.assertEqual(timeout.returncode, 0, timeout.stderr)
            timeout_failure = json.loads(
                (timeout_package / "failure.json").read_text())
            self.assertEqual(timeout_failure["outcome"], "timed_out")
            self.assertEqual(timeout_failure["status"],
                             "FAILURE_PACKAGE_NON_ACCEPTING")

            # R16-F04: execute real success, failure and bounded timeout commands.
            for label, command, limit, expected_exit in (
                    ("success", [sys.executable, "-c", "pass"], "5", 0),
                    ("failure", [sys.executable, "-c", "raise SystemExit(23)"], "5", 23),
                    ("timed_out", [sys.executable, "-c", "import time; time.sleep(10)"], "0.1", 124)):
                with self.subTest(r18_command=label):
                    outcome_file = envelope / "fresh-command-outcome.json"
                    executed = subprocess.run(
                        ["bash", "-c", 'source "$1"; shift; cth3ds_run_fresh_command "$@"',
                         "command-test", str(ROOT / "scripts/ci_diagnostics.sh"),
                         str(outcome_file), limit, *command],
                        text=True, capture_output=True)
                    self.assertEqual(executed.returncode, expected_exit, executed.stderr)
                    command_result = json.loads(outcome_file.read_text())
                    self.assertEqual(command_result["outcome"], label)
                    self.assertEqual(command_result["exit_code"], expected_exit)
                    if label == "success":
                        continue
                    diagnostic = session / "00-preflight/stage-diagnostics/last.stderr"
                    diagnostic.parent.mkdir(parents=True, exist_ok=True)
                    diagnostic.write_text("final diagnostic bytes\n")
                    journal_record = {"stage_id": "partial", "stderr_path": str(diagnostic),
                                      "stderr_sha256": hashlib.sha256(diagnostic.read_bytes()).hexdigest()}
                    journal_path = session / "00-preflight/execution-journal.jsonl"
                    saved_journal = journal_path.read_bytes()
                    write_json(journal_path, journal_record)
                    partial = fresh_root / ("command-package-" + label)
                    staged_partial = fresh_command("stage", session, envelope, partial, "failure", *FRESH_BINDINGS)
                    journal_path.write_bytes(saved_journal)
                    self.assertEqual(staged_partial.returncode, 0, staged_partial.stderr)
                    body = json.loads((partial / "failure.json").read_text())
                    self.assertEqual(body["command_outcome"], command_result)
                    self.assertEqual((partial / "00-preflight/stage-diagnostics/last.stderr").read_bytes(),
                                     diagnostic.read_bytes())
                    self.assertEqual(body["status"], "FAILURE_PACKAGE_NON_ACCEPTING")
                    self.assertNotEqual(fresh_command("validate", partial, *FRESH_BINDINGS).returncode, 0)

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

            # R16-F03: construct raw central/local names; ZipInfo construction
            # itself truncates NUL, so the byte mutation is essential.
            nul_archive = fresh_root / "raw-nul.zip"
            with zipfile.ZipFile(nul_archive, "w", compression=zipfile.ZIP_DEFLATED) as handle:
                for path in sorted(p for p in sealed.rglob("*") if p.is_file()):
                    name = path.relative_to(sealed).as_posix()
                    handle.writestr(name + ("Xevil" if name == "authority-binding.json" else ""), path.read_bytes())
            nul_bytes = nul_archive.read_bytes().replace(b"authority-binding.jsonXevil",
                                                        b"authority-binding.json\x00evil")
            nul_archive.write_bytes(nul_bytes)
            rejected = fresh_command("archive", nul_archive, hashlib.sha256(nul_bytes).hexdigest(), *FRESH_BINDINGS)
            self.assertEqual(rejected.returncode, 86, rejected.stderr)
            self.assertEqual(json.loads(rejected.stderr)["code"], "FRESH_PATH_INVALID")

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
