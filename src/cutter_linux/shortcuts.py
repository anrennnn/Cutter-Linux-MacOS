"""Registra Super+Shift+S y Super+V en el escritorio del usuario.

Cada escritorio guarda sus atajos en un sitio distinto, así que no hay una única
forma de hacerlo. Se ejecuta una vez por usuario (al primer arranque) y se puede
repetir con `cutter-linux atajos`.
"""

import ast
import shutil
import subprocess

from . import config

SNIP_CMD = "cutter-linux recortar"
HISTORY_CMD = "cutter-linux historial"


def _run(*cmd) -> str:
    try:
        return subprocess.run(cmd, capture_output=True, text=True, timeout=5, check=True).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def _gsettings_list(schema: str, key: str) -> list[str]:
    raw = _run("gsettings", "get", schema, key)
    raw = raw.removeprefix("@as ")
    try:
        value = ast.literal_eval(raw) if raw else []
    except (ValueError, SyntaxError):
        value = []
    return list(value)


def _gsettings_set(schema: str, key: str, value):
    if isinstance(value, list):
        value = "[" + ", ".join(repr(v) for v in value) + "]"
    _run("gsettings", "set", schema, key, value)


# --- GNOME (Ubuntu, Pop!_OS, Zorin) -----------------------------------------------

GNOME_KEYS = "org.gnome.settings-daemon.plugins.media-keys"
GNOME_BASE = "/org/gnome/settings-daemon/plugins/media-keys/custom-keybindings/"


def _setup_gnome() -> list[str]:
    notes = []
    paths = _gsettings_list(GNOME_KEYS, "custom-keybindings")
    for slug, name, command, binding in (
        ("cutter-linux-snip", "Cutter: recortar pantalla", SNIP_CMD, "<Super><Shift>s"),
        ("cutter-linux-history", "Cutter: historial del portapapeles", HISTORY_CMD, "<Super>v"),
    ):
        path = f"{GNOME_BASE}{slug}/"
        if path not in paths:
            paths.append(path)
        schema = f"{GNOME_KEYS}.custom-keybinding:{path}"
        _gsettings_set(schema, "name", name)
        _gsettings_set(schema, "command", command)
        _gsettings_set(schema, "binding", binding)
    _gsettings_set(GNOME_KEYS, "custom-keybindings", paths)

    # GNOME usa Super+V para abrir las notificaciones; se deja solo Super+M.
    tray = _gsettings_list("org.gnome.shell.keybindings", "toggle-message-tray")
    if any(b.lower() == "<super>v" for b in tray):
        _gsettings_set(
            "org.gnome.shell.keybindings", "toggle-message-tray",
            [b for b in tray if b.lower() != "<super>v"] or ["<Super>m"],
        )
        notes.append("Las notificaciones de GNOME ahora se abren con Super+M.")
    return notes


# --- Cinnamon (Linux Mint) --------------------------------------------------------

CINNAMON_KEYS = "org.cinnamon.desktop.keybindings"
CINNAMON_BASE = "/org/cinnamon/desktop/keybindings/custom-keybindings/"


def _setup_cinnamon() -> list[str]:
    names = _gsettings_list(CINNAMON_KEYS, "custom-list")
    for slug, name, command, binding in (
        ("custom-cutter-snip", "Cutter: recortar pantalla", SNIP_CMD, "<Super><Shift>s"),
        ("custom-cutter-history", "Cutter: historial del portapapeles", HISTORY_CMD, "<Super>v"),
    ):
        if slug not in names:
            names.append(slug)
        schema = f"{CINNAMON_KEYS}.custom-keybinding:{CINNAMON_BASE}{slug}/"
        _gsettings_set(schema, "name", name)
        _gsettings_set(schema, "command", command)
        _gsettings_set(schema, "binding", [binding])
    _gsettings_set(CINNAMON_KEYS, "custom-list", names)
    return []


# --- XFCE (Xubuntu, MX Linux, Mint XFCE) ------------------------------------------


def _setup_xfce() -> list[str]:
    for binding, command in (("<Super><Shift>s", SNIP_CMD), ("<Super>v", HISTORY_CMD)):
        _run(
            "xfconf-query", "-c", "xfce4-keyboard-shortcuts",
            "-p", f"/commands/custom/{binding}", "-n", "-t", "string", "-s", command,
        )
    return []


# --- KDE Plasma (Kubuntu, KDE neon) -----------------------------------------------


# Códigos de tecla de Qt, tal como los espera kglobalaccel.
_META, _SHIFT = 0x10000000, 0x02000000
_KEY_S, _KEY_V, _KEY_PRINT = 0x53, 0x56, 0x01000009

# (componente, acción, teclas nuevas). Los atajos de Cutter vienen de las líneas
# X-KDE-Shortcuts de cutter-linux.desktop; antes hay que quitárselos a quien los use.
KDE_CHANGES = [
    # Spectacle (Plasma 6) abre su recorte con Print y Meta+Shift+S: se le deja solo Print.
    ("org.kde.spectacle.desktop", "_launch", [_KEY_PRINT]),
    # Klipper muestra su menú con Meta+V (en Plasma 6 vive dentro de plasmashell).
    ("plasmashell", "show-on-mouse-pos", []),
    ("klipper", "show-on-mouse-pos", []),
    ("cutter-linux.desktop", "_launch", [_META | _SHIFT | _KEY_S]),
    ("cutter-linux.desktop", "historial", [_META | _KEY_V]),
]


def _kglobalaccel_set(component: str, action: str, keys: list[int]) -> bool:
    """Cambia un atajo en caliente por D-Bus; kglobalaccel lo guarda por su cuenta."""
    if not shutil.which("gdbus"):
        return False
    sequences = ", ".join(f"([{k}, 0, 0, 0],)" for k in keys)
    try:
        subprocess.run(
            [
                "gdbus", "call", "--session", "--dest", "org.kde.kglobalaccel",
                "--object-path", "/kglobalaccel",
                "--method", "org.kde.KGlobalAccel.setForeignShortcutKeys",
                f"['{component}', '{action}', '', '']",
                f"@a(ai) [{sequences}]",
            ],
            capture_output=True, timeout=5, check=True,
        )
        return True
    except (OSError, subprocess.SubprocessError):
        return False


def _setup_kde() -> list[str]:
    if all(_kglobalaccel_set(*change) for change in KDE_CHANGES):
        return ["Spectacle conserva la tecla Imprimir y Klipper deja libre Meta+V."]

    # kglobalaccel no responde: se deja escrito para el próximo inicio de sesión.
    writer = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    if not writer:
        raise ShortcutError("No se pudo hablar con KDE; asigna los atajos en Preferencias del sistema → Atajos.")

    def write(groups, key, current, default, label):
        cmd = [writer, "--file", "kglobalshortcutsrc"]
        for g in groups:
            cmd += ["--group", g]
        _run(*cmd, "--key", key, f"{current},{default},{label}")

    write(["services", "org.kde.spectacle.desktop"], "_launch", "Print", "Print\tMeta+Shift+S", "Spectacle")
    write(["plasmashell"], "show-on-mouse-pos", "none", "Meta+V", "Show Clipboard Items at Mouse Position")
    write(["services", "cutter-linux.desktop"], "_launch", "Meta+Shift+S", "Meta+Shift+S", "Cutter")
    write(["services", "cutter-linux.desktop"], "historial", "Meta+V", "Meta+V", "Historial del portapapeles")
    return ["Cierra sesión y vuelve a entrar para activar los atajos en KDE Plasma."]


class ShortcutError(RuntimeError):
    pass


SETUP = {
    "gnome": _setup_gnome,
    "cinnamon": _setup_cinnamon,
    "xfce": _setup_xfce,
    "kde": _setup_kde,
}


# Gestores de ventanas en mosaico (habituales en CachyOS y Arch): los atajos viven en
# el archivo de configuración del usuario, que no tocamos; se indica qué añadir.
MANUAL = {
    "hyprland": (
        "~/.config/hypr/hyprland.conf",
        [f"bind = SUPER SHIFT, S, exec, {SNIP_CMD}", f"bind = SUPER, V, exec, {HISTORY_CMD}"],
    ),
    "sway": (
        "~/.config/sway/config",
        [f"bindsym Mod4+Shift+s exec {SNIP_CMD}", f"bindsym Mod4+v exec {HISTORY_CMD}"],
    ),
    "niri": (
        "~/.config/niri/config.kdl (dentro de binds { })",
        ['Mod+Shift+S { spawn "cutter-linux" "recortar"; }', 'Mod+V { spawn "cutter-linux" "historial"; }'],
    ),
}


def setup_shortcuts(force: bool = False) -> list[str]:
    """Configura los atajos una sola vez. Devuelve mensajes para mostrar al usuario."""
    if config.SHORTCUTS_MARKER.exists() and not force:
        return []
    desktop = config.desktop()
    func = SETUP.get(desktop)
    if func is not None:
        try:
            notes = [f"Atajos configurados para {desktop}: Super+Shift+S y Super+V.", *func()]
        except ShortcutError as exc:
            notes = [str(exc), f"  Super+Shift+S → {SNIP_CMD}", f"  Super+V → {HISTORY_CMD}"]
    elif desktop in MANUAL:
        path, lines = MANUAL[desktop]
        notes = [f"Añade estas líneas a {path} (si ya usas Super+V, quita ese atajo):", *lines]
    else:
        notes = [
            f"Escritorio «{desktop}» no reconocido. Asigna a mano:",
            f"  Super+Shift+S → {SNIP_CMD}",
            f"  Super+V → {HISTORY_CMD}",
        ]
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config.SHORTCUTS_MARKER.write_text(desktop + "\n", encoding="utf-8")
    return notes
