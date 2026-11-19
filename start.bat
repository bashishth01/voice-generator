@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title Voice Generator launcher
set "PATH=%PATH%;%LocalAppData%\Microsoft\WinGet\Links;%~dp0bin"

REM ---------- 1. find Python ----------
set "PY="
call :findpy
if defined PY goto havepy

echo.
echo  Python is required to run Voice Generator, but it was not found on this PC.
choice /c YN /m "Do you want to install Python now"
if errorlevel 2 goto nopython

where winget >nul 2>nul
if errorlevel 1 (
  echo.
  echo  ERROR: winget is not available, so Python cannot be installed automatically.
  echo  Please install Python from https://www.python.org/downloads/ and run this file again.
  pause
  exit /b 1
)
echo.
echo  Installing Python 3.12 ... this can take a few minutes.
winget install -e --id Python.Python.3.12 --silent --accept-package-agreements --accept-source-agreements
call :findpy
if not defined PY (
  echo.
  echo  Python was installed, but this window cannot see it yet.
  echo  Please close this window and double-click start.bat again.
  pause
  exit /b 0
)
goto havepy

:nopython
echo.
echo  ERROR: Python is required to run Voice Generator. Install it from https://www.python.org/downloads/
echo  and run this file again.
pause
exit /b 1

REM ---------- 2. private environment + edge-tts ----------
:havepy
if not exist ".venv\Scripts\python.exe" (
  echo  Setting up Voice Generator for the first time ...
  %PY% -m venv .venv
  if errorlevel 1 (
    echo  ERROR: could not create the Python environment.
    pause
    exit /b 1
  )
)
".venv\Scripts\python.exe" -c "import edge_tts" >nul 2>nul
if errorlevel 1 (
  echo  Installing edge-tts ...
  ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip edge-tts
  if errorlevel 1 (
    echo  ERROR: could not install edge-tts. Check your internet connection.
    pause
    exit /b 1
  )
)

REM ---------- 3. ffmpeg (needed for pauses and joining lines) ----------
where ffmpeg >nul 2>nul
if not errorlevel 1 goto run
echo.
echo  ffmpeg was not found. It is needed for pauses ^(break^) and joining conversation lines.
choice /c YN /m "Do you want to install ffmpeg now"
if errorlevel 2 (
  echo  Skipping ffmpeg. The app will run, but pauses will be skipped.
  goto run
)
where winget >nul 2>nul
if errorlevel 1 (
  echo  winget is not available. Download ffmpeg from https://www.gyan.dev/ffmpeg/builds/ and put ffmpeg.exe in the "bin" folder here.
  goto run
)
winget install -e --id Gyan.FFmpeg --silent --accept-package-agreements --accept-source-agreements
where ffmpeg >nul 2>nul
if errorlevel 1 echo  ffmpeg installed. If pauses do not work, close this window and run start.bat again.

REM ---------- 4. start ----------
:run
echo.
echo  Starting Voice Generator ... keep this window open while you use it. Close it to stop.
".venv\Scripts\python.exe" server.py
pause
exit /b 0

:findpy
where py >nul 2>nul && (py -3 --version >nul 2>nul && set "PY=py -3" && exit /b 0)
for %%P in (python.exe) do if not "%%~$PATH:P"=="" (
  "%%~$PATH:P" -c "import sys" >nul 2>nul && set "PY="%%~$PATH:P"" && exit /b 0
)
for /d %%D in ("%LocalAppData%\Programs\Python\Python3*") do (
  if exist "%%D\python.exe" set "PY="%%D\python.exe"" && exit /b 0
)
exit /b 1
