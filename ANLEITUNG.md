# Simple BG Remover – Hintergrund entfernen in DaVinci Resolve Studio (Windows + Mac)

## Installation (einmalig)
1. Python 3.12 von python.org installieren (Windows: „Add python.exe to PATH“ anhaken).
2. In DaVinci Resolve: Preferences → System → General → External scripting using: **Local**.
3. Den Ordner `simple-bg-rm-davinci-resolve` an einen festen Ort legen und später nicht mehr verschieben.
   Windows z. B. `C:\simple-bg-rm-davinci-resolve`, Mac z. B. im Benutzerordner `~/simple-bg-rm-davinci-resolve`.
4. Installationsskript starten:
   - **Windows:** `install_windows.bat` doppelklicken.
   - **Mac:** Terminal öffnen, `bash ` eintippen (mit Leerzeichen), `install_mac.command` ins Fenster ziehen, Enter.
     ffmpeg wird über Homebrew installiert (https://brew.sh).
5. Für fal.ai: API-Key in `config.json` bei `"api_key"` eintragen.
6. Resolve neu starten.

## Benutzung
- Clips in der Timeline markieren → Workspace → Scripts → *Hintergrund entfernen (lokal)* oder *(fal.ai)*.
  Jeder Clip wird einzeln freigestellt, alles in einem Durchgang (ab Resolve 21.0.4).
- Ist nichts markiert, wird der Clip unter dem Playhead genommen.
- Ältere Resolve-Version: Clips mit Clipfarbe **Orange** einfärben, dann Skript starten.
- Ergebnis: ProRes 4444 mit Alpha, framegenau auf der freien Spur darüber. Original wird deaktiviert und türkis markiert.
- Dateien landen im Unterordner `_BG_entfernt` neben dem Originalmaterial.

## Rechner
- Windows mit NVIDIA: läuft über CUDA (schnell).
- Mac mit Apple Silicon (M1–M4): läuft über die Apple-GPU (MPS). Ist es zu langsam, in `config.json` `"model": "mobilenetv3"` setzen.
- Intel-Mac oder Windows ohne NVIDIA: läuft auf der CPU, also langsam – hier besser fal.ai verwenden.

## Einstellungen (config.json)
- `handles_frames`: Puffer vor/nach dem Schnitt (Standard 0 = exakt die Clip-Länge).
- `local.model`: `resnet50` (Qualität) oder `mobilenetv3` (schneller).
- `local.fp16`: nur NVIDIA; bei Bildfehlern auf `false` setzen.
- `fal.model`: `veed/video-background-removal/fast` oder `veed/video-background-removal`.
- `fal.confirm_cost`: zeigt vor dem Upload die geschätzten Kosten.

## Bekannte Grenzen
- iPhone-HDR (HLG/Dolby Vision): vorher als SDR aufnehmen/umwandeln, sonst stimmen die Farben nicht.
- Clips mit Geschwindigkeitsänderung oder abweichender Framerate: Sync prüfen (das Skript warnt).
- Weicht die Länge des freigestellten Clips ab, meldet das Skript es am Ende.
- Speicherbedarf: ProRes 4444 in 1080×1920 ca. 2–3 GB pro Minute.
- Fehlerprotokoll: `last_error.log` im Projektordner.
