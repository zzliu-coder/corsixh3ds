#!/usr/bin/env bash
set -euo pipefail

# Shared fail-closed diagnostics for CI-facing scripts. Call ci_diag_init once,
# ci_diag_step before each meaningful command, and ci_diag_mark_pass only after
# every required command has completed.

ci_diag_init() {
  CI_DIAG_MATRIX="$1"
  CI_DIAG_DIR="$2"
  CI_DIAG_STAGE="initialization"
  CI_DIAG_LOGS=("")
  mkdir -p "${CI_DIAG_DIR}"

  local identity_status=0
  python3 - "${CI_DIAG_DIR}/identity.json" "${CI_DIAG_MATRIX}" \
    "${CTH3DS_CONTAINER_IMAGE:-}" <<'PY' || identity_status=$?
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import platform
import shutil
import subprocess
import sys

output = pathlib.Path(sys.argv[1])
matrix = sys.argv[2]
container_image = sys.argv[3] or None
root = pathlib.Path(os.environ.get("CTH3DS_ROOT", pathlib.Path.cwd()))


def capture(command: list[str]) -> str | None:
    if shutil.which(command[0]) is None:
        return None
    result = subprocess.run(command, text=True, capture_output=True, check=False)
    text = (result.stdout or result.stderr).strip()
    return text or None


def first_line(command: list[str]) -> str | None:
    text = capture(command)
    return text.splitlines()[0] if text else None


def required_git(*arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(root), *arguments],
        text=True,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(
            f"git {' '.join(arguments)} exited {result.returncode}: {detail}"
        )
    return result.stdout.strip()


def package_rows(command: list[str]) -> list[str]:
    text = capture(command)
    return sorted(text.splitlines()) if text else []


pin_path = root / "config" / "upstream-pins.json"
identity_error = None
try:
    commit = required_git("rev-parse", "HEAD")
    tree = required_git("rev-parse", "HEAD^{tree}")
    parent_row = required_git("rev-list", "--parents", "-n", "1", "HEAD").split()
    shallow = required_git("rev-parse", "--is-shallow-repository")
    if not commit or not tree:
        raise RuntimeError("Git returned an empty commit or tree identity")
    if not parent_row or parent_row[0] != commit or len(parent_row) < 2:
        raise RuntimeError("Git returned an empty or inconsistent parent identity")
    if shallow != "false":
        raise RuntimeError("Git ancestry is shallow")
    source = {
        "status": "PASS",
        "commit": commit,
        "tree": tree,
        "parents": parent_row[1:],
        "dirty": bool(
            required_git("status", "--porcelain=v1", "--untracked-files=all")
        ),
        "pin_manifest_sha256": (
            hashlib.sha256(pin_path.read_bytes()).hexdigest()
            if pin_path.is_file()
            else None
        ),
    }
except (OSError, RuntimeError) as error:
    identity_error = str(error)
    source = {
        "status": "FAIL",
        "error": identity_error,
        "pin_manifest_sha256": (
            hashlib.sha256(pin_path.read_bytes()).hexdigest()
            if pin_path.is_file()
            else None
        ),
    }

if identity_error is not None:
    identity = {
        "format": 1,
        "matrix": matrix,
        "source": source,
    }
    output.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
    print(identity_error, file=sys.stderr)
    raise SystemExit(42)

identity = {
    "format": 1,
    "matrix": matrix,
    "source": source,
    "machine": {
        "platform": platform.platform(),
        "architecture": platform.machine(),
        "runner_os": os.environ.get("RUNNER_OS"),
        "runner_arch": os.environ.get("RUNNER_ARCH"),
    },
    "container": {
        "requested_image": container_image,
        "hostname": platform.node(),
    },
    "tools": {
        "bash": first_line(["bash", "--version"]),
        "cmake": first_line(["cmake", "--version"]),
        "ninja": first_line(["ninja", "--version"]),
        "python": first_line(["python3", "--version"]),
        "gcc": first_line(["gcc", "--version"]),
        "g++": first_line(["g++", "--version"]),
        "clang": first_line(["clang", "--version"]),
        "clang++": first_line(["clang++", "--version"]),
        "arm_none_eabi_gcc": first_line(["arm-none-eabi-gcc", "--version"]),
        "dkp_pacman": first_line(["dkp-pacman", "--version"]),
    },
    "dependencies": {
        "debian": package_rows([
            "dpkg-query",
            "-W",
            "-f=${Package}=${Version}\\n",
            "cmake",
            "ninja-build",
            "clang",
            "python3",
            "git",
            "curl",
            "tar",
        ]),
        "devkitpro": package_rows(["dkp-pacman", "-Q"]),
    },
}
output.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
PY

  if [[ "${identity_status}" -ne 0 ]]; then
    CI_DIAG_STAGE="source-identity"
    CI_DIAG_LOGS=("${CI_DIAG_DIR}/identity.json")
    ci_diag_emit_failure "${identity_status}" \
      "Git source identity preflight failed"
    return "${identity_status}"
  fi

  trap 'ci_diag_on_error "$?" "$BASH_COMMAND"' ERR
  die() { ci_diag_die "$@"; }
}

ci_diag_step() {
  CI_DIAG_STAGE="$1"
  shift
  if [[ $# -eq 0 ]]; then
    CI_DIAG_LOGS=("")
  else
    CI_DIAG_LOGS=("$@")
  fi
}

ci_diag_write_result() {
  local status="$1" exit_code="$2" failed_command="$3"
  shift 3
  python3 - "${CI_DIAG_DIR}/summary.json" "${CI_DIAG_DIR}/identity.json" \
    "${CI_DIAG_MATRIX}" "${CI_DIAG_STAGE}" "${status}" "${exit_code}" \
    "${failed_command}" "$@" <<'PY'
from __future__ import annotations

import datetime
import hashlib
import json
import os
import pathlib
import stat
import sys
import tempfile

(
    output,
    identity_path,
    matrix,
    stage,
    status,
    exit_code,
    failed_command,
    *logs,
) = sys.argv[1:]
logs = [path for path in logs if path]
identity_file = pathlib.Path(identity_path)
identity = json.loads(identity_file.read_text()) if identity_file.is_file() else None
log_artifacts = []
log_validation_errors = []
for log in logs:
    path = pathlib.Path(log)
    artifact = {"path": log}
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode):
            raise OSError("path is not a regular file")
        if metadata.st_mode & 0o444 == 0:
            raise PermissionError("path has no readable permission bits")
        content = path.read_bytes()
        artifact.update(
            {
                "byte_size": len(content),
                "sha256": hashlib.sha256(content).hexdigest(),
            }
        )
    except OSError as error:
        detail = f"{log}: {error}"
        artifact["error"] = str(error)
        log_validation_errors.append(detail)
    log_artifacts.append(artifact)

if log_validation_errors:
    status = "FAIL"
    if int(exit_code) == 0:
        exit_code = "74"
    if not failed_command:
        failed_command = "diagnostic log validation failed"
summary = {
    "format": 1,
    "status": status,
    "matrix": matrix,
    "stage": stage,
    "exit_code": int(exit_code),
    "failed_command": failed_command or None,
    "logs": logs,
    "log_artifacts": log_artifacts,
    "log_validation_errors": log_validation_errors,
    "identity": identity,
    "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
output_path = pathlib.Path(output)
payload = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode("utf-8")
descriptor, temporary_name = tempfile.mkstemp(
    prefix=f".{output_path.name}.", suffix=".tmp", dir=output_path.parent
)
try:
    with os.fdopen(descriptor, "wb") as temporary:
        temporary.write(payload)
        temporary.flush()
        os.fsync(temporary.fileno())
    os.replace(temporary_name, output_path)
    directory_descriptor = os.open(output_path.parent, os.O_RDONLY)
    try:
        os.fsync(directory_descriptor)
    finally:
        os.close(directory_descriptor)
except BaseException:
    try:
        os.unlink(temporary_name)
    except FileNotFoundError:
        pass
    raise

if log_validation_errors:
    raise SystemExit(74)
PY
}

ci_diag_emit_failure() {
  local status="$1" command="$2" log_path write_status=0
  ci_diag_write_result FAIL "${status}" "${command}" \
    "${CI_DIAG_LOGS[@]}" || write_status=$?
  printf '[cth3ds-ci] matrix: %s\n' "${CI_DIAG_MATRIX}" >&2
  printf '[cth3ds-ci] stage: %s\n' "${CI_DIAG_STAGE}" >&2
  printf '[cth3ds-ci] failed command: %s\n' "${command}" >&2
  printf '[cth3ds-ci] exit code: %s\n' "${status}" >&2
  for log_path in "${CI_DIAG_LOGS[@]}"; do
    [[ -n "${log_path}" ]] || continue
    printf '[cth3ds-ci] tail: %s\n' "${log_path}" >&2
    if [[ -f "${log_path}" && -r "${log_path}" ]]; then
      tail -n "${CTH3DS_LOG_TAIL_LINES:-80}" "${log_path}" >&2
    else
      printf '[cth3ds-ci] tail unavailable: declared log is missing, nonregular, or unreadable\n' >&2
    fi
  done
  if [[ "${write_status}" -ne 0 ]]; then
    printf '[cth3ds-ci] diagnostic log validation exit code: %s\n' \
      "${write_status}" >&2
  fi
  printf '[cth3ds-ci] machine summary: %s\n' "${CI_DIAG_DIR}/summary.json" >&2
}

ci_diag_die() {
  local message="$*"
  trap - ERR
  set +e
  printf '[cth3ds] error: %s\n' "${message}" >&2
  ci_diag_emit_failure 2 "${message}"
  exit 2
}

ci_diag_on_error() {
  local status="$1" command="$2"
  trap - ERR
  set +e
  ci_diag_emit_failure "${status}" "${command}"
  exit "${status}"
}

ci_diag_mark_pass() {
  local status=0
  trap - ERR
  ci_diag_write_result PASS 0 "" "${CI_DIAG_LOGS[@]}" || status=$?
  if [[ "${status}" -ne 0 ]]; then
    ci_diag_emit_failure "${status}" "diagnostic log validation failed"
    return "${status}"
  fi
}

# Record the inner command result while the step still has time to retain it.
# The record lives outside the session so Fresh can require an empty session.
cth3ds_run_fresh_command() {
  python3 - "$@" <<'PY'
import datetime
import json
import os
import pathlib
import signal
import subprocess
import sys

record = pathlib.Path(sys.argv[1])
timeout = float(sys.argv[2])
command = sys.argv[3:]
started = datetime.datetime.now(datetime.timezone.utc).isoformat()
record.parent.mkdir(parents=True, exist_ok=True)
def save(outcome, code):
    record.write_text(json.dumps({"started_at_utc": started,
        "ended_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "outcome": outcome, "exit_code": code, "timeout_seconds": timeout},
        sort_keys=True) + "\n")
try:
    process = subprocess.Popen(command, start_new_session=True)
except OSError:
    save("failure", 127)
    raise
try:
    code = process.wait(timeout=timeout)
    save("success" if code == 0 else "failure", code)
except subprocess.TimeoutExpired:
    os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        os.killpg(process.pid, signal.SIGKILL)
        process.wait()
    save("timed_out", 124)
    code = 124
raise SystemExit(code if code >= 0 else 128 - code)
PY
}

# Public Fresh evidence is a separate, fail-closed protocol.  The producer session
# remains in RUNNER_TEMP; this helper stages the exact acceptance subset into a
# canonical tree and validates the same tree (or its downloaded ZIP) without
# importing candidate Python modules.
cth3ds_fresh_evidence() {
  python3 - "$@" <<'PY'
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import pathlib
import shutil
import stat
import sys
import tempfile
import zipfile


MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 128 * 1024 * 1024
ENVELOPE = [
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
CORE = [
    ("00-preflight/execution-journal.jsonl", "00-preflight/execution-journal.jsonl"),
    ("50-matrix/receipt.json", "50-matrix/receipt.json"),
    ("80-acceptance/base32/summary.json", "80-acceptance/base/summary.json"),
    ("80-acceptance/r4-additive22/summary.json", "80-acceptance/r4/summary.json"),
    ("90-final-audit/fresh-chain-result.json", "90-final-audit/fresh-chain-result.json"),
    ("90-final-audit/h2-exact20/summary.json", "90-final-audit/h2-exact20/summary.json"),
    ("90-final-audit/observed-dag.json", "90-final-audit/observed-dag.json"),
]
H2 = [
    ("90-final-audit/h2-exact20/%s-%02d.json" % (profile, index),
     "90-final-audit/h2-exact20/%s-%02d.json" % (profile, index))
    for profile in ("sanitized", "non_sanitized") for index in range(1, 21)
]
MAPPINGS = [(path, path) for path in ENVELOPE] + CORE + H2
PAYLOAD_PATHS = sorted(public for _, public in MAPPINGS)
SUCCESS_PATHS = sorted(PAYLOAD_PATHS + ["artifact-manifest.json", "SHA256SUMS"])


class EvidenceError(Exception):
    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code
        self.detail = detail


def fail(code: str, detail: str) -> None:
    raise EvidenceError(code, detail)


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":"),
                       ensure_ascii=True) + "\n").encode("ascii")


def strict_json(data: bytes, label: str):
    def pairs(rows):
        result = {}
        for key, value in rows:
            if key in result:
                fail("FRESH_JSON_DUPLICATE_KEY", "%s duplicate key %s" % (label, key))
            result[key] = value
        return result
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=pairs,
                           parse_constant=lambda value: fail("FRESH_JSON_INVALID", label + ": nonfinite number"))
        if not isinstance(value, dict):
            fail("FRESH_JSON_INVALID", label + ": expected object")
        return value
    except EvidenceError:
        raise
    except (ValueError, UnicodeDecodeError, RecursionError) as error:
        fail("FRESH_JSON_INVALID", "%s: %s" % (label, error))


def safe_relative(value: str) -> pathlib.PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        fail("FRESH_PATH_INVALID", repr(value))
    path = pathlib.PurePosixPath(value)
    if path.as_posix() != value:
        fail("FRESH_PATH_INVALID", value)
    if path.is_absolute() or any(part in ("", ".", "..") for part in path.parts):
        fail("FRESH_PATH_INVALID", value)
    if any(part.startswith(".") for part in path.parts):
        fail("FRESH_HIDDEN_ENTRY", value)
    return path


def read_regular(path: pathlib.Path, label: str) -> bytes:
    try:
        node = path.lstat()
    except FileNotFoundError:
        fail("FRESH_PAYLOAD_MISSING", label)
    if not stat.S_ISREG(node.st_mode) or path.is_symlink():
        fail("FRESH_NODE_INVALID", label)
    if node.st_size > MAX_FILE:
        fail("FRESH_FILE_TOO_LARGE", label)
    try:
        return path.read_bytes()
    except OSError as error:
        fail("FRESH_PAYLOAD_READ_FAILED", "%s: %s" % (label, error))


def lexical_entries(root: pathlib.Path) -> list[str]:
    if root.is_symlink() or not root.is_dir():
        fail("FRESH_ROOT_INVALID", str(root))
    rows = []
    folded = {}
    total = 0
    for directory, directories, files in os.walk(str(root), followlinks=False):
        base = pathlib.Path(directory)
        for name in directories:
            node = base / name
            relative = node.relative_to(root).as_posix()
            safe_relative(relative)
            mode = node.lstat().st_mode
            if node.is_symlink() or not stat.S_ISDIR(mode):
                fail("FRESH_NODE_INVALID", relative)
        for name in files:
            node = base / name
            relative = node.relative_to(root).as_posix()
            safe_relative(relative)
            raw = read_regular(node, relative)
            total += len(raw)
            if total > MAX_TOTAL:
                fail("FRESH_TOTAL_TOO_LARGE", str(total))
            key = relative.casefold()
            if key in folded:
                fail("FRESH_CASE_COLLISION", "%s / %s" % (folded[key], relative))
            folded[key] = relative
            rows.append(relative)
    return sorted(rows)


def identity_matches(row, head: str, tree: str, parent: str) -> bool:
    if not isinstance(row, dict):
        return False
    actual_head = row.get("head", row.get("commit"))
    if any(row[key] != head for key in ("head", "commit") if key in row):
        return False
    if any(row[key] != parent for key in ("parent", "first_parent") if key in row):
        return False
    parents = row.get("parents")
    if parents is None and row.get("parent") is not None:
        parents = [row.get("parent")]
    if parents is None and row.get("first_parent") is not None:
        parents = [row.get("first_parent")]
    return actual_head == head and row.get("tree") == tree and parents == [parent]


# Frozen R14 row expectations projected from the unchanged matrix/base/R4 inputs.
MATRIX_CODES = ["PRODUCER_VERDICT_FORBIDDEN","SCHEMA_REQUIRED_FIELD_MISSING","H2_DERIVED_OR_MISLABELED_FIELD_FORBIDDEN","JSON_NONFINITE_NUMBER","JSON_DUPLICATE_KEY","MALFORMED_CANDIDATE_IDENTITY","CANDIDATE_IDENTITY_MISMATCH","CANDIDATE_FINGERPRINT_MISMATCH","PRODUCT_FINGERPRINT_MISMATCH","CANDIDATE_DIRTY","DIFF_OUTSIDE_ALLOWLIST","UPSTREAM_ARCHIVE_HASH_MISMATCH","SYMLINK_ESCAPE","STREAM_TRUNCATED","TOOL_HASH_MISMATCH","OBSERVATION_REPLAY","TIME_ORDER_INVALID","SANITIZER_PRODUCT_FAILURE","SANITIZER_INSTRUMENTATION_UNPROVEN",None,"EXTRA_ROOT_OR_BUILD","NESTED_UNKNOWN_FIELD","UNBOUND_EXTERNAL_STREAM","DUPLICATE_BUILD_ROLE","MISSING_BUILD_ROLE","DUPLICATE_TOOL_ROLE","EXTRA_TOOL_ROLE","MISSING_TOOL_ROLE","DUPLICATE_ARTIFACT_ROLE","EXTRA_ORPHAN_ARTIFACT","UPSTREAM_TREE_MANIFEST_MISSING","DUPLICATE_INVOCATION_ROLE","EXTRA_INVOCATION_ROLE","MISSING_INVOCATION_ROLE","STREAM_ROLE_SWAP","INTEGRATED_SOURCE_TREE_TAMPERED","DANGLING_ARTIFACT_REFERENCE","DUPLICATE_CANONICAL_OWNER_SLOT","SYMLINK_COMPONENT","PATH_IDENTITY_CHANGED","CONSUMER_HASH_MISMATCH","POLICY_HASH_MISMATCH","SCHEMA_HASH_MISMATCH","ORACLE_HASH_MISMATCH","CTEST_STREAM_UNPROVEN","SIMULATOR_OUTPUT_UNPROVEN","UPSTREAM_SOURCE_TREE_EXPANDED","CONSUMER_NOT_SEALED","POLICY_NOT_SEALED","SCHEMA_NOT_SEALED","ORACLE_NOT_SEALED","RH10_TRACKED_OUTER_MANIFEST_MISSING","RH10_FRESH_OUTER_MANIFEST_HASH_MISMATCH","RH10_OUTER_PROVENANCE_FALSE","ARGV_MISMATCH","CWD_MISMATCH","ENVIRONMENT_MISMATCH","TERMINATION_FIELDS_INCONSISTENT","OBSERVATION_STDOUT_MISMATCH","FINAL_CHECKSUM_MISMATCH"]
BASE_CODES = [None,"MATRIX_RECEIPT_MISSING","MATRIX_EXECUTION_COUNT_MISMATCH","MATRIX_CASE_FAILED","MATRIX_CASE_SET_INCOMPLETE","MATRIX_CASE_SET_INCOMPLETE","RECEIPT_RUN_ID_MISMATCH","RECEIPT_CANDIDATE_MISMATCH","RECEIPT_POLICY_MISMATCH","RECEIPT_CANONICAL_RUN_MISMATCH","MATRIX_HASH_MISMATCH","RUNNER_HASH_MISMATCH","MATRIX_SUMMARY_DIGEST_MISMATCH","MATRIX_CASE_SET_DIGEST_MISMATCH","MATRIX_CASE_OUTPUT_MISMATCH","PROTOCOL_GATE_SET_MISMATCH","PROTOCOL_GATE_SET_MISMATCH","MANIFEST_CANDIDATE_BINDING_MISMATCH","RESULT_CANDIDATE_BINDING_MISMATCH","RESULT_MANIFEST_BINDING_MISMATCH","PRODUCT_VERDICT_MISMATCH","PRODUCT_FAILURE_CODE_MISMATCH","FINAL_REVIEW_INCONSISTENT","FINAL_RESULT_DERIVATION_MISMATCH","EXPECTED_MATRIX_RECEIPT_DIGEST_REQUIRED","MATRIX_RECEIPT_DIGEST_MISMATCH","EXPECTED_SEAL_DIGEST_REQUIRED","SEAL_ROOT_DIGEST_MISMATCH","SEAL_ROOT_DIGEST_MISMATCH","MATRIX_BYTES_MISSING","POLICY_BINDING_MISMATCH","RECEIPT_REQUIRED_FIELD_MISSING"]
R4_CODES = ["SESSION_ROOT_EMPTY","SESSION_ROOT_NOT_EMPTY","CANONICAL_SEAL_RESERVED_EMPTY","NO_PRIOR_RUN_REFERENCE","CLOSURE_FIXTURE_VALID","CLOSURE_FIXTURE_RUN_ID_MISMATCH","CLOSURE_FIXTURE_CANDIDATE_MISMATCH","CLOSURE_FIXTURE_POLICY_MISMATCH","CLOSURE_FIXTURE_FACTS_MISMATCH","CLOSURE_FIXTURE_FINAL_ACCEPT_FORBIDDEN",["CLOSURE_FIXTURE_REVIEW_SESSION_MISMATCH","CLOSURE_FIXTURE_ALREADY_CONSUMED"],"CONSUMER_NOT_SEALED","POLICY_NOT_SEALED","SCHEMA_NOT_SEALED","ORACLE_NOT_SEALED","FINAL_CHECKSUM_MISMATCH","MATRIX_CASE_FAILED","FINAL_ACCEPTANCE_FIXTURE_FORBIDDEN","EXECUTION_ORDER_IDENTICAL","INPUT_OUTPUT_OVERLAP","CANONICAL_SEAL_RESERVED_EMPTY","EXECUTION_DAG_ACYCLIC"]
DAG_DEPENDENCIES = {"r4.n00_preflight":[],"r4.n10_policy":["r4.n00_preflight"],"r4.n20_produce":["r4.n10_policy"],"r4.n30_derive":["r4.n20_produce"],"r4.n35_seal_empty":["r4.n30_derive"],"r4.n40_fixture":["r4.n30_derive","r4.n35_seal_empty"],"r4.n41_fixture_anchor":["r4.n40_fixture"],"r4.n42_fixture_verify":["r4.n41_fixture_anchor"],"r4.n50_closure_cases":["r4.n42_fixture_verify"],"r4.n50_other_cases":["r4.n30_derive"],"r4.n51_receipt":["r4.n50_closure_cases","r4.n50_other_cases"],"r4.n52_receipt_anchor":["r4.n51_receipt"],"r4.n60_finalize":["r4.n52_receipt_anchor","r4.n41_fixture_anchor"],"r4.n61_final_anchor":["r4.n60_finalize"],"r4.n70_semantic_verify":["r4.n61_final_anchor"],"r4.n80_base_acceptance":["r4.n70_semantic_verify"],"r4.n81_cycle_acceptance":["r4.n80_base_acceptance"],"r4.n90_final_audit":["r4.n81_cycle_acceptance"]}


def obj(value, label):
    if not isinstance(value, dict):
        fail("FRESH_JSON_INVALID", label + ": expected object")
    return value


def seq(value, label):
    if not isinstance(value, list):
        fail("FRESH_JSON_INVALID", label + ": expected array")
    return value


def integer(value, label):
    if type(value) is not int:
        fail("FRESH_JSON_INVALID", label + ": expected integer")
    return value


def string(value, label):
    if not isinstance(value, str) or not value:
        fail("FRESH_JSON_INVALID", label + ": expected nonempty string")
    return value


def hash_value(value, label):
    if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
        fail("FRESH_MANIFEST_BINDING_MISMATCH", label + ": SHA256")
    return value


def utc(value, label):
    string(value, label)
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        fail("FRESH_MANIFEST_BINDING_MISMATCH", label + ": UTC timestamp")
    if "T" not in value or not value.endswith(("Z", "+00:00")) or parsed.utcoffset() != dt.timedelta(0):
        fail("FRESH_MANIFEST_BINDING_MISMATCH", label + ": UTC timestamp")
    return parsed


def require(condition, code, label):
    if not condition:
        fail(code, label)


def case_rows(document, prefix, codes, code):
    rows = seq(document.get("cases"), prefix + ".cases")
    for row in rows:
        obj(row, prefix + ".case")
    require([r.get("id") for r in rows] == ["%s%02d" % (prefix, i) for i in range(1, len(codes) + 1)], code, "exact IDs")
    for index, row in enumerate(rows):
        require(row.get("pass") is True, code, row["id"])
        if prefix == "R4C":
            allowed = codes[index] if isinstance(codes[index], list) else [codes[index]]
            require(row.get("actual_code") in allowed, code, row["id"])
            continue
        expected = {"exit": 0 if (prefix == "E" and index == 19) or (prefix == "R3P" and index == 0) else 2,
                    "failure_code": codes[index]}
        if prefix == "E":
            expected.update(gate="PASS" if index == 19 else ("FAIL" if index in (17, 53) else "NOT_PROVEN"),
                            product="FAIL" if index in (17, 19, 53) else "NOT_PROVEN",
                            review="ACCEPT_C3_EVIDENCE_PROTOCOL" if index == 19 else "REJECT_C3_EVIDENCE_PROTOCOL")
        for key, value in expected.items():
            require(type(row.get("actual_" + key)) is type(value) and row.get("actual_" + key) == value
                    and type(row.get("expected_" + key)) is type(value) and row.get("expected_" + key) == value,
                    code, row["id"] + "." + key)
    for key, value in (("passed", len(rows)), ("failed", 0),
                       ("case_count" if prefix == "E" else "total", len(rows))):
        require(integer(document.get(key), prefix + "." + key) == value, code, key)
    return rows


def semantic_checks(root: pathlib.Path, manifest: dict, expected: dict) -> None:
    load = lambda name: strict_json(read_regular(root / name, name), name)
    authority = load("authority-binding.json")
    require(authority.get("status") == "PASS" and identity_matches(authority, expected["head"], expected["tree"], expected["parent"]),
            "FRESH_AUTHORITY_BINDING_MISMATCH", "authority-binding.json")
    bundle = load("bundle-verification.json")
    require(bundle.get("status") == "PASS", "FRESH_BUNDLE_VERIFICATION_MISMATCH", "bundle status")
    receipt = load("50-matrix/receipt.json")
    base = load("80-acceptance/base/summary.json")
    r4 = load("80-acceptance/r4/summary.json")
    matrix_rows = case_rows(receipt, "E", MATRIX_CODES, "FRESH_MATRIX_COUNT_MISMATCH")
    base_rows = case_rows(base, "R3P", BASE_CODES, "FRESH_BASE_COUNT_MISMATCH")
    r4_rows = case_rows(r4, "R4C", R4_CODES, "FRESH_R4_COUNT_MISMATCH")
    result = load("90-final-audit/fresh-chain-result.json")
    session = string(result.get("review_session_id"), "review session")
    require(all(d.get("review_session_id") == session for d in (manifest, receipt, r4)),
            "FRESH_REVIEW_SESSION_MISMATCH", "manifest/result/receipt/r4")
    for document in (receipt, result):
        require(identity_matches(document.get("candidate_identity"), expected["head"], expected["tree"], expected["parent"]),
                "FRESH_CANDIDATE_BINDING_MISMATCH", "receipt/result")
    require(receipt["candidate_identity"] == result["candidate_identity"],
            "FRESH_CANDIDATE_BINDING_MISMATCH", "complete candidate identity")
    matrix_summary = obj(receipt.get("matrix"), "receipt.matrix")
    require(matrix_summary == {"definition_sha256": receipt.get("matrix_sha256"), "passed": 60, "total": 60, "failed": 0}
            and receipt.get("matrix_sha256") == "8b7cf0d8e3b3702e9aa3c32aff9d1ed3e363ceab52699539251975a61985060f",
            "FRESH_MATRIX_COUNT_MISMATCH", "frozen matrix definition")
    require(receipt.get("case_set_sha256") == digest(canonical({"schema": "cth3ds.runtime-core-matrix-case-set/v1", "cases": matrix_rows})),
            "FRESH_MANIFEST_BINDING_MISMATCH", "case-set digest")
    summary = {k: v for k, v in receipt.items() if k not in
               ("schema", "stage_id", "created_at", "summary_sha256", "case_count")}
    summary.update(schema="cth3ds.runtime-core-c3-matrix-result/v2", total=len(matrix_rows))
    require(receipt.get("summary_sha256") == digest(canonical(summary)),
            "FRESH_MANIFEST_BINDING_MISMATCH", "matrix summary digest")
    required_counts = {"matrix": len(matrix_rows), "base_acceptance": len(base_rows),
                       "r4_acceptance": len(r4_rows), "composed_acceptance": len(base_rows) + len(r4_rows),
                       "facts_checks": 18}
    for key, count in required_counts.items():
        row = obj(result.get(key), key)
        require(all(integer(row.get(k), key + "." + k) == count for k in ("passed", "total")),
                "FRESH_RESULT_COUNT_MISMATCH", key)
    require(result.get("semantic_verify") == "PASS" and result.get("construction_self_verification") == "PASS"
            and result.get("independent_review") == "NOT_PROVEN", "FRESH_RESULT_STATUS_MISMATCH", "result status")
    require(result.get("receipt_sha256") == digest(read_regular(root / "50-matrix/receipt.json", "receipt")),
            "FRESH_MANIFEST_BINDING_MISMATCH", "receipt digest")
    invocation = hash_value(result.get("verified_invocation_sha256"), "invocation")
    require(receipt.get("verified_invocation_sha256") == invocation,
            "FRESH_MANIFEST_BINDING_MISMATCH", "receipt invocation")
    utc(receipt.get("created_at"), "receipt.created_at")
    input_bundle = obj(result.get("input_bundle"), "result.input_bundle")
    final_rehash = obj(input_bundle.get("final_rehash"), "final rehash")
    manifest_bundle = obj(manifest.get("bundle"), "manifest.bundle")
    for key in ("manifest_sha256", "sha256sums_sha256"):
        value = hash_value(bundle.get(key), key)
        require(manifest_bundle.get(key) == value and final_rehash.get(key) == value,
                "FRESH_BUNDLE_BINDING_MISMATCH", key)
    require(input_bundle.get("manifest_sha256") == bundle["manifest_sha256"],
            "FRESH_BUNDLE_BINDING_MISMATCH", "input bundle manifest")
    fixture = obj(receipt.get("closure_fixture"), "closure fixture")
    require(fixture.get("sha256s_sha256") == result.get("fixture_sha256s_sha256")
            and fixture.get("consumed_once") is True and fixture.get("final_acceptance_eligible") is False,
            "FRESH_MANIFEST_BINDING_MISMATCH", "fixture binding")
    hash_value(fixture.get("sha256s_sha256"), "fixture digest")
    checked = seq(final_rehash.get("checked"), "bundle role checks")
    roles = set()
    for role in checked:
        obj(role, "bundle role")
        name = string(role.get("role"), "bundle role name")
        safe_relative(role.get("bundle_relative_path"))
        hash_value(role.get("sha256_or_tree_digest"), "bundle role digest")
        require(name not in roles, "FRESH_BUNDLE_BINDING_MISMATCH", "duplicate role")
        roles.add(name)

    # Rebuild journal topology before consulting its reported DAG counts.
    raw_journal = read_regular(root / "00-preflight/execution-journal.jsonl", "journal")
    journal = [strict_json(line, "journal row") for line in raw_journal.splitlines()]
    byid = {}
    for row in journal:
        name = string(row.get("stage_id"), "journal.stage_id")
        require(name not in byid or name == "r4.n80_base_acceptance.case",
                "FRESH_DAG_MISMATCH", "duplicate stage " + name)
        deps = seq(row.get("dependency_ids"), name + ".dependencies")
        for dependency in deps:
            string(dependency, "dependency")
        require(len(set(deps)) == len(deps), "FRESH_DAG_MISMATCH", "duplicate dependency")
        started = utc(row.get("started_at"), name + ".started_at")
        ended = utc(row.get("ended_at"), name + ".ended_at")
        require(started <= ended, "FRESH_DAG_MISMATCH", "stage time")
        integer(row.get("exit_code"), name + ".exit_code")
        for key in ("stdout_sha256", "stderr_sha256"):
            hash_value(row.get(key), name + "." + key)
        if ".case" not in name and "fixture-consume" not in name:
            require(row.get("verified_invocation_sha256") == invocation,
                    "FRESH_MANIFEST_BINDING_MISMATCH", "journal invocation")
        byid[name] = row
    # Authority stages must exist once, match the frozen dependencies and complete
    # before their successors. Extra diagnostic stages do not create authority.
    edges = sorted([[dep, name] for name, deps in DAG_DEPENDENCIES.items() for dep in deps])
    for name, deps in DAG_DEPENDENCIES.items():
        row = obj(byid.get(name), name)
        require(sorted(row["dependency_ids"]) == sorted(deps) and row["exit_code"] == 0,
                "FRESH_DAG_MISMATCH", name)
        for dep in deps:
            prior = obj(byid.get(dep), dep)
            require(utc(prior["ended_at"], dep) <= utc(row["started_at"], name), "FRESH_DAG_MISMATCH", "dependency time")
    pending = {n: set(ds) for n, ds in DAG_DEPENDENCIES.items()}
    visited = []
    while pending:
        ready = [n for n, ds in pending.items() if not ds]
        require(bool(ready), "FRESH_DAG_MISMATCH", "cycle")
        for name in ready:
            visited.append(name)
            del pending[name]
        for deps in pending.values():
            deps.difference_update(ready)
    dag = load("90-final-audit/observed-dag.json")
    nodes = seq(dag.get("nodes"), "dag.nodes")
    actual_edges = seq(dag.get("edges"), "dag.edges")
    for name in nodes:
        string(name, "dag.node")
    for edge in actual_edges:
        seq(edge, "dag.edge")
        require(len(edge) == 2 and all(isinstance(n, str) for n in edge), "FRESH_DAG_MISMATCH", "edge shape")
    require(dag.get("review_session_id") == session and sorted(nodes) == sorted(visited) and sorted(actual_edges) == edges
            and all(type(dag.get(k)) is int and dag[k] == v for k, v in (("node_count",len(visited)),("edge_count",len(edges)),("cycle_count",0))),
            "FRESH_DAG_MISMATCH", "observed DAG")
    for row in matrix_rows:
        j = obj(byid.get("r4.n50_matrix.case." + row["id"]), "matrix invocation")
        require(all(j.get(k) == row.get(k if k != "exit_code" else "actual_exit")
                    for k in ("exit_code", "stdout_sha256", "stderr_sha256")),
                "FRESH_MATRIX_COUNT_MISMATCH", "journal/" + row["id"])

    h2 = load("90-final-audit/h2-exact20/summary.json")
    run_ids = set()
    for profile in ("sanitized", "non_sanitized"):
        passed = 0
        for index in range(1, 21):
            name = "90-final-audit/h2-exact20/%s-%02d.json" % (profile, index)
            payload = load(name)
            record = obj(payload.get("record"), name + ".record")
            observation = obj(payload.get("observation"), name + ".observation")
            values = obj(observation.get("observations"), name + ".observations")
            run_id = string(record.get("run_id"), name + ".run_id")
            require(record.get("profile") == profile and type(record.get("process_index")) is int and record["process_index"] == index
                    and record.get("exit_code") == 0 and type(record.get("exit_code")) is int
                    and record.get("exact_red_fact") is True and run_id not in run_ids and observation.get("run_id") == run_id,
                    "FRESH_H2_RECORD_MISMATCH", name)
            run_ids.add(run_id)
            for key, delta in (("entries",1),("leases",1),("allocation_records",1),("pins",0),("dependencies",0),("mounted_package_count",0)):
                require(integer(values.get(key + "_after"), key) - integer(values.get(key + "_before"), key) == delta,
                        "FRESH_H2_RECORD_MISMATCH", name + "." + key)
            totals = {}
            for key, length in (("pool_bytes",7),("backend_bytes",2)):
                arrays = [seq(values.get(key + suffix), name + key) for suffix in ("_before","_after")]
                require(all(len(a) == length for a in arrays), "FRESH_H2_RECORD_MISMATCH", "accounting shape")
                totals[key] = sum(integer(v,key) for v in arrays[1]) - sum(integer(v,key) for v in arrays[0])
            require(totals["pool_bytes"] == integer(record.get("logical_pool_delta"), "logical delta") == 64
                    and totals["backend_bytes"] == integer(record.get("backend_accounted_delta"), "backend delta") >= totals["pool_bytes"]
                    and values.get("escaped_lease_valid_after") is True
                    and values.get("state_before") == values.get("state_after") == "MENU_STABLE"
                    and values.get("transition_active_before") is False and values.get("transition_active_after") is False
                    and values.get("call_result") == "E_TEST_PREPARE_ABORT"
                    and values.get("fault_point") == "after-first-staged-acquire",
                    "FRESH_H2_RECORD_MISMATCH", name + ".observation")
            j = obj(byid.get("r4.n90_final_audit.h2_%s_%02d" % (profile,index)), "H2 invocation")
            require(all(j.get(k) == record.get(k) for k in ("exit_code","stdout_sha256","stderr_sha256")),
                    "FRESH_H2_RECORD_MISMATCH", name + ".journal")
            passed += 1
        summary = obj(h2.get(profile), "H2 profile summary")
        require(all(type(summary.get(k)) is int and summary[k] == passed for k in ("passed","total")),
                "FRESH_H2_SUMMARY_MISMATCH", profile)
    require(h2.get("status") == "PASS" and type(h2.get("independent_process_count")) is int
            and h2["independent_process_count"] == len(run_ids) == 40,
            "FRESH_H2_SUMMARY_MISMATCH", "independent processes")
    require(result.get("h2_exact20_gate") == h2, "FRESH_H2_SUMMARY_MISMATCH", "result summary")

    # R4 row evidence has several existing shapes; validate each before use.
    for index, row in enumerate(r4_rows, 1):
        evidence = row.get("evidence")
        if index == 3:
            observations = seq(evidence, "R4C03.evidence")
            require(len(observations) == 3 and observations == result.get("canonical_seal_pre_finalizer_observations"),
                    "FRESH_R4_COUNT_MISMATCH", "seal observations")
            for observation in observations:
                obj(observation, "seal observation")
                utc(observation.get("observed_at"), "seal observation")
                require(type(observation.get("entry_count")) is int and observation["entry_count"] == 0 and observation.get("is_symlink") is False,
                        "FRESH_R4_COUNT_MISMATCH", "seal was not empty")
            continue
        evidence = obj(evidence, row["id"] + ".evidence")
        if index == 1:
            rehash = obj(evidence.get("preflight_rehash"), "preflight rehash")
            transport = obj(evidence.get("candidate_transport"), "candidate transport")
            require(evidence.get("initial_entry_count") == 0 and evidence.get("review_session_id") == session
                    and evidence.get("verified_invocation_sha256") == invocation and transport.get("head") == expected["head"]
                    and evidence.get("bundle_manifest_sha256") == bundle["manifest_sha256"],
                    "FRESH_MANIFEST_BINDING_MISMATCH", "R4 preflight binding")
            for key in ("manifest_sha256","sha256sums_sha256","checked"):
                require(rehash.get(key) == final_rehash.get(key), "FRESH_BUNDLE_BINDING_MISMATCH", "preflight/final " + key)
        elif index == 4:
            require(evidence.get("initial_entry_count") == 0 and evidence.get("review_session_id") == session
                    and evidence.get("canonical_seal_writer") == "finalizer", "FRESH_R4_COUNT_MISMATCH", row["id"])
        elif index == 19:
            require(evidence.get("equal") is True, "FRESH_R4_COUNT_MISMATCH", row["id"])
            hash_value(evidence.get("normalized_sha256"), "normalized journal")
        elif index == 20:
            integration = obj(evidence.get("integration"), "overlap integration")
            submatrix = obj(evidence.get("submatrix"), "overlap submatrix")
            cases = seq(submatrix.get("cases"), "overlap cases")
            require(bool(cases) and integration.get("actual_exit") == 2 and integration.get("actual_failure_code") == row["actual_code"]
                    and integration.get("no_stage_started") is True, "FRESH_R4_COUNT_MISMATCH", row["id"])
            for case in cases:
                obj(case, "overlap case")
                require(case.get("pass") is True and case.get("actual_code") == case.get("expected_code")
                        and case.get("continuation_creation_count") == (1 if case.get("id") == "disjoint-continuation" else 0)
                        and case.get("validation_new_node_count") == 0, "FRESH_R4_COUNT_MISMATCH", "overlap case")
        elif index == 22:
            require(all(type(evidence.get(k)) is int and evidence[k] == v for k,v in
                        (("cycle_count",0),("edge_count",len(edges)),("node_count",len(visited)),("final_seal_to_matrix_edge_count",0)))
                    and evidence.get("completed_prefix_exact") is True, "FRESH_R4_COUNT_MISMATCH", row["id"])
        else:
            require(type(evidence.get("actual_exit")) is int and evidence["actual_exit"] == (0 if index == 5 else 2)
                    and (index == 5 and evidence.get("actual_failure_code") is None or evidence.get("actual_failure_code") == row["actual_code"]),
                    "FRESH_R4_COUNT_MISMATCH", row["id"])
            if 12 <= index <= 16:
                require(evidence in matrix_rows, "FRESH_R4_COUNT_MISMATCH", "closure matrix binding")


def expected_from_args(values: list[str]) -> dict:
    keys = ["run_id", "attempt", "job", "artifact_name", "head", "tree", "parent", "bundle_url", "bundle_sha256"]
    if len(values) != len(keys):
        fail("FRESH_ARGUMENT_ERROR", "expected %d binding arguments" % len(keys))
    result = dict(zip(keys, values))
    wanted_name = "official-fresh-chain-evidence-%s-%s-%s" % (result["run_id"], result["attempt"], result["head"])
    if result["artifact_name"] != wanted_name:
        fail("FRESH_ARTIFACT_NAME_MISMATCH", result["artifact_name"])
    if len(result["head"]) != 40 or len(result["tree"]) != 40 or len(result["parent"]) != 40:
        fail("FRESH_IDENTITY_FORMAT_INVALID", "head/tree/parent")
    if len(result["bundle_sha256"]) != 64 or not result["bundle_url"].startswith("https://"):
        fail("FRESH_BUNDLE_BINDING_MISMATCH", "bundle transport")
    return result


def verify_root(root: pathlib.Path, expected: dict) -> dict:
    entries = lexical_entries(root)
    if entries != SUCCESS_PATHS:
        missing = sorted(set(SUCCESS_PATHS) - set(entries))
        extra = sorted(set(entries) - set(SUCCESS_PATHS))
        fail("FRESH_ENTRY_SET_MISMATCH", "missing=%s extra=%s" % (missing, extra))
    manifest_raw = read_regular(root / "artifact-manifest.json", "artifact-manifest.json")
    manifest = strict_json(manifest_raw, "artifact-manifest.json")
    utc(manifest.get("created_at_utc"), "manifest.created_at_utc")
    if (manifest.get("schema") != "cth3ds.public-fresh-evidence/v1"
            or manifest.get("status") != "PASS"
            or manifest.get("outcome") != "success"
            or manifest.get("payload_count") != 56):
        fail("FRESH_MANIFEST_INVALID", "header")
    if manifest.get("run") != {"id": expected["run_id"], "attempt": expected["attempt"], "job": expected["job"]} or manifest.get("artifact") != {"name": expected["artifact_name"]}:
        fail("FRESH_RUN_BINDING_MISMATCH", "run/artifact")
    if manifest.get("candidate_identity") != {"head": expected["head"], "tree": expected["tree"], "parents": [expected["parent"]]}:
        fail("FRESH_CANDIDATE_BINDING_MISMATCH", "manifest")
    bundle_row = obj(manifest.get("bundle"), "manifest.bundle")
    if bundle_row.get("url") != expected["bundle_url"] or bundle_row.get("transport_sha256") != expected["bundle_sha256"]:
        fail("FRESH_BUNDLE_BINDING_MISMATCH", "manifest")
    rows = manifest.get("payloads")
    if not isinstance(rows, list) or len(rows) != 56:
        fail("FRESH_MANIFEST_INVALID", "payload rows")
    expected_map = {public: source for source, public in MAPPINGS}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or set(row) != {"source", "path", "bytes", "sha256"}:
            fail("FRESH_MANIFEST_INVALID", "payload shape")
        name = row["path"]
        string(name, "payload.path")
        string(row["source"], "payload.source")
        integer(row["bytes"], "payload.bytes")
        hash_value(row["sha256"], "payload.sha256")
        if name in seen or name not in expected_map or row["source"] != expected_map[name]:
            fail("FRESH_MANIFEST_INVALID", "payload mapping %s" % name)
        seen.add(name)
        raw = read_regular(root / name, name)
        if row["bytes"] != len(raw) or row["sha256"] != digest(raw):
            fail("FRESH_PAYLOAD_DIGEST_MISMATCH", name)
    if seen != set(PAYLOAD_PATHS):
        fail("FRESH_MANIFEST_INVALID", "payload set")
    sums_raw = read_regular(root / "SHA256SUMS", "SHA256SUMS")
    try:
        sums_text = sums_raw.decode("ascii")
    except UnicodeDecodeError:
        fail("FRESH_SHA256SUMS_INVALID", "non-ASCII")
    if "\r" in sums_text or not sums_text.endswith("\n"):
        fail("FRESH_SHA256SUMS_INVALID", "line endings")
    sum_rows = sums_text.splitlines()
    expected_sum_paths = sorted(PAYLOAD_PATHS + ["artifact-manifest.json"])
    actual_sum_paths = []
    for line in sum_rows:
        if len(line) < 67 or line[64:66] != "  ":
            fail("FRESH_SHA256SUMS_INVALID", line)
        value, name = line[:64], line[66:]
        safe_relative(name)
        if digest(read_regular(root / name, name)) != value:
            fail("FRESH_SHA256SUMS_MISMATCH", name)
        actual_sum_paths.append(name)
    if actual_sum_paths != expected_sum_paths:
        fail("FRESH_SHA256SUMS_INVALID", "coverage/order")
    semantic_checks(root, manifest, expected)
    return {"status": "PASS", "entry_count": 58, "payload_count": 56,
            "manifest_sha256": digest(manifest_raw), "sha256sums_sha256": digest(sums_raw),
            "review_session_id": manifest["review_session_id"]}


def stage(args: list[str]) -> dict:
    if len(args) < 4:
        fail("FRESH_ARGUMENT_ERROR", "stage")
    session, envelope, target = map(pathlib.Path, args[:3])
    outcome = args[3]
    expected = expected_from_args(args[4:])
    if target.exists() or target.is_symlink():
        fail("FRESH_STAGE_ALREADY_EXISTS", str(target))
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = pathlib.Path(tempfile.mkdtemp(prefix=".%s." % target.name, dir=str(target.parent)))
    try:
        if outcome != "success":
            payload_rows = []
            for relative in ENVELOPE:
                raw = read_regular(envelope / relative, relative)
                output = temporary / relative
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_bytes(raw)
                payload_rows.append({"source": "envelope/" + relative,
                                     "path": relative, "bytes": len(raw),
                                     "sha256": digest(raw)})
            diagnostics = []
            unavailable_diagnostics = []
            command_outcome = None
            for relative in ("00-preflight/durable-failure.json", "00-preflight/execution-journal.jsonl"):
                source = session / relative
                if source.exists() or source.is_symlink():
                    raw = read_regular(source, relative)
                    output = temporary / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(raw)
                    payload_rows.append({"source": "session/" + relative,
                                         "path": relative, "bytes": len(raw),
                                         "sha256": digest(raw)})
                    if relative.endswith(".jsonl"):
                        diagnostics.extend(strict_json(line, "failure journal") for line in raw.splitlines())
                    else:
                        failure = strict_json(raw, "durable failure")
                        if "last_journal_entry" in failure:
                            diagnostics.append(obj(failure["last_journal_entry"], "last journal entry"))
            command_record = envelope / "fresh-command-outcome.json"
            if command_record.exists() or command_record.is_symlink():
                raw = read_regular(command_record, "fresh-command-outcome.json")
                command_outcome = strict_json(raw, "command outcome")
                integer(command_outcome.get("exit_code"), "command exit")
                require(command_outcome.get("outcome") in ("success", "failure", "timed_out"),
                        "FRESH_JSON_INVALID", "command outcome")
                utc(command_outcome.get("started_at_utc"), "command start")
                utc(command_outcome.get("ended_at_utc"), "command end")
                (temporary / "fresh-command-outcome.json").write_bytes(raw)
                payload_rows.append({"source": "envelope/fresh-command-outcome.json",
                                     "path": "fresh-command-outcome.json", "bytes": len(raw),
                                     "sha256": digest(raw)})
            retained = {row["path"] for row in payload_rows}
            for diagnostic in diagnostics:
                for stream in ("stdout", "stderr"):
                    reference = diagnostic.get(stream + "_path")
                    if reference is None:
                        continue
                    string(reference, "diagnostic path")
                    if "\x00" in reference or "\\" in reference or ".." in pathlib.PurePosixPath(reference).parts:
                        fail("FRESH_PATH_INVALID", reference)
                    referenced = pathlib.Path(reference)
                    if referenced.is_absolute():
                        try:
                            relative = referenced.relative_to(session.absolute()).as_posix()
                        except ValueError:
                            # A relocated failed session can retain references to
                            # a runner that no longer exists. Never read outside it.
                            if not referenced.exists():
                                unavailable_diagnostics.append(reference)
                                continue
                            fail("FRESH_PATH_INVALID", reference)
                    else:
                        relative = reference
                    safe_relative(relative)
                    source = session / relative
                    if not source.exists() and not source.is_symlink():
                        unavailable_diagnostics.append(reference)
                        continue
                    # Every component must remain within the session without links.
                    cursor = session
                    if cursor.is_symlink():
                        fail("FRESH_NODE_INVALID", str(cursor))
                    for component in pathlib.PurePosixPath(relative).parts:
                        cursor = cursor / component
                        if cursor.is_symlink():
                            fail("FRESH_NODE_INVALID", relative)
                    raw = read_regular(source, relative)
                    expected_hash = hash_value(diagnostic.get(stream + "_sha256"), "diagnostic digest")
                    require(digest(raw) == expected_hash, "FRESH_PAYLOAD_DIGEST_MISMATCH", relative)
                    if relative not in retained:
                        output = temporary / relative
                        output.parent.mkdir(parents=True, exist_ok=True)
                        output.write_bytes(raw)
                        retained.add(relative)
                        payload_rows.append({"source": "session/" + relative, "path": relative,
                                             "bytes": len(raw), "sha256": digest(raw)})
                    require(sum(row["bytes"] for row in payload_rows) <= MAX_TOTAL,
                            "FRESH_TOTAL_TOO_LARGE", "failure diagnostics")
            body = {"schema": "cth3ds.public-fresh-failure/v1",
                    "status": "FAILURE_PACKAGE_NON_ACCEPTING",
                    "outcome": outcome, "fresh_outcome": outcome,
                    "command_outcome": command_outcome,
                    "unavailable_diagnostics": sorted(set(unavailable_diagnostics)),
                    "run": {key: expected[key] for key in ("run_id", "attempt", "job")},
                    "artifact": {"name": expected["artifact_name"]},
                    "candidate_identity": {"head": expected["head"],
                                           "tree": expected["tree"],
                                           "parents": [expected["parent"]]},
                    "bundle": {"url": expected["bundle_url"],
                               "transport_sha256": expected["bundle_sha256"]},
                    "payload_count": len(payload_rows),
                    "payloads": sorted(payload_rows, key=lambda row: row["path"]),
                    "recorded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            (temporary / "failure.json").write_bytes(canonical(body))
            lexical_entries(temporary)
            os.replace(str(temporary), str(target))
            return {"status": "FAILURE_PACKAGE_NON_ACCEPTING", "fresh_outcome": outcome}
        duplicate_journal = session / "50-matrix/execution-journal.jsonl"
        canonical_journal = session / "00-preflight/execution-journal.jsonl"
        if read_regular(duplicate_journal, "50-matrix/execution-journal.jsonl") != read_regular(canonical_journal, "00-preflight/execution-journal.jsonl"):
            fail("FRESH_JOURNAL_DIVERGENCE", "matrix/preflight journals differ")
        payload_rows = []
        for source_name, public_name in MAPPINGS:
            source_root = envelope if source_name in ENVELOPE else session
            source = source_root / source_name
            raw = read_regular(source, source_name)
            destination = temporary / public_name
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(raw)
            payload_rows.append({"source": source_name, "path": public_name,
                                 "bytes": len(raw), "sha256": digest(raw)})
        result = strict_json(read_regular(temporary / "90-final-audit/fresh-chain-result.json", "fresh result"), "fresh result")
        bundle = strict_json(read_regular(temporary / "bundle-verification.json", "bundle verification"), "bundle verification")
        manifest = {
            "schema": "cth3ds.public-fresh-evidence/v1", "status": "PASS",
            "outcome": "success",
            "created_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
            "payload_count": 56, "payloads": sorted(payload_rows, key=lambda row: row["path"]),
            "run": {"id": expected["run_id"], "attempt": expected["attempt"], "job": expected["job"]},
            "artifact": {"name": expected["artifact_name"]},
            "candidate_identity": {"head": expected["head"], "tree": expected["tree"], "parents": [expected["parent"]]},
            "bundle": {"url": expected["bundle_url"], "transport_sha256": expected["bundle_sha256"],
                       "manifest_sha256": bundle.get("manifest_sha256"),
                       "sha256sums_sha256": bundle.get("sha256sums_sha256")},
            "review_session_id": result.get("review_session_id"),
        }
        manifest_raw = canonical(manifest)
        (temporary / "artifact-manifest.json").write_bytes(manifest_raw)
        sums = []
        for name in sorted(PAYLOAD_PATHS + ["artifact-manifest.json"]):
            sums.append("%s  %s\n" % (digest(read_regular(temporary / name, name)), name))
        with (temporary / "SHA256SUMS").open("w", encoding="ascii", newline="\n") as handle:
            handle.write("".join(sums))
        verify_root(temporary, expected)
        os.replace(str(temporary), str(target))
        return verify_root(target, expected)
    except BaseException:
        if temporary.exists():
            shutil.rmtree(temporary)
        raise


def verify_archive(args: list[str]) -> dict:
    if len(args) < 2:
        fail("FRESH_ARGUMENT_ERROR", "archive")
    archive = pathlib.Path(args[0])
    expected_transport = args[1]
    expected = expected_from_args(args[2:])
    raw = read_regular(archive, str(archive))
    if digest(raw) != expected_transport:
        fail("FRESH_TRANSPORT_DIGEST_MISMATCH", str(archive))
    try:
        handle = zipfile.ZipFile(archive)
        infos = handle.infolist()
    except (OSError, zipfile.BadZipFile) as error:
        fail("FRESH_ARCHIVE_INVALID", str(error))
    names = []
    folded = {}
    for info in infos:
        name = info.filename
        safe_relative(info.orig_filename)
        if info.orig_filename != name:
            fail("FRESH_PATH_INVALID", repr(info.orig_filename))
        safe_relative(name.rstrip("/") if name.endswith("/") else name)
        if name.endswith("/"):
            fail("FRESH_ARCHIVE_ENTRY_INVALID", name)
        if name in names:
            fail("FRESH_ARCHIVE_DUPLICATE_ENTRY", name)
        if name.casefold() in folded:
            fail("FRESH_CASE_COLLISION", "%s / %s" % (folded[name.casefold()], name))
        folded[name.casefold()] = name
        names.append(name)
        mode = (info.external_attr >> 16) & 0o170000
        if mode not in (0, stat.S_IFREG):
            fail("FRESH_ARCHIVE_ENTRY_INVALID", name)
        if info.file_size > MAX_FILE:
            fail("FRESH_FILE_TOO_LARGE", name)
    if sorted(names) != SUCCESS_PATHS:
        fail("FRESH_ENTRY_SET_MISMATCH", "archive")
    if sum(info.file_size for info in infos) > MAX_TOTAL:
        fail("FRESH_TOTAL_TOO_LARGE", "archive")
    with tempfile.TemporaryDirectory(prefix="cth3ds-public-fresh-verify-") as temporary:
        root = pathlib.Path(temporary)
        for info in infos:
            destination = root / info.filename
            destination.parent.mkdir(parents=True, exist_ok=True)
            try:
                content = handle.read(info)
            except (zipfile.BadZipFile, RuntimeError, NotImplementedError, EOFError) as error:
                fail("FRESH_ARCHIVE_INVALID", str(error))
            destination.write_bytes(content)
        return verify_root(root, expected)


try:
    operation = sys.argv[1] if len(sys.argv) > 1 else ""
    if operation == "stage":
        result = stage(sys.argv[2:])
    elif operation == "validate":
        if len(sys.argv) < 3:
            fail("FRESH_ARGUMENT_ERROR", "validate")
        result = verify_root(pathlib.Path(sys.argv[2]), expected_from_args(sys.argv[3:]))
    elif operation == "archive":
        result = verify_archive(sys.argv[2:])
    else:
        fail("FRESH_ARGUMENT_ERROR", "unknown operation %s" % operation)
    print(json.dumps(result, sort_keys=True, separators=(",", ":")))
except EvidenceError as error:
    print(json.dumps({"status": "FAIL", "code": error.code, "detail": error.detail},
                     sort_keys=True, separators=(",", ":")), file=sys.stderr)
    raise SystemExit(86)
except OSError as error:
    print(json.dumps({"status": "FAIL", "code": "FRESH_IO_FAILURE", "detail": str(error)},
                     sort_keys=True, separators=(",", ":")), file=sys.stderr)
    raise SystemExit(87)
PY
}

cth3ds_stage_fresh_evidence() {
  cth3ds_fresh_evidence stage "$@"
}

cth3ds_validate_fresh_evidence() {
  cth3ds_fresh_evidence validate "$@"
}

cth3ds_validate_fresh_archive() {
  cth3ds_fresh_evidence archive "$@"
}

cth3ds_enforce_fresh_evidence() {
  local fresh_outcome="$1" stage_outcome="$2" validation_outcome="$3"
  local upload_outcome="$4" artifact_id="${5:-}" artifact_url="${6:-}"
  if [[ "$fresh_outcome" != success ]]; then
    printf '%s\n' 'FRESH_EXECUTION_NOT_SUCCESSFUL' >&2
    return 90
  fi
  if [[ "$stage_outcome" != success ]]; then
    printf '%s\n' 'FRESH_STAGING_NOT_SUCCESSFUL' >&2
    return 91
  fi
  if [[ "$validation_outcome" != success ]]; then
    printf '%s\n' 'FRESH_VALIDATION_NOT_SUCCESSFUL' >&2
    return 92
  fi
  if [[ "$upload_outcome" != success || -z "$artifact_id" || -z "$artifact_url" ]]; then
    printf '%s\n' 'UPLOAD_NOT_FINALIZED' >&2
    return 93
  fi
}
