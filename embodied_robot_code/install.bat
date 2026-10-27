@echo off
setlocal
net session >nul 2>&1
if %errorLevel% neq 0 (
  echo Requesting administrator privilege...
  powershell -Command "Start-Process '%~f0' -Verb RunAs"
  exit /b
)
set "SRC=%~dp0controllers\webots_controller"
set "WEBOTS=C:\Program Files\Webots"
if not exist "%WEBOTS%" (
  echo Webots not found at default path. Edit WEBOTS in this script.
  pause
  exit /b 1
)
set "DST=%WEBOTS%\projects\default\controllers\webots_controller"
if not exist "%WEBOTS%\projects\default\controllers" (
  echo Built-in controllers folder missing: %WEBOTS%\projects\default\controllers
  pause
  exit /b 1
)
if not exist "%SRC%" (
  echo Controller folder not found: %SRC%
  pause
  exit /b 1
)
xcopy /E /I /Y "%SRC%" "%DST%" >nul
if errorlevel 1 (
  echo Copy failed. Check permission or path.
  pause
  exit /b 1
)
echo.
echo [OK] Controller copied to:
echo   %DST%
echo.
echo In Webots: select Pioneer3DX - controller field Select... - webots_controller - press Run.
echo.
pause
