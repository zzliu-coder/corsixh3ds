#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

THEME_HOSPITAL=""
NO_BINARY_COPY=0
NO_DATA_PACK=0
while [[ $# -gt 0 ]]; do
  case "$1" in
    --theme-hospital)
      [[ $# -ge 2 ]] || die '--theme-hospital requires a path'
      THEME_HOSPITAL="$2"; shift ;;
    --no-binary-copy) NO_BINARY_COPY=1 ;;
    --no-data-pack) NO_DATA_PACK=1 ;;
    *) die "unknown argument: $1" ;;
  esac
  shift
done

UPSTREAM_DIR="${CTH3DS_EXTERNAL_DIR}/CorsixTH"
SOURCE_DATA="${UPSTREAM_DIR}/CorsixTH"
DEST="${CTH3DS_DIST_DIR}/sd-card/3ds/corsixth"
[[ -f "${SOURCE_DATA}/CorsixTH.lua" ]] || die 'integrated CorsixTH runtime data is missing'
mkdir -p "${DEST}"

if [[ "${NO_BINARY_COPY}" -eq 0 ]]; then
  built="${CTH3DS_BUILD_DIR}/CorsixTH/CorsixTH-3DS.3dsx"
  [[ -f "${built}" ]] || die 'build the .3dsx first'
  cp "${built}" "${DEST}/CorsixTH-3DS.3dsx"
fi

python3 - "${SOURCE_DATA}" "${DEST}" <<'PY'
from pathlib import Path
import shutil, sys
source, dest = map(Path, sys.argv[1:])
required = ['CorsixTH.lua', 'Bitmap', 'Campaigns', 'Graphics', 'Levels', 'Lua']
for name in required:
    item = source / name
    if not item.exists():
        raise SystemExit(f'missing CorsixTH runtime item: {item}')
    target = dest / name
    if target.exists():
        shutil.rmtree(target) if target.is_dir() else target.unlink()
    shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
for name in ('Languages', 'Fonts'):
    item = source / name
    if item.exists():
        target = dest / name
        if target.exists():
            shutil.rmtree(target) if target.is_dir() else target.unlink()
        shutil.copytree(item, target) if item.is_dir() else shutil.copy2(item, target)
PY

if [[ -f "${CTH3DS_DEPS_PREFIX}/share/lpeg/re.lua" ]]; then
  cp "${CTH3DS_DEPS_PREFIX}/share/lpeg/re.lua" "${DEST}/re.lua"
fi
cat > "${DEST}/config.txt" <<'CFG'
theme_hospital_install = "sdmc:/3ds/corsixth/game"
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

# Record which overlay produced this SD-card tree. The runtime prints its own
# version and adapter origin on the lower screen, so a mismatch between the
# binary and the Lua tree can be spotted without a debugger.
printf '%s\n' "$(cat "${CTH3DS_ROOT}/VERSION")" > "${DEST}/cth3ds-overlay-version.txt"

if [[ -n "${THEME_HOSPITAL}" ]]; then
  if [[ "${NO_DATA_PACK}" -eq 1 ]]; then
    python3 "${CTH3DS_ROOT}/tools/th3ds_pack.py" stage "${THEME_HOSPITAL}" \
      "${CTH3DS_DIST_DIR}/sd-card" --no-pack
  else
    python3 "${CTH3DS_ROOT}/tools/th3ds_pack.py" stage "${THEME_HOSPITAL}" \
      "${CTH3DS_DIST_DIR}/sd-card"
  fi
  # CorsixTH reads DATA/LEVELS/QDATA/SOUND, while retaining the original
  # executable/config at the root makes the staged folder self-identifying
  # and matches the layout expected by the upstream data-folder guidance.
  for root_file in HOSPITAL.EXE HOSP95.EXE HOSPITAL.CFG; do
    if [[ -f "${THEME_HOSPITAL}/${root_file}" ]]; then
      cp "${THEME_HOSPITAL}/${root_file}" "${DEST}/game/${root_file}"
    fi
  done
fi

python3 - "${DEST}" <<'PY'
from pathlib import Path
import hashlib, json, sys
root = Path(sys.argv[1])
files = []
for path in sorted(p for p in root.rglob('*') if p.is_file()):
    rel = path.relative_to(root).as_posix()
    h = hashlib.sha256()
    with path.open('rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    files.append({'path': rel, 'size': path.stat().st_size, 'sha256': h.hexdigest()})
manifest = {'format': 1, 'root': 'sdmc:/3ds/corsixth', 'files': files}
(root / 'sd-manifest.json').write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n')
PY
log "SD-card staging is ready at ${CTH3DS_DIST_DIR}/sd-card"
