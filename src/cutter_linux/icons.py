"""Iconos propios de Cutter.

Línea redondeada de 1,7 px sobre una cuadrícula de 24×24, pintados con el color
del texto del tema (claro u oscuro) y un color de acento. Se generan como SVG en
memoria, así se ven igual en KDE, GNOME, Cinnamon, XFCE y macOS sin depender de
los iconos del sistema.
"""

from PyQt6.QtCore import QByteArray, QSize
from PyQt6.QtGui import QColor, QGuiApplication, QIcon, QPixmap

ACCENT = "#3a9df8"

# «A» marca las piezas que se pintan con el color de acento (o el color de la pluma).
SHAPES = {
    "new": '<path d="M12 5v14M5 12h14"/>',
    "cut": '<circle cx="7" cy="17" r="2.6"/><circle cx="17" cy="17" r="2.6"/>'
           '<path d="M8.9 15.1 18 5M15.1 15.1 6 5"/>',
    "camera": '<path d="M4 8h3l1.5-2h7L17 8h3a1 1 0 0 1 1 1v9a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1V9a1 1 0 0 1 1-1z"/>'
              '<circle cx="12" cy="13.5" r="3.3"/>',
    "mode-rect": '<rect x="4" y="6" width="16" height="12" rx="2" stroke-dasharray="3 2.4"/>'
                 '<path d="M17 15.5l3.5 3.5" A/>',
    "mode-window": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 9h18"/>'
                   '<path d="M6 7h.01M8.5 7h.01" stroke-width="2.2" A/>',
    "mode-full": '<path d="M4 9V6a1 1 0 0 1 1-1h3M16 5h3a1 1 0 0 1 1 1v3M20 15v3a1 1 0 0 1-1 1h-3M8 19H5a1 1 0 0 1-1-1v-3"/>'
                 '<rect x="8" y="9" width="8" height="6" rx="1" A/>',
    "mode-free": '<path d="M7 16c-3-3-2-8 3-9.5s9.5.5 9 4.5-4 3-6 5-4 3.5-6 0z" stroke-dasharray="3 2.4"/>',
    "delay": '<circle cx="12" cy="13" r="7"/><path d="M12 13V9.5M10 3h4"/><path d="M18.3 6.7l1.2-1.2" A/>',
    "cancel": '<circle cx="12" cy="12" r="8.5"/><path d="M9 9l6 6M15 9l-6 6"/>',
    "settings": '<path d="M4 7h9M17 7h3M4 17h3M11 17h9"/><circle cx="15" cy="7" r="2"/><circle cx="9" cy="17" r="2" A/>',
    "pen": '<path d="M15.5 4.5l4 4L9 19l-5 1 1-5z"/><path d="M13.5 6.5l4 4"/>'
           '<path d="M4 20l1-5 4 4z" fill="A" A/>',
    "highlighter": '<path d="M15 4l5 5-8 8H8v-4z"/><path d="M8 13l-3 4.5h4.5L11 16"/>'
                   '<path d="M3 21h18" stroke-width="2.6" A/>',
    "eraser": '<path d="M4.6 15.4l9-9a2 2 0 0 1 2.8 0l3.2 3.2a2 2 0 0 1 0 2.8L13 19H8.2z"/>'
              '<path d="M9.5 10.5l5.6 5.6"/><path d="M13 19h7" A/>',
    "shapes": '<rect x="3.5" y="3.5" width="10" height="10" rx="1.5"/><circle cx="15.5" cy="15.5" r="5" A/>',
    "shape-rect": '<rect x="4" y="6" width="16" height="12" rx="2"/>',
    "shape-ellipse": '<ellipse cx="12" cy="12" rx="8.5" ry="6"/>',
    "shape-arrow": '<path d="M5 19L19 5"/><path d="M10 5h9v9" A/>',
    "shape-line": '<path d="M5 19L19 5"/>',
    "text": '<path d="M5 7V4.5h14V7M12 4.5v15M9 19.5h6"/>',
    "crop": '<path d="M7 3v13a1 1 0 0 0 1 1h13"/><path d="M3 7h13a1 1 0 0 1 1 1v13" A/>',
    "undo": '<path d="M9 14L4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="M15 14l5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "save": '<path d="M5 3.5h10.5l4 4V19a1.5 1.5 0 0 1-1.5 1.5H5A1.5 1.5 0 0 1 3.5 19V5A1.5 1.5 0 0 1 5 3.5z"/>'
            '<path d="M8 3.5v4.5h6.5V3.5"/><path d="M7.5 20.5v-6h9v6" A/>',
    "copy": '<rect x="8.5" y="8.5" width="12" height="12" rx="2"/>'
            '<path d="M15.5 8.5V5a1.5 1.5 0 0 0-1.5-1.5H5A1.5 1.5 0 0 0 3.5 5v9A1.5 1.5 0 0 0 5 15.5h3.5"/>',
    "open-with": '<path d="M14 4h6v6M20 4l-8.5 8.5"/>'
                 '<path d="M18 14v4.5a1.5 1.5 0 0 1-1.5 1.5h-11A1.5 1.5 0 0 1 4 18.5v-11A1.5 1.5 0 0 1 5.5 6H10"/>',
    "more": '<path d="M6 12h.01M12 12h.01M18 12h.01" stroke-width="2.6"/>',
    "folder": '<path d="M3.5 7.5A2 2 0 0 1 5.5 5.5h3.6l2 2h7.4a2 2 0 0 1 2 2v7.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2z"/>',
    "history": '<rect x="5" y="4.5" width="14" height="16.5" rx="2"/><rect x="9" y="2.5" width="6" height="3.5" rx="1" A/>'
               '<path d="M8.5 11h7M8.5 15h4.5"/>',
    "info": '<circle cx="12" cy="12" r="8.5"/><path d="M12 11v5.5"/><path d="M12 7.8h.01" stroke-width="2.4"/>',
    "exit": '<path d="M12 3.5v8"/><path d="M6.6 6.9a7.8 7.8 0 1 0 10.8 0"/>',
    "zoom-in": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4.5 4.5"/><path d="M10.5 8v5M8 10.5h5" A/>',
    "zoom-out": '<circle cx="10.5" cy="10.5" r="6.5"/><path d="M15.5 15.5l4.5 4.5"/><path d="M8 10.5h5" A/>',
    "zoom-fit": '<path d="M4 9V5h4M16 5h4v4M20 15v4h-4M8 19H4v-4"/><circle cx="12" cy="12" r="2.5" A/>',
    "keyboard": '<rect x="3" y="6" width="18" height="12" rx="2"/>'
                '<path d="M7 10h.01M11 10h.01M15 10h.01M8 14h8" stroke-width="1.9"/>',
    "trash": '<path d="M4 7h16M10 11v6M14 11v6M6 7l1 12.5a1.5 1.5 0 0 0 1.5 1.4h7a1.5 1.5 0 0 0 1.5-1.4L18 7M9 7V4.5h6V7"/>',
    "check": '<path d="M5 12.5l4.5 4.5L19 7.5"/>',
    "close": '<path d="M6 6l12 12M18 6L6 18"/>',
    "pin": '<path d="M9 4h6l-1 5 3 3H7l3-3z"/><path d="M12 15v5"/>',
    "color": '<circle cx="12" cy="12" r="8" fill="A" A/>',
}

# Nombres del tema de iconos (freedesktop) que usaba el código → icono propio.
ALIASES = {
    "edit-cut": "cut", "camera-photo": "camera", "document-new": "new",
    "select-rectangular": "mode-rect", "selection-rectangular": "mode-rect", "draw-rectangle": "mode-rect",
    "window": "mode-window", "window-new": "mode-window",
    "view-fullscreen": "mode-full", "video-display": "mode-full",
    "draw-freehand": "mode-free", "draw-path": "mode-free",
    "chronometer": "delay", "alarm-symbolic": "delay", "appointment-soon": "delay", "clock": "delay",
    "process-stop": "cancel", "dialog-cancel": "cancel",
    "configure": "settings", "preferences-system": "settings", "preferences-other": "settings",
    "help-about": "info", "dialog-information": "info",
    "document-save-as": "save", "document-save": "save", "edit-copy": "copy",
    "edit-undo": "undo", "edit-redo": "redo", "window-close": "close", "application-exit": "exit",
    "draw-brush": "pen", "draw-highlight": "highlighter", "format-text-highlight": "highlighter",
    "draw-eraser": "eraser", "edit-clear": "trash", "edit-clear-history": "trash",
    "edit-paste": "history", "preferences-desktop-keyboard-shortcuts": "keyboard", "input-keyboard": "keyboard",
}

SIZES = (16, 20, 24, 32, 48)
_cache: dict = {}


def text_color() -> QColor:
    return QGuiApplication.palette().windowText().color()


def svg(name: str, size: int, color: str, accent: str, opacity: float = 1.0) -> bytes:
    body = SHAPES[name].replace('fill="A"', f'fill="{accent}"').replace(" A/>", f' stroke="{accent}"/>')
    return (
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{size}" height="{size}" viewBox="0 0 24 24" '
        f'fill="none" stroke="{color}" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round" '
        f'opacity="{opacity}">{body}</svg>'
    ).encode()


def make(name: str, accent: str | None = None, color: QColor | None = None) -> QIcon:
    """Icono propio `name`. `accent` pinta las piezas de acento (p. ej. el color de la pluma)."""
    if name not in SHAPES:
        return QIcon()
    color = color or text_color()
    accent = accent or ACCENT
    key = (name, color.name(QColor.NameFormat.HexArgb), accent)
    if key in _cache:
        return _cache[key]
    screen = QGuiApplication.primaryScreen()
    dpr = screen.devicePixelRatio() if screen else 1.0
    result = QIcon()
    for size in SIZES:
        for mode, opacity in ((QIcon.Mode.Normal, 1.0), (QIcon.Mode.Disabled, 0.35)):
            pix = QPixmap()
            pix.loadFromData(QByteArray(svg(name, round(size * dpr), color.name(), accent, opacity)), "SVG")
            if pix.isNull():
                continue
            pix.setDevicePixelRatio(dpr)
            result.addPixmap(pix, mode)
    _cache[key] = result
    return result


def has(name: str) -> bool:
    return name in SHAPES or name in ALIASES


def icon(*names: str) -> QIcon:
    """Primer icono disponible: los propios de Cutter y, si no, el tema del sistema."""
    for name in names:
        own = ALIASES.get(name, name)
        if own in SHAPES:
            found = make(own)
            if not found.isNull():
                return found
    for name in names:
        found = QIcon.fromTheme(name)
        if not found.isNull():
            return found
    return QIcon()


def app_icon() -> QIcon:
    from pathlib import Path

    found = QIcon.fromTheme("cutter-linux")
    if found.isNull():
        found = QIcon(str(Path(__file__).with_name("cutter-linux.svg")))
    return found


def size_hint(size: int = 20) -> QSize:
    return QSize(size, size)
