#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

THEME_HOSPITAL=""
ASSET_MODE="loose"
LANGUAGE="English"
NO_BINARY_COPY=0
NO_DATA_PACK=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --theme-hospital)
      [[ $# -ge 2 ]] || die '--theme-hospital requires a path'
      THEME_HOSPITAL="$2"; shift ;;
    --asset-mode)
      [[ $# -ge 2 ]] || die '--asset-mode requires th3ds or loose'
      ASSET_MODE="$2"; shift ;;
    --language)
      [[ $# -ge 2 ]] || die '--language requires a language name or tag'
      LANGUAGE="$2"; shift ;;
    --no-binary-copy) NO_BINARY_COPY=1 ;;
    --no-data-pack) NO_DATA_PACK=1 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

[[ "${ASSET_MODE}" == "th3ds" || "${ASSET_MODE}" == "loose" ]] || \
  die '--asset-mode must be th3ds or loose'
[[ -n "${THEME_HOSPITAL}" ]] || \
  die '--theme-hospital is required for both th3ds candidates and loose diagnostics'
[[ "${NO_BINARY_COPY}" -eq 0 ]] || \
  die '--no-binary-copy cannot produce a boot-contract-complete package'
[[ "${NO_DATA_PACK}" -eq 0 ]] || \
  die '--no-data-pack is obsolete; use --asset-mode loose for a diagnostic baseline'

require_cmd git
if [[ -n "$(git -C "${CTH3DS_ROOT}" status --porcelain --untracked-files=normal)" ]]; then
  die 'refusing to package a dirty source tree; commit the exact candidate first'
fi
CANDIDATE_COMMIT="$(git -C "${CTH3DS_ROOT}" rev-parse HEAD^{commit})"
CANDIDATE_TREE="$(git -C "${CTH3DS_ROOT}" rev-parse HEAD^{tree})"

UPSTREAM_DIR="${CTH3DS_EXTERNAL_DIR}/CorsixTH"
SOURCE_DATA="${UPSTREAM_DIR}/CorsixTH"
DEST="${CTH3DS_DIST_DIR}/sd-card/3ds/corsixth"
[[ -f "${SOURCE_DATA}/CorsixTH.lua" ]] || die 'integrated CorsixTH runtime data is missing'
[[ -d "${THEME_HOSPITAL}" ]] || die 'Theme Hospital source directory is missing'
if [[ -e "${DEST}" ]]; then
  die "refusing to merge with an existing SD application tree: ${DEST}"
fi
mkdir -p "${CTH3DS_DIST_DIR}"
STAGE_ROOT="$(mktemp -d "${CTH3DS_DIST_DIR}/.package-sd.XXXXXX")"
trap 'rm -rf -- "${STAGE_ROOT}"' EXIT
WORK_DEST="${STAGE_ROOT}/3ds/corsixth"
mkdir -p "${WORK_DEST}"

built="${CTH3DS_BUILD_DIR}/CorsixTH/CorsixTH-3DS.3dsx"
[[ -s "${built}" ]] || die 'build the non-empty .3dsx first'
cp "${built}" "${WORK_DEST}/CorsixTH-3DS.3dsx"

python3 - "${SOURCE_DATA}" "${WORK_DEST}" <<'PY'
from pathlib import Path
import shutil, sys
source, dest = map(Path, sys.argv[1:])
required = ['CorsixTH.lua', 'Bitmap', 'Campaigns', 'Graphics', 'Levels', 'Lua']
for name in required:
    item = source / name
    if not item.exists():
        raise SystemExit(f'missing CorsixTH runtime item: {item}')
    target = dest / name
    shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
for name in ('Languages', 'Fonts'):
    item = source / name
    if item.exists():
        target = dest / name
        shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
PY

if [[ -f "${CTH3DS_DEPS_PREFIX}/share/lpeg/re.lua" ]]; then
  cp "${CTH3DS_DEPS_PREFIX}/share/lpeg/re.lua" "${WORK_DEST}/re.lua"
fi
cat > "${WORK_DEST}/config.txt" <<CFG
theme_hospital_install = "sdmc:/3ds/corsixth/game"
asset_mode = "${ASSET_MODE}"
language = "${LANGUAGE}"
use_new_graphics = false
autosave_frequency = 1
player_name = "PLAYER"
width = 640
height = 480
fullscreen = true
ui_scale = 1
direct_zoom = true
scrolling_momentum = false
play_intro = false
play_demo = false
track_fps = false
audio = true
play_sounds = true
play_announcements = true
play_music = false
prevent_edge_scrolling = true
new_graphics_folder = ""
CFG

printf '%s\n' "$(cat "${CTH3DS_ROOT}/VERSION")" > "${WORK_DEST}/cth3ds-overlay-version.txt"

if [[ "${ASSET_MODE}" == "th3ds" ]]; then
  [[ -d "${SOURCE_DATA}/Lua/languages" ]] || \
    die 'integrated CorsixTH Languages directory is required for TH3DS conversion'
  python3 "${CTH3DS_ROOT}/tools/th3ds_pack.py" convert \
    "${THEME_HOSPITAL}" "${WORK_DEST}/resources" \
    --language-dir "${SOURCE_DATA}/Lua/languages" \
    --language "${LANGUAGE}"
else
  python3 "${CTH3DS_ROOT}/tools/th3ds_pack.py" stage \
    "${THEME_HOSPITAL}" "${STAGE_ROOT}" --no-pack
  python3 "${CTH3DS_ROOT}/tools/prepare_loose_assets.py" \
    --runtime "${SOURCE_DATA}" --game "${THEME_HOSPITAL}" \
    --stage "${WORK_DEST}" --language "${LANGUAGE}" \
    --upstream "${UPSTREAM_DIR}"
fi

python3 "${CTH3DS_ROOT}/tools/validate_sd_tree.py" create-contract "${WORK_DEST}" \
  --asset-mode "${ASSET_MODE}" \
  --candidate-commit "${CANDIDATE_COMMIT}" \
  --candidate-tree "${CANDIDATE_TREE}" >/dev/null
python3 "${CTH3DS_ROOT}/tools/validate_sd_tree.py" write-manifest "${WORK_DEST}" >/dev/null
python3 "${CTH3DS_ROOT}/tools/validate_sd_tree.py" validate "${WORK_DEST}" \
  --require-mode "${ASSET_MODE}" >/dev/null
mkdir -p "$(dirname "${DEST}")"
mv "${WORK_DEST}" "${DEST}"

if [[ "${ASSET_MODE}" == "th3ds" ]]; then
  log "TH3DS experimental staging passed the boot contract at ${CTH3DS_DIST_DIR}/sd-card"
else
  log "loose product-candidate staging passed; runtime/device=NOT_PROVEN at ${CTH3DS_DIST_DIR}/sd-card"
fi
