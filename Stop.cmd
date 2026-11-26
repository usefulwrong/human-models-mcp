@echo off
setlocal
if not exist "%~dp0.runtime\python\hmm-python-ready" exit /b 0
"%~dp0.runtime\python\python.exe" -X utf8 "%~dp0scripts\native.py" stop %*
exit /b %errorlevel%
