@echo off
setlocal
cd /d "%~dp0"

rem Optional environment variables, set before running if you need them:
rem   FIGLAB_DATA_ROOT=<dir>   share one datasets/specs/outputs folder between installs
rem   FIGLAB_AUTO_DELIVER=1    also mirror every export into Desktop\FigLab
rem Usage: Start-FigLab.cmd [port] [--no-browser]

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

set "PORT=8778"
set "OPENBROWSER=1"
if not "%~1"=="" set "PORT=%~1"
if /i "%~2"=="--no-browser" set "OPENBROWSER="

rem If this port already serves FigLab, open the page instead of starting a second copy.
.venv\Scripts\python.exe -c "import sys,urllib.request;sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:%PORT%/api/locations',timeout=2).status==200 else 1)" >nul 2>&1
if not errorlevel 1 (
    echo FigLab is already running on port %PORT%.
    if defined OPENBROWSER start "" "http://127.0.0.1:%PORT%/"
    exit /b 0
)

if defined OPENBROWSER (
    .venv\Scripts\python.exe run.py --browser %PORT%
) else (
    .venv\Scripts\python.exe run.py %PORT%
)
if errorlevel 1 goto failed
exit /b 0

:failed
echo FigLab could not start. Check that Python 3.10+ is installed and read the message above.
pause
exit /b 1