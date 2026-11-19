#!/bin/bash
cd "$(dirname "$0")"
echo "=== Simple BG Remover Installation (macOS) ==="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3 fehlt. Bitte Python 3.12 von python.org installieren und erneut starten."
  read -p "Enter zum Beenden"; exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1 && [ ! -x /opt/homebrew/bin/ffmpeg ] && [ ! -x /usr/local/bin/ffmpeg ]; then
  if command -v brew >/dev/null 2>&1; then
    echo "Installiere ffmpeg ueber Homebrew ..."
    brew install ffmpeg
  else
    echo "ffmpeg fehlt. Bitte Homebrew installieren (https://brew.sh) und dann: brew install ffmpeg"
    read -p "Enter zum Beenden"; exit 1
  fi
fi

[ -d venv ] || python3 -m venv venv
venv/bin/python -m pip install --upgrade pip
venv/bin/python -m pip install torch torchvision numpy tqdm fal-client
venv/bin/python setup_menu.py
echo
echo "=== Selbsttest ==="
venv/bin/python worker.py --selftest
echo
echo "Fertig. DaVinci Resolve neu starten, dann: Workspace > Scripts > Hintergrund entfernen"
read -p "Enter zum Beenden"
