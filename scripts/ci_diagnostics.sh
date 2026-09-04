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
        return json.loads(data.decode("utf-8"), object_pairs_hook=pairs)
    except EvidenceError:
        raise
    except Exception as error:
        fail("FRESH_JSON_INVALID", "%s: %s" % (label, error))


def safe_relative(value: str) -> pathlib.PurePosixPath:
    if not value or "\x00" in value or "\\" in value:
        fail("FRESH_PATH_INVALID", repr(value))
    path = pathlib.PurePosixPath(value)
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
    parents = row.get("parents")
    if parents is None and row.get("parent") is not None:
        parents = [row.get("parent")]
    if parents is None and row.get("first_parent") is not None:
        parents = [row.get("first_parent")]
    return actual_head == head and row.get("tree") == tree and parents == [parent]


def semantic_checks(root: pathlib.Path, manifest: dict, expected: dict) -> None:
    load = lambda name: strict_json(read_regular(root / name, name), name)
    authority = load("authority-binding.json")
    if authority.get("status") != "PASS" or not identity_matches(authority, expected["head"], expected["tree"], expected["parent"]):
        fail("FRESH_AUTHORITY_BINDING_MISMATCH", "authority-binding.json")
    bundle = load("bundle-verification.json")
    if bundle.get("status") != "PASS":
        fail("FRESH_BUNDLE_VERIFICATION_MISMATCH", "bundle status")
    receipt = load("50-matrix/receipt.json")
    if (receipt.get("passed"), receipt.get("case_count", receipt.get("total")), receipt.get("failed")) != (60, 60, 0):
        fail("FRESH_MATRIX_COUNT_MISMATCH", "receipt")
    base = load("80-acceptance/base/summary.json")
    r4 = load("80-acceptance/r4/summary.json")
    if (base.get("passed"), base.get("total"), base.get("failed")) != (32, 32, 0):
        fail("FRESH_BASE_COUNT_MISMATCH", "base")
    if (r4.get("passed"), r4.get("total"), r4.get("failed")) != (22, 22, 0):
        fail("FRESH_R4_COUNT_MISMATCH", "r4")
    result = load("90-final-audit/fresh-chain-result.json")
    session = result.get("review_session_id")
    required_counts = {
        "matrix": (60, 60), "base_acceptance": (32, 32),
        "r4_acceptance": (22, 22), "composed_acceptance": (54, 54),
        "facts_checks": (18, 18),
    }
    for key, pair in required_counts.items():
        row = result.get(key, {})
        if (row.get("passed"), row.get("total")) != pair:
            fail("FRESH_RESULT_COUNT_MISMATCH", key)
    if result.get("semantic_verify") != "PASS" or result.get("construction_self_verification") != "PASS" or result.get("independent_review") != "NOT_PROVEN":
        fail("FRESH_RESULT_STATUS_MISMATCH", "result status")
    if not identity_matches(result.get("candidate_identity"), expected["head"], expected["tree"], expected["parent"]):
        fail("FRESH_CANDIDATE_BINDING_MISMATCH", "fresh result")
    if session != manifest.get("review_session_id") or not session:
        fail("FRESH_REVIEW_SESSION_MISMATCH", "manifest/result")
    if receipt.get("review_session_id") != session or r4.get("review_session_id") != session:
        fail("FRESH_REVIEW_SESSION_MISMATCH", "receipt/r4")
    h2 = load("90-final-audit/h2-exact20/summary.json")
    if h2.get("status") != "PASS" or h2.get("independent_process_count") != 40:
        fail("FRESH_H2_SUMMARY_MISMATCH", "summary")
    if (h2.get("sanitized", {}).get("passed"), h2.get("sanitized", {}).get("total")) != (20, 20) or (h2.get("non_sanitized", {}).get("passed"), h2.get("non_sanitized", {}).get("total")) != (20, 20):
        fail("FRESH_H2_SUMMARY_MISMATCH", "counts")
    run_ids = set()
    for profile in ("sanitized", "non_sanitized"):
        for index in range(1, 21):
            name = "90-final-audit/h2-exact20/%s-%02d.json" % (profile, index)
            record = load(name).get("record", {})
            run_id = record.get("run_id")
            if record.get("profile") != profile or record.get("process_index") != index or record.get("exit_code") != 0 or record.get("exact_red_fact") is not True or not run_id or run_id in run_ids:
                fail("FRESH_H2_RECORD_MISMATCH", name)
            run_ids.add(run_id)
    dag = load("90-final-audit/observed-dag.json")
    if dag.get("review_session_id") != session or (dag.get("node_count"), dag.get("edge_count"), dag.get("cycle_count")) != (18, 20, 0):
        fail("FRESH_DAG_MISMATCH", "observed-dag")


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
    if manifest.get("schema") != "cth3ds.public-fresh-evidence/v1" or manifest.get("status") != "PASS" or manifest.get("payload_count") != 56:
        fail("FRESH_MANIFEST_INVALID", "header")
    if manifest.get("run") != {"id": expected["run_id"], "attempt": expected["attempt"], "job": expected["job"]} or manifest.get("artifact") != {"name": expected["artifact_name"]}:
        fail("FRESH_RUN_BINDING_MISMATCH", "run/artifact")
    if manifest.get("candidate_identity") != {"head": expected["head"], "tree": expected["tree"], "parents": [expected["parent"]]}:
        fail("FRESH_CANDIDATE_BINDING_MISMATCH", "manifest")
    bundle_row = manifest.get("bundle", {})
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
            body = {"schema": "cth3ds.public-fresh-failure/v1", "status": "FAILURE_PACKAGE_NON_ACCEPTING",
                    "fresh_outcome": outcome, "run": {key: expected[key] for key in ("run_id", "attempt", "job")},
                    "candidate_identity": {"head": expected["head"], "tree": expected["tree"], "parents": [expected["parent"]]},
                    "recorded_at_utc": dt.datetime.now(dt.timezone.utc).isoformat()}
            (temporary / "failure.json").write_bytes(canonical(body))
            for relative in ("00-preflight/durable-failure.json", "00-preflight/execution-journal.jsonl"):
                source = session / relative
                if source.exists() or source.is_symlink():
                    raw = read_regular(source, relative)
                    output = temporary / relative
                    output.parent.mkdir(parents=True, exist_ok=True)
                    output.write_bytes(raw)
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
            destination.write_bytes(handle.read(info))
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
