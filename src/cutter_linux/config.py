"""Rutas y ajustes compartidos."""

import os
import sys
from pathlib import Path

APP_ID = "cutter-linux"
APP_NAME = "Cutter"
VERSION = "0.4.0"

IS_MAC = sys.platform == "darwin"

# Cómo se muestran los atajos. En Mac, Cmd+Shift+S es «Guardar como» y Cmd+V es
# pegar, así que se usa Control.
SNIP_KEYS = "Ctrl+Shift+S" if IS_MAC else "Super+Shift+S"
HISTORY_KEYS = "Ctrl+Shift+V" if IS_MAC else "Super+V"

# Igual que Windows: el historial guarda como máximo 25 elementos (los fijados no cuentan).
HISTORY_LIMIT = 25


def _xdg(var: str, fallback: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / fallback


if IS_MAC:
    DATA_DIR = CONFIG_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
else:
    DATA_DIR = _xdg("XDG_DATA_HOME", ".local/share") / APP_ID
    CONFIG_DIR = _xdg("XDG_CONFIG_HOME", ".config") / APP_ID
HISTORY_DIR = DATA_DIR / "historial"
HISTORY_FILE = HISTORY_DIR / "historial.json"
SHORTCUTS_MARKER = CONFIG_DIR / "atajos-configurados"


def screenshots_dir() -> Path:
    """Carpeta donde se guardan los recortes automáticamente (como Imágenes/Capturas de pantalla en Windows)."""
    if IS_MAC:
        return Path.home() / "Pictures" / "Capturas de pantalla"
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


def cli_command() -> str:
    """Ruta del comando para atajos y autoarranque.

    Con los paquetes basta «cutter-linux»; en la instalación por usuario
    (~/.local/bin) se usa la ruta completa, porque los atajos del escritorio
    no siempre tienen ~/.local/bin en el PATH.
    """
    import shutil

    if IS_MAC:
        # Dentro de Cutter.app el ejecutable es el propio bundle.
        return sys.executable if getattr(sys, "frozen", False) else "cutter-linux"
    found = shutil.which("cutter-linux")
    if found and not found.startswith(("/usr/bin/", "/bin/")):
        return found
    return "cutter-linux"


def session_type() -> str:
    """'wayland', 'x11' o 'macos'."""
    if IS_MAC:
        return "macos"
    if os.environ.get("WAYLAND_DISPLAY") or os.environ.get("XDG_SESSION_TYPE") == "wayland":
        return "wayland"
    return "x11"


def desktop() -> str:
    """Escritorio normalizado: kde, gnome, cinnamon, xfce, macos u otro."""
    if IS_MAC:
        return "macos"
    raw = (os.environ.get("XDG_CURRENT_DESKTOP") or os.environ.get("DESKTOP_SESSION") or "").lower()
    for name in ("kde", "cinnamon", "xfce", "gnome", "mate", "cosmic", "hyprland", "sway", "niri", "wayfire"):
        if name in raw:
            return name
    # Pop!_OS, Zorin y Ubuntu usan variantes de GNOME ("pop:GNOME", "zorin:GNOME", "ubuntu:GNOME").
    if "unity" in raw or "budgie" in raw:
        return "gnome"
    return raw or "desconocido"
