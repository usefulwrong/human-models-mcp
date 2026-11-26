@echo off
setlocal
for %%I in ("%~dp0..\..") do set "HMM_BOOTSTRAP_ROOT=%%~fI"
powershell.exe -NoLogo -NoProfile -Command "try { & ([scriptblock]::Create([IO.File]::ReadAllText([IO.Path]::Combine($env:HMM_BOOTSTRAP_ROOT, 'scripts\windows\bootstrap.ps1')))) } catch { [Console]::Error.WriteLine($_.Exception.Message); exit 1 }"
exit /b %errorlevel%
