@echo off
REM ============================================================================
REM AI Job Search & Auto-Apply Agent Launcher (Adithya Krishna)
REM ============================================================================
cd /d "%~dp0"
if exist "C:\Python315\python.exe" (
    "C:\Python315\python.exe" "%~dp0job_agent.py" --max-apply 25 %*
) else (
    python "%~dp0job_agent.py" --max-apply 25 %*
)
