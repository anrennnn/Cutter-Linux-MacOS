"""Proceso en segundo plano y comandos de Cutter.

Un único proceso por usuario vigila el portapapeles y muestra las ventanas.
Los atajos de teclado lanzan `cutter-linux recortar` o `cutter-linux historial`
(y el icono del menú, `cutter-linux abrir`),
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
from . import settings as settings_mod

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
        self.main_window = None
        self.editor = None
        self.tray = None
        self.hidden_for_snip = []

        QLocalServer.removeServer(SOCKET_NAME)
        self.server = QLocalServer()
        self.server.newConnection.connect(self._on_connection)
        if not self.server.listen(SOCKET_NAME):
            print("No se pudo abrir el socket de control:", self.server.errorString(), file=sys.stderr)
        self.update_tray()
        if config.IS_MAC:
            self._setup_mac()

    def _setup_mac(self):
        """Atajos globales, Dock y reapertura desde el Finder."""
        from . import macos

        self.hotkeys = macos.HotKeys()
        self.hotkeys.pressed.connect(self._on_hotkey)
        failed = [
            keys for hid, code, keys in ((1, macos.KEY_S, config.SNIP_KEYS), (2, macos.KEY_V, config.HISTORY_KEYS))
            if not self.hotkeys.register(hid, code, macos.CONTROL | macos.SHIFT)
        ]
        if failed:
            notify(config.APP_NAME, "Otra app ya usa " + " y ".join(failed) + ".")
        macos.set_autostart(settings_mod.current.autostart)
        # En el Dock solo mientras haya una ventana de Cutter abierta.
        self._dock_visible = None
        self._dock_timer = QTimer()
        self._dock_timer.setInterval(700)
        self._dock_timer.timeout.connect(self._sync_dock)
        self._dock_timer.start()
        self._sync_dock()
        # Abrir Cutter.app otra vez (Finder, Launchpad, Dock) no lanza otro proceso:
        # solo activa este. Si no hay nada abierto, se muestra la ventana principal.
        self._last_internal_activation = 0.0
        self.app.applicationStateChanged.connect(self._on_app_state)

    def _on_hotkey(self, hotkey_id: int):
        import time

        self._last_internal_activation = time.monotonic()
        if hotkey_id == 1:
            self.snip(settings_mod.current.default_mode)
        elif hotkey_id == 2:
            self.popup.toggle()

    def _sync_dock(self):
        from . import macos

        visible = any(w is not None and w.isVisible() for w in (self.main_window, self.editor))
        if visible != self._dock_visible:
            self._dock_visible = visible
            macos.set_dock_visible(visible)

    def _on_app_state(self, state):
        import time

        from PyQt6.QtCore import Qt

        if state != Qt.ApplicationState.ApplicationActive:
            return
        if time.monotonic() - self._last_internal_activation < 2 or self.session is not None:
            return
        if not any(w.isVisible() for w in QApplication.topLevelWidgets()):
            self.show_main_window()

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
        elif name == "abrir":
            self.show_main_window()
        elif name == "opciones":
            self.show_options()
        elif name == "salir":
            self.app.quit()

    # --- ventanas ---------------------------------------------------------------

    def show_main_window(self):
        from .main_window import MainWindow

        if self.main_window is None:
            self.main_window = MainWindow()
            self.main_window.snip_requested.connect(lambda mode, _d: self.snip(mode, source="window"))
            self.main_window.options_requested.connect(self.show_options)
            self.main_window.history_requested.connect(self.popup.toggle)
        self.main_window.present()

    def show_options(self):
        from .options import OptionsDialog

        parent = self.main_window if self.main_window and self.main_window.isVisible() else None
        dialog = OptionsDialog(parent, on_clear_history=self.store.clear)
        if dialog.exec():
            self.update_tray()

    def open_editor(self, pixmap, saved_path=None):
        from .editor import EditorWindow

        if self.editor is None:
            self.editor = EditorWindow(pixmap)
            self.editor.new_snip_requested.connect(lambda mode: self.snip(mode, source="editor"))
        else:
            self.editor.load(pixmap, saved_path)
        self.editor.saved_path = saved_path
        self.editor.show()
        self.editor.raise_()
        self.editor.activateWindow()

    def update_tray(self):
        from PyQt6.QtWidgets import QSystemTrayIcon

        wanted = settings_mod.current.tray_icon and QSystemTrayIcon.isSystemTrayAvailable()
        if not wanted:
            if self.tray is not None:
                self.tray.hide()
                self.tray = None
            return
        if self.tray is not None:
            return
        from PyQt6.QtWidgets import QMenu

        from .editor import icon
        from .main_window import DELAYS, delay_label, mode_menu

        if config.IS_MAC:
            # Icono de plantilla: macOS lo pinta en negro o blanco según la barra de menús.
            from PyQt6.QtGui import QIcon

            from .macos import resource_dir

            tray_icon = QIcon(str(resource_dir() / "cutter-menubar.svg"))
            tray_icon.setIsMask(True)
        else:
            tray_icon = icon(config.APP_ID, "edit-cut")
        self.tray = QSystemTrayIcon(tray_icon, self.app)
        self.tray.setToolTip(f"{config.APP_NAME}: {config.SNIP_KEYS} recortar · {config.HISTORY_KEYS} historial")
        menu = QMenu()
        menu.addAction(icon("edit-cut"), "Nuevo recorte", lambda: self.snip(settings_mod.current.default_mode))
        modes = mode_menu(menu, lambda m: self.snip(m))
        modes.setTitle("Modo de recorte")
        menu.addMenu(modes)
        delayed = menu.addMenu(icon("chronometer", "clock"), "Recorte aplazado")
        for seconds in DELAYS[1:]:
            delayed.addAction(delay_label(seconds), lambda s=seconds: QTimer.singleShot(
                s * 1000, lambda: self.snip(settings_mod.current.default_mode)))
        menu.addSeparator()
        menu.addAction(icon("edit-paste"), "Historial del portapapeles", self.popup.toggle)
        menu.addAction(icon(config.APP_ID), "Abrir Cutter", self.show_main_window)
        menu.addAction(icon("configure", "preferences-system"), "Opciones…", self.show_options)
        menu.addSeparator()
        menu.addAction(icon("application-exit"), "Salir", self.app.quit)
        self.tray.setContextMenu(menu)
        self._tray_menu = menu
        self.tray.activated.connect(self._tray_activated)
        self.tray.messageClicked.connect(_on_message_clicked)
        self.tray.show()
        global _tray
        _tray = self.tray

    def _tray_activated(self, reason):
        from PyQt6.QtWidgets import QSystemTrayIcon

        # En macOS el clic ya abre el menú; abrir también la ventana sería molesto.
        if reason == QSystemTrayIcon.ActivationReason.Trigger and not config.IS_MAC:
            self.show_main_window()
        elif reason == QSystemTrayIcon.ActivationReason.MiddleClick:
            self.snip(settings_mod.current.default_mode)

    # --- recorte ------------------------------------------------------------

    def snip(self, mode: str, source: str = "shortcut"):
        if self.session is not None:
            return
        self.source = source
        # Nuestras ventanas no deben salir en la captura.
        self.hidden_for_snip = [w for w in (self.main_window, self.editor, self.popup) if w is not None and w.isVisible()]
        for w in self.hidden_for_snip:
            w.hide()
        # Se da tiempo al compositor para quitarlas de la pantalla.
        QTimer.singleShot(250 if self.hidden_for_snip else 0, lambda: self._capture(mode))

    def _capture(self, mode: str):
        from .capture import CaptureError, capture_screens
        from .overlay import SnipSession

        try:
            shots = capture_screens()
        except CaptureError as exc:
            notify("No se pudo recortar", str(exc))
            self._restore_windows()
            return
        self.session = SnipSession(shots, self._snip_done, mode)
        self.session.start()

    def _restore_windows(self):
        for w in self.hidden_for_snip:
            if w is not self.popup:
                w.show()
        self.hidden_for_snip = []

    def _snip_done(self, pixmap):
        self.session = None
        if pixmap is None or pixmap.isNull():
            self._restore_windows()
            return
        s = settings_mod.current
        image = pixmap.toImage()
        if s.copy_to_clipboard:
            QGuiApplication.clipboard().setImage(image)
        self.store.add_image(image)
        self.hidden_for_snip = []

        if self.source in ("window", "editor"):
            # Como la herramienta clásica: el recorte se abre en el editor.
            if self.main_window is not None:
                self.main_window.hide()
            self.open_editor(pixmap)
            return

        path = None
        if s.autosave:
            folder = s.screenshots_dir()
            folder.mkdir(parents=True, exist_ok=True)
            path = folder / f"Captura de pantalla {datetime.now():%Y-%m-%d %H%M%S}.png"
            image.save(str(path), "PNG")
        if s.open_editor_after_shortcut:
            self.open_editor(pixmap, path)
        elif s.notify:
            title = "Recorte copiado al portapapeles" if s.copy_to_clipboard else "Recorte listo"
            body = "Selecciona aquí para anotarlo y compartirlo."
            if path:
                body += f" Guardado en {path.parent}"
            notify(title, body, image_path=str(path or ""), on_click=lambda: self.open_editor(pixmap, path))


def notify(title: str, body: str, image_path: str = "", on_click=None):
    """Notificación del escritorio; al pulsarla se ejecuta on_click (si el escritorio lo admite)."""
    if config.IS_MAC:
        global _message_click
        if _tray is not None:
            _message_click = on_click
            _tray.showMessage(title, body, _tray.icon(), 6000)
        else:
            from . import macos

            macos.notify(title, body)
        return
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
_tray = None  # icono de la barra de menús (macOS); muestra las notificaciones
_message_click = None


def _on_message_clicked():
    if _message_click is not None:
        _message_click()


def _stop_notifications():
    """Al salir se cierran las notificaciones pendientes antes de que Qt destruya sus procesos."""
    for proc in list(_live_processes):
        proc.finished.disconnect()
        proc.kill()
        proc.waitForFinished(500)
    _live_processes.clear()


def _ensure_icon_theme():
    """Garantiza iconos aunque el tema del escritorio no tenga alguno (o no haya tema).

    Sin integración de Qt con el escritorio (XFCE, Hyprland…) el tema es «hicolor»
    y casi no tiene iconos; se elige uno instalado. Además se fija un tema de
    respaldo para los iconos que falten en el tema elegido por el usuario.
    """
    from pathlib import Path

    from PyQt6.QtGui import QIcon

    dark = QApplication.palette().window().color().lightness() < 128
    if config.IS_MAC:
        # macOS no tiene temas de iconos: Cutter trae un subconjunto de Breeze.
        from .macos import resource_dir

        QIcon.setThemeSearchPaths([str(resource_dir() / "icons")])
        QIcon.setThemeName("breeze-dark" if dark else "breeze")
        return
    candidates = ["breeze-dark", "Papirus-Dark"] if dark else ["breeze", "Papirus"]
    candidates += ["Adwaita", "Yaru", "elementary", "Mint-Y"]
    installed = [
        name for name in candidates
        if any((Path(base) / name / "index.theme").exists()
               for base in ("/usr/share/icons", str(Path.home() / ".local/share/icons")))
    ]
    if not installed:
        return
    if QIcon.themeName() in ("", "hicolor"):
        QIcon.setThemeName(installed[0])
    QIcon.setFallbackThemeName(next((n for n in installed if n != QIcon.themeName()), installed[0]))


def _prepare_platform():
    # En GNOME/Cinnamon con Wayland un programa sin foco no puede leer el portapapeles.
    # Usando XWayland sí recibe los cambios, porque Mutter los replica en X11.
    if (
        config.session_type() == "wayland"
        and config.desktop() in ("gnome", "cinnamon")
        and os.environ.get("DISPLAY")
        and "QT_QPA_PLATFORM" not in os.environ
    ):
        # Si XWayland no está disponible (o falta libxcb-cursor), Qt usa Wayland.
        os.environ["QT_QPA_PLATFORM"] = "xcb;wayland"


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="cutter-linux",
        description=f"Recortes de pantalla ({config.SNIP_KEYS}) e historial del portapapeles ({config.HISTORY_KEYS}).",
    )
    sub = parser.add_subparsers(dest="command")
    snip = sub.add_parser("recortar", help=f"Abrir la selección de recorte ({config.SNIP_KEYS})")
    snip.add_argument(
        "--modo", choices=["rect", "window", "full", "free"], default="rect",
        help="rect=rectangular, window=ventana, full=pantalla completa, free=forma libre",
    )
    sub.add_parser("historial", help=f"Mostrar el historial del portapapeles ({config.HISTORY_KEYS})")
    sub.add_parser("abrir", help="Abrir la ventana de Cutter (es lo que hace sin argumentos)")
    sub.add_parser("opciones", help="Abrir la ventana de opciones")
    sub.add_parser("segundo-plano", help="Iniciar solo el proceso de fondo (se usa al iniciar sesión)")
    sub.add_parser("atajos", help=f"Volver a configurar {config.SNIP_KEYS} y {config.HISTORY_KEYS} en el escritorio")
    sub.add_parser("salir", help="Detener el proceso de fondo")
    sub.add_parser("version", help="Mostrar la versión")
    if argv is None:
        argv = sys.argv[1:]
    # El Finder de macOS antiguos añade «-psn_…» al abrir la app.
    argv = [a for a in argv if not a.startswith("-psn_")]
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
        "abrir": "abrir",
        "opciones": "opciones",
        "salir": "salir",
    }.get(args.command or "abrir", "")

    _prepare_platform()
    app = QApplication(sys.argv[:1])
    app.setApplicationName(config.APP_ID)
    app.setApplicationDisplayName(config.APP_NAME)
    app.setDesktopFileName(config.APP_ID)
    app.setQuitOnLastWindowClosed(False)
    _ensure_icon_theme()
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
