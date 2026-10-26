"""Editor del recorte, al estilo de la Herramienta Recortes de Windows 11.

Una sola barra con: Nuevo, Modo, Retraso · Pluma, Resaltador, Borrador, Formas,
Texto, Recortar · Deshacer, Rehacer · Guardar, Copiar, Abrir con, Más. Abajo, el
tamaño de la imagen y el zoom.

Cada anotación es un elemento independiente (trazo, forma o texto): el borrador
quita uno entero, como en Windows, y todo se puede deshacer, incluido el recorte
de la imagen.
"""

import math
import tempfile
from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QEvent, QPoint, QPointF, QRect, QRectF, QSize, QSizeF, Qt, QTimer, QUrl, pyqtSignal
from PyQt6.QtGui import (
    QAction, QActionGroup, QColor, QDesktopServices, QFont, QGuiApplication, QImage, QKeySequence,
    QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF,
)
from PyQt6.QtWidgets import (
    QColorDialog, QFileDialog, QGridLayout, QHBoxLayout, QInputDialog, QLabel, QMainWindow, QMenu,
    QMessageBox, QScrollArea, QSizePolicy, QSlider, QStatusBar, QToolBar, QToolButton, QVBoxLayout,
    QWidget, QWidgetAction,
)

from . import config, icons
from . import settings as settings_mod
from .icons import icon  # noqa: F401  (otras ventanas lo importan desde aquí)

PEN_COLORS = [
    ("Negro", "#000000"), ("Blanco", "#ffffff"), ("Rojo", "#e81123"), ("Naranja", "#f7630c"),
    ("Amarillo", "#ffb900"), ("Verde", "#107c10"), ("Azul", "#0063b1"), ("Morado", "#8764b8"),
]
HIGHLIGHT_COLORS = [
    ("Amarillo", "#ffeb00"), ("Verde", "#5df35d"), ("Celeste", "#5cd3ff"), ("Rosa", "#ff7ad9"),
]
HIGHLIGHT_ALPHA = 110
SHAPES = [
    ("rect", "Rectángulo", "shape-rect"),
    ("ellipse", "Elipse", "shape-ellipse"),
    ("arrow", "Flecha", "shape-arrow"),
    ("line", "Línea", "shape-line"),
]
ZOOMS = [0.25, 0.33, 0.5, 0.67, 0.75, 1.0, 1.25, 1.5, 2.0, 3.0, 4.0]


# --- elementos de dibujo ----------------------------------------------------------------


class Stroke:
    """Una anotación: trazo a mano (pluma/resaltador), forma o texto."""

    def __init__(self, tool: str, color: QColor, width: float, start: QPointF):
        self.tool = tool
        self.color = QColor(color)
        self.width = width
        self.start = QPointF(start)
        self.end = QPointF(start)
        self.text = ""
        self.path = QPainterPath(start)
        # Un clic sin arrastrar también deja un punto.
        self.path.lineTo(start + QPointF(0.01, 0.01))

    # Formas: el arrastre define el rectángulo o la línea.
    def shape_path(self) -> QPainterPath:
        if self.tool in ("pen", "highlighter"):
            return self.path
        path = QPainterPath()
        rect = QRectF(self.start, self.end).normalized()
        if self.tool == "rect":
            path.addRect(rect)
        elif self.tool == "ellipse":
            path.addEllipse(rect)
        elif self.tool in ("line", "arrow"):
            path.moveTo(self.start)
            path.lineTo(self.end)
        elif self.tool == "text":
            path.addRect(self.text_rect())
        return path

    def font(self) -> QFont:
        font = QFont()
        font.setPixelSize(int(10 + self.width * 3))
        font.setBold(True)
        return font

    def text_rect(self) -> QRectF:
        from PyQt6.QtGui import QFontMetricsF

        metrics = QFontMetricsF(self.font())
        lines = self.text.splitlines() or [""]
        width = max(metrics.horizontalAdvance(line) for line in lines)
        return QRectF(self.start, QSizeF(width + 2, metrics.lineSpacing() * len(lines) + 2))

    def pen(self) -> QPen:
        pen = QPen(self.color, self.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        if self.tool == "highlighter":
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        return pen

    def paint(self, painter: QPainter):
        if self.tool == "text":
            painter.setPen(self.color)
            painter.setFont(self.font())
            painter.drawText(self.text_rect(), Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop, self.text)
            return
        painter.setPen(self.pen())
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawPath(self.shape_path())
        if self.tool == "arrow":
            self._paint_arrow_head(painter)

    def _paint_arrow_head(self, painter: QPainter):
        dx, dy = self.end.x() - self.start.x(), self.end.y() - self.start.y()
        if math.hypot(dx, dy) < 2:
            return
        angle = math.atan2(dy, dx)
        size = 8 + self.width * 2.5
        head = QPolygonF([
            self.end,
            self.end - QPointF(size * math.cos(angle - 0.45), size * math.sin(angle - 0.45)),
            self.end - QPointF(size * math.cos(angle + 0.45), size * math.sin(angle + 0.45)),
        ])
        painter.setBrush(self.color)
        painter.drawPolygon(head)

    def hit(self, point: QPointF, radius: float = 6) -> bool:
        if self.tool == "text":
            return self.text_rect().adjusted(-radius, -radius, radius, radius).contains(point)
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.width, 1) + radius * 2)
        return stroker.createStroke(self.shape_path()).contains(point)

    def translate(self, offset: QPointF):
        self.path.translate(offset)
        self.start += offset
        self.end += offset


# --- lienzo -----------------------------------------------------------------------


class Canvas(QWidget):
    changed = pyqtSignal()
    crop_pending = pyqtSignal(bool)
    zoom_changed = pyqtSignal(float)

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.base = pixmap
        self.strokes: list[Stroke] = []
        self.undo_stack: list[tuple] = []
        self.redo_stack: list[tuple] = []
        self.tool = "pen"
        self.color = QColor("#e81123")
        self.pen_width = 4
        self.highlight_color = QColor(HIGHLIGHT_COLORS[0][1])
        self.highlight_width = 16
        self.current: Stroke | None = None
        self.crop_rect: QRectF | None = None
        self._crop_origin: QPointF | None = None
        self.zoom = 1.0
        self.setMouseTracking(True)
        self._resize()
        self._update_cursor()

    # --- tamaño y zoom ----------------------------------------------------------

    def image_size(self) -> QSize:
        return self.base.deviceIndependentSize().toSize()

    def _resize(self):
        size = self.image_size()
        self.setFixedSize(max(1, round(size.width() * self.zoom)), max(1, round(size.height() * self.zoom)))

    def set_zoom(self, zoom: float):
        self.zoom = max(0.1, min(8.0, zoom))
        self._resize()
        self.update()
        self.zoom_changed.emit(self.zoom)

    def _to_image(self, pos: QPointF) -> QPointF:
        return QPointF(pos.x() / self.zoom, pos.y() / self.zoom)

    # --- herramientas -----------------------------------------------------------

    def set_tool(self, tool: str):
        if self.tool == "crop" and tool != "crop":
            self.cancel_crop()
        self.tool = tool
        self._update_cursor()

    def _update_cursor(self):
        cursors = {
            "eraser": Qt.CursorShape.PointingHandCursor,
            "text": Qt.CursorShape.IBeamCursor,
        }
        self.setCursor(cursors.get(self.tool, Qt.CursorShape.CrossCursor))

    # --- deshacer -------------------------------------------------------------------

    def _record(self, undo, redo):
        self.undo_stack.append((undo, redo))
        self.redo_stack.clear()
        self.update()
        self.changed.emit()

    def _push(self, kind: str, stroke: Stroke, index: int):
        """Registra que se añadió («add») o quitó («remove») `stroke` en `index`."""
        def add():
            self.strokes.insert(index, stroke)

        def remove():
            self.strokes.remove(stroke)

        if kind == "add":
            self._record(remove, add)
        else:
            self._record(add, remove)

    def undo(self):
        if not self.undo_stack:
            return
        undo, redo = self.undo_stack.pop()
        undo()
        self.redo_stack.append((undo, redo))
        self._after_history()

    def redo(self):
        if not self.redo_stack:
            return
        undo, redo = self.redo_stack.pop()
        redo()
        self.undo_stack.append((undo, redo))
        self._after_history()

    def _after_history(self):
        self._resize()
        self.update()
        self.changed.emit()

    # --- recortar la imagen ---------------------------------------------------------------

    def apply_crop(self):
        if self.crop_rect is None:
            return
        rect = self.crop_rect.toAlignedRect().intersected(QRect(QPoint(0, 0), self.image_size()))
        self.cancel_crop()
        if rect.width() < 2 or rect.height() < 2:
            return
        dpr = self.base.devicePixelRatio()
        old_base, new_base = self.base, self.base.copy(
            QRect(round(rect.x() * dpr), round(rect.y() * dpr), round(rect.width() * dpr), round(rect.height() * dpr))
        )
        new_base.setDevicePixelRatio(dpr)
        offset = QPointF(-rect.x(), -rect.y())

        def do():
            self.base = new_base
            for s in self.strokes:
                s.translate(offset)

        def undo():
            self.base = old_base
            for s in self.strokes:
                s.translate(-offset)

        do()
        self._record(undo, do)
        self._resize()

    def cancel_crop(self):
        if self.crop_rect is not None:
            self.crop_rect = None
            self.crop_pending.emit(False)
            self.update()

    # --- edición con el ratón ----------------------------------------------------------

    def _erase_at(self, point: QPointF):
        for index in range(len(self.strokes) - 1, -1, -1):
            stroke = self.strokes[index]
            if stroke.hit(point):
                del self.strokes[index]
                self._push("remove", stroke, index)

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = self._to_image(event.position())
        if self.tool == "eraser":
            self._erase_at(pos)
        elif self.tool == "text":
            self._add_text(pos)
        elif self.tool == "crop":
            self._crop_origin = pos
            self.crop_rect = QRectF(pos, pos)
        elif self.tool == "highlighter":
            color = QColor(self.highlight_color)
            color.setAlpha(HIGHLIGHT_ALPHA)
            self.current = Stroke("highlighter", color, self.highlight_width, pos)
        else:
            self.current = Stroke(self.tool, self.color, self.pen_width, pos)
        self.update()

    def mouseMoveEvent(self, event):
        pos = self._to_image(event.position())
        if self.tool == "eraser" and event.buttons() & Qt.MouseButton.LeftButton:
            self._erase_at(pos)
        elif self.tool == "crop" and self._crop_origin is not None:
            self.crop_rect = QRectF(self._crop_origin, pos).normalized()
            self.update()
        elif self.current is not None:
            if self.current.tool in ("pen", "highlighter"):
                self.current.path.lineTo(pos)
            else:
                end = pos
                if event.modifiers() & Qt.KeyboardModifier.ShiftModifier:
                    end = _constrain(self.current.start, pos, self.current.tool)
                self.current.end = end
            self.update()

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.tool == "crop" and self._crop_origin is not None:
            self._crop_origin = None
            if self.crop_rect and self.crop_rect.width() > 3 and self.crop_rect.height() > 3:
                self.crop_pending.emit(True)
            else:
                self.cancel_crop()
            return
        if self.current is not None:
            self.strokes.append(self.current)
            self._push("add", self.current, len(self.strokes) - 1)
            self.current = None

    def _add_text(self, pos: QPointF):
        text, ok = QInputDialog.getMultiLineText(self, "Texto", "Escribe el texto:")
        if not ok or not text.strip():
            return
        stroke = Stroke("text", self.color, self.pen_width, pos)
        stroke.text = text
        self.strokes.append(stroke)
        self._push("add", stroke, len(self.strokes) - 1)

    def keyPressEvent(self, event):
        if self.crop_rect is not None and event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self.apply_crop()
        elif self.crop_rect is not None and event.key() == Qt.Key.Key_Escape:
            self.cancel_crop()
        else:
            super().keyPressEvent(event)

    # --- pintado ----------------------------------------------------------------

    def _paint_strokes(self, painter: QPainter, strokes):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        for stroke in strokes:
            stroke.paint(painter)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self.zoom < 1)
        p.scale(self.zoom, self.zoom)
        p.drawPixmap(QPointF(0, 0), self.base)
        self._paint_strokes(p, self.strokes + ([self.current] if self.current else []))
        if self.crop_rect is not None:
            outside = QPainterPath()
            outside.addRect(QRectF(QPointF(0, 0), QSizeF(self.image_size())))
            inside = QPainterPath()
            inside.addRect(self.crop_rect)
            p.fillPath(outside.subtracted(inside), QColor(0, 0, 0, 120))
            p.setPen(QPen(QColor("white"), 1.5 / self.zoom, Qt.PenStyle.DashLine))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawRect(self.crop_rect)
        p.end()

    def render_image(self) -> QImage:
        """Recorte con las anotaciones, a la resolución real de la pantalla."""
        image = self.base.toImage().convertToFormat(QImage.Format.Format_ARGB32)
        dpr = self.base.devicePixelRatio()
        image.setDevicePixelRatio(1)
        if self.strokes:
            p = QPainter(image)
            p.scale(dpr, dpr)
            self._paint_strokes(p, self.strokes)
            p.end()
        return image


def _constrain(start: QPointF, pos: QPointF, tool: str) -> QPointF:
    """Con Shift: cuadrados, círculos y líneas a 45°."""
    dx, dy = pos.x() - start.x(), pos.y() - start.y()
    if tool in ("rect", "ellipse"):
        side = max(abs(dx), abs(dy))
        return QPointF(start.x() + math.copysign(side, dx or 1), start.y() + math.copysign(side, dy or 1))
    angle = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4)
    length = math.hypot(dx, dy)
    return QPointF(start.x() + length * math.cos(angle), start.y() + length * math.sin(angle))


# --- paleta de color y grosor -----------------------------------------------------------


class InkPopup(QWidget):
    """Colores en círculos y control de grosor, como el desplegable de la pluma de Windows."""

    def __init__(self, colors, current: QColor, width: int, width_range, on_color, on_width, custom=True):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        grid = QGridLayout()
        grid.setSpacing(8)
        self.buttons = []
        for i, (name, value) in enumerate(colors):
            btn = QToolButton()
            btn.setToolTip(name)
            btn.setCheckable(True)
            btn.setChecked(QColor(value) == QColor(current.rgb()))
            btn.setFixedSize(28, 28)
            btn.setStyleSheet(
                f"QToolButton {{ background: {value}; border: 1px solid rgba(128,128,128,0.6); border-radius: 14px; }}"
                "QToolButton:checked { border: 3px solid palette(highlight); }"
            )
            btn.clicked.connect(lambda _c=False, v=value: on_color(QColor(v)))
            grid.addWidget(btn, i // 4, i % 4)
            self.buttons.append(btn)
        layout.addLayout(grid)
        if custom:
            more = QToolButton()
            more.setText("Más colores…")
            more.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextOnly)
            more.clicked.connect(lambda: self._custom(current, on_color))
            layout.addWidget(more, 0, Qt.AlignmentFlag.AlignLeft)
        row = QHBoxLayout()
        row.addWidget(QLabel("Grosor"))
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setRange(*width_range)
        slider.setValue(width)
        slider.setMinimumWidth(140)
        self.value = QLabel(str(width))
        self.value.setMinimumWidth(22)
        slider.valueChanged.connect(lambda v: (self.value.setText(str(v)), on_width(v)))
        row.addWidget(slider, 1)
        row.addWidget(self.value)
        layout.addLayout(row)

    def _custom(self, current, on_color):
        color = QColorDialog.getColor(current, self, "Color de la pluma")
        if color.isValid():
            on_color(color)


def _toolbar_style() -> str:
    text = QGuiApplication.palette().windowText().color()
    r, g, b = text.red(), text.green(), text.blue()
    return f"""
        QToolBar#herramientas {{ border: none; padding: 6px 8px; spacing: 2px; }}
        QToolBar#herramientas QToolButton {{
            border: 1px solid transparent; border-radius: 6px; padding: 5px; margin: 0 1px;
        }}
        QToolBar#herramientas QToolButton:hover {{ background: rgba({r},{g},{b},0.08); }}
        QToolBar#herramientas QToolButton:pressed {{ background: rgba({r},{g},{b},0.14); }}
        QToolBar#herramientas QToolButton:checked {{
            background: rgba({r},{g},{b},0.10); border: 1px solid rgba({r},{g},{b},0.35);
        }}
        QToolBar#herramientas QToolButton[popupMode="1"] {{ padding-right: 14px; }}
        QToolBar#herramientas QToolButton::menu-button {{ border: none; width: 12px; }}
        QToolBar#herramientas::separator {{ background: rgba({r},{g},{b},0.18); width: 1px; margin: 6px 6px; }}
        QScrollArea#lienzo {{ border: none; background: rgba({r},{g},{b},0.06); }}
        QScrollArea#lienzo > QWidget > QWidget {{ background: transparent; }}
    """


# --- ventana ------------------------------------------------------------------------


class EditorWindow(QMainWindow):
    """Ventana del editor con el último recorte."""

    new_snip_requested = pyqtSignal(str)  # modo
    options_requested = pyqtSignal()
    history_requested = pyqtSignal()

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.setWindowIcon(icons.app_icon())
        self.saved_path: Path | None = None
        self.dirty = False
        self.canvas: Canvas | None = None
        self.settings = settings_mod.current
        self.shape = "rect"
        self.pending_delay = QTimer(self)
        self.pending_delay.setSingleShot(True)
        self.pending_delay.timeout.connect(lambda: self.new_snip_requested.emit(self.settings.default_mode))

        self.scroll = QScrollArea()
        self.scroll.setObjectName("lienzo")
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidgetResizable(False)
        self.scroll.viewport().installEventFilter(self)  # Ctrl+rueda = zoom
        self.setCentralWidget(self.scroll)

        self._build_actions()
        self._build_toolbar()
        self._build_statusbar()
        self.setStyleSheet(_toolbar_style())
        self.load(pixmap)

    # --- acciones ------------------------------------------------------------------

    def _action(self, text, icon_name, shortcut=None, slot=None, checkable=False, tip=None):
        action = QAction(icons.make(icon_name), text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if slot:
            action.triggered.connect(slot)
        action.setCheckable(checkable)
        hint = tip or text.replace("&", "")
        action.setToolTip(f"{hint} ({QKeySequence(shortcut).toString(QKeySequence.SequenceFormat.NativeText)})"
                          if shortcut else hint)
        self.addAction(action)  # los atajos funcionan aunque el botón no esté visible
        return action

    def _build_actions(self):
        self.act_new = self._action("Nuevo recorte", "new", "Ctrl+N", self._new_snip)
        self.act_save = self._action("Guardar como", "save", "Ctrl+S", self.save_as)
        self.act_copy = self._action("Copiar", "copy", "Ctrl+C", self.copy)
        self.act_open = self._action("Abrir con la app predeterminada", "open-with", "Ctrl+Shift+O", self.open_external)
        self.act_undo = self._action("Deshacer", "undo", "Ctrl+Z", lambda: self.canvas.undo())
        self.act_redo = self._action("Rehacer", "redo", "Ctrl+Y", lambda: self.canvas.redo())

        self.tools = QActionGroup(self)
        self.act_pen = self._action("Pluma", "pen", "Ctrl+P", lambda: self._tool("pen"), True)
        self.act_high = self._action("Resaltador", "highlighter", "Ctrl+H", lambda: self._tool("highlighter"), True)
        self.act_eraser = self._action("Borrador", "eraser", "Ctrl+E", lambda: self._tool("eraser"), True)
        self.act_shape = self._action("Formas", "shape-rect", "Ctrl+R", lambda: self._tool(self.shape), True,
                                      tip="Formas (con Shift: cuadrados, círculos y 45°)")
        self.act_text = self._action("Texto", "text", "Ctrl+T", lambda: self._tool("text"), True)
        self.act_crop = self._action("Recortar imagen", "crop", "Ctrl+Shift+R", lambda: self._tool("crop"), True,
                                     tip="Recortar imagen (arrastra y pulsa Intro)")
        for a in (self.act_pen, self.act_high, self.act_eraser, self.act_shape, self.act_text, self.act_crop):
            self.tools.addAction(a)
        self.act_pen.setChecked(True)

        self.act_crop_apply = self._action("Aplicar recorte", "check", None, lambda: self.canvas.apply_crop())
        self.act_crop_cancel = self._action("Cancelar recorte", "close", None, lambda: self.canvas.cancel_crop())

        self.act_zoom_in = self._action("Acercar", "zoom-in", "Ctrl++", lambda: self._zoom_step(1))
        self.act_zoom_out = self._action("Alejar", "zoom-out", "Ctrl+-", lambda: self._zoom_step(-1))
        self.act_zoom_fit = self._action("Ajustar a la ventana", "zoom-fit", "Ctrl+0", self.fit_zoom)
        self.act_zoom_100 = self._action("Tamaño real", "zoom-fit", "Ctrl+1", lambda: self.canvas.set_zoom(1.0))
        self.act_close = self._action("Cerrar", "close", "Ctrl+W", self.close)

    def _tool_button(self, action: QAction, menu: QMenu | None = None) -> QToolButton:
        btn = QToolButton()
        btn.setDefaultAction(action)
        btn.setIconSize(QSize(20, 20))
        btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        btn.setAutoRaise(True)
        if menu is not None:
            btn.setMenu(menu)
            btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        return btn

    def _menu_button(self, icon_name: str, tip: str, menu: QMenu) -> QToolButton:
        btn = QToolButton()
        btn.setIcon(icons.make(icon_name))
        btn.setToolTip(tip)
        btn.setIconSize(QSize(20, 20))
        btn.setAutoRaise(True)
        btn.setMenu(menu)
        btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        return btn

    def _spacer(self) -> QWidget:
        spacer = QWidget()
        spacer.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        return spacer

    def _build_toolbar(self):
        from .main_window import DELAYS, MODE_LABELS, delay_label

        tb = QToolBar("Herramientas", self)
        tb.setObjectName("herramientas")
        tb.setMovable(False)
        tb.setFloatable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setContextMenuPolicy(Qt.ContextMenuPolicy.PreventContextMenu)
        self.addToolBar(tb)
        self.toolbar = tb

        # Nuevo · Modo · Retraso
        tb.addWidget(self._tool_button(self.act_new))
        mode_menu = QMenu(self)
        group = QActionGroup(mode_menu)
        window_ok = config.session_type() in ("x11", "macos")
        for key, label, icon_names in MODE_LABELS:
            own = icons.ALIASES.get(icon_names[0], icon_names[0])
            a = mode_menu.addAction(icons.make(own), label, lambda k=key: self._set_mode(k))
            a.setCheckable(True)
            a.setChecked(key == self.settings.default_mode)
            a.setEnabled(key != "window" or window_ok)
            group.addAction(a)
        self.mode_button = self._menu_button(self._mode_icon(), "Modo de recorte", mode_menu)
        tb.addWidget(self.mode_button)
        delay_menu = QMenu(self)
        delays = QActionGroup(delay_menu)
        for seconds in DELAYS:
            a = delay_menu.addAction(delay_label(seconds), lambda s=seconds: self._set_delay(s))
            a.setCheckable(True)
            a.setChecked(seconds == self.settings.default_delay)
            delays.addAction(a)
        self.delay_button = self._menu_button("delay", "Retraso del recorte", delay_menu)
        tb.addWidget(self.delay_button)

        tb.addWidget(self._spacer())

        # Herramientas de dibujo
        self.pen_button = self._tool_button(self.act_pen, QMenu(self))
        self.pen_button.menu().aboutToShow.connect(self._fill_pen_menu)
        tb.addWidget(self.pen_button)
        self.high_button = self._tool_button(self.act_high, QMenu(self))
        self.high_button.menu().aboutToShow.connect(self._fill_highlight_menu)
        tb.addWidget(self.high_button)
        tb.addWidget(self._tool_button(self.act_eraser))
        shape_menu = QMenu(self)
        shapes = QActionGroup(shape_menu)
        for key, label, icon_name in SHAPES:
            a = shape_menu.addAction(icons.make(icon_name), label, lambda k=key: self._set_shape(k))
            a.setCheckable(True)
            a.setChecked(key == self.shape)
            shapes.addAction(a)
        tb.addWidget(self._tool_button(self.act_shape, shape_menu))
        tb.addWidget(self._tool_button(self.act_text))
        tb.addWidget(self._tool_button(self.act_crop))
        self.crop_apply_widget = tb.addWidget(self._tool_button(self.act_crop_apply))
        self.crop_cancel_widget = tb.addWidget(self._tool_button(self.act_crop_cancel))
        tb.addSeparator()
        tb.addWidget(self._tool_button(self.act_undo))
        tb.addWidget(self._tool_button(self.act_redo))

        tb.addWidget(self._spacer())

        # Guardar · Copiar · Abrir con · Más
        tb.addWidget(self._tool_button(self.act_save))
        tb.addWidget(self._tool_button(self.act_copy))
        tb.addWidget(self._tool_button(self.act_open))
        more = QMenu(self)
        more.addAction(icons.make("folder"), "Mostrar en la carpeta", self.show_in_folder)
        more.addAction(icons.make("history"), "Historial del portapapeles", self.history_requested.emit)
        more.addSeparator()
        more.addAction(icons.make("settings"), "Opciones…", self.options_requested.emit)
        more.addSeparator()
        more.addAction(self.act_close)
        tb.addWidget(self._menu_button("more", "Más opciones", more))
        self._set_crop_buttons(False)

    def _build_statusbar(self):
        bar = QStatusBar(self)
        self.setStatusBar(bar)
        self.size_label = QLabel()
        bar.addWidget(self.size_label)
        self.zoom_label = QLabel()
        self.zoom_label.setMinimumWidth(44)
        self.zoom_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        for action in (self.act_zoom_out,):
            bar.addPermanentWidget(self._tool_button(action))
        bar.addPermanentWidget(self.zoom_label)
        for action in (self.act_zoom_in, self.act_zoom_fit):
            bar.addPermanentWidget(self._tool_button(action))

    # --- estado de la barra ---------------------------------------------------------

    def _mode_icon(self) -> str:
        return {"rect": "mode-rect", "window": "mode-window", "full": "mode-full", "free": "mode-free"}.get(
            self.settings.default_mode, "mode-rect")

    def _set_mode(self, mode: str):
        self.settings.default_mode = mode
        self.settings.save()
        self.mode_button.setIcon(icons.make(self._mode_icon()))

    def _set_delay(self, seconds: int):
        self.settings.default_delay = seconds
        self.settings.save()

    def _new_snip(self):
        delay = self.settings.default_delay
        if delay:
            self.statusBar().showMessage(f"El recorte empezará en {delay} s…", delay * 1000)
            self.pending_delay.start(delay * 1000)
        else:
            self.new_snip_requested.emit(self.settings.default_mode)

    def _set_shape(self, shape: str):
        self.shape = shape
        icon_name = next(i for k, _l, i in SHAPES if k == shape)
        self.act_shape.setIcon(icons.make(icon_name, accent=self.canvas.color.name()))
        self.act_shape.setChecked(True)
        self._tool(shape)

    def _refresh_ink_icons(self):
        """La pluma y las formas muestran el color elegido, como en Windows."""
        pen = self.canvas.color.name()
        self.act_pen.setIcon(icons.make("pen", accent=pen))
        icon_name = next(i for k, _l, i in SHAPES if k == self.shape)
        self.act_shape.setIcon(icons.make(icon_name, accent=pen))
        self.act_text.setIcon(icons.make("text", accent=pen))
        self.act_high.setIcon(icons.make("highlighter", accent=self.canvas.highlight_color.name()))

    def _fill_pen_menu(self):
        menu = self.pen_button.menu()
        menu.clear()
        popup = InkPopup(PEN_COLORS, self.canvas.color, self.canvas.pen_width, (1, 20),
                         lambda c: (self._pen_color(c), menu.close()), self._pen_width)
        action = QWidgetAction(menu)
        action.setDefaultWidget(popup)
        menu.addAction(action)

    def _fill_highlight_menu(self):
        menu = self.high_button.menu()
        menu.clear()
        popup = InkPopup(HIGHLIGHT_COLORS, self.canvas.highlight_color, self.canvas.highlight_width, (6, 40),
                         lambda c: (self._highlight_color(c), menu.close()), self._highlight_width, custom=False)
        action = QWidgetAction(menu)
        action.setDefaultWidget(popup)
        menu.addAction(action)

    def _pen_color(self, color: QColor):
        self.canvas.color = QColor(color)
        self._refresh_ink_icons()
        if self.canvas.tool in ("highlighter", "eraser", "crop"):
            self.act_pen.setChecked(True)
            self._tool("pen")

    def _pen_width(self, width: int):
        self.canvas.pen_width = width

    def _highlight_color(self, color: QColor):
        self.canvas.highlight_color = QColor(color)
        self._refresh_ink_icons()
        self.act_high.setChecked(True)
        self._tool("highlighter")

    def _highlight_width(self, width: int):
        self.canvas.highlight_width = width

    def _tool(self, tool: str):
        self.canvas.set_tool(tool)
        self.canvas.setFocus()

    def _set_crop_buttons(self, visible: bool):
        self.crop_apply_widget.setVisible(visible)
        self.crop_cancel_widget.setVisible(visible)

    # --- contenido ------------------------------------------------------------------

    def load(self, pixmap: QPixmap, saved_path: Path | None = None):
        old = self.canvas
        self.canvas = Canvas(pixmap)
        if old is not None:
            self.canvas.color, self.canvas.pen_width = old.color, old.pen_width
            self.canvas.highlight_color, self.canvas.highlight_width = old.highlight_color, old.highlight_width
        checked = self.tools.checkedAction()
        tool = {self.act_high: "highlighter", self.act_eraser: "eraser", self.act_shape: self.shape,
                self.act_text: "text", self.act_crop: "crop"}.get(checked, "pen")
        self.canvas.set_tool(tool)
        self.canvas.changed.connect(self._on_changed)
        self.canvas.crop_pending.connect(self._set_crop_buttons)
        self.canvas.zoom_changed.connect(self._on_zoom)
        self.scroll.setWidget(self.canvas)
        self.saved_path = saved_path
        self.dirty = False
        self._refresh_ink_icons()
        self._on_changed(mark_dirty=False)
        self._fit_window()
        QTimer.singleShot(0, self.fit_zoom)

    def _fit_window(self):
        screen = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        size = self.canvas.image_size()
        chrome = QSize(60, self.toolbar.sizeHint().height() + 70)
        width = min(max(size.width() + chrome.width(), 760), int(screen.width() * 0.9))
        height = min(max(size.height() + chrome.height(), 420), int(screen.height() * 0.9))
        self.resize(width, height)

    def fit_zoom(self):
        """Como Windows: si el recorte no cabe, se reduce; si cabe, se ve a tamaño real."""
        view = self.scroll.viewport().size()
        size = self.canvas.image_size()
        if size.width() <= 0 or size.height() <= 0:
            return
        scale = min((view.width() - 24) / size.width(), (view.height() - 24) / size.height(), 1.0)
        self.canvas.set_zoom(max(scale, 0.1))

    def _zoom_step(self, direction: int):
        current = self.canvas.zoom
        if direction > 0:
            target = next((z for z in ZOOMS if z > current + 0.001), ZOOMS[-1])
        else:
            target = next((z for z in reversed(ZOOMS) if z < current - 0.001), ZOOMS[0])
        self.canvas.set_zoom(target)

    def _on_zoom(self, zoom: float):
        self.zoom_label.setText(f"{round(zoom * 100)} %")

    def eventFilter(self, obj, event):
        if (
            event.type() == QEvent.Type.Wheel
            and event.modifiers() & Qt.KeyboardModifier.ControlModifier
        ):
            self._zoom_step(1 if event.angleDelta().y() > 0 else -1)
            return True
        return super().eventFilter(obj, event)

    def _on_changed(self, mark_dirty: bool = True):
        if mark_dirty:
            self.dirty = True
        self.act_undo.setEnabled(bool(self.canvas and self.canvas.undo_stack))
        self.act_redo.setEnabled(bool(self.canvas and self.canvas.redo_stack))
        size = self.canvas.render_image().size() if self.canvas else QSize()
        self.size_label.setText(f"{size.width()} × {size.height()} px")
        name = self.saved_path.name if self.saved_path else "Recorte"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} - Herramienta Recortes")

    # --- archivo ----------------------------------------------------------------------

    def copy(self):
        QGuiApplication.clipboard().setImage(self.canvas.render_image())
        self.statusBar().showMessage("Copiado al portapapeles", 2500)

    def _flattened(self, image: QImage) -> QImage:
        flat = QImage(image.size(), QImage.Format.Format_RGB32)
        flat.fill(Qt.GlobalColor.white)
        p = QPainter(flat)
        p.drawImage(0, 0, image)
        p.end()
        return flat

    def save_as(self) -> bool:
        folder = self.settings.screenshots_dir()
        folder.mkdir(parents=True, exist_ok=True)
        default = self.saved_path or folder / f"Captura de pantalla {datetime.now():%Y-%m-%d %H%M%S}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Guardar como", str(default),
            "Imagen PNG (*.png);;Imagen JPEG (*.jpg *.jpeg);;Imagen BMP (*.bmp)",
        )
        if not path:
            return False
        target = Path(path)
        if not target.suffix:
            target = target.with_suffix(".png")
        image = self.canvas.render_image()
        if target.suffix.lower() in (".jpg", ".jpeg", ".bmp"):
            # Sin transparencia: el fondo de la forma libre queda en blanco.
            image = self._flattened(image)
        if not image.save(str(target)):
            QMessageBox.warning(self, config.APP_NAME, f"No se pudo guardar en:\n{target}")
            return False
        self.saved_path = target
        self.dirty = False
        self._on_changed(mark_dirty=False)
        self.statusBar().showMessage(f"Guardado en {target}", 4000)
        return True

    def open_external(self):
        """Abre el recorte (con anotaciones) en la app de imágenes predeterminada, p. ej. para editarlo más."""
        folder = Path(tempfile.gettempdir()) / "cutter"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"Recorte {datetime.now():%Y-%m-%d %H%M%S}.png"
        self.canvas.render_image().save(str(path), "PNG")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def show_in_folder(self):
        folder = self.saved_path.parent if self.saved_path else self.settings.screenshots_dir()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def closeEvent(self, event):
        if self.dirty:
            answer = QMessageBox.question(
                self, config.APP_NAME, "¿Quieres guardar los cambios del recorte?",
                QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Save,
            )
            if answer == QMessageBox.StandardButton.Cancel or (
                answer == QMessageBox.StandardButton.Save and not self.save_as()
            ):
                event.ignore()
                return
        self.pending_delay.stop()
        event.accept()
