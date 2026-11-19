@echo off
setlocal
cd /d "%~dp0"
echo === Simple BG Remover Installation ===
echo.

where python >nul 2>nul
if errorlevel 1 goto nopython

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo ffmpeg nicht gefunden - installiere ueber winget ...
  winget install -e --id Gyan.FFmpeg --accept-source-agreements --accept-package-agreements
)

if not exist venv python -m venv venv
venv\Scripts\python -m pip install --upgrade pip
venv\Scripts\python -m pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
venv\Scripts\python -m pip install numpy tqdm fal-client
venv\Scripts\python setup_menu.py
echo.
echo === Selbsttest ===
venv\Scripts\python worker.py --selftest
echo.
echo Fertig. DaVinci Resolve neu starten, dann: Workspace - Scripts - Hintergrund entfernen
pause
exit /b 0

:nopython
echo Python wurde nicht gefunden.
echo Bitte Python 3.12 von python.org installieren und "Add python.exe to PATH" anhaken.
pause
exit /b 1
