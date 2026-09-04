#!/usr/bin/env bash
set -euo pipefail
set -E
source "$(cd "$(dirname "$0")" && pwd)/common.sh"
source "$(cd "$(dirname "$0")" && pwd)/ci_diagnostics.sh"

LOG_DIR="${CTH3DS_ROOT}/artifacts/verification"
PREVIEW_DIR="${LOG_DIR}/preview"
VERIFY_RESUME="${CTH3DS_VERIFY_RESUME:-0}"
HOST_MATRIX="${CTH3DS_HOST_MATRIX:-all}"
RUN_COMMON="${CTH3DS_RUN_COMMON:-}"
case "${HOST_MATRIX}" in
  all|gcc-debug|gcc-release|gcc-sanitized|clang-debug) ;;
  *) die "unknown host verification matrix: ${HOST_MATRIX}" ;;
esac
if [[ -z "${RUN_COMMON}" ]]; then
  if [[ "${HOST_MATRIX}" == "all" ]]; then
    RUN_COMMON=1
  else
    RUN_COMMON=0
  fi
fi
[[ "${RUN_COMMON}" == "0" || "${RUN_COMMON}" == "1" ]] || \
  die 'CTH3DS_RUN_COMMON must be 0 or 1'
require_cmd python3
SOURCE_FINGERPRINT="$(python3 - "${CTH3DS_ROOT}" <<'PY'
from __future__ import annotations
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
roots = [
    root / "CMakeLists.txt",
    root / "VERSION",
    root / "include",
    root / "src",
    root / "tests",
    root / "tools",
    root / "lua",
    root / "config",
    root / "scripts",
    root / "cmake",
    root / "integrations",
]
files: list[pathlib.Path] = []
for candidate in roots:
    if candidate.is_file():
        files.append(candidate)
    elif candidate.is_dir():
        files.extend(
            path for path in candidate.rglob("*")
            if path.is_file()
            and "__pycache__" not in path.parts
            and path.suffix not in {".pyc", ".pyo"}
        )

hasher = hashlib.sha256()
for path in sorted(files, key=lambda item: item.relative_to(root).as_posix()):
    relative = path.relative_to(root).as_posix().encode("utf-8")
    payload = path.read_bytes()
    hasher.update(len(relative).to_bytes(4, "big"))
    hasher.update(relative)
    hasher.update(len(payload).to_bytes(8, "big"))
    hasher.update(payload)
print(hasher.hexdigest())
PY
)"
if [[ "${VERIFY_RESUME}" != "1" ]]; then
  rm -rf "${LOG_DIR}" "${PREVIEW_DIR}"
fi
mkdir -p "${LOG_DIR}" "${PREVIEW_DIR}"
ci_diag_init "host-${HOST_MATRIX}" "${LOG_DIR}"
printf '%s\n' "${SOURCE_FINGERPRINT}" >"${LOG_DIR}/source.sha256"

CTH3DS_ASAN_LEAKS_OPTION="${CTH3DS_ASAN_LEAKS_OPTION:-}"
if [[ -z "${CTH3DS_ASAN_LEAKS_OPTION}" && "$(uname -s)" != "Darwin" ]]; then
  CTH3DS_ASAN_LEAKS_OPTION=':detect_leaks=1'
fi

configure_build_test() {
  local name="$1" cc="$2" cxx="$3" build_type="$4" sanitizers="$5"
  local build="${CTH3DS_ROOT}/build-verify-${name}"
  local fingerprint_file="${LOG_DIR}/${name}-source.sha256"
  if [[ "${VERIFY_RESUME}" == "1" && -f "${fingerprint_file}" &&
        "$(cat "${fingerprint_file}")" == "${SOURCE_FINGERPRINT}" &&
        -f "${LOG_DIR}/${name}-compiler.json" &&
        -f "${LOG_DIR}/${name}-ctest.log" &&
        -s "${LOG_DIR}/${name}-simulator/top.ppm" ]] &&
        grep -q '100% tests passed, 0 tests failed' "${LOG_DIR}/${name}-ctest.log"; then
    log "verification matrix already complete for current source: ${name}"
    return
  fi
  rm -rf "${build}"
  set_cmake_generator
  log "verification matrix: ${name}"
  ci_diag_step "${name}-configure" "${LOG_DIR}/${name}-configure.log"
  env CC="${cc}" CXX="${cxx}" cmake -S "${CTH3DS_ROOT}" -B "${build}" "${CTH3DS_CMAKE_GENERATOR[@]}" \
    -DCMAKE_BUILD_TYPE="${build_type}" \
    -DCTH3DS_BUILD_TESTS=ON \
    -DCTH3DS_BUILD_SIMULATOR=ON \
    -DCTH3DS_BUILD_3DS_SYNTAX_CHECK=ON \
    -DCTH3DS_WARNINGS_AS_ERRORS=ON \
    -DCTH3DS_ENABLE_SANITIZERS="${sanitizers}" \
    >"${LOG_DIR}/${name}-configure.log" 2>&1
  ci_diag_step "${name}-compiler-identity" \
    "${LOG_DIR}/${name}-configure.log" "${LOG_DIR}/${name}-compiler.json"
  python3 - "${build}" "${name}" "${cc}" "${cxx}" \
    "${LOG_DIR}/${name}-compiler.json" <<'PY'
from __future__ import annotations
import json
import pathlib
import re
import shutil
import sys

build = pathlib.Path(sys.argv[1])
name, requested_cc, requested_cxx = sys.argv[2:5]
output = pathlib.Path(sys.argv[5])
matches = list(build.glob("CMakeFiles/*/CMakeCXXCompiler.cmake"))
if len(matches) != 1:
    raise SystemExit(f"expected one CMakeCXXCompiler.cmake, found {len(matches)}")
text = matches[0].read_text(encoding="utf-8", errors="replace")


def cmake_value(variable: str) -> str:
    match = re.search(rf'^set\({variable} "([^"]*)"\)$', text, re.MULTILINE)
    if match is None or not match.group(1):
        raise SystemExit(f"missing {variable} in {matches[0]}")
    return match.group(1)


compiler_id = cmake_value("CMAKE_CXX_COMPILER_ID")
compiler_version = cmake_value("CMAKE_CXX_COMPILER_VERSION")
compiler_value = cmake_value("CMAKE_CXX_COMPILER")
resolved = pathlib.Path(compiler_value).resolve(strict=True)
expected_ids = ("GNU",) if name.startswith("gcc-") else ("Clang", "AppleClang")
if compiler_id not in expected_ids:
    raise SystemExit(
        f"{name} resolved {compiler_id}, expected one of {expected_ids}"
    )
if name.startswith("gcc-") and not compiler_version.startswith("13."):
    raise SystemExit(f"{name} resolved GNU {compiler_version}, expected GNU 13")
identity = {
    "matrix": name,
    "expected_ids": list(expected_ids),
    "requested_cc": requested_cc,
    "requested_cxx": requested_cxx,
    "requested_cxx_path": shutil.which(requested_cxx),
    "compiler_path": str(resolved),
    "compiler_id": compiler_id,
    "compiler_version": compiler_version,
    "cmake_identity_file": str(matches[0].resolve()),
}
output.write_text(json.dumps(identity, indent=2, sort_keys=True) + "\n")
print(json.dumps(identity, sort_keys=True))
PY
  ci_diag_step "${name}-build" "${LOG_DIR}/${name}-configure.log" \
    "${LOG_DIR}/${name}-compiler.json" "${LOG_DIR}/${name}-build.log"
  cmake --build "${build}" --parallel "${CTH3DS_JOBS}" \
    >"${LOG_DIR}/${name}-build.log" 2>&1
  ci_diag_step "${name}-ctest" "${LOG_DIR}/${name}-configure.log" \
    "${LOG_DIR}/${name}-build.log" "${LOG_DIR}/${name}-ctest.log"
  if [[ "${sanitizers}" == "ON" ]]; then
    # Apple ships AddressSanitizer without LeakSanitizer support. Enabling
    # detect_leaks there aborts every sanitized test before it starts.
    ASAN_OPTIONS="halt_on_error=1${CTH3DS_ASAN_LEAKS_OPTION:-}" \
    UBSAN_OPTIONS=halt_on_error=1:print_stacktrace=1 \
      ctest --test-dir "${build}" --output-on-failure \
      >"${LOG_DIR}/${name}-ctest.log" 2>&1
  else
    ctest --test-dir "${build}" --output-on-failure \
      >"${LOG_DIR}/${name}-ctest.log" 2>&1
  fi
  ci_diag_step "${name}-cpp-tests" "${LOG_DIR}/${name}-ctest.log" \
    "${LOG_DIR}/${name}-cpp-tests.log"
  "${build}/cth3ds-tests" >"${LOG_DIR}/${name}-cpp-tests.log" 2>&1
  ci_diag_step "${name}-simulator" "${LOG_DIR}/${name}-cpp-tests.log" \
    "${LOG_DIR}/${name}-simulator.log"
  "${build}/cth3ds-simulator" "${LOG_DIR}/${name}-simulator" \
    >"${LOG_DIR}/${name}-simulator.log" 2>&1
  printf '%s\n' "${SOURCE_FINGERPRINT}" >"${fingerprint_file}"
}

require_cmd cmake
GNU_CC="${CTH3DS_GCC:-gcc}"
GNU_CXX="${CTH3DS_GXX:-g++}"
CLANG_CC="${CTH3DS_CLANG:-clang}"
CLANG_CXX="${CTH3DS_CLANGXX:-clang++}"
case "${HOST_MATRIX}" in
  all)
    require_cmd "${GNU_CC}"
    require_cmd "${GNU_CXX}"
    configure_build_test gcc-debug "${GNU_CC}" "${GNU_CXX}" Debug OFF
    configure_build_test gcc-release "${GNU_CC}" "${GNU_CXX}" Release OFF
    configure_build_test gcc-sanitized "${GNU_CC}" "${GNU_CXX}" Debug ON
    if command -v "${CLANG_CC}" >/dev/null 2>&1 && \
       command -v "${CLANG_CXX}" >/dev/null 2>&1; then
      configure_build_test clang-debug "${CLANG_CC}" "${CLANG_CXX}" Debug OFF
    else
      log 'clang unavailable; clang matrix skipped'
    fi
    ;;
  gcc-debug)
    require_cmd "${GNU_CC}"
    require_cmd "${GNU_CXX}"
    configure_build_test gcc-debug "${GNU_CC}" "${GNU_CXX}" Debug OFF
    ;;
  gcc-release)
    require_cmd "${GNU_CC}"
    require_cmd "${GNU_CXX}"
    configure_build_test gcc-release "${GNU_CC}" "${GNU_CXX}" Release OFF
    ;;
  gcc-sanitized)
    require_cmd "${GNU_CC}"
    require_cmd "${GNU_CXX}"
    configure_build_test gcc-sanitized "${GNU_CC}" "${GNU_CXX}" Debug ON
    ;;
  clang-debug)
    require_cmd "${CLANG_CC}"
    require_cmd "${CLANG_CXX}"
    configure_build_test clang-debug "${CLANG_CC}" "${CLANG_CXX}" Debug OFF
    ;;
esac

if [[ "${RUN_COMMON}" == "1" ]]; then
  [[ -x "${CTH3DS_ROOT}/build-verify-gcc-debug/cth3ds-tests" ]] || \
    die 'common verification requires the gcc-debug matrix'

  # Catch flaky state transitions without repeatedly starting the Python runtime.
  ci_diag_step repeat-50 "${LOG_DIR}/repeat-50.log"
  ctest --test-dir "${CTH3DS_ROOT}/build-verify-gcc-debug" \
    -R '^cth3ds-tests$' --repeat until-fail:50 --output-on-failure \
    >"${LOG_DIR}/repeat-50.log" 2>&1

  ci_diag_step python-compileall "${LOG_DIR}/python-compileall.log"
  PYTHONDONTWRITEBYTECODE=1 python3 -m compileall -q \
    "${CTH3DS_ROOT}/tools" "${CTH3DS_ROOT}/tests" \
    >"${LOG_DIR}/python-compileall.log" 2>&1
  ci_diag_step python-tests "${LOG_DIR}/python-compileall.log" \
    "${LOG_DIR}/python-tests.log"
  PYTHONPATH="${CTH3DS_ROOT}/tools" \
  CTH3DS_SIMULATOR="${CTH3DS_ROOT}/build-verify-gcc-debug/cth3ds-simulator" \
  CTH3DS_RUNTIME_PROBE="${CTH3DS_ROOT}/build-verify-gcc-debug/cth3ds-runtime-probe" \
  PYTHONDONTWRITEBYTECODE=1 \
    python3 "${CTH3DS_ROOT}/scripts/run_host_python_suite.py" \
      --repo "${CTH3DS_ROOT}" \
      --manifest "${CTH3DS_ROOT}/tests/host-python-suite.json" \
      --output "${LOG_DIR}/host-python-suite-result.json" \
    >"${LOG_DIR}/python-tests.log" 2>&1

# The device present path is compiled for the real CPU and inspected here: an
# ARM11 has no hardware divider, so a division that creeps back into the
# framebuffer copy would silently cost tens of milliseconds per frame again.
  ARM_CHECK_EXECUTED=0
  ci_diag_step arm-codegen "${LOG_DIR}/arm-codegen.log"
  if "${CTH3DS_ROOT}/scripts/check_arm_codegen.sh" >"${LOG_DIR}/arm-codegen.log" 2>&1; then
    if grep -q 'ARM codegen check passed' "${LOG_DIR}/arm-codegen.log"; then
      ARM_CHECK_EXECUTED=1
    fi
  else
    cat "${LOG_DIR}/arm-codegen.log" >&2
    die 'ARM codegen check failed'
  fi

  SHELL_COUNT=0
  ci_diag_step shell-syntax "${LOG_DIR}/shell-syntax.log"
  for script in "${CTH3DS_ROOT}"/scripts/*.sh; do
    bash -n "${script}" >>"${LOG_DIR}/shell-syntax.log" 2>&1
    SHELL_COUNT=$((SHELL_COUNT + 1))
  done
  ci_diag_step pins "${LOG_DIR}/pins.json"
  python3 "${CTH3DS_ROOT}/tools/check_pins.py" --json \
    >"${LOG_DIR}/pins.json"

  ACTUAL_API_CHECKED=0
  UPSTREAM_DIR="${CTH3DS_EXTERNAL_DIR}/CorsixTH"
  if [[ -d "${UPSTREAM_DIR}" ]]; then
    ci_diag_step upstream-lua-api "${LOG_DIR}/upstream-lua-api.json"
    python3 "${CTH3DS_ROOT}/tools/check_upstream_lua_api.py" "${UPSTREAM_DIR}" --json \
      >"${LOG_DIR}/upstream-lua-api.json"
    ACTUAL_API_CHECKED=1
  else
    printf '{"ok": false, "skipped": true, "reason": "pinned upstream checkout is absent"}\n' \
      >"${LOG_DIR}/upstream-lua-api.json"
  fi

  ci_diag_step preview "${LOG_DIR}/preview.log"
  python3 "${CTH3DS_ROOT}/tools/make_preview.py" \
    "${LOG_DIR}/gcc-debug-simulator/top.ppm" \
    "${LOG_DIR}/gcc-debug-simulator/bottom.ppm" \
    "${PREVIEW_DIR}/dual-screen-preview.png" \
    >"${LOG_DIR}/preview.log" 2>&1
  cp "${LOG_DIR}/gcc-debug-simulator/trace.json" "${PREVIEW_DIR}/trace.json"

  CROSS_EXECUTED=0
  CROSS_SKIP_REASON=""
  VERIFY_CROSS="${CTH3DS_VERIFY_CROSS:-auto}"
  if [[ "${VERIFY_CROSS}" == "0" || "${VERIFY_CROSS}" == "off" ]]; then
    CROSS_SKIP_REASON="cross-build disabled by CTH3DS_VERIFY_CROSS"
  elif [[ -z "${DEVKITPRO:-}" || ! -f "${DEVKITPRO}/cmake/3DS.cmake" ]]; then
    CROSS_SKIP_REASON="devkitPro/devkitARM is unavailable in this environment"
  elif [[ ! -f "${UPSTREAM_DIR}/CorsixTH/Src/3ds/integration-manifest.json" ]]; then
    CROSS_SKIP_REASON="integrated pinned CorsixTH checkout is unavailable"
  elif [[ ! -f "${CTH3DS_DEPS_PREFIX}/cth3ds-dependencies.json" ]]; then
    CROSS_SKIP_REASON="staged 3DS dependency libraries are unavailable"
  else
    ci_diag_step old3ds-cross-build "${LOG_DIR}/old3ds-cross-build.log"
    "${CTH3DS_ROOT}/scripts/build_3ds.sh" --skip-bootstrap \
      >"${LOG_DIR}/old3ds-cross-build.log" 2>&1
    CROSS_EXECUTED=1
  fi
else
  ARM_CHECK_EXECUTED=0
  SHELL_COUNT=0
  ACTUAL_API_CHECKED=0
  CROSS_EXECUTED=0
  CROSS_SKIP_REASON="common verification runs in the gcc-debug matrix"
fi

export CTH3DS_VERIFY_ARM_CHECK="${ARM_CHECK_EXECUTED}"
export CTH3DS_VERIFY_SHELL_COUNT="${SHELL_COUNT}"
export CTH3DS_VERIFY_ACTUAL_API="${ACTUAL_API_CHECKED}"
export CTH3DS_VERIFY_CROSS_EXECUTED="${CROSS_EXECUTED}"
export CTH3DS_VERIFY_CROSS_SKIP="${CROSS_SKIP_REASON}"
export CTH3DS_VERIFY_HOST_MATRIX="${HOST_MATRIX}"
export CTH3DS_VERIFY_RUN_COMMON="${RUN_COMMON}"
ci_diag_step summary "${LOG_DIR}/summary.json"
python3 - "${CTH3DS_ROOT}" "${LOG_DIR}" <<'PY'
from __future__ import annotations
import hashlib, json, os, pathlib, platform, re, shutil, subprocess, sys
root = pathlib.Path(sys.argv[1])
logs = pathlib.Path(sys.argv[2])


def read(path: pathlib.Path) -> str:
    return path.read_text(errors='replace') if path.is_file() else ''


matrix_names = ('gcc-debug', 'gcc-release', 'gcc-sanitized', 'clang-debug')
selected = os.environ['CTH3DS_VERIFY_HOST_MATRIX']
matrices = []
matrix_skips = []
cpp_suites = []
for name in matrix_names:
    ctest_text = read(logs / f'{name}-ctest.log')
    ctest_match = re.search(
        r'(\d+)% tests passed, (\d+) tests failed out of (\d+)', ctest_text
    )
    not_run = len(re.findall(r'\*\*\*Not Run', ctest_text))
    if ctest_match:
        total = int(ctest_match.group(3))
        failed = int(ctest_match.group(2))
        compiler_identity = json.loads(
            (logs / f'{name}-compiler.json').read_text(encoding='utf-8')
        )
        matrices.append({
            'name': name,
            'status': 'PASS' if failed == 0 and not_run == 0 else 'FAIL',
            'ctest_total': total,
            'ctest_passed': total - failed - not_run,
            'ctest_failed': failed,
            'ctest_skipped': not_run,
            'compiler': compiler_identity,
        })
    else:
        reason = (
            'compiler unavailable'
            if selected == 'all' and name == 'clang-debug'
            else f'isolated in the {name} CI job'
        )
        matrix_skips.append({
            'name': name,
            'status': 'SKIP',
            'reason': reason,
        })

    cpp_text = read(logs / f'{name}-cpp-tests.log')
    cpp_match = re.search(r'Ran (\d+) tests; (\d+) failed', cpp_text)
    if cpp_match:
        total = int(cpp_match.group(1))
        failed = int(cpp_match.group(2))
        cpp_suites.append({
            'matrix': name,
            'status': 'PASS' if failed == 0 else 'FAIL',
            'total': total,
            'passed': total - failed,
            'failed': failed,
            'skipped': 0,
        })

common_ran = os.environ['CTH3DS_VERIFY_RUN_COMMON'] == '1'
python_receipt = None
python_total = 0
python_failed = 0
python_errors = 0
python_skipped = 0
python_passed = 0
if common_ran:
    python_receipt = json.loads((logs / 'host-python-suite-result.json').read_text())
    if python_receipt.get('verdict') != 'PASS':
        raise SystemExit('host Python suite receipt is not PASS')
    python_totals = python_receipt['execution']['totals']
    python_total = python_totals['selected']
    python_failed = python_totals['failed']
    python_errors = python_totals['errors']
    python_skipped = python_totals['skipped']
    python_passed = python_totals['passed']
python_expected_failures = 0
python_unexpected_successes = 0
frames = {}
for name in ('top.ppm', 'bottom.ppm', 'trace.json'):
    path = logs / 'gcc-debug-simulator' / name
    if path.is_file():
        frames[name] = hashlib.sha256(path.read_bytes()).hexdigest()
identity_path = logs / 'identity.json'
identity = json.loads(identity_path.read_text()) if identity_path.is_file() else None
cpp_total = sum(row['total'] for row in cpp_suites)
cpp_failed = sum(row['failed'] for row in cpp_suites)
compiler_identities = [row['compiler'] for row in matrices]
actual_gnu = next(
    (row for row in compiler_identities if row['compiler_id'] == 'GNU'), None
)
actual_clang = next(
    (
        row for row in compiler_identities
        if row['compiler_id'] in ('Clang', 'AppleClang')
    ),
    None,
)


def compiler_summary(row):
    if row is None:
        return None
    return f"{row['compiler_id']} {row['compiler_version']} ({row['compiler_path']})"


summary = {
    'format': 3,
    'status': 'PASS',
    'matrix': f'host-{selected}',
    'stage': 'complete',
    'exit_code': 0,
    'failed_command': None,
    'identity': identity,
    'version': (root / 'VERSION').read_text().strip(),
    'platform': platform.platform(),
    'python': platform.python_version(),
    'cmake': subprocess.check_output(['cmake', '--version'], text=True).splitlines()[0],
    'gcc': compiler_summary(actual_gnu),
    'clang': compiler_summary(actual_clang),
    'compiler_identities': compiler_identities,
    'matrices': matrices,
    'matrix_skips': matrix_skips,
    'cpp_suites': cpp_suites,
    'cpp_tests': cpp_total,
    'cpp_failed': cpp_failed,
    'python_tests': python_total,
    'python_passed': python_passed,
    'python_failed': python_failed,
    'python_errors': python_errors,
    'python_skipped': python_skipped,
    'python_expected_failures': python_expected_failures,
    'python_unexpected_successes': python_unexpected_successes,
    'host_python_suite': python_receipt,
    'common_checks': {
        'status': 'PASS' if common_ran else 'SKIP',
        'reason': None if common_ran else 'runs in the gcc-debug CI job',
    },
    'repeat_count': 50 if common_ran else 0,
    'shell_scripts_checked': int(os.environ['CTH3DS_VERIFY_SHELL_COUNT']),
    'pins_validated': common_ran,
    'arm_codegen_checked': os.environ['CTH3DS_VERIFY_ARM_CHECK'] == '1',
    'actual_upstream_api_checked': os.environ['CTH3DS_VERIFY_ACTUAL_API'] == '1',
    'simulator_sha256': frames,
    'preview': 'artifacts/verification/preview/dual-screen-preview.png' if common_ran else None,
    'true_3ds_cross_build_executed': os.environ['CTH3DS_VERIFY_CROSS_EXECUTED'] == '1',
    'cross_build_skip_reason': os.environ['CTH3DS_VERIFY_CROSS_SKIP'],
    'hardware_tests_executed': False,
}
(logs / 'summary.json').write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n')
print(json.dumps(summary, indent=2, sort_keys=True))
PY
ci_diag_step report "${LOG_DIR}/summary.json" "${LOG_DIR}/report.md"
python3 "${CTH3DS_ROOT}/tools/write_verification_report.py" \
  "${LOG_DIR}/summary.json" "${LOG_DIR}/report.md"
trap - ERR
log "verification complete: ${LOG_DIR}/summary.json"
