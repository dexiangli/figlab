@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    where py >nul 2>&1
    if errorlevel 1 (
        python -m venv .venv || goto failed
    ) else (
        py -3 -m venv .venv || goto failed
    )
)
if not exist ".venv\figlab-installed" (
    .venv\Scripts\python.exe -m pip install -r requirements.txt || goto failed
    type nul > .venv\figlab-installed
)
.venv\Scripts\python.exe run.py --browser %*
if errorlevel 1 goto failed
exit /b 0

:failed
echo FigLab could not start. Check Python 3.10+ and the message above.
pause
exit /b 1
