"""Lista de ventanas visibles en X11 para el modo «Recorte de ventana».

En Wayland las aplicaciones no pueden conocer la posición de otras ventanas, así
que el modo ventana solo se ofrece en sesiones X11 (Cinnamon, XFCE, GNOME/KDE en X11).
"""

import re
import shutil
import subprocess

from PyQt6.QtCore import QRect


def list_windows() -> list[QRect]:
    """Rectángulos de las ventanas visibles, de la más alta a la más baja en el apilado."""
    if not (shutil.which("xprop") and shutil.which("xwininfo")):
        return []
    try:
        out = subprocess.run(
            ["xprop", "-root", "_NET_CLIENT_LIST_STACKING"],
            capture_output=True, text=True, timeout=2,
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    ids = re.findall(r"0x[0-9a-fA-F]+", out)
    rects = []
    for wid in reversed(ids):
        rect = _window_rect(wid)
        if rect is not None and rect.width() > 1 and rect.height() > 1:
            rects.append(rect)
    return rects


def _window_rect(wid: str) -> QRect | None:
    try:
        info = subprocess.run(
            ["xwininfo", "-id", wid], capture_output=True, text=True, timeout=2
        ).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    if "IsViewable" not in info:
        return None
    values = {}
    for key, label in (
        ("x", "Absolute upper-left X"),
        ("y", "Absolute upper-left Y"),
        ("w", "Width"),
        ("h", "Height"),
    ):
        m = re.search(rf"{label}:\s+(-?\d+)", info)
        if not m:
            return None
        values[key] = int(m.group(1))
    return QRect(values["x"], values["y"], values["w"], values["h"])
