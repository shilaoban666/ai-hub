@echo off
setlocal
rem Also works when launched from PowerShell 7 with its own PSModulePath.
set "PSModulePath=%SystemRoot%\System32\WindowsPowerShell\v1.0\Modules;%ProgramFiles%\WindowsPowerShell\Modules;%PSModulePath%"
"%SystemRoot%\System32\WindowsPowerShell\v1.0\powershell.exe" -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\aihub-windows.ps1" %*
set "RESULT=%ERRORLEVEL%"
if "%~1"=="" pause
exit /b %RESULT%
