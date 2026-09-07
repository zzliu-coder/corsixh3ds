#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

ENGINE="${CTH3DS_CONTAINER_ENGINE:-}"
if [[ -z "${ENGINE}" ]]; then
  if command -v docker >/dev/null 2>&1; then
    ENGINE=docker
  elif command -v podman >/dev/null 2>&1; then
    ENGINE=podman
  else
    die 'Docker or Podman is required for the containerized 3DS build'
  fi
fi

PINNED_IMAGE="devkitpro/devkitarm@sha256:116afba8df8453961de2936ffab20dd441edf4d682856c1ec8b0e53d7ed0bbf5"
IMAGE="${CTH3DS_CONTAINER_IMAGE:-${PINNED_IMAGE}}"
# The package list is emitted already joined and space-prefixed. A heredoc
# cannot be followed by a pipe on the next line, which is why the previous
# form was a bash syntax error and this script could never run.
PACKAGE_ARGS="$(python3 - "${PIN_FILE}" <<'PY'
import json, pathlib, sys
pins = json.loads(pathlib.Path(sys.argv[1]).read_text())
packages = pins['devkitpro']['required_packages']
if not packages:
    raise SystemExit('no devkitPro packages are pinned')
for package in packages:
    if not package or any(character.isspace() for character in package):
        raise SystemExit(f'invalid devkitPro package name: {package!r}')
print(''.join(' ' + package for package in packages))
PY
)"
ROOT_Q="$(printf '%q' "${CTH3DS_ROOT}")"
PACKAGE_MOUNT_ARGS=()
PACKAGE_COMMAND=""
if [[ -n "${CTH3DS_THEME_HOSPITAL:-}" ]]; then
  [[ -d "${CTH3DS_THEME_HOSPITAL}" ]] || \
    die 'CTH3DS_THEME_HOSPITAL must name a directory'
  PACKAGE_ASSET_MODE="${CTH3DS_PACKAGE_ASSET_MODE:-loose}"
  case "${PACKAGE_ASSET_MODE}" in
    th3ds) log 'container will build a TH3DS experimental package' ;;
    loose) log 'container will build a loose product-candidate package; device NOT_PROVEN' ;;
    *) die 'CTH3DS_PACKAGE_ASSET_MODE must be th3ds or loose' ;;
  esac
  PACKAGE_MOUNT_ARGS=(-v "${CTH3DS_THEME_HOSPITAL}:/theme-hospital:ro")
  PACKAGE_COMMAND="; scripts/run_ci_command.sh old3ds-package artifacts/ci/old3ds-package -- scripts/package_sd.sh --asset-mode ${PACKAGE_ASSET_MODE} --theme-hospital /theme-hospital"
else
  log 'CTH3DS_THEME_HOSPITAL is unset; cross-build only, SD package remains NOT_PROVEN'
fi

log "running reproducible 3DS cross-build in ${IMAGE}"
"${ENGINE}" run --rm \
  -e CTH3DS_JOBS="${CTH3DS_JOBS}" \
  -e CTH3DS_CONTAINER_IMAGE="${IMAGE}" \
  -v "${CTH3DS_ROOT}:/work" \
  "${PACKAGE_MOUNT_ARGS[@]}" \
  -w /work \
  "${IMAGE}" \
  bash -lc "set -euo pipefail; dkp-pacman -S --needed --noconfirm 3ds-dev${PACKAGE_ARGS}; export DEVKITPRO=/opt/devkitpro DEVKITARM=/opt/devkitpro/devkitARM; scripts/build_3ds.sh${PACKAGE_COMMAND}"
log "containerized output is under ${ROOT_Q}/build-3ds and ${ROOT_Q}/dist"
