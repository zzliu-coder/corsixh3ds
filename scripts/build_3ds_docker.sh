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

IMAGE="$(pin devkitpro.docker_image)"
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

log "running reproducible 3DS cross-build in ${IMAGE}"
"${ENGINE}" run --rm \
  -e CTH3DS_JOBS="${CTH3DS_JOBS}" \
  -v "${CTH3DS_ROOT}:/work" \
  -w /work \
  "${IMAGE}" \
  bash -lc "set -euo pipefail; dkp-pacman -Syu --noconfirm; dkp-pacman -S --needed --noconfirm${PACKAGE_ARGS}; export DEVKITPRO=/opt/devkitpro DEVKITARM=/opt/devkitpro/devkitARM; scripts/build_3ds.sh; scripts/package_sd.sh"
log "containerized output is under ${ROOT_Q}/build-3ds and ${ROOT_Q}/dist"
