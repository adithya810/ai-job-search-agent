#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV_PY="${PROJECT_DIR}/.venv/bin/python"
if [ ! -x "${VENV_PY}" ]; then
  VENV_PY="$(command -v python3)"
fi
RUNNER="${PROJECT_DIR}/agent_runner.py"
EMAILER="${PROJECT_DIR}/send_jobs_email.py"
LOG_FILE="${PROJECT_DIR}/agent.log"
MODEL="hydrogen-medium"
EFFORT="medium"

# Schedule: Every Monday at 11:00 AM IST ONLY (runs agent + emails Applied_Companies_Tracker.xlsx)
CRON_JOB="0 11 * * 1 cd ${PROJECT_DIR} && ${VENV_PY} ${RUNNER} --model ${MODEL} --effort ${EFFORT} >> ${LOG_FILE} 2>&1 && ${VENV_PY} ${EMAILER} --if-exists >> ${LOG_FILE} 2>&1"

# Replace crontab completely so ONLY the Monday 11:00 AM IST job exists
{
  echo "TZ=Asia/Kolkata"
  echo "AGENT_MODEL=${MODEL}"
  echo "AGENT_REASONING_EFFORT=${EFFORT}"
  echo "${CRON_JOB}"
} | crontab -

echo "=== Verified Crontab (Monday 11:00 AM IST Only) ==="
crontab -l
echo ""
"${VENV_PY}" "${RUNNER}" --show-next-runs
