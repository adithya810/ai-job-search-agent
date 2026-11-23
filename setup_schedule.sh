#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/antigravity/job-search-agent"
VENV_PY="${PROJECT_DIR}/.venv/bin/python"
RUNNER="${PROJECT_DIR}/agent_runner.py"
LOG_FILE="${PROJECT_DIR}/agent.log"

CRON_JOB="0 11,18 * * 1 ${VENV_PY} ${RUNNER} >> ${LOG_FILE} 2>&1"

# Preserve existing non-duplicate crontab entries, enforce TZ=Asia/Kolkata
EXISTING="$(crontab -l 2>/dev/null || true)"
CLEANED="$(printf '%s\n' "${EXISTING}" | grep -v "${RUNNER}" | grep -v '^TZ=Asia/Kolkata$' || true)"

{
  echo "TZ=Asia/Kolkata"
  if [ -n "${CLEANED}" ]; then
    printf '%s\n' "${CLEANED}"
  fi
  echo "${CRON_JOB}"
} | crontab -

echo "=== Verified Crontab ==="
crontab -l
echo ""
"${VENV_PY}" "${RUNNER}" --show-next-runs
