#!/usr/bin/env bash
set -euo pipefail
set -E

source "$(cd "$(dirname "$0")" && pwd)/common.sh"
source "$(cd "$(dirname "$0")" && pwd)/ci_diagnostics.sh"

[[ $# -ge 4 ]] || die 'usage: run_ci_command.sh MATRIX OUTPUT_DIR -- COMMAND [ARG ...]'
MATRIX="$1"
OUTPUT_DIR="$2"
shift 2
[[ "$1" == "--" ]] || die 'missing -- before command'
shift
[[ $# -gt 0 ]] || die 'missing command'

LOG_FILE="${OUTPUT_DIR}/command.log"
ci_diag_init "${MATRIX}" "${OUTPUT_DIR}"
ci_diag_step command "${LOG_FILE}"

trap - ERR
set +e
"$@" 2>&1 | tee "${LOG_FILE}"
PIPE_STATUSES=("${PIPESTATUS[@]}")
set -e
COMMAND_STATUS="${PIPE_STATUSES[0]}"
LOGGER_STATUS="${PIPE_STATUSES[1]}"
if [[ "${COMMAND_STATUS}" -ne 0 ]]; then
  COMMAND_TEXT="$(printf '%q ' "$@")"
  ci_diag_emit_failure "${COMMAND_STATUS}" "${COMMAND_TEXT% }"
  exit "${COMMAND_STATUS}"
fi
if [[ "${LOGGER_STATUS}" -ne 0 ]]; then
  ci_diag_emit_failure "${LOGGER_STATUS}" \
    "diagnostic logger failed while capturing command output"
  exit "${LOGGER_STATUS}"
fi

ci_diag_mark_pass
