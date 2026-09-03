#!/usr/bin/env bash
set -euo pipefail
source "$(cd "$(dirname "$0")" && pwd)/common.sh"

BUILD_DIR="${CTH3DS_HOST_BUILD_DIR:-${CTH3DS_ROOT}/build-host}"
BUILD_TYPE="${CTH3DS_HOST_BUILD_TYPE:-RelWithDebInfo}"
set_cmake_generator

require_cmd cmake
require_cmd python3
log "configuring host validation build (${BUILD_TYPE})"
cmake -S "${CTH3DS_ROOT}" -B "${BUILD_DIR}" "${CTH3DS_CMAKE_GENERATOR[@]}" \
  -DCMAKE_BUILD_TYPE="${BUILD_TYPE}" \
  -DCTH3DS_BUILD_TESTS=ON \
  -DCTH3DS_BUILD_SIMULATOR=ON \
  -DCTH3DS_BUILD_3DS_SYNTAX_CHECK=ON \
  -DCTH3DS_WARNINGS_AS_ERRORS=ON
cmake --build "${BUILD_DIR}" --parallel "${CTH3DS_JOBS}"
ctest --test-dir "${BUILD_DIR}" --output-on-failure
log "host validation build passed: ${BUILD_DIR}"
