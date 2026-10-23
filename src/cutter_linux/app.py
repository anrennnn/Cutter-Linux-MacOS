"""Proceso en segundo plano y comandos de Cutter.

Un único proceso por usuario vigila el portapapeles y muestra las ventanas.
Los atajos de teclado lanzan `cutter-linux recortar` o `cutter-linux historial`,
que solo envían la orden por un socket local y terminan. Si el proceso de
fondo no está corriendo, el primero que se lance se convierte en él.
"""

import argparse
import os
import shutil
import subprocess
import sys
from datetime import datetime

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QGuiApplication
from PyQt6.QtNetwork import QLocalServer, QLocalSocket
from PyQt6.QtWidgets import QApplication

from . import config

SOCKET_NAME = f"{config.APP_ID}-{os.getuid()}"


def send_to_daemon(command: str) -> bool:
    sock = QLocalSocket()
    sock.connectToServer(SOCKET_NAME)
    if not sock.waitForConnected(500):
        return False
    sock.write(command.encode() + b"\n")
    sock.waitForBytesWritten(500)
    sock.disconnectFromServer()
    return True


class Daemon:
    def __init__(self, app: QApplication):
        from .history import ClipboardWatcher, HistoryStore
        from .history_ui import HistoryPopup

        self.app = app
        self.store = HistoryStore()
        self.watcher = ClipboardWatcher(self.store)
        self.popup = HistoryPopup(self.store)
        self.session = None

        QLocalServer.removeServer(SOCKET_NAME)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._on_connection)
        if not self.server.listen(SOCKET_NAME):
            print("No se pudo abrir el socket de control:", self.server.errorString(), file=sys.stderr)

    def _on_connection(self):
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            conn.readyRead.connect(lambda c=conn: self._read(c))

    def _read(self, conn):
        while conn.canReadLine():
            self.handle(bytes(conn.readLine()).decode().strip())

    def handle(self, command: str):
        name, _, arg = command.partition(" ")
        if name == "recortar":
            QTimer.singleShot(0, lambda: self.snip(arg or "rect"))
        elif name == "historial":
            self.popup.toggle()
        elif name == "salir":
            self.app.quit()

    # --- recorte -----------------------------------------------------------

    def snip(self, mode: str):
        from .capture import CaptureError, capture_screens
        from .overlay import SnipSession

        if self.session is not None:
            return
        if self.popup.isVisible():
            self.popup.hide()
        try:
            shots = capture_screens()
        except CaptureError as exc:
            notify("No se pudo recortar", str(exc))
            return
        self.session = SnipSession(shots, self._snip_done, mode)
        self.session.start()

    def _snip_done(self, pixmap):
        self.session = None
        if pixmap is None or pixmap.isNull():
            return
        image = pixmap.toImage()
        QGuiApplication.clipboard().setImage(image)
        self.store.add_image(image)

        folder = config.screenshots_dir()
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"Captura de pantalla {datetime.now():%Y-%m-%d %H%M%S}.png"
        image.save(str(path), "PNG")
        notify(
            "Recorte copiado al portapapeles",
            "Seleccione aquí para abrirlo. También se guardó en " + str(folder),
            image_path=str(path),
            on_click=lambda: subprocess.Popen(["xdg-open", str(path)]),
        )


def notify(title: str, body: str, image_path: str = "", on_click=None):
    """Notificación del escritorio; al pulsarla se ejecuta on_click (si el escritorio lo admite)."""
    if not shutil.which("notify-send"):
        print(f"{title}: {body}")
        return
    cmd = ["notify-send", "--app-name", config.APP_NAME, "--icon", image_path or config.APP_ID]
    if on_click is not None:
        cmd += ["--action=default=Abrir", "--wait"]
    cmd += [title, body]
    if on_click is None:
        subprocess.Popen(cmd)
        return
    from PyQt6.QtCore import QProcess

    proc = QProcess()
    _live_processes.append(proc)

    def finished():
        clicked = bytes(proc.readAllStandardOutput()).decode().strip() == "default"
        _live_processes.remove(proc)
        if clicked:
            on_click()

    proc.finished.connect(finished)
    proc.start(cmd[0], cmd[1:])


_live_processes = []


def _stop_notifications():
    """Al salir se cierran las notificaciones pendientes antes de que Qt destruya sus procesos."""
    for proc in list(_live_processes):
        proc.finished.disconnect()
        proc.kill()
        proc.waitForFinished(500)
    _live_processes.clear()


def _prepare_platform():
    # En GNOME/Cinnamon con Wayland un programa sin foco no puede leer el portapapeles.
    # Usando XWayland sí recibe los cambios, porque Mutter los replica en X11.
    if (
        config.session_type() == "wayland"
        and config.desktop() in ("gnome", "cinnamon")
        and os.environ.get("DISPLAY")
        and "QT_QPA_PLATFORM" not in os.environ
    ):
        os.environ["QT_QPA_PLATFORM"] = "xcb"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cutter-linux",
        description="Recortes de pantalla (Super+Shift+S) e historial del portapapeles (Super+V).",
    )
    sub = parser.add_subparsers(dest="command")
    snip = sub.add_parser("recortar", help="Abrir la selección de recorte (Super+Shift+S)")
    snip.add_argument(
        "--modo", choices=["rect", "window", "full", "free"], default="rect",
        help="rect=rectangular, window=ventana, full=pantalla completa, free=forma libre",
    )
    sub.add_parser("historial", help="Mostrar el historial del portapapeles (Super+V)")
    sub.add_parser("segundo-plano", help="Iniciar solo el proceso de fondo (se usa al iniciar sesión)")
    sub.add_parser("atajos", help="Volver a configurar Super+Shift+S y Super+V en el escritorio")
    sub.add_parser("salir", help="Detener el proceso de fondo")
    sub.add_parser("version", help="Mostrar la versión")
    args = parser.parse_args(argv)

    if args.command == "version":
        print(config.APP_NAME, config.VERSION)
        return 0
    if args.command == "atajos":
        from .shortcuts import setup_shortcuts

        for line in setup_shortcuts(force=True):
            print(line)
        return 0

    command = {
        "recortar": f"recortar {getattr(args, 'modo', 'rect')}",
        "historial": "historial",
        "salir": "salir",
    }.get(args.command or "recortar", "")

    _prepare_platform()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(config.APP_ID)
    app.setApplicationDisplayName(config.APP_NAME)
    app.setDesktopFileName(config.APP_ID)
    app.setQuitOnLastWindowClosed(False)
    app.aboutToQuit.connect(_stop_notifications)

    if command and send_to_daemon(command):
        return 0
    if args.command == "salir":
        return 0
    if args.command == "segundo-plano" and send_to_daemon("ping"):
        return 0  # ya hay uno corriendo

    from .shortcuts import setup_shortcuts

    messages = setup_shortcuts()
    daemon = Daemon(app)
    if messages:
        notify(config.APP_NAME, "\n".join(messages))
    if command:
        QTimer.singleShot(200, lambda: daemon.handle(command))
    return app.exec()
