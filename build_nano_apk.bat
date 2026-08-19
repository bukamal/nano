@echo off
setlocal
uv run flet build apk --product "Nano | نانو" --org com.nano --build-number 8 --build-version 0.7.1
if errorlevel 1 exit /b %errorlevel%
if not exist dist mkdir dist
for /r build %%F in (*.apk) do (
  copy /Y "%%F" "dist\nano-release.apk" >nul
  echo Nano installer: %CD%\dist\nano-release.apk
  exit /b 0
)
echo Nano APK was not produced.
exit /b 1
