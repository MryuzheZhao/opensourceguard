@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
set "REPO=%~1"
set "PORT=%~2"
if "%PORT%"=="" set "PORT=8787"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%start.ps1" -Repo "%REPO%" -Port %PORT%
if errorlevel 1 (
  echo.
  echo 启动失败，请查看上面的提示。
  pause
)
endlocal
