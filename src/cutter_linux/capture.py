"""Captura de la pantalla completa en X11 y Wayland.

En X11 se lee el framebuffer directamente con Qt. En Wayland las aplicaciones no
pueden leer la pantalla, así que se pide la imagen al portal de escritorio
(org.freedesktop.portal.Screenshot), que funciona en GNOME, KDE y wlroots; si el
portal no responde se prueban las herramientas propias de cada escritorio.
"""

import os
import secrets
import shutil
import subprocess
import tempfile
from urllib.parse import unquote, urlparse

from PyQt6.QtCore import QEventLoop, QObject, QRect, QTimer, pyqtSlot
from PyQt6.QtDBus import QDBusConnection, QDBusInterface, QDBusMessage
from PyQt6.QtGui import QGuiApplication, QImage, QPixmap

from . import config


class CaptureError(RuntimeError):
    pass


def capture_screens() -> list[tuple]:
    """Devuelve [(QScreen, QPixmap)] con la imagen de cada monitor, sin recortar."""
    screens = QGuiApplication.screens()
    if config.session_type() == "x11" and QGuiApplication.platformName() == "xcb":
        return [(s, s.grabWindow(0)) for s in screens]

    full = _capture_wayland()
    return _split_by_screen(full, screens)


def _split_by_screen(full: QImage, screens) -> list[tuple]:
    virtual = QRect()
    for s in screens:
        virtual = virtual.united(s.geometry())
    # El portal entrega píxeles físicos; la geometría de Qt es lógica.
    scale_x = full.width() / max(1, virtual.width())
    scale_y = full.height() / max(1, virtual.height())
    result = []
    for s in screens:
        g = s.geometry().translated(-virtual.topLeft())
        src = QRect(
            round(g.x() * scale_x),
            round(g.y() * scale_y),
            round(g.width() * scale_x),
            round(g.height() * scale_y),
        )
        pix = QPixmap.fromImage(full.copy(src))
        pix.setDevicePixelRatio(scale_x)
        result.append((s, pix))
    return result


def _capture_wayland() -> QImage:
    image = _capture_portal()
    if image is not None and not image.isNull():
        return image
    image = _capture_with_tools()
    if image is not None and not image.isNull():
        return image
    raise CaptureError(
        "No se pudo capturar la pantalla. Instala xdg-desktop-portal y el backend de tu escritorio "
        "(xdg-desktop-portal-gnome, -kde o -gtk)."
    )


class _PortalWaiter(QObject):
    def __init__(self):
        super().__init__()
        self.uri = None
        self.loop = QEventLoop()

    @pyqtSlot(QDBusMessage)
    def on_response(self, message: QDBusMessage):
        args = message.arguments()
        if args and args[0] == 0 and len(args) > 1:
            self.uri = args[1].get("uri")
        self.loop.quit()


def _capture_portal() -> QImage | None:
    bus = QDBusConnection.sessionBus()
    if not bus.isConnected():
        return None
    token = "cutter_" + secrets.token_hex(6)
    sender = bus.baseService().lstrip(":").replace(".", "_")
    request_path = f"/org/freedesktop/portal/desktop/request/{sender}/{token}"

    waiter = _PortalWaiter()
    bus.connect(
        "org.freedesktop.portal.Desktop",
        request_path,
        "org.freedesktop.portal.Request",
        "Response",
        waiter.on_response,
    )
    iface = QDBusInterface(
        "org.freedesktop.portal.Desktop",
        "/org/freedesktop/portal/desktop",
        "org.freedesktop.portal.Screenshot",
        bus,
    )
    if not iface.isValid():
        return None
    reply = iface.call("Screenshot", "", {"handle_token": token, "interactive": False})
    if reply.type() == QDBusMessage.MessageType.ErrorMessage:
        return None

    # La primera vez GNOME pide permiso al usuario, así que se espera con holgura.
    QTimer.singleShot(60_000, waiter.loop.quit)
    waiter.loop.exec()
    bus.disconnect(
        "org.freedesktop.portal.Desktop",
        request_path,
        "org.freedesktop.portal.Request",
        "Response",
        waiter.on_response,
    )
    if not waiter.uri:
        return None
    path = unquote(urlparse(waiter.uri).path)
    image = QImage(path)
    try:
        os.remove(path)  # El portal deja el archivo en Imágenes; nosotros guardamos solo el recorte.
    except OSError:
        pass
    return image


def _capture_with_tools() -> QImage | None:
    fd, path = tempfile.mkstemp(prefix="cutter-", suffix=".png")
    os.close(fd)
    commands = [
        ["spectacle", "-b", "-n", "-f", "-o", path],
        ["grim", path],
        ["gnome-screenshot", "-f", path],
    ]
    try:
        for cmd in commands:
            if not shutil.which(cmd[0]):
                continue
            try:
                subprocess.run(cmd, timeout=15, check=True, capture_output=True)
            except (OSError, subprocess.SubprocessError):
                continue
            image = QImage(path)
            if not image.isNull():
                return image
        return None
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
