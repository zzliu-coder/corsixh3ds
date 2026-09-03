#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

python3 "${CTH3DS_ROOT}/tools/check_pins.py"
printf '\nHost tools:\n'
for tool in cmake python3 git ninja gcc g++ clang++; do
  if command -v "${tool}" >/dev/null 2>&1; then
    printf '  %-18s %s\n' "${tool}" "$(command -v "${tool}")"
  else
    printf '  %-18s missing\n' "${tool}"
  fi
done
printf '\n3DS toolchain:\n'
if [[ -n "${DEVKITPRO:-}" && -f "${DEVKITPRO}/cmake/3DS.cmake" ]]; then
  printf '  DEVKITPRO          %s\n' "${DEVKITPRO}"
  printf '  arm-none-eabi-g++  %s\n' "$(command -v arm-none-eabi-g++ || echo missing)"
  printf '  3dsxtool           %s\n' "$(command -v 3dsxtool || echo missing)"
else
  printf '  unavailable (use scripts/build_3ds_docker.sh or install devkitPro)\n'
fi
