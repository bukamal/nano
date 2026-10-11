@echo off
setlocal
rem Single source of truth: src\nano_offline\version.py (via tools\app_version.py).
for /f "tokens=1,2" %%a in ('python tools\app_version.py') do (
  set "BUILD_VERSION=%%a"
  set "BUILD_NUMBER=%%b"
)
if not defined BUILD_VERSION set "BUILD_VERSION=0.0.0"
if not defined BUILD_NUMBER set "BUILD_NUMBER=1"
uv run flet build apk --product "Nano | نانو" --org com.nano --build-number %BUILD_NUMBER% --build-version %BUILD_VERSION%
if errorlevel 1 exit /b %errorlevel%
if not exist dist mkdir dist
for /r build %%F in (*.apk) do (
  copy /Y "%%F" "dist\nano-release.apk" >nul
  echo Nano installer: %CD%\dist\nano-release.apk
  exit /b 0
)
echo Nano APK was not produced.
exit /b 1
