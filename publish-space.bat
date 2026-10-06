@echo off
setlocal
set "SCRIPT_DIR=%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%SCRIPT_DIR%publish-space.ps1" %*
if errorlevel 1 (
  echo.
  echo 上传未完成，请查看上面的提示。
  pause
)
endlocal
