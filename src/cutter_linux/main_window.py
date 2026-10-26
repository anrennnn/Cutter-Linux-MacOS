"""Ventana principal clásica: Nuevo · Modo · Aplazar · Cancelar · Opciones."""

from PyQt6.QtCore import QSize, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QAction, QActionGroup
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QMainWindow, QMenu, QToolBar, QToolButton, QVBoxLayout, QWidget,
)

from . import config
from . import settings as settings_mod
from . import icons
from .editor import icon

MODE_LABELS = [
    ("free", "Recorte de forma libre", ("draw-freehand", "draw-path")),
    ("rect", "Recorte rectangular", ("select-rectangular", "draw-rectangle")),
    ("window", "Recorte de ventana", ("window", "window-new")),
    ("full", "Recorte de pantalla completa", ("view-fullscreen", "video-display")),
]
DELAYS = [0, 1, 2, 3, 4, 5]


def mode_menu(parent, on_pick, checked: str | None = None) -> QMenu:
    menu = QMenu("Modo", parent)
    group = QActionGroup(menu)
    window_ok = config.session_type() in ("x11", "macos")
    for key, label, names in MODE_LABELS:
        action = menu.addAction(icon(*names), label, lambda k=key: on_pick(k))
        if key == "window" and not window_ok:
            action.setEnabled(False)
            action.setText(label + " (no disponible en Wayland)")
        if checked is not None:
            action.setCheckable(True)
            action.setChecked(key == checked)
            group.addAction(action)
    return menu


def delay_label(seconds: int) -> str:
    return "Sin retraso" if seconds == 0 else f"{seconds} segundo{'s' if seconds > 1 else ''}"


class MainWindow(QMainWindow):
    snip_requested = pyqtSignal(str, int)  # modo, segundos de retraso
    options_requested = pyqtSignal()
    history_requested = pyqtSignal()

    def __init__(self):
        super().__init__()
        self.settings = settings_mod.current
        self.mode = self.settings.default_mode
        self.delay = self.settings.default_delay
        self.remaining = 0
        self.timer = QTimer(self)
        self.timer.setInterval(1000)
        self.timer.timeout.connect(self._tick)

        self.setWindowTitle("Herramienta Recortes - Cutter")
        self.setWindowIcon(icons.app_icon())

        tb = QToolBar("Recortes", self)
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(22, 22))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.addToolBar(tb)

        self.btn_new = QToolButton()
        self.btn_new.setText("&Nuevo")
        self.btn_new.setIcon(icon("edit-cut", "camera-photo", config.APP_ID))
        self.btn_new.setToolTip("Nuevo recorte (Ctrl+N)")
        self.btn_new.setShortcut("Ctrl+N")
        self.btn_new.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_new.clicked.connect(self.start)
        tb.addWidget(self.btn_new)

        self.btn_mode = QToolButton()
        self.btn_mode.setText("&Modo")
        self.btn_mode.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_mode.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        self.btn_mode.clicked.connect(self.start)
        tb.addWidget(self.btn_mode)

        self.btn_delay = QToolButton()
        self.btn_delay.setText("&Aplazar")
        self.btn_delay.setIcon(icon("chronometer", "alarm-symbolic", "appointment-soon", "clock"))
        self.btn_delay.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.btn_delay.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        delay_menu = QMenu(self)
        delays = QActionGroup(delay_menu)
        for seconds in DELAYS:
            a = delay_menu.addAction(delay_label(seconds), lambda s=seconds: self._set_delay(s))
            a.setCheckable(True)
            a.setChecked(seconds == self.delay)
            delays.addAction(a)
        self.btn_delay.setMenu(delay_menu)
        tb.addWidget(self.btn_delay)

        self.act_cancel = QAction(icon("process-stop", "dialog-cancel"), "&Cancelar", self)
        self.act_cancel.setShortcut("Esc")
        self.act_cancel.triggered.connect(self.cancel)
        self.act_cancel.setEnabled(False)
        tb.addAction(self.act_cancel)

        self.act_options = QAction(icon("configure", "preferences-system", "preferences-other"), "&Opciones", self)
        self.act_options.triggered.connect(self.options_requested.emit)
        tb.addAction(self.act_options)

        # Texto de ayuda, como en la herramienta clásica.
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(14, 10, 14, 12)
        row = QHBoxLayout()
        self.status = QLabel()
        self.status.setWordWrap(True)
        row.addWidget(self.status, 1)
        info = QLabel()
        info.setPixmap(icon("help-about", "dialog-information").pixmap(20, 20))
        row.addWidget(info, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(row)
        tips = QLabel(
            f"Atajos: <b>{config.SNIP_KEYS}</b> recortar · <b>{config.HISTORY_KEYS}</b> "
            "<a href='historial'>historial del portapapeles</a>"
        )
        tips.setTextFormat(Qt.TextFormat.RichText)
        tips.linkActivated.connect(lambda _l: self.history_requested.emit())
        tips.setEnabled(True)
        tips.setStyleSheet("color: palette(placeholder-text);")
        layout.addWidget(tips)
        self.setCentralWidget(body)

        self._set_mode(self.mode)
        self._set_status()
        self.setFixedWidth(max(self.sizeHint().width(), 470))
        self.adjustSize()

    # --- estado -------------------------------------------------------------

    def _set_mode(self, mode: str):
        if mode == "window" and config.session_type() not in ("x11", "macos"):
            mode = "rect"
        self.mode = mode
        _key, label, names = next(m for m in MODE_LABELS if m[0] == mode)
        self.btn_mode.setIcon(icon(*names))
        self.btn_mode.setToolTip(label)
        self.btn_mode.setMenu(mode_menu(self, self._pick_mode, checked=mode))
        self.settings.default_mode = mode
        self.settings.save()

    def _pick_mode(self, mode: str):
        self._set_mode(mode)
        self.start()

    def _set_delay(self, seconds: int):
        self.delay = seconds
        self.settings.default_delay = seconds
        self.settings.save()
        self._set_status()

    def _set_status(self, text: str | None = None):
        if text is None:
            text = "Selecciona el modo de recorte mediante el botón Modo o haz clic en el botón Nuevo."
            if self.delay:
                text += f" El recorte se hará {delay_label(self.delay).lower()} después."
        self.status.setText(text)

    # --- recorte ------------------------------------------------------------

    def start(self):
        if self.timer.isActive():
            return
        if self.delay == 0:
            self.snip_requested.emit(self.mode, 0)
            return
        self.remaining = self.delay
        self._toggle_busy(True)
        self._tick(first=True)
        self.timer.start()

    def _tick(self, first: bool = False):
        if not first:
            self.remaining -= 1
        if self.remaining <= 0:
            self.timer.stop()
            self._toggle_busy(False)
            self._set_status()
            self.snip_requested.emit(self.mode, 0)
            return
        self._set_status(f"El recorte empezará en {self.remaining} s… Prepara lo que quieras capturar.")

    def cancel(self):
        if self.timer.isActive():
            self.timer.stop()
        self._toggle_busy(False)
        self._set_status()

    def _toggle_busy(self, busy: bool):
        self.act_cancel.setEnabled(busy)
        self.btn_new.setEnabled(not busy)
        self.btn_mode.setEnabled(not busy)
        self.btn_delay.setEnabled(not busy)

    def present(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized)
        self.raise_()
        self.activateWindow()
