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
import json
import pathlib
import sys

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
summary = {
    "format": 1,
    "status": status,
    "matrix": matrix,
    "stage": stage,
    "exit_code": int(exit_code),
    "failed_command": failed_command or None,
    "logs": logs,
    "identity": identity,
    "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
pathlib.Path(output).write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
PY
}

ci_diag_emit_failure() {
  local status="$1" command="$2" log_path
  ci_diag_write_result FAIL "${status}" "${command}" "${CI_DIAG_LOGS[@]}"
  printf '[cth3ds-ci] matrix: %s\n' "${CI_DIAG_MATRIX}" >&2
  printf '[cth3ds-ci] stage: %s\n' "${CI_DIAG_STAGE}" >&2
  printf '[cth3ds-ci] failed command: %s\n' "${command}" >&2
  printf '[cth3ds-ci] exit code: %s\n' "${status}" >&2
  for log_path in "${CI_DIAG_LOGS[@]}"; do
    if [[ -f "${log_path}" ]]; then
      printf '[cth3ds-ci] tail: %s\n' "${log_path}" >&2
      tail -n "${CTH3DS_LOG_TAIL_LINES:-80}" "${log_path}" >&2
    fi
  done
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
  trap - ERR
  ci_diag_write_result PASS 0 "" "${CI_DIAG_LOGS[@]}"
}
