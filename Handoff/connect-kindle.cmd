@echo off
setlocal
set "KINDLE_IP=%~1"
if "%KINDLE_IP%"=="" set "KINDLE_IP=192.168.1.109"
set "SSH_EXE=%WINDIR%\System32\OpenSSH\ssh.exe"
set "KEY_FILE=%~dp0keys\kindle_handoff_rsa"

if not exist "%SSH_EXE%" (
  echo Windows OpenSSH was not found at:
  echo   %SSH_EXE%
  exit /b 1
)

if not exist "%KEY_FILE%" (
  echo Kindle handoff key was not found at:
  echo   %KEY_FILE%
  exit /b 1
)

echo Connecting to KOReader SSH at %KINDLE_IP%:2222...
"%SSH_EXE%" -i "%KEY_FILE%" -o IdentitiesOnly=yes -p 2222 root@%KINDLE_IP%
exit /b %ERRORLEVEL%
