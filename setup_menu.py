"""Legt die zwei Menue-Eintraege in DaVinci Resolve an (Workspace > Scripts)."""
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__))
if sys.platform.startswith("win"):
    TARGET = os.path.join(os.environ["APPDATA"], "Blackmagic Design", "DaVinci Resolve",
                          "Support", "Fusion", "Scripts", "Edit")
else:
    TARGET = os.path.expanduser("~/Library/Application Support/Blackmagic Design/"
                                "DaVinci Resolve/Fusion/Scripts/Edit")

TEMPLATE = '''# Hintergrund entfernen ({label}) - erzeugt von Simple BG Remover
import sys, importlib
sys.path.insert(0, r"{base}")
import resolve_bridge
importlib.reload(resolve_bridge)
try:
    _r = resolve
except NameError:
    try:
        _r = bmd.scriptapp("Resolve")
    except NameError:
        import DaVinciResolveScript as _dvr
        _r = _dvr.scriptapp("Resolve")
resolve_bridge.run(_r, "{mode}")
'''

os.makedirs(TARGET, exist_ok=True)
for label, mode in (("lokal", "local"), ("fal.ai", "fal")):
    p = os.path.join(TARGET, f"Hintergrund entfernen ({label}).py")
    with open(p, "w", encoding="utf-8") as f:
        f.write(TEMPLATE.format(label=label, base=BASE, mode=mode))
    print("Angelegt:", p)
