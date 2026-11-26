@echo off
powershell.exe -NoProfile -NonInteractive -Command "& ([scriptblock]::Create([IO.File]::ReadAllText('C:\OEM\prepare.ps1')))"
