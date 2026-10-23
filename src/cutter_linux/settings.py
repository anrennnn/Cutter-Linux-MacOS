"""Preferencias del usuario (ventana «Opciones»), guardadas en ~/.config/cutter-linux/ajustes.json."""

import json
from dataclasses import asdict, dataclass, fields

from . import config

SETTINGS_FILE = config.CONFIG_DIR / "ajustes.json"


@dataclass
class Settings:
    # Recortes
    copy_to_clipboard: bool = True
    autosave: bool = True  # guardar los recortes de Super+Shift+S en la carpeta
    save_dir: str = ""  # vacío = Imágenes/Capturas de pantalla
    notify: bool = True
    open_editor_after_shortcut: bool = False
    default_mode: str = "rect"
    default_delay: int = 0
    # Historial
    history_enabled: bool = True
    history_limit: int = config.HISTORY_LIMIT
    # Aplicación
    tray_icon: bool = True
    autostart: bool = True

    def screenshots_dir(self):
        from pathlib import Path

        return Path(self.save_dir).expanduser() if self.save_dir else config.screenshots_dir()

    def save(self):
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        tmp = SETTINGS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(self), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(SETTINGS_FILE)
        _apply_autostart(self.autostart)


def load() -> Settings:
    try:
        raw = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return Settings()
    known = {f.name: f.type for f in fields(Settings)}
    values = {}
    for key, value in raw.items():
        if key in known and isinstance(value, type(getattr(Settings(), key))):
            values[key] = value
    return Settings(**values)


def _apply_autostart(enabled: bool):
    """Activa o desactiva el arranque con la sesión solo para este usuario.

    Los paquetes instalan /etc/xdg/autostart/cutter-linux.desktop; una copia con
    Hidden=true en ~/.config/autostart lo anula. La instalación por usuario
    (Bazzite y similares) usa directamente el archivo de ~/.config/autostart.
    """
    from pathlib import Path

    if config.IS_MAC:
        from . import macos

        macos.set_autostart(enabled)
        return
    user_entry = config.CONFIG_DIR.parent / "autostart" / "cutter-linux.desktop"
    system_entry = Path("/etc/xdg/autostart/cutter-linux.desktop")
    hidden = user_entry.exists() and "Hidden=true" in user_entry.read_text(encoding="utf-8", errors="ignore")
    if enabled and hidden:
        if system_entry.exists():
            user_entry.unlink()
        else:
            user_entry.write_text(_entry(hidden=False), encoding="utf-8")
    elif not enabled and not hidden:
        user_entry.parent.mkdir(parents=True, exist_ok=True)
        user_entry.write_text(_entry(hidden=True), encoding="utf-8")


def _entry(hidden: bool) -> str:
    return (
        "[Desktop Entry]\nType=Application\nName=Cutter\nIcon=cutter-linux\nNoDisplay=true\n"
        f"Exec={config.cli_command()} segundo-plano\n"
        + ("Hidden=true\n" if hidden else "")
    )


# Instancia compartida por todo el proceso.
current = load()
