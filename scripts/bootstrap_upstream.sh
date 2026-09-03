#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

UPSTREAM_DIR="${CTH3DS_EXTERNAL_DIR}/CorsixTH"
REPO="$(pin corsixth.repository)"
COMMIT="$(pin corsixth.commit)"

clone_pinned CorsixTH "${REPO}" "${COMMIT}" "${UPSTREAM_DIR}"
python3 "${CTH3DS_ROOT}/tools/check_upstream_lua_api.py" "${UPSTREAM_DIR}" \
  --contract "${CTH3DS_ROOT}/config/corsixth-lua-api-v0.70.1.json"
python3 "${CTH3DS_ROOT}/tools/integrate_corsixth.py" "${UPSTREAM_DIR}" \
  --overlay-root "${CTH3DS_ROOT}"
python3 "${CTH3DS_ROOT}/tools/integrate_corsixth.py" "${UPSTREAM_DIR}" \
  --overlay-root "${CTH3DS_ROOT}" --check
log "CorsixTH source is pinned and integrated at ${UPSTREAM_DIR}"
