"""
Simple BG Remover - Bruecke zu DaVinci Resolve (Windows + macOS, nur Standardbibliothek).
Ablauf: Clips sammeln -> Worker starten -> Ergebnis importieren -> ueber Original legen.
"""
import json
import os
import re
import subprocess
import sys
import time

BASE = os.path.dirname(os.path.abspath(__file__))
TITLE = "Hintergrund entfernen"
IS_WIN = sys.platform.startswith("win")
VERSION_TAG = "v5"  # neue Dateinamen, damit alte (fehlerhafte) Ergebnisse nicht wiederverwendet werden


def msg(text):
    print(text)
    try:
        if IS_WIN:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, text, TITLE, 0x40)
        else:
            subprocess.run(["osascript", "-e", "on run argv",
                            "-e", f'display dialog (item 1 of argv) buttons {{"OK"}} '
                                  f'default button 1 with title "{TITLE}"',
                            "-e", "end run", text], capture_output=True)
    except Exception:
        pass


def load_cfg():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def parse_num(v):
    m = re.search(r"[\d.]+", str(v or ""))
    return float(m.group()) if m else 0.0


def venv_python():
    return os.path.join(BASE, "venv", "Scripts", "python.exe") if IS_WIN \
        else os.path.join(BASE, "venv", "bin", "python")


def collect_items(tl, color):
    found = []
    n = tl.GetTrackCount("video")
    # 1) In der Timeline markierte Clips (ab Resolve 21.0.4: Timeline.GetSelectedClips).
    #    Liefert auch verknuepfte Audio-Items mit; ueber die Videospuren wird gefiltert.
    try:
        sel = tl.GetSelectedClips() or []
        if isinstance(sel, dict):
            sel = list(sel.values())
        uids = {it.GetUniqueId() for it in sel}
    except Exception:
        uids = set()
    if uids:
        for t in range(1, n + 1):
            for it in tl.GetItemListInTrack("video", t) or []:
                if it.GetUniqueId() in uids:
                    found.append((t, it))
        if found:
            return found
    # 2) Clips mit der Markierungsfarbe (Fallback fuer aeltere Resolve-Versionen)
    for t in range(1, n + 1):
        for it in tl.GetItemListInTrack("video", t) or []:
            if it.GetClipColor() == color:
                found.append((t, it))
    if found:
        return found
    # 3) Clip unter dem Playhead
    cur = tl.GetCurrentVideoItem()
    if cur:
        uid = cur.GetUniqueId()
        for t in range(1, n + 1):
            for it in tl.GetItemListInTrack("video", t) or []:
                if it.GetUniqueId() == uid:
                    return [(t, it)]
    return []


def free_track_above(tl, base, a, b):
    n = tl.GetTrackCount("video")
    for t in range(base + 1, n + 1):
        if all(not (it.GetStart() < b and it.GetEnd() > a)
               for it in tl.GetItemListInTrack("video", t) or []):
            return t
    tl.AddTrack("video")
    return tl.GetTrackCount("video")


def get_bin(mp, name):
    root = mp.GetRootFolder()
    for f in root.GetSubFolderList() or []:
        if f.GetName() == name:
            return f
    return mp.AddSubFolder(root, name)


def import_clip(mp, folder, path):
    cur = mp.GetCurrentFolder()
    mp.SetCurrentFolder(folder)
    clips = mp.ImportMedia([path]) or []
    mp.SetCurrentFolder(cur)
    if clips:
        return clips[0]
    for c in folder.GetClipList() or []:  # schon importiert
        if os.path.normcase(c.GetClipProperty("File Path") or "") == os.path.normcase(path):
            return c
    return None


def run_worker(mode, jobs):
    os.makedirs(os.path.join(BASE, "tmp"), exist_ok=True)
    jf = os.path.join(BASE, "tmp", "jobs.json")
    with open(jf, "w", encoding="utf-8") as f:
        json.dump({"mode": mode, "jobs": jobs}, f, indent=1)
    py, wk = venv_python(), os.path.join(BASE, "worker.py")
    print(f"[Simple BG Remover] Starte Worker fuer {len(jobs)} Clip(s) ...")
    if IS_WIN:
        subprocess.Popen([py, wk, jf],
                         creationflags=getattr(subprocess, "CREATE_NEW_CONSOLE", 0)).wait()
        return
    # macOS: im Terminal starten (Fortschritt sichtbar) und auf Ende warten
    done = os.path.join(BASE, "tmp", "done.txt")
    pidf = os.path.join(BASE, "tmp", "pid.txt")
    for p in (done, pidf):
        if os.path.exists(p):
            os.remove(p)
    sh = os.path.join(BASE, "tmp", "run.command")
    with open(sh, "w", encoding="utf-8") as f:
        f.write("#!/bin/bash\n"
                f"echo $$ > '{pidf}'\n"
                f"cd '{BASE}'\n"
                f"'{py}' '{wk}' '{jf}'\n"
                f"echo $? > '{done}'\n")
    os.chmod(sh, 0o755)
    subprocess.run(["open", "-a", "Terminal", sh])
    t0 = time.time()
    while not os.path.exists(done):
        time.sleep(1)
        if os.path.exists(pidf):
            try:
                os.kill(int(open(pidf).read().strip()), 0)
            except (OSError, ValueError):
                if not os.path.exists(done):
                    break  # Terminal-Fenster wurde geschlossen
        elif time.time() - t0 > 60:
            break  # Terminal hat nicht gestartet


def run(resolve, mode):
    cfg = load_cfg()
    project = resolve.GetProjectManager().GetCurrentProject()
    tl = project.GetCurrentTimeline() if project else None
    if not tl:
        msg("Keine Timeline geoeffnet.")
        return
    tl_fps = 0.0
    try:
        tl_fps = parse_num(tl.GetSetting("timelineFrameRate"))  # jede Timeline kann eigene fps haben
    except Exception:
        pass
    if not tl_fps:
        tl_fps = parse_num(project.GetSetting("timelineFrameRate"))
    targets = collect_items(tl, cfg["mark_color"])
    if not targets:
        msg(f"Kein Clip gefunden.\n\nClips in der Timeline markieren, den Playhead auf einen "
            f"Clip stellen oder Clips mit der Clipfarbe '{cfg['mark_color']}' einfaerben.")
        return

    warnings, entries, jobs = [], [], []
    h = int(cfg.get("handles_frames", 0))
    for track, item in targets:
        name = item.GetName()
        mpi = item.GetMediaPoolItem()
        path = mpi.GetClipProperty("File Path") if mpi else ""
        if not path or not os.path.isfile(path):
            warnings.append(f"'{name}': keine Videodatei (Compound/Generator?) - uebersprungen.")
            continue
        fps = parse_num(mpi.GetClipProperty("FPS"))
        dur = int(item.GetDuration())  # Laenge in TIMELINE-Frames
        # Wie viele QUELL-Frames entsprechen dieser Laenge? Bei abweichender Framerate
        # (z. B. 25-fps-Clip in 30-fps-Timeline) ist das NICHT dieselbe Zahl.
        ratio = (fps / tl_fps) if (fps and tl_fps) else 1.0
        expected = max(1, int(round(dur * ratio)))
        try:
            s = int(round(item.GetSourceStartFrame()))
            api_len = int(round(item.GetSourceEndFrame())) - s
        except Exception:
            s, api_len = int(round(item.GetLeftOffset() * ratio)), 0
        # GetSourceEndFrame ist je nach Clip inklusiv oder exklusiv -> Abweichung um 1 Frame
        # ignorieren und die aus der Timeline-Laenge berechnete Zahl nehmen.
        if api_len > 0 and abs(api_len - expected) > 1:
            src_len = api_len
            warnings.append(f"'{name}': Geschwindigkeitsaenderung erkannt - wird nicht "
                            f"uebernommen, bitte Sync pruefen.")
        else:
            src_len = expected
        s0 = max(0, s - h)
        tail = 3 + src_len // 30  # Reserve fuer die Laengenkorrektur; Worker begrenzt aufs Dateiende
        e0 = s + src_len + h + tail
        stem = os.path.splitext(os.path.basename(path))[0]
        out = os.path.join(os.path.dirname(path), cfg["output_subfolder"],
                           f"{stem}_BG_{s0}-{e0}_{mode}_{VERSION_TAG}.mov")
        entries.append(dict(item=item, track=track, out=out, offset=s - s0, dur=dur,
                            src_len=src_len))
        if not (cfg.get("reuse_existing", True) and os.path.isfile(out)):
            if not any(j["out"] == out for j in jobs):
                jobs.append(dict(src=path, start_frame=s0, frames=e0 - s0, fps=fps, out=out))

    if jobs:
        if not os.path.isfile(venv_python()):
            msg("venv nicht gefunden. Bitte zuerst das Installationsskript ausfuehren.")
            return
        run_worker(mode, jobs)

    mp = project.GetMediaPool()
    folder = get_bin(mp, cfg.get("media_pool_bin", "BG entfernt"))
    done = 0
    for e in entries:
        nm = e["item"].GetName()
        if not os.path.isfile(e["out"]):
            warnings.append(f"'{nm}': kein Ergebnis (Abbruch oder Fehler, siehe last_error.log).")
            continue
        clip = import_clip(mp, folder, e["out"])
        if not clip:
            warnings.append(f"Import fehlgeschlagen: {e['out']}")
            continue
        try:
            clip.SetClipProperty("Alpha mode", "Straight")
        except Exception:
            pass
        a, b = e["item"].GetStart(), e["item"].GetEnd()
        t = free_track_above(tl, e["track"], a, b)
        # Platzieren und pruefen; weicht die Laenge ab, wieder entfernen und korrigiert neu setzen.
        n, placed, got = e["src_len"], None, -1
        for attempt in range(4):
            placed = mp.AppendToTimeline([{
                "mediaPoolItem": clip, "startFrame": e["offset"],
                "endFrame": e["offset"] + n,
                "trackIndex": t, "recordFrame": a, "mediaType": 1}])
            if not placed:
                break
            try:
                got = int(placed[0].GetDuration())
            except Exception:
                break
            if got == e["dur"] or attempt == 3:
                break
            tl.DeleteClips([placed[0]], False)
            step = int(round((e["dur"] - got) * (n / got if got else 1.0)))
            if step == 0:
                step = 1 if e["dur"] > got else -1
            n = max(1, n + step)
        if not placed:
            warnings.append(f"'{nm}': konnte freigestellten Clip nicht platzieren.")
            continue
        if got != e["dur"]:
            warnings.append(f"'{nm}': freigestellter Clip ist {got} statt {e['dur']} "
                            f"Frames lang - bitte pruefen.")
        if cfg.get("disable_original", True):
            try:
                e["item"].SetClipEnabled(False)
            except Exception:
                pass
        try:
            e["item"].SetClipColor(cfg.get("done_color", "Teal"))
        except Exception:
            pass
        done += 1

    text = f"{done} von {len(entries)} Clip(s) freigestellt."
    if warnings:
        text += "\n\nHinweise:\n- " + "\n- ".join(warnings)
    msg(text)
