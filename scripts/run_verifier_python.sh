#!/usr/bin/env bash
set -euo pipefail

# Closed bootstrap for the Runtime Core verifier.  This file has exactly three
# public operations.  It never forwards Python options, modules, or scripts.

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd -P)"
LOCK="${ROOT}/requirements/verifier.lock"
LOCK_SHA256="0bec73ce08a019ea3b7a78429f75d03e074d25c0599c8e5a770f25cbbe93bf37"
DRIVER="${ROOT}/scripts/verifier_driver.py"
BOOTSTRAP_PYTHON=""
ENV_DIR=""
EVIDENCE_DIR="${ROOT}/artifacts/verification/verifier-python"
STAGE="cli-contract"
DETAIL="wrapper did not start an operation"
FINISHED=0

sha256_file() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$1" | awk '{print $1}'
  else
    shasum -a 256 "$1" | awk '{print $1}'
  fi
}

sha256_stdin() {
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum | awk '{print $1}'
  else
    shasum -a 256 | awk '{print $1}'
  fi
}

json_summary() {
  local status="$1" code="$2" detail="$3" verb="${4:-}"
  mkdir -p "${EVIDENCE_DIR}"
  local writer="${BOOTSTRAP_PYTHON:-$(command -v python3 || true)}"
  if [[ -n "${writer}" && -x "${writer}" ]]; then
    "${writer}" -I - "${EVIDENCE_DIR}/bootstrap-summary.json" "${status}" \
      "${STAGE}" "${code}" "${detail}" "${verb}" "${LOCK}" \
      "${LOCK_SHA256}" "${ENV_DIR}" <<'PY'
import datetime, json, pathlib, sys
out, status, stage, code, detail, verb, lock, lock_sha, env_dir = sys.argv[1:]
payload = {
    "schema": "cth3ds.verifier-bootstrap/v2",
    "bootstrap_scope": "ENVIRONMENT_AND_COMMAND_ONLY",
    "status": status,
    "stage": stage,
    "exit_code": int(code),
    "detail": detail,
    "verb": verb or None,
    "lock": {"path": lock, "expected_sha256": lock_sha},
    "environment": env_dir or None,
    "recorded_at_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
}
audit_path = pathlib.Path(out).parent / "environment-audit.json"
if audit_path.is_file():
    try:
        payload["verified_invocation_sha256"] = json.loads(
            audit_path.read_text()).get("verified_invocation_sha256")
    except Exception:
        payload["verified_invocation_sha256"] = None
pathlib.Path(out).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
PY
  else
    printf '{"bootstrap_scope":"ENVIRONMENT_AND_COMMAND_ONLY","status":"%s","stage":"%s","exit_code":%s}\n' \
      "${status}" "${STAGE}" "${code}" >"${EVIDENCE_DIR}/bootstrap-summary.json"
  fi
}

on_exit() {
  local code="$?"
  if [[ "${FINISHED}" -eq 0 ]]; then
    set +e
    json_summary FAIL "${code}" "${DETAIL}" "${VERB:-}"
  fi
}
trap on_exit EXIT

cli_error() {
  DETAIL="$*"
  printf '[cth3ds-verifier] CLI_CONTRACT: %s\n' "${DETAIL}" >&2
  exit 64
}

integrity_error() {
  DETAIL="$*"
  printf '[cth3ds-verifier] %s\n' "${DETAIL}" >&2
  exit 2
}

for reserved in CTH3DS_VERIFIER_CANONICAL CTH3DS_VERIFIER_LOCK_SHA256 CTH3DS_VERIFIER_PYTHON_DISPATCH; do
  if [[ -n "${!reserved+x}" ]]; then
    cli_error "RESERVED_AUTHORITY_ENV: ${reserved}"
  fi
done

SEEN_BOOTSTRAP=0
SEEN_ENV=0
SEEN_EVIDENCE=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --bootstrap-python|--env-dir|--evidence-dir)
      option="$1"
      [[ $# -ge 2 && -n "$2" ]] || cli_error "missing value for ${option}"
      [[ "$2" = /* ]] || cli_error "${option} requires an absolute path"
      case "${option}" in
        --bootstrap-python)
          [[ "${SEEN_BOOTSTRAP}" -eq 0 ]] || cli_error "duplicate option: ${option}"
          SEEN_BOOTSTRAP=1; BOOTSTRAP_PYTHON="$2" ;;
        --env-dir)
          [[ "${SEEN_ENV}" -eq 0 ]] || cli_error "duplicate option: ${option}"
          SEEN_ENV=1; ENV_DIR="$2" ;;
        --evidence-dir)
          [[ "${SEEN_EVIDENCE}" -eq 0 ]] || cli_error "duplicate option: ${option}"
          SEEN_EVIDENCE=1; EVIDENCE_DIR="$2" ;;
      esac
      shift 2
      ;;
    check-env|protocol-self-test|fresh-chain)
      VERB="$1"
      shift
      break
      ;;
    --|-c|-m|_*) cli_error "forbidden entry shape: $1" ;;
    -*) cli_error "unknown wrapper option: $1" ;;
    *) cli_error "unknown or script-path operation: $1" ;;
  esac
done

[[ -n "${VERB:-}" ]] || cli_error "missing public operation"
if [[ "${VERB}" == "check-env" && $# -ne 0 ]]; then
  cli_error "check-env accepts no operation arguments"
fi
for token in "$@"; do
  [[ "${token}" != "--" ]] || cli_error "-- remainder syntax is forbidden"
done

if [[ -n "${PYTHONPATH+x}" || -n "${PYTHONHOME+x}" || \
      -n "${PYTHONUSERBASE+x}" || -n "${PYTHONSTARTUP+x}" || \
      -n "${PYTHONINSPECT+x}" || -n "${VIRTUAL_ENV+x}" ]]; then
  STAGE="environment-audit"
  integrity_error "FORBIDDEN_PYTHON_ENV"
fi

[[ -f "${LOCK}" ]] || integrity_error "verifier lock is missing: ${LOCK}"
[[ "$(sha256_file "${LOCK}")" == "${LOCK_SHA256}" ]] || \
  integrity_error "verifier lock SHA-256 mismatch"
[[ -f "${DRIVER}" && ! -L "${DRIVER}" ]] || integrity_error "canonical driver is missing or invalid"

if [[ -z "${BOOTSTRAP_PYTHON}" ]]; then
  BOOTSTRAP_PYTHON="$(command -v python3 || true)"
fi
[[ -x "${BOOTSTRAP_PYTHON}" ]] || integrity_error "bootstrap Python is missing"
BOOTSTRAP_PYTHON="$("${BOOTSTRAP_PYTHON}" -I -c 'import pathlib,sys; print(pathlib.Path(sys.executable).absolute())')" || \
  integrity_error "cannot identify bootstrap Python"
PYTHON_TAG="$("${BOOTSTRAP_PYTHON}" -I -c 'import sys; assert sys.version_info >= (3,9); print(f"{sys.version_info.major}.{sys.version_info.minor}")')" || \
  integrity_error "verifier requires CPython 3.9 or newer"
if [[ -z "${ENV_DIR}" ]]; then
  ENV_DIR="${ROOT}/work/verifier-python/py${PYTHON_TAG}-${LOCK_SHA256:0:16}"
fi

VENV_PYTHON="${ENV_DIR}/bin/python"
DISPATCH="${ENV_DIR}/bin/cth3ds-verifier-python"
MARKER="${ENV_DIR}/.cth3ds-verifier-environment.json"
PYVENV_CFG="${ENV_DIR}/pyvenv.cfg"
mkdir -p "${EVIDENCE_DIR}"

write_dispatch_and_marker() {
  printf '#!/bin/sh\nexec "%s" -I "%s" "$@"\n' "${VENV_PYTHON}" "${DRIVER}" >"${DISPATCH}"
  chmod 755 "${DISPATCH}"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    DISPATCH_LINKS="$(stat -f %l "${DISPATCH}")"
  else
    DISPATCH_LINKS="$(stat -c %h "${DISPATCH}")"
  fi
  [[ "${DISPATCH_LINKS}" == "1" ]] || \
    integrity_error "dispatch must have exactly one link"
  "${VENV_PYTHON}" -I - "${MARKER}" "${ENV_DIR}" "${LOCK}" "${DRIVER}" \
    "${ROOT}/scripts/run_verifier_python.sh" "${DISPATCH}" "${PYVENV_CFG}" <<'PY'
import hashlib, importlib.metadata, json, pathlib, site, stat, sys
marker, env, lock, driver, wrapper, dispatch, cfg = map(pathlib.Path, sys.argv[1:])
expected = {"attrs":"25.3.0", "jsonschema":"4.25.1",
 "jsonschema-specifications":"2025.9.1", "referencing":"0.36.2",
 "rpds-py":"0.27.1", "typing-extensions":"4.14.1"}
def sha(path):
    h=hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda:f.read(1024*1024), b""): h.update(block)
    return h.hexdigest()
def deps():
    rows=[]
    for name, version in sorted(expected.items()):
        d=importlib.metadata.distribution(name)
        if d.version != version: raise RuntimeError(f"dependency version mismatch: {name}")
        files=[]
        for entry in d.files or ():
            rel=pathlib.PurePosixPath(str(entry))
            if rel.suffix == ".pyc" or "__pycache__" in rel.parts: continue
            path=pathlib.Path(d.locate_file(entry)).resolve(strict=True)
            path.relative_to(env.resolve(strict=True))
            if not path.is_file(): raise RuntimeError(f"dependency entry is not regular: {path}")
            files.append({"path":str(path.relative_to(env.resolve(strict=True))),"bytes":path.stat().st_size,"sha256":sha(path)})
        files.sort(key=lambda r:r["path"].encode())
        rows.append({"name":name,"version":version,"file_count":len(files),
          "installed_files_sha256":hashlib.sha256((json.dumps(files,sort_keys=True,separators=(",",":"))+"\n").encode()).hexdigest()})
    return rows
exe=pathlib.Path(sys.executable).absolute(); impl=exe.resolve(strict=True); ds=dispatch.lstat()
basis={"schema":"cth3ds.verifier-environment-marker-basis/v2",
 "environment_realpath":str(env.resolve(strict=True)),
 "lock":{"path":str(lock.resolve(strict=True)),"sha256":sha(lock)},
 "driver":{"path":str(driver.absolute()),"realpath":str(driver.resolve(strict=True)),"sha256":sha(driver)},
 "wrapper":{"path":str(wrapper.resolve(strict=True)),"sha256":sha(wrapper)},
 "dispatch":{"path":str(dispatch.resolve(strict=True)),"realpath":str(dispatch.resolve(strict=True)),"sha256":sha(dispatch),
   "device":ds.st_dev,"inode":ds.st_ino,"mode":stat.S_IMODE(ds.st_mode),"nlink":ds.st_nlink,"bytes":ds.st_size},
 "python":{"executable":str(exe),"implementation_realpath":str(impl),"sha256":sha(impl),
   "version":sys.version,"cache_tag":sys.implementation.cache_tag,"prefix":str(pathlib.Path(sys.prefix).resolve(strict=True)),
   "base_prefix":str(pathlib.Path(sys.base_prefix).resolve(strict=True)),"isolated":sys.flags.isolated,
   "user_site_enabled":bool(site.ENABLE_USER_SITE)},
 "pyvenv_cfg_sha256":sha(cfg),"dependencies":deps()}
marker.write_text(json.dumps(basis,indent=2,sort_keys=True)+"\n")
PY
}

if [[ ! -e "${ENV_DIR}" ]]; then
  STAGE="environment-create"
  TEMP_ENV="${ENV_DIR}.creating.$$"
  [[ ! -e "${TEMP_ENV}" ]] || integrity_error "temporary environment already exists"
  mkdir -p "$(dirname "${ENV_DIR}")"
  "${BOOTSTRAP_PYTHON}" -I -m venv "${TEMP_ENV}" || integrity_error "venv creation failed"
  TEMP_PYTHON="${TEMP_ENV}/bin/python"
  STAGE="dependency-install"
  "${TEMP_PYTHON}" -I -m pip --isolated --disable-pip-version-check install --no-input \
    --index-url https://pypi.org/simple --require-hashes --only-binary=:all: \
    -r "${LOCK}" >"${EVIDENCE_DIR}/install.log" 2>&1 || integrity_error "locked dependency install failed"
  "${TEMP_PYTHON}" -I -m pip --isolated --disable-pip-version-check check \
    >"${EVIDENCE_DIR}/pip-check.log" 2>&1 || integrity_error "pip check failed"
  mv "${TEMP_ENV}" "${ENV_DIR}"
  write_dispatch_and_marker
else
  [[ -d "${ENV_DIR}" && -x "${VENV_PYTHON}" && -f "${MARKER}" ]] || \
    integrity_error "verifier environment is incomplete"
  [[ -f "${DISPATCH}" && ! -L "${DISPATCH}" && -x "${DISPATCH}" ]] || \
    integrity_error "canonical dispatch is missing or invalid"
  EXPECTED_DISPATCH_SHA="$(printf '#!/bin/sh\nexec "%s" -I "%s" "$@"\n' \
    "${VENV_PYTHON}" "${DRIVER}" | sha256_stdin)"
  [[ "$(sha256_file "${DISPATCH}")" == "${EXPECTED_DISPATCH_SHA}" ]] || \
    integrity_error "canonical dispatch content mismatch"
  if [[ "$(uname -s)" == "Darwin" ]]; then
    DISPATCH_LINKS="$(stat -f %l "${DISPATCH}")"
  else
    DISPATCH_LINKS="$(stat -c %h "${DISPATCH}")"
  fi
  [[ "${DISPATCH_LINKS}" == "1" ]] || \
    integrity_error "dispatch must have exactly one link"
  grep -Eq '^include-system-site-packages = false$' "${PYVENV_CFG}" || \
    integrity_error "system site packages are enabled"
fi

STAGE="driver"
set +e
"${DISPATCH}" --evidence-dir "${EVIDENCE_DIR}" "${VERB}" "$@"
STATUS=$?
set -e
FINISHED=1
if [[ "${STATUS}" -eq 0 ]]; then
  json_summary PASS 0 "closed operation completed" "${VERB}"
else
  json_summary FAIL "${STATUS}" "closed operation rejected" "${VERB}"
fi
exit "${STATUS}"
