"""Capa de selección que aparece con Super+Shift+S.

Congela la pantalla, la oscurece y muestra arriba la barra de modos de la
Herramienta Recortes: rectángulo, ventana, pantalla completa y forma libre.
"""

from PyQt6.QtCore import QPoint, QPointF, QRect, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QBrush, QColor, QCursor, QGuiApplication, QIcon, QKeySequence, QPainter,
    QPainterPath, QPen, QPixmap, QShortcut,
)
from PyQt6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QToolButton, QWidget

from . import config
from .windows import list_windows

MODES = [
    ("rect", "Recorte rectangular", "selection-rectangular", "▭"),
    ("window", "Recorte de ventana", "window", "🗔"),
    ("full", "Recorte de pantalla completa", "view-fullscreen", "⛶"),
    ("free", "Recorte de forma libre", "draw-freehand", "✎"),
]

DIM = QColor(0, 0, 0, 110)
ACCENT = QColor("#4cc2ff")


def _span(a: QPoint, b: QPoint) -> QRect:
    """Rectángulo entre dos puntos, sin el píxel extra que añade QRect(QPoint, QPoint)."""
    return QRect(min(a.x(), b.x()), min(a.y(), b.y()), abs(a.x() - b.x()), abs(a.y() - b.y()))


class ModeBar(QFrame):
    mode_changed = pyqtSignal(str)
    cancelled = pyqtSignal()

    def __init__(self, parent, mode: str, window_mode_available: bool):
        super().__init__(parent)
        self.setObjectName("modebar")
        self.setStyleSheet(
            """
            #modebar { background: #2b2b2b; border: 1px solid #3d3d3d; border-radius: 8px; }
            QToolButton { color: white; background: transparent; border: none; border-radius: 4px;
                          min-width: 40px; min-height: 36px; font-size: 18px; }
            QToolButton:hover { background: #3a3a3a; }
            QToolButton:checked { background: #454545; border-bottom: 2px solid #4cc2ff; }
            QToolButton:disabled { color: #666; }
            """
        )
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 4, 6, 4)
        layout.setSpacing(4)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        for key, label, icon_name, fallback in MODES:
            btn = QToolButton(self)
            btn.setCheckable(True)
            btn.setToolTip(label)
            btn.setAccessibleName(label)
            icon = QIcon.fromTheme(icon_name)
            if icon.isNull():
                btn.setText(fallback)
            else:
                btn.setIcon(icon)
                btn.setIconSize(QSize(22, 22))
            if key == "window" and not window_mode_available:
                btn.setEnabled(False)
                btn.setToolTip(label + " (no disponible en Wayland)")
            btn.setChecked(key == mode)
            btn.clicked.connect(lambda _=False, k=key: self.mode_changed.emit(k))
            self.group.addButton(btn)
            layout.addWidget(btn)

        sep = QFrame(self)
        sep.setFrameShape(QFrame.Shape.VLine)
        sep.setStyleSheet("color: #555;")
        layout.addWidget(sep)

        close = QToolButton(self)
        close.setText("✕")
        close.setToolTip("Cerrar (Esc)")
        close.clicked.connect(self.cancelled.emit)
        layout.addWidget(close)
        self.adjustSize()


class SnipOverlay(QWidget):
    """Una capa por monitor. Todas comparten el modo a través de la sesión."""

    def __init__(self, session, screen, pixmap: QPixmap, show_bar: bool):
        super().__init__(None)
        self.session = session
        self.screen_ = screen
        self.pixmap = pixmap
        self.origin: QPoint | None = None
        self.current: QPoint | None = None
        self.path = QPainterPath()
        self.hover_window: QRect | None = None

        self.setWindowTitle(config.APP_NAME)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.BypassWindowManagerHint
            if config.session_type() == "x11"
            else Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.setMouseTracking(True)
        self.setCursor(Qt.CursorShape.CrossCursor)
        self.setGeometry(screen.geometry())

        self.bar = None
        if show_bar:
            self.bar = ModeBar(self, session.mode, session.window_mode_available)
            self.bar.mode_changed.connect(session.set_mode)
            self.bar.cancelled.connect(session.cancel)
            self.bar.move((self.width() - self.bar.width()) // 2, 12)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=session.cancel)

    def show_on_screen(self):
        self.setScreen(self.screen_)
        self.showFullScreen()
        self.raise_()
        self.activateWindow()

    # --- coordenadas -------------------------------------------------------

    def _to_pixmap_rect(self, rect: QRect) -> QRect:
        dpr = self.pixmap.devicePixelRatio()
        return QRect(
            round(rect.x() * dpr), round(rect.y() * dpr),
            round(rect.width() * dpr), round(rect.height() * dpr),
        )

    def _local_window_rect(self) -> QRect | None:
        """Ventana bajo el cursor, en coordenadas de este monitor."""
        pos = QCursor.pos()
        for rect in self.session.windows:
            if rect.contains(pos):
                local = rect.translated(-self.screen_.geometry().topLeft())
                return local.intersected(self.rect())
        return None

    # --- eventos -----------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            if event.button() == Qt.MouseButton.RightButton:
                self.session.cancel()
            return
        mode = self.session.mode
        pos = event.position().toPoint()
        if mode == "full":
            self._finish_rect(self.rect())
        elif mode == "window":
            rect = self._local_window_rect()
            if rect is not None and not rect.isEmpty():
                self._finish_rect(rect)
        elif mode == "rect":
            self.origin = self.current = pos
        elif mode == "free":
            self.path = QPainterPath(QPointF(pos))
            self.origin = pos

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()
        if self.session.mode == "window":
            self.hover_window = self._local_window_rect()
        elif self.origin is not None:
            self.current = pos
            if self.session.mode == "free":
                self.path.lineTo(QPointF(pos))
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or self.origin is None:
            return
        mode = self.session.mode
        if mode == "rect":
            rect = _span(self.origin, event.position().toPoint())
            self.origin = None
            if rect.width() < 3 or rect.height() < 3:
                self.update()
                return
            self._finish_rect(rect)
        elif mode == "free":
            self.path.closeSubpath()
            self.origin = None
            if self.path.boundingRect().width() < 3:
                self.update()
                return
            self._finish_path(self.path)

    def _finish_rect(self, rect: QRect):
        self.session.finish(self.pixmap.copy(self._to_pixmap_rect(rect)))

    def _finish_path(self, path: QPainterPath):
        bounds = path.boundingRect().toAlignedRect().intersected(self.rect())
        src = self._to_pixmap_rect(bounds)
        dpr = self.pixmap.devicePixelRatio()
        result = QPixmap(src.size())
        result.fill(Qt.GlobalColor.transparent)
        p = QPainter(result)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(dpr, dpr)
        p.translate(-bounds.topLeft().toPointF())
        p.setClipPath(path)
        p.scale(1 / dpr, 1 / dpr)
        p.drawPixmap(QPoint(round(bounds.x() * dpr), round(bounds.y() * dpr)), self.pixmap, src)
        p.end()
        self.session.finish(result)

    # --- pintado -----------------------------------------------------------

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.drawPixmap(self.rect(), self.pixmap)

        highlight = QPainterPath()
        mode = self.session.mode
        if mode == "rect" and self.origin is not None and self.current is not None:
            highlight.addRect(QRectF(_span(self.origin, self.current)))
        elif mode == "free" and self.origin is not None:
            highlight = QPainterPath(self.path)
            highlight.closeSubpath()
        elif mode == "window" and self.hover_window is not None:
            highlight.addRect(QRectF(self.hover_window))
        elif mode == "full" and self.rect().contains(self.mapFromGlobal(QCursor.pos())):
            highlight.addRect(QRectF(self.rect()))

        dim = QPainterPath()
        dim.addRect(QRectF(self.rect()))
        p.fillPath(dim.subtracted(highlight), QBrush(DIM))
        if not highlight.isEmpty():
            p.setPen(QPen(ACCENT if mode != "free" else QColor("white"), 2))
            p.drawPath(highlight)
        p.end()


class SnipSession:
    """Coordina las capas de todos los monitores durante un recorte."""

    def __init__(self, shots, on_done, mode: str = "rect"):
        self.on_done = on_done
        self.window_mode_available = config.session_type() == "x11"
        self.mode = mode if (mode != "window" or self.window_mode_available) else "rect"
        self.windows = list_windows() if self.window_mode_available else []
        self.done = False

        cursor_screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        self.overlays = [
            SnipOverlay(self, screen, pixmap, show_bar=(screen is cursor_screen))
            for screen, pixmap in shots
        ]
        if not any(o.bar for o in self.overlays) and self.overlays:
            first = self.overlays[0]
            first.bar = ModeBar(first, self.mode, self.window_mode_available)
            first.bar.mode_changed.connect(self.set_mode)
            first.bar.cancelled.connect(self.cancel)
            first.bar.move((first.width() - first.bar.width()) // 2, 12)

    def start(self):
        for overlay in self.overlays:
            overlay.show_on_screen()
        for overlay in self.overlays:
            if overlay.bar is not None:
                overlay.activateWindow()

    def set_mode(self, mode: str):
        self.mode = mode
        for overlay in self.overlays:
            overlay.origin = None
            if overlay.bar:
                for btn, (key, *_rest) in zip(overlay.bar.group.buttons(), MODES):
                    btn.setChecked(key == mode)
            overlay.update()

    def finish(self, pixmap: QPixmap):
        if self.done:
            return
        self.done = True
        # En Wayland solo se puede escribir en el portapapeles mientras una ventana
        # nuestra tiene el foco, por eso se entrega el resultado antes de cerrar.
        self.on_done(pixmap)
        self._close()

    def cancel(self):
        if self.done:
            return
        self.done = True
        self.on_done(None)
        self._close()

    def _close(self):
        for overlay in self.overlays:
            overlay.close()
        self.overlays = []
