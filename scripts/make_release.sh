#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

require_cmd python3
python3 "${CTH3DS_ROOT}/tools/make_release.py" \
  --root "${CTH3DS_ROOT}" \
  --output "${CTH3DS_DIST_DIR}"
log "release archives are ready under ${CTH3DS_DIST_DIR}"
