#!/usr/bin/env bash
set -euo pipefail

PROJECT_DIR="/home/antigravity/job-search-agent"
VENV_PY="${PROJECT_DIR}/.venv/bin/python"
RUNNER="${PROJECT_DIR}/agent_runner.py"
LOG_FILE="${PROJECT_DIR}/agent.log"
MODEL="flash-3.8"

# Schedule: Every Monday at 11:00 AM IST ONLY (removes all other schedules)
CRON_JOB="0 11 * * 1 ${VENV_PY} ${RUNNER} --model ${MODEL} >> ${LOG_FILE} 2>&1"

# Replace crontab completely so ONLY the Monday 11:00 AM IST job exists
{
  echo "TZ=Asia/Kolkata"
  echo "AGENT_MODEL=${MODEL}"
  echo "${CRON_JOB}"
} | crontab -

echo "=== Verified Crontab (Monday 11:00 AM IST Only) ==="
crontab -l
echo ""
"${VENV_PY}" "${RUNNER}" --show-next-runs
