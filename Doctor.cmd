@echo off
setlocal
if not exist "%~dp0.runtime\python\hmm-python-ready" (
    echo Portable Python is missing. Run Install.cmd.
    if "%~1"=="" pause
    exit /b 1
)
"%~dp0.runtime\python\python.exe" -X utf8 "%~dp0scripts\native.py" doctor %*
set "HMM_EXIT=%errorlevel%"
if "%~1"=="" pause
exit /b %HMM_EXIT%
