"""
Simple BG Remover Worker (Windows + macOS)
Stellt Personen in Videoabschnitten frei und schreibt ProRes 4444 mit Alphakanal.
Aufruf durch Resolve:  python worker.py jobs.json
Selbsttest:            python worker.py --selftest
"""
import json
import math
import os
import shutil
import subprocess
import sys
import tempfile
import time
import traceback
import urllib.request
from fractions import Fraction

os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")  # Apple Silicon
BASE = os.path.dirname(os.path.abspath(__file__))
IS_WIN = sys.platform.startswith("win")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

PRORES = ["-c:v", "prores_ks", "-profile:v", "4444", "-alpha_bits", "16",
          "-vendor", "apl0", "-pix_fmt", "yuva444p10le",
          "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709"]

# Preise laut fal.ai (USD pro 30 Frames): (Kanten verfeinert, ohne Verfeinerung)
FAL_PRICES = {
    "veed/video-background-removal": (0.0225, 0.015),
    "veed/video-background-removal/fast": (0.012, 0.008),
}


# ---------------------------------------------------------------- Hilfsfunktionen
def load_cfg():
    with open(os.path.join(BASE, "config.json"), encoding="utf-8") as f:
        return json.load(f)


def find_tool(name, cfg):
    exe = name + (".exe" if IS_WIN else "")
    cands = []
    d = cfg.get("ffmpeg_dir") or ""
    if d:
        cands.append(os.path.join(d, exe))
    w = shutil.which(name)
    if w:
        cands.append(w)
    if IS_WIN:
        la = os.environ.get("LOCALAPPDATA", "")
        cands.append(os.path.join(la, "Microsoft", "WinGet", "Links", exe))
        pk = os.path.join(la, "Microsoft", "WinGet", "Packages")
        if os.path.isdir(pk):
            for root, _dirs, files in os.walk(pk):
                if exe in files:
                    cands.append(os.path.join(root, exe))
    else:
        cands += [f"/opt/homebrew/bin/{name}", f"/usr/local/bin/{name}"]
    for c in cands:
        if c and os.path.isfile(c):
            return c
    raise RuntimeError(f"{name} nicht gefunden. Bitte ffmpeg installieren oder "
                       f"'ffmpeg_dir' in config.json auf den Ordner mit ffmpeg setzen.")


def fps_rational(fps):
    known = {23.976: "24000/1001", 29.97: "30000/1001", 47.952: "48000/1001",
             59.94: "60000/1001", 119.88: "120000/1001"}
    for k, v in known.items():
        if abs(fps - k) < 0.01:
            return v
    fr = Fraction(fps).limit_denominator(1001)
    return f"{fr.numerator}/{fr.denominator}"


def probe_size(ffprobe, src):
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height:stream_side_data=rotation:stream_tags=rotate",
         "-of", "json", src],
        capture_output=True, text=True, check=True).stdout
    info = json.loads(out)["streams"][0]
    w, h = int(info["width"]), int(info["height"])
    rot = 0
    for sd in info.get("side_data_list") or []:
        if "rotation" in sd:
            rot = int(float(sd["rotation"]))
    if not rot:
        rot = int(float((info.get("tags") or {}).get("rotate", 0)))
    if abs(rot) % 180 == 90:
        w, h = h, w
    return w, h


def frame_times(ffprobe, src):
    """Zeitstempel jedes Videoframes in Abspielreihenfolge (fuer frame-genaues Schneiden)."""
    out = subprocess.run(
        [ffprobe, "-v", "error", "-select_streams", "v:0",
         "-show_entries", "packet=pts_time", "-of", "csv=p=0", src],
        capture_output=True, text=True, check=True).stdout
    pts = []
    for line in out.split():
        v = line.split(",")[0]
        try:
            pts.append(float(v))
        except ValueError:
            pass
    st = subprocess.run(
        [ffprobe, "-v", "error", "-show_entries", "format=start_time", "-of", "csv=p=0", src],
        capture_output=True, text=True).stdout.strip()
    try:
        base = float(st)
    except ValueError:
        base = min(pts) if pts else 0.0
    pts = sorted(p for p in pts if p >= base - 1e-6)
    return pts, base


def seek_args(pts, base, k):
    """-ss so setzen, dass genau Frame k das erste ausgegebene Frame ist."""
    if k <= 0:
        return []
    half = (pts[k] - pts[k - 1]) / 2
    return ["-ss", f"{max(0.0, pts[k] - base - half):.6f}"]


def count_frames(ffprobe, path, vp9=False):
    cmd = [ffprobe, "-v", "error"]
    if vp9:
        cmd += ["-c:v", "libvpx-vp9"]
    cmd += ["-select_streams", "v:0", "-count_packets",
            "-show_entries", "stream=nb_read_packets", "-of", "csv=p=0", path]
    out = subprocess.run(cmd, capture_output=True, text=True).stdout.strip()
    try:
        return int(out.split(",")[0])
    except ValueError:
        return -1


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg-Fehler:\n" + r.stderr[-2000:])


def prepare(job, ffprobe):
    """Frame-Zeiten lesen und Bereich auf die tatsaechlich vorhandenen Frames begrenzen."""
    pts, base = frame_times(ffprobe, job["src"])
    k = int(job["start_frame"])
    if k >= len(pts):
        raise RuntimeError(f"Startframe {k} liegt hinter dem Dateiende ({len(pts)} Frames).")
    n = min(int(job["frames"]), len(pts) - k)
    return pts, base, k, n


def wait_key():
    try:
        input("\nEnter druecken zum Schliessen ...")
    except Exception:
        pass


# ---------------------------------------------------------------- Lokal (RVM)
def pick_device(torch, lc):
    if torch.cuda.is_available():
        return torch.device("cuda"), (torch.float16 if lc.get("fp16", True) else torch.float32), \
            torch.cuda.get_device_name(0)
    if getattr(torch.backends, "mps", None) and torch.backends.mps.is_available():
        return torch.device("mps"), torch.float32, "Apple Silicon (MPS)"
    print("WARNUNG: Keine GPU gefunden - laeuft auf der CPU und ist entsprechend langsam.")
    return torch.device("cpu"), torch.float32, "CPU"


def run_local(jobs, cfg, ffmpeg, ffprobe):
    import numpy as np
    import torch
    from tqdm import tqdm

    lc = cfg.get("local", {})
    dev, dtype, dev_name = pick_device(torch, lc)
    print(f"Geraet: {dev_name} | Lade Modell ({lc.get('model', 'resnet50')}) ...")
    model = torch.hub.load("PeterL1n/RobustVideoMatting", lc.get("model", "resnet50"),
                           trust_repo=True)
    model = model.eval().to(dev, dtype)

    for idx, job in enumerate(jobs, 1):
        src = job["src"]
        pts, base, k, n = prepare(job, ffprobe)
        w, h = probe_size(ffprobe, src)
        rat = fps_rational(job["fps"])
        ratio = lc.get("downsample_ratio") or min(512 / max(w, h), 1.0)
        fsize = w * h * 3
        tmp_out = job["out"][:-4] + ".part.mov"
        os.makedirs(os.path.dirname(job["out"]), exist_ok=True)

        dec = subprocess.Popen(
            [ffmpeg, "-v", "error", *seek_args(pts, base, k), "-i", src, "-an",
             "-fps_mode", "passthrough",
             "-vf", "setpts=N/TB,scale=in_color_matrix=bt709,format=rgb24",
             "-frames:v", str(n), "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
            stdout=subprocess.PIPE)
        enc = subprocess.Popen(
            [ffmpeg, "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgba64le",
             "-s", f"{w}x{h}", "-framerate", rat, "-i", "-",
             "-vf", "scale=out_color_matrix=bt709:out_range=tv", *PRORES, tmp_out],
            stdin=subprocess.PIPE)

        rec = [None] * 4
        got = 0
        with torch.inference_mode():
            for _ in tqdm(range(n), desc=f"Clip {idx}/{len(jobs)} {os.path.basename(src)}",
                          unit="frame"):
                buf = dec.stdout.read(fsize)
                if len(buf) < fsize:
                    break
                arr = np.frombuffer(buf, np.uint8).reshape(h, w, 3)
                x = torch.from_numpy(arr.copy()).to(dev).permute(2, 0, 1)
                x = x.unsqueeze(0).to(dtype).div_(255)
                fgr, pha, *rec = model(x, *rec, ratio)
                rgba = torch.cat([fgr, pha], 1)[0].clamp_(0, 1).permute(1, 2, 0)
                rgba = rgba.float().mul_(65535).round_().to(torch.int32)
                enc.stdin.write(rgba.cpu().numpy().astype(np.uint16).tobytes())
                got += 1
        dec.stdout.close()
        dec.wait()
        enc.stdin.close()
        if enc.wait() != 0 or got == 0:
            raise RuntimeError("Encoding nach ProRes 4444 fehlgeschlagen.")
        if got < n:
            print(f"  WARNUNG: nur {got} von {n} Frames gelesen - Clip wird kuerzer.")
        os.replace(tmp_out, job["out"])
        print(f"  -> {job['out']} ({got} Frames)")


# ---------------------------------------------------------------- fal.ai (VEED)
def _pick_files(files):
    if isinstance(files, dict):
        files = [files]
    names = [((f.get("file_name") or "") + " " + (f.get("url") or "")).lower() for f in files]
    alpha_i = next((i for i, nm in enumerate(names)
                    if any(t in nm for t in ("alpha", "matte", "mask"))), None)
    if alpha_i is not None and len(files) >= 2:
        rgb_i = 0 if alpha_i != 0 else 1
        return files[rgb_i]["url"], files[alpha_i]["url"]
    if len(files) >= 2:
        return files[0]["url"], files[1]["url"]
    return files[0]["url"], None


def run_fal(jobs, cfg, ffmpeg, ffprobe):
    import fal_client

    fc = cfg.get("fal", {})
    key = fc.get("api_key") or os.environ.get("FAL_KEY")
    if not key:
        raise RuntimeError("Kein fal.ai API-Key. In config.json unter fal.api_key eintragen.")
    os.environ["FAL_KEY"] = key
    model = fc.get("model", "veed/video-background-removal/fast")
    refine = bool(fc.get("refine_edges", True))

    total = sum(int(j["frames"]) for j in jobs)
    if model in FAL_PRICES:
        price = FAL_PRICES[model][0 if refine else 1]
        print(f"Modell: {model} | {total} Frames | geschaetzte Kosten ca. "
              f"${math.ceil(total / 30) * price:.2f} (Preisstand Okt. 2026, ohne Gewaehr)")
    else:
        print(f"Modell: {model} | {total} Frames | Preis siehe fal.ai")
    if fc.get("confirm_cost", True):
        input("Enter = Starten, Strg+C = Abbrechen ")

    for idx, job in enumerate(jobs, 1):
        src = job["src"]
        pts, base, k, n = prepare(job, ffprobe)
        w, h = probe_size(ffprobe, src)
        rat = fps_rational(job["fps"])
        fps = float(Fraction(rat))
        idx_pts = f"setpts=N/({rat})/TB"  # Zeitstempel nach Framenummer: 1 Frame = 1 Frame
        chunk = max(1, int(fc.get("max_chunk_seconds", 55) * fps))
        tmpdir = tempfile.mkdtemp(prefix="simple_bg_remover_")
        os.makedirs(os.path.dirname(job["out"]), exist_ok=True)
        parts, pos, part_no, got_total = [], 0, 0, 0
        try:
            while pos < n:
                cn = min(chunk, n - pos)
                seg = os.path.join(tmpdir, f"seg{part_no}.mp4")
                print(f"Clip {idx}/{len(jobs)} Teil {part_no + 1}: schneide {cn} Frames ...")
                run([ffmpeg, "-v", "error", "-y", *seek_args(pts, base, k + pos), "-i", src,
                     "-an", "-vf", idx_pts, "-fps_mode", "cfr", "-r", rat,
                     "-frames:v", str(cn), "-c:v", "libx264", "-crf", "14", "-preset", "fast",
                     "-pix_fmt", "yuv420p", seg])
                print("  lade hoch ...")
                url = fal_client.upload_file(seg)
                print("  fal.ai rechnet ...")
                res = fal_client.subscribe(model, arguments={
                    "video_url": url, "output_codec": "h264",
                    "refine_foreground_edges": refine, "subject_is_person": True})
                rgb_url, alpha_url = _pick_files(res["video"])
                part = os.path.join(tmpdir, f"part{part_no}.mov")
                print("  lade Ergebnis herunter ...")
                if alpha_url:
                    rgb_f = os.path.join(tmpdir, f"rgb{part_no}.mp4")
                    a_f = os.path.join(tmpdir, f"alpha{part_no}.mp4")
                    urllib.request.urlretrieve(rgb_url, rgb_f)
                    urllib.request.urlretrieve(alpha_url, a_f)
                    nr = count_frames(ffprobe, rgb_f)
                    na = count_frames(ffprobe, a_f)
                    if nr == cn and na == cn:  # 1:1 nach Framenummer zusammenfuegen
                        tf = f"{idx_pts},scale={w}:{h}"
                    else:                      # Fallback: nach Zeit angleichen
                        print(f"  HINWEIS: fal lieferte {nr}/{na} statt {cn} Frames - "
                              f"gleiche nach Zeit an.")
                        tf = f"fps={rat},scale={w}:{h}"
                    run([ffmpeg, "-v", "error", "-y", "-i", rgb_f, "-i", a_f, "-filter_complex",
                         f"[0:v]{tf}[c];[1:v]{tf},format=gray[a];[c][a]alphamerge[o]",
                         "-map", "[o]", "-fps_mode", "cfr", "-r", rat,
                         "-frames:v", str(cn), *PRORES, part])
                else:  # einzelne VP9-WebM mit Alpha
                    wf = os.path.join(tmpdir, f"out{part_no}.webm")
                    urllib.request.urlretrieve(rgb_url, wf)
                    nr = count_frames(ffprobe, wf, vp9=True)
                    tf = f"{idx_pts},scale={w}:{h}" if nr == cn else f"fps={rat},scale={w}:{h}"
                    if nr != cn:
                        print(f"  HINWEIS: fal lieferte {nr} statt {cn} Frames.")
                    run([ffmpeg, "-v", "error", "-y", "-c:v", "libvpx-vp9", "-i", wf,
                         "-vf", tf, "-fps_mode", "cfr", "-r", rat,
                         "-frames:v", str(cn), *PRORES, part])
                pc = count_frames(ffprobe, part)
                if 0 <= pc < cn:
                    print(f"  WARNUNG: Teil hat nur {pc} von {cn} Frames.")
                got_total += max(pc, 0)
                parts.append(part)
                pos += cn
                part_no += 1

            tmp_out = job["out"][:-4] + ".part.mov"
            if len(parts) == 1:
                shutil.move(parts[0], tmp_out)
            else:
                lst = os.path.join(tmpdir, "list.txt")
                with open(lst, "w", encoding="utf-8") as f:
                    for p in parts:
                        f.write(f"file '{p.replace(os.sep, '/')}'\n")
                run([ffmpeg, "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                     "-c", "copy", tmp_out])
            os.replace(tmp_out, job["out"])
            print(f"  -> {job['out']} ({got_total} Frames)")
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------- Start
def selftest():
    cfg = load_cfg()
    print("ffmpeg :", find_tool("ffmpeg", cfg))
    print("ffprobe:", find_tool("ffprobe", cfg))
    import torch
    _dev, _dt, name = pick_device(torch, cfg.get("local", {}))
    print("PyTorch:", torch.__version__, "| Geraet:", name)
    print("Lade Modell einmalig herunter ...")
    torch.hub.load("PeterL1n/RobustVideoMatting", cfg.get("local", {}).get("model", "resnet50"),
                   trust_repo=True)
    print("\nSelbsttest OK.")


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "--selftest":
        try:
            selftest()
        except Exception:
            traceback.print_exc()
        return
    with open(sys.argv[1], encoding="utf-8") as f:
        data = json.load(f)
    cfg = load_cfg()
    t0 = time.time()
    try:
        ffmpeg, ffprobe = find_tool("ffmpeg", cfg), find_tool("ffprobe", cfg)
        if data["mode"] == "fal":
            run_fal(data["jobs"], cfg, ffmpeg, ffprobe)
        else:
            run_local(data["jobs"], cfg, ffmpeg, ffprobe)
    except KeyboardInterrupt:
        print("\nAbgebrochen.")
        sys.exit(2)
    except Exception:
        traceback.print_exc()
        with open(os.path.join(BASE, "last_error.log"), "w", encoding="utf-8") as f:
            f.write(traceback.format_exc())
        wait_key()
        sys.exit(1)
    print(f"\nFertig in {time.time() - t0:.0f} s. Fenster schliesst sich ...")
    time.sleep(2)


if __name__ == "__main__":
    main()
