@echo off
rem KeywordPlanner launcher (ASCII only on purpose: Korean text in .bat files can break cmd.exe parsing)
cd /d "%~dp0"
title KeywordPlanner
if not exist "%~dp0app.py" goto notextracted
if not exist "%~dp0static\index.html" goto notextracted

echo.
echo  [1/3] Closing any older KeywordPlanner that is still running...
powershell -NoProfile -ExecutionPolicy Bypass -Command "Get-NetTCPConnection -State Listen -LocalPort 8765,8766,8767,8768,8769,8770,8771,8772,8773,8774 -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }" >nul 2>&1
timeout /t 1 /nobreak >nul

echo  [2/3] Looking for Python...
set "PY="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PY=py -3"
if defined PY goto run
python --version >nul 2>&1
if not errorlevel 1 set "PY=python"
if defined PY goto run
if exist "%LOCALAPPDATA%\Programs\Python\Python313\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python313\python.exe"
if defined PY goto run
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto run
if exist "%LOCALAPPDATA%\Programs\Python\Python311\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python311\python.exe"
if defined PY goto run

echo.
echo  Python is not installed. Installing Python 3.12 now (1-3 minutes)...
echo.
winget install -e --id Python.Python.3.12 --scope user --accept-package-agreements --accept-source-agreements
if exist "%LOCALAPPDATA%\Programs\Python\Python312\python.exe" set PY="%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if defined PY goto run
echo.
echo  [!] Could not install Python automatically.
echo      Install Python from https://www.python.org and check "Add python.exe to PATH",
echo      then run this file again.
echo.
pause
exit /b

:run
%PY% -c "import anthropic" >nul 2>&1
if errorlevel 1 (
  echo  Installing the Claude connector for AI drafts - first time only...
  %PY% -m pip install --user --quiet --disable-pip-version-check anthropic
)
echo  [3/3] Starting KeywordPlanner from: %~dp0
echo.
%PY% app.py %*
echo.
echo  KeywordPlanner stopped. If you see an error above, please send a screenshot of this window.
pause
exit /b

:notextracted
echo.
echo  [!] Please extract the zip first.
echo      Right-click the zip file, choose "Extract All", then run START_windows.bat
echo      inside the extracted folder.
echo.
pause
exit /b
