"""Rutas y ajustes compartidos."""

import os
from pathlib import Path

APP_ID = "cutter-linux"
APP_NAME = "Cutter"
VERSION = "0.1.0"

# Igual que Windows: el historial guarda como máximo 25 elementos (los fijados no cuentan).
HISTORY_LIMIT = 25


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / APP_ID
CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / APP_ID
HISTORY_DIR = DATA_DIR / "historial"
HISTORY_FILE = HISTORY_DIR / "historial.json"
SHORTCUTS_MARKER = CONFIG_DIR / "atajos-configurados"


def screenshots_dir() -> Path:
    """Carpeta donde se guardan los recortes automáticamente (como Imágenes/Capturas de pantalla en Windows)."""
    pictures = None
    try:
        import subprocess

        out = subprocess.run(
            ["xdg-user-dir", "PICTURES"], capture_output=True, text=True, timeout=2
        ).stdout.strip()
        if out and out != str(Path.home()):
            pictures = Path(out)
    except (OSError, subprocess.SubprocessError):
        pass
    if pictures is None:
        pictures = Path.home() / "Imágenes"
        if not pictures.exists() and (Path.home() / "Pictures").exists():
            pictures = Path.home() / "Pictures"
    return pictures / "Capturas de pantalla"


def session_type() -> str:
    """'wayland' o 'x11'."""
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    return "x11"


def desktop() -> str:
    """Escritorio normalizado: kde, gnome, cinnamon, xfce u otro."""
    raw = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").lower()
    for name in ("kde", "cinnamon", "xfce", "gnome", "mate", "cosmic"):
        if name in raw:
            return name
    # Pop!_OS, Zorin y Ubuntu usan variantes de GNOME ("pop:GNOME", "zorin:GNOME", "ubuntu:GNOME").
    if "unity" in raw or "budgie" in raw:
        return "gnome"
    return raw or "desconocido"
