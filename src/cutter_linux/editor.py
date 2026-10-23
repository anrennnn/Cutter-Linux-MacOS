"""Editor del recorte: pluma, resaltador, borrador, copiar y guardar.

Es la ventana que abre la Herramienta Recortes clásica después de hacer un
recorte con «Nuevo». Las anotaciones se guardan como trazos independientes, así
el borrador quita un trazo entero (como en Windows) y se puede deshacer.
"""

from datetime import datetime
from pathlib import Path

from PyQt6.QtCore import QPointF, QRectF, QSize, Qt, pyqtSignal
from PyQt6.QtGui import (
    QAction, QActionGroup, QColor, QGuiApplication, QIcon, QImage, QKeySequence, QPainter,
    QPainterPath, QPainterPathStroker, QPen, QPixmap,
)
from PyQt6.QtWidgets import (
    QColorDialog, QFileDialog, QMainWindow, QMenu, QMessageBox, QScrollArea, QToolBar,
    QToolButton, QWidget,
)

from . import config
from . import settings as settings_mod

PEN_COLORS = [
    ("Rojo", "#e81123"),
    ("Azul", "#0063b1"),
    ("Negro", "#000000"),
    ("Verde", "#107c10"),
]
PEN_WIDTHS = [("Fina", 2), ("Media", 4), ("Gruesa", 8)]
HIGHLIGHTER = QColor(255, 235, 0, 110)


def icon(*names: str) -> QIcon:
    """Primer icono disponible en el tema del sistema (o el propio de Cutter)."""
    for name in names:
        for candidate in (name, name + "-symbolic"):
            found = QIcon.fromTheme(candidate)
            if not found.isNull():
                return found
    if config.APP_ID in names:
        return QIcon(str(Path(__file__).with_name("cutter-linux.svg")))
    return QIcon()


class Stroke:
    def __init__(self, tool: str, color: QColor, width: float, start: QPointF):
        self.tool = tool
        self.color = QColor(color)
        self.width = width
        self.path = QPainterPath(start)
        # Un clic sin arrastrar también deja un punto.
        self.path.lineTo(start + QPointF(0.01, 0.01))

    def pen(self) -> QPen:
        pen = QPen(self.color, self.width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin)
        if self.tool == "highlighter":
            pen.setCapStyle(Qt.PenCapStyle.SquareCap)
        return pen

    def hit(self, point: QPointF, radius: float = 6) -> bool:
        stroker = QPainterPathStroker()
        stroker.setWidth(max(self.width, 1) + radius * 2)
        return stroker.createStroke(self.path).contains(point)


class Canvas(QWidget):
    changed = pyqtSignal()

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.base = pixmap
        self.strokes: list[Stroke] = []
        self.undo_stack: list[tuple[str, Stroke, int]] = []
        self.redo_stack: list[tuple[str, Stroke, int]] = []
        self.tool = "pen"
        self.color = QColor(PEN_COLORS[0][1])
        self.width = 4
        self.current: Stroke | None = None
        self.setFixedSize(pixmap.deviceIndependentSize().toSize())
        self._update_cursor()

    def set_tool(self, tool: str):
        self.tool = tool
        self._update_cursor()

    def _update_cursor(self):
        self.setCursor(Qt.CursorShape.PointingHandCursor if self.tool == "eraser" else Qt.CursorShape.CrossCursor)

    # --- edición --------------------------------------------------------------

    def _push(self, kind: str, stroke: Stroke, index: int):
        self.undo_stack.append((kind, stroke, index))
        self.redo_stack.clear()
        self.changed.emit()

    def undo(self):
        if not self.undo_stack:
            return
        kind, stroke, index = self.undo_stack.pop()
        if kind == "add":
            self.strokes.remove(stroke)
        else:
            self.strokes.insert(index, stroke)
        self.redo_stack.append((kind, stroke, index))
        self.update()
        self.changed.emit()

    def redo(self):
        if not self.redo_stack:
            return
        kind, stroke, index = self.redo_stack.pop()
        if kind == "add":
            self.strokes.append(stroke)
        else:
            self.strokes.remove(stroke)
        self.undo_stack.append((kind, stroke, index))
        self.update()
        self.changed.emit()

    def _erase_at(self, point: QPointF):
        for index in range(len(self.strokes) - 1, -1, -1):
            stroke = self.strokes[index]
            if stroke.hit(point):
                del self.strokes[index]
                self._push("remove", stroke, index)
                self.update()

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return
        pos = event.position()
        if self.tool == "eraser":
            self._erase_at(pos)
            return
        if self.tool == "highlighter":
            self.current = Stroke("highlighter", HIGHLIGHTER, 16, pos)
        else:
            self.current = Stroke("pen", self.color, self.width, pos)
        self.update()

    def mouseMoveEvent(self, event):
        pos = event.position()
        if self.tool == "eraser" and event.buttons() & Qt.MouseButton.LeftButton:
            self._erase_at(pos)
        elif self.current is not None:
            self.current.path.lineTo(pos)
            self.update()

    def mouseReleaseEvent(self, event):
        if self.current is not None and event.button() == Qt.MouseButton.LeftButton:
            self.strokes.append(self.current)
            self._push("add", self.current, len(self.strokes) - 1)
            self.current = None
            self.update()

    # --- pintado --------------------------------------------------------------

    def _paint_strokes(self, painter: QPainter, strokes):
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        for stroke in strokes:
            painter.setPen(stroke.pen())
            painter.drawPath(stroke.path)

    def paintEvent(self, _event):
        p = QPainter(self)
        p.drawPixmap(QRectF(self.rect()).topLeft(), self.base)
        self._paint_strokes(p, self.strokes + ([self.current] if self.current else []))
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


class EditorWindow(QMainWindow):
    """Ventana «Herramienta Recortes» con el último recorte."""

    new_snip_requested = pyqtSignal(str)  # modo

    def __init__(self, pixmap: QPixmap):
        super().__init__()
        self.setWindowIcon(icon(config.APP_ID))
        self.saved_path: Path | None = None
        self.dirty = False
        self.canvas: Canvas | None = None

        self.scroll = QScrollArea()
        self.scroll.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.scroll.setWidgetResizable(False)
        self.setCentralWidget(self.scroll)

        self._build_actions()
        self._build_menus()
        self._build_toolbar()
        self.load(pixmap)

    # --- interfaz -------------------------------------------------------------

    def _action(self, text, icons, shortcut=None, slot=None, checkable=False):
        action = QAction(icon(*icons), text, self)
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        if slot:
            action.triggered.connect(slot)
        action.setCheckable(checkable)
        return action

    def _build_actions(self):
        self.act_new = self._action("&Nuevo recorte", ("edit-cut", "camera-photo"), "Ctrl+N",
                                    lambda: self.new_snip_requested.emit(settings_mod.current.default_mode))
        self.act_save = self._action("&Guardar como…", ("document-save-as", "document-save"), "Ctrl+S", self.save_as)
        self.act_copy = self._action("&Copiar", ("edit-copy",), "Ctrl+C", self.copy)
        self.act_undo = self._action("&Deshacer", ("edit-undo",), "Ctrl+Z", lambda: self.canvas.undo())
        self.act_redo = self._action("&Rehacer", ("edit-redo",), "Ctrl+Y", lambda: self.canvas.redo())
        self.act_close = self._action("&Salir", ("window-close", "application-exit"), "Ctrl+W", self.close)

        self.tools = QActionGroup(self)
        self.act_pen = self._action("&Pluma", ("draw-freehand", "draw-brush"), "Ctrl+P", lambda: self._tool("pen"), True)
        self.act_high = self._action("&Resaltador", ("draw-highlight", "format-text-highlight", "draw-brush"),
                                     "Ctrl+H", lambda: self._tool("highlighter"), True)
        self.act_eraser = self._action("&Borrador", ("draw-eraser", "edit-clear"), "Ctrl+E", lambda: self._tool("eraser"), True)
        for a in (self.act_pen, self.act_high, self.act_eraser):
            self.tools.addAction(a)
        self.act_pen.setChecked(True)

        self.pen_menu = QMenu("Pluma", self)
        colors = QActionGroup(self)
        for name, value in PEN_COLORS:
            a = self.pen_menu.addAction(name, lambda v=value: self._pen_color(QColor(v)))
            a.setCheckable(True)
            a.setChecked(value == PEN_COLORS[0][1])
            pix = QPixmap(14, 14)
            pix.fill(QColor(value))
            a.setIcon(QIcon(pix))
            colors.addAction(a)
        self.pen_menu.addAction("Personalizar…", self._pen_custom)
        self.pen_menu.addSeparator()
        widths = QActionGroup(self)
        for name, value in PEN_WIDTHS:
            a = self.pen_menu.addAction(f"Punta {name.lower()}", lambda v=value: self._pen_width(v))
            a.setCheckable(True)
            a.setChecked(value == 4)
            widths.addAction(a)

    def _build_menus(self):
        bar = self.menuBar()
        m = bar.addMenu("&Archivo")
        m.addAction(self.act_new)
        m.addAction(self.act_save)
        m.addSeparator()
        m.addAction(self.act_close)
        m = bar.addMenu("&Editar")
        m.addAction(self.act_copy)
        m.addSeparator()
        m.addAction(self.act_undo)
        m.addAction(self.act_redo)
        m = bar.addMenu("&Herramientas")
        m.addAction(self.act_pen)
        m.addMenu(self.pen_menu)
        m.addAction(self.act_high)
        m.addAction(self.act_eraser)

    def _build_toolbar(self):
        tb = QToolBar("Herramientas", self)
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        tb.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        self.addToolBar(tb)

        new_btn = QToolButton()
        new_btn.setDefaultAction(self.act_new)
        new_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextBesideIcon)
        new_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        from .main_window import mode_menu

        new_btn.setMenu(mode_menu(self, lambda mode: self.new_snip_requested.emit(mode)))
        tb.addWidget(new_btn)
        tb.addAction(self.act_save)
        tb.addAction(self.act_copy)
        tb.addSeparator()

        pen_btn = QToolButton()
        pen_btn.setDefaultAction(self.act_pen)
        pen_btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        pen_btn.setPopupMode(QToolButton.ToolButtonPopupMode.MenuButtonPopup)
        pen_btn.setMenu(self.pen_menu)
        tb.addWidget(pen_btn)
        for a in (self.act_high, self.act_eraser):
            btn = QToolButton()
            btn.setDefaultAction(a)
            btn.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
            tb.addWidget(btn)
        tb.addSeparator()
        tb.addAction(self.act_undo)
        tb.addAction(self.act_redo)
        for a in (self.act_undo, self.act_redo, self.act_save, self.act_copy):
            tb.widgetForAction(a).setToolButtonStyle(
                Qt.ToolButtonStyle.ToolButtonIconOnly if a in (self.act_undo, self.act_redo)
                else Qt.ToolButtonStyle.ToolButtonTextBesideIcon
            )

    # --- contenido ------------------------------------------------------------

    def load(self, pixmap: QPixmap, saved_path: Path | None = None):
        self.canvas = Canvas(pixmap)
        self.canvas.set_tool({self.act_high: "highlighter", self.act_eraser: "eraser"}.get(self.tools.checkedAction(), "pen"))
        self.canvas.changed.connect(self._on_changed)
        self.scroll.setWidget(self.canvas)
        self.saved_path = saved_path
        self.dirty = False
        self._on_changed(mark_dirty=False)
        self._fit_window()

    def _fit_window(self):
        screen = (self.screen() or QGuiApplication.primaryScreen()).availableGeometry()
        size = self.canvas.size()
        chrome = QSize(40, self.menuBar().sizeHint().height() + 80)
        width = min(max(size.width() + chrome.width(), 520), int(screen.width() * 0.9))
        height = min(max(size.height() + chrome.height(), 260), int(screen.height() * 0.9))
        self.resize(width, height)

    def _on_changed(self, mark_dirty: bool = True):
        if mark_dirty:
            self.dirty = True
        self.act_undo.setEnabled(bool(self.canvas and self.canvas.undo_stack))
        self.act_redo.setEnabled(bool(self.canvas and self.canvas.redo_stack))
        name = self.saved_path.name if self.saved_path else "Recorte"
        self.setWindowTitle(f"{'*' if self.dirty else ''}{name} - {config.APP_NAME}")

    def _tool(self, tool: str):
        self.canvas.set_tool(tool)

    def _pen_color(self, color: QColor):
        self.canvas.color = color
        self.act_pen.setChecked(True)
        self._tool("pen")

    def _pen_custom(self):
        color = QColorDialog.getColor(self.canvas.color, self, "Color de la pluma")
        if color.isValid():
            self._pen_color(color)

    def _pen_width(self, width: int):
        self.canvas.width = width
        self.act_pen.setChecked(True)
        self._tool("pen")

    def copy(self):
        QGuiApplication.clipboard().setImage(self.canvas.render_image())

    def save_as(self) -> bool:
        folder = settings_mod.current.screenshots_dir()
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
            flat = QImage(image.size(), QImage.Format.Format_RGB32)
            flat.fill(Qt.GlobalColor.white)
            p = QPainter(flat)
            p.drawImage(0, 0, image)
            p.end()
            image = flat
        if not image.save(str(target)):
            QMessageBox.warning(self, config.APP_NAME, f"No se pudo guardar en:\n{target}")
            return False
        self.saved_path = target
        self.dirty = False
        self._on_changed(mark_dirty=False)
        return True

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
        event.accept()
