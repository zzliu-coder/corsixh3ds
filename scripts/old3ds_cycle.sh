#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

HOST="${CTH3DS_HOST:-}"
PORT="${CTH3DS_FTP_PORT:-5000}"
JOBS="${CTH3DS_FTP_JOBS:-2}"
LANE="fast"
DEPLOY_MODE="delta"
GAME_SOURCE="${CTH3DS_GAME_SOURCE:-${CTH3DS_DIST_DIR}/sd-card/3ds/corsixth/game}"
WAIT_NETLOADER=0
RUN_DIR=""

while [[ $# -gt 0 ]]; do
  case "$1" in
    --host) [[ $# -ge 2 ]] || die '--host requires an IPv4 address'; HOST="$2"; shift ;;
    --port) [[ $# -ge 2 ]] || die '--port requires a number'; PORT="$2"; shift ;;
    --jobs) [[ $# -ge 2 ]] || die '--jobs requires 1-4'; JOBS="$2"; shift ;;
    --lane) [[ $# -ge 2 ]] || die '--lane requires fast or release'; LANE="$2"; shift ;;
    --deploy-mode) [[ $# -ge 2 ]] || die '--deploy-mode requires delta or full'; DEPLOY_MODE="$2"; shift ;;
    --game-source) [[ $# -ge 2 ]] || die '--game-source requires a directory'; GAME_SOURCE="$2"; shift ;;
    --wait-netloader) [[ $# -ge 2 ]] || die '--wait-netloader requires seconds'; WAIT_NETLOADER="$2"; shift ;;
    --run-dir) [[ $# -ge 2 ]] || die '--run-dir requires a directory'; RUN_DIR="$2"; shift ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

[[ -n "${HOST}" ]] || die 'provide --host or CTH3DS_HOST'
[[ "${LANE}" == "fast" || "${LANE}" == "release" ]] || die '--lane must be fast or release'
[[ "${DEPLOY_MODE}" == "delta" || "${DEPLOY_MODE}" == "full" ]] || die '--deploy-mode must be delta or full'
if [[ "${DEPLOY_MODE}" == "full" ]]; then
  [[ -d "${GAME_SOURCE}" ]] || die "Theme Hospital data directory is missing: ${GAME_SOURCE}"
fi
case "${HOST}" in
  *[!0-9.]*|'') die 'host must be a numeric IPv4 address' ;;
esac

if [[ -z "${RUN_DIR}" ]]; then
  RUN_DIR="${CTH3DS_ROOT}/work/hardmac-runs/$(date '+%Y%m%d-%H%M%S')-cycle"
fi
[[ ! -e "${RUN_DIR}" ]] || die "run directory already exists: ${RUN_DIR}"
mkdir -p "${RUN_DIR}/logs"

if [[ -d "${CTH3DS_ROOT}/local-devkitpro" ]]; then
  export DEVKITPRO="${CTH3DS_ROOT}/local-devkitpro"
else
  export DEVKITPRO="${DEVKITPRO:-/opt/devkitpro}"
fi
export DEVKITARM="${DEVKITPRO}/devkitARM"
export PATH="${DEVKITARM}/bin:${DEVKITPRO}/tools/bin:${PATH}"

python3 "${CTH3DS_ROOT}/tools/integrate_corsixth.py" "${CTH3DS_EXTERNAL_DIR}/CorsixTH" \
  --overlay-root "${CTH3DS_ROOT}" --check >"${RUN_DIR}/logs/integration-check.log"

if [[ "${LANE}" == "release" ]]; then
  CTH3DS_VERIFY_RESUME=0 CTH3DS_VERIFY_CROSS=1 \
    "${CTH3DS_ROOT}/scripts/test_all.sh" >"${RUN_DIR}/logs/test-all.log" 2>&1
else
  PYTHONPATH="${CTH3DS_ROOT}/tools" PYTHONDONTWRITEBYTECODE=1 \
    python3 -m unittest discover -s "${CTH3DS_ROOT}/tests" -p 'test_*.py' -v \
    >"${RUN_DIR}/logs/python-tests.log" 2>&1
fi

BUILD_DIR="${RUN_DIR}/build"
DIST_DIR="${RUN_DIR}/dist"
CTH3DS_BUILD_DIR="${BUILD_DIR}" CTH3DS_DEPS_PREFIX="${CTH3DS_ROOT}/build-3ds/deps" \
  "${CTH3DS_ROOT}/scripts/build_3ds.sh" --skip-bootstrap \
  >"${RUN_DIR}/logs/build.log" 2>&1
if [[ "${DEPLOY_MODE}" == "full" ]]; then
  CTH3DS_BUILD_DIR="${BUILD_DIR}" CTH3DS_DEPS_PREFIX="${CTH3DS_ROOT}/build-3ds/deps" \
  CTH3DS_DIST_DIR="${DIST_DIR}" \
    "${CTH3DS_ROOT}/scripts/package_sd.sh" --theme-hospital "${GAME_SOURCE}" --asset-mode loose \
    >"${RUN_DIR}/logs/package.log" 2>&1
else
  CTH3DS_BUILD_DIR="${BUILD_DIR}" CTH3DS_DEPS_PREFIX="${CTH3DS_ROOT}/build-3ds/deps" \
  CTH3DS_DIST_DIR="${DIST_DIR}" \
    "${CTH3DS_ROOT}/scripts/package_sd.sh" --theme-hospital "${GAME_SOURCE}" --asset-mode loose \
    >"${RUN_DIR}/logs/package.log" 2>&1
fi

PACKAGE="${DIST_DIR}/sd-card/3ds/corsixth"
log "preflight FTPD ${HOST}:${PORT}"
python3 - "${HOST}" "${PORT}" <<'PY'
import ftplib, sys
ftp = ftplib.FTP()
ftp.connect(sys.argv[1], int(sys.argv[2]), timeout=5)
ftp.login()
ftp.cwd('/3ds')
ftp.quit()
PY
# Pull whatever the previous CorsixTH run left behind before anything else
# touches the console. The runtime writes this log unbuffered, so its last line
# is the last thing that executed - that is what turns a freeze report into an
# actual stage number.
mkdir -p "${RUN_DIR}/device-logs"
python3 "${CTH3DS_ROOT}/tools/old3ds_fetch_log.py" \
  --host "${HOST}" --port "${PORT}" --out "${RUN_DIR}/device-logs" \
  >"${RUN_DIR}/logs/device-boot-log.log" 2>&1 || \
  log 'no previous boot.log on the device (first run, or the console never got that far)'

if [[ "${DEPLOY_MODE}" == "delta" ]]; then
  python3 "${CTH3DS_ROOT}/tools/old3ds_delta.py" "${PACKAGE}" \
    --host "${HOST}" --port "${PORT}" \
    --backup-dir "${RUN_DIR}/device-backup" \
    --report "${RUN_DIR}/deploy-report.json" --disable-legacy \
    2>&1 | tee "${RUN_DIR}/logs/deploy.log"
else
  python3 "${CTH3DS_ROOT}/tools/old3ds_ftp.py" "${PACKAGE}" \
    --host "${HOST}" --port "${PORT}" --jobs "${JOBS}" \
    --report "${RUN_DIR}/deploy-report.json" \
    2>&1 | tee "${RUN_DIR}/logs/deploy.log"
fi

LAUNCH_RESULT="NOT_PROVEN"
for debug_port in 4000 4001 4002 4003 17491; do
  if nc -z -w 2 "${HOST}" "${debug_port}" >/dev/null 2>&1; then
    printf '%s OPEN\n' "${debug_port}"
  else
    printf '%s CLOSED\n' "${debug_port}"
  fi
done >"${RUN_DIR}/logs/ports-after-deploy.log"

if command -v arm-none-eabi-gdb >/dev/null 2>&1 && \
   nc -z -w 2 "${HOST}" 4000 >/dev/null 2>&1; then
  arm-none-eabi-gdb -q -batch \
    -ex 'set pagination off' \
    -ex "target extended-remote ${HOST}:4000" \
    -ex 'info os processes' \
    -ex 'disconnect' \
    >"${RUN_DIR}/logs/gdb-processes-after-deploy.log" 2>&1 || true
fi

if [[ "${WAIT_NETLOADER}" -gt 0 ]]; then
  deadline=$(( $(date +%s) + WAIT_NETLOADER ))
  while [[ "$(date +%s)" -lt "${deadline}" ]]; do
    if nc -z -w 2 "${HOST}" 17491 >/dev/null 2>&1; then
      "${DEVKITPRO}/tools/bin/3dslink" -a "${HOST}" "${PACKAGE}/CorsixTH-3DS.3dsx" \
        >"${RUN_DIR}/logs/3dslink.log" 2>&1
      LAUNCH_RESULT="SENT_TO_NETLOADER"
      # Luma port 4003 is the break-on-start slot. Capture a bounded snapshot
      # when the user has enabled it; the ELF gives GDB symbols for this build.
      if nc -z -w 5 "${HOST}" 4003 >/dev/null 2>&1; then
        arm-none-eabi-gdb -q -batch \
          "${BUILD_DIR}/CorsixTH/CorsixTH/CorsixTH-3DS.elf" \
          -ex 'set pagination off' \
          -ex "target extended-remote ${HOST}:4003" \
          -ex 'info threads' \
          -ex 'thread apply all bt' \
          -ex 'disconnect' \
          >"${RUN_DIR}/logs/gdb-break-on-start.log" 2>&1 || true
      fi
      break
    fi
    sleep 2
  done
fi

python3 - "${RUN_DIR}" "${LAUNCH_RESULT}" <<'PY'
import hashlib, json, pathlib, sys
root = pathlib.Path(sys.argv[1])
deploy = json.loads((root / 'deploy-report.json').read_text())
ports = (root / 'logs/ports-after-deploy.log').read_text().splitlines()
summary = {
    'result': 'PASS' if deploy.get('ok') else 'FAIL',
    'deploy': deploy,
    'launch': sys.argv[2],
    'realDeviceRunning': 'NOT_PROVEN',
    'portsAfterDeploy': ports,
    'debugSnapshot': 'logs/gdb-processes-after-deploy.log',
}
(root / 'cycle-summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
print(json.dumps(summary, indent=2, sort_keys=True))
PY

if [[ -f "${CTH3DS_ROOT}/artifacts/verification/summary.json" ]]; then
  ACCEPTANCE_ARGS=(
    --host-summary "${CTH3DS_ROOT}/artifacts/verification/summary.json"
    --heap-budget "${BUILD_DIR}/CorsixTH/heap-budget.json"
    --package "${PACKAGE}"
    --deploy-report "${RUN_DIR}/deploy-report.json"
    --output "${RUN_DIR}/acceptance.json"
  )
  if [[ -f "${RUN_DIR}/device-logs/boot.log" ]]; then
    ACCEPTANCE_ARGS+=(--boot-log "${RUN_DIR}/device-logs/boot.log")
  fi
  python3 "${CTH3DS_ROOT}/tools/v061_acceptance.py" "${ACCEPTANCE_ARGS[@]}" \
    >"${RUN_DIR}/logs/acceptance.log"
fi

log "cycle evidence: ${RUN_DIR}/cycle-summary.json"
