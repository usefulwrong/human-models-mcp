@echo off
setlocal
if /I "%~1"=="--yes" set "HMM_ASSUME_YES=1"
if not exist "%~dp0.runtime\python\hmm-python-ready" call "%~dp0scripts\windows\bootstrap.cmd"
if errorlevel 1 goto failed
"%~dp0.runtime\python\python.exe" -X utf8 "%~dp0scripts\native.py" install %*
if not errorlevel 1 exit /b 0
:failed
if not "%HMM_ASSUME_YES%"=="1" pause
exit /b 1
