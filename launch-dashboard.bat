@echo off
REM Double-click this file to build + open the budget dashboard.
REM Wraps scripts/launch.ps1 with the right execution policy.

powershell.exe -ExecutionPolicy Bypass -NoProfile -File "%~dp0scripts\launch.ps1"
