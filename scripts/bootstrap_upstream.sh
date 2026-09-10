#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
source_owner "$0" "$@"

UPSTREAM_DIR="${CTH3DS_EXTERNAL_DIR}/CorsixTH"
REPO="$(pin corsixth.repository)"
COMMIT="$(pin corsixth.commit)"
clone_pinned CorsixTH "${REPO}" "${COMMIT}" "${CTH3DS_UPSTREAM_PIN}"
python3 "${CTH3DS_ROOT}/tools/check_upstream_lua_api.py" "${CTH3DS_UPSTREAM_PIN}" \
  --contract "${CTH3DS_ROOT}/config/corsixth-lua-api-v0.70.1.json"

# Complete views are immutable inputs to a game build. Reuse an exact verified
# view; changed generation inputs require a fresh one. Dependencies stay cached.
if python3 "${CTH3DS_ROOT}/tools/integrate_corsixth.py" "${UPSTREAM_DIR}" \
  --overlay-root "${CTH3DS_ROOT}" --build-profile "${CTH3DS_BUILD_PROFILE}" --check >/dev/null 2>&1; then
  log "verified existing complete source view at ${UPSTREAM_DIR}"
  exit 0
fi
mkdir -p "${CTH3DS_GENERATED_DIR}"
VIEW_OWNER="$(mktemp -d "${CTH3DS_GENERATED_DIR}/source-generation.XXXXXX")"
VIEW="${VIEW_OWNER}/view"
python3 "${CTH3DS_ROOT}/tools/integrate_corsixth.py" "${CTH3DS_UPSTREAM_PIN}" \
  --overlay-root "${CTH3DS_ROOT}" --build-profile "${CTH3DS_BUILD_PROFILE}" --output "${VIEW}"
python3 "${CTH3DS_ROOT}/tools/source_view.py" select --view "${VIEW}" \
  --overlay "${CTH3DS_ROOT}" --build-profile "${CTH3DS_BUILD_PROFILE}" --alias "${UPSTREAM_DIR}" \
  --lock "${CTH3DS_SOURCE_OWNER_LOCK}"
log "CorsixTH complete source selected at ${UPSTREAM_DIR}"
