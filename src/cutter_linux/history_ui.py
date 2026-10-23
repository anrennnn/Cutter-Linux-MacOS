"""Ventana del historial del portapapeles (Super+V), al estilo de Windows 11."""

import shutil
import subprocess

from PyQt6.QtCore import QRectF, QSize, Qt, QTimer
from PyQt6.QtGui import (
    QCursor, QGuiApplication, QImageReader, QKeySequence, QPainterPath, QPixmap, QRegion, QShortcut,
)
from PyQt6.QtWidgets import (
    QAbstractItemView, QFrame, QHBoxLayout, QLabel, QListWidget, QListWidgetItem,
    QMenu, QPushButton, QToolButton, QVBoxLayout, QWidget,
)

from . import config
from .history import ClipItem, HistoryStore

WIDTH, HEIGHT = 380, 470
THUMB_HEIGHT = 120


def _is_dark() -> bool:
    return QGuiApplication.palette().window().color().lightness() < 128


def _stylesheet() -> str:
    if _is_dark():
        bg, card, hover, text, sub, border = "#202020", "#2d2d2d", "#383838", "#ffffff", "#c5c5c5", "#3b3b3b"
    else:
        bg, card, hover, text, sub, border = "#f3f3f3", "#ffffff", "#f0f6fc", "#1b1b1b", "#5f5f5f", "#e1e1e1"
    return f"""
        #popup {{ background: {bg}; border: 1px solid {border}; border-radius: 10px; }}
        QLabel {{ color: {text}; }}
        #title {{ font-size: 15px; font-weight: 600; }}
        #empty {{ color: {sub}; }}
        QPushButton#clear {{ color: {text}; background: transparent; border: none; padding: 4px 8px; border-radius: 4px; }}
        QPushButton#clear:hover {{ background: {hover}; }}
        QListWidget {{ background: transparent; border: none; outline: none; }}
        QListWidget::item {{ background: {card}; border: 1px solid {border}; border-radius: 6px; margin: 3px 2px; }}
        QListWidget::item:hover {{ background: {hover}; }}
        QListWidget::item:selected {{ background: {hover}; border: 1px solid #4cc2ff; }}
        QToolButton {{ color: {sub}; background: transparent; border: none; border-radius: 4px; padding: 2px 6px; }}
        QToolButton:hover {{ background: {border}; }}
        #pin {{ color: #4cc2ff; }}
    """


class CardWidget(QWidget):
    def __init__(self, popup: "HistoryPopup", item: ClipItem):
        super().__init__()
        self.popup = popup
        self.item = item
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 6, 10)
        layout.setSpacing(6)

        if item.kind == "text":
            preview = item.text.strip().replace("\t", "    ")
            lines = preview.splitlines()[:4]
            label = QLabel("\n".join(line[:200] for line in lines))
            label.setWordWrap(True)
            label.setTextFormat(Qt.TextFormat.PlainText)
            layout.addWidget(label, 1)
        else:
            label = QLabel()
            reader = QImageReader(str(item.image_path()))
            size = reader.size()
            box = QSize(WIDTH - 110, THUMB_HEIGHT)
            if size.isValid() and (size.height() > box.height() or size.width() > box.width()):
                reader.setScaledSize(size.scaled(box, Qt.AspectRatioMode.KeepAspectRatio))
            label.setPixmap(QPixmap.fromImage(reader.read()))
            layout.addWidget(label, 1, Qt.AlignmentFlag.AlignLeft)

        side = QVBoxLayout()
        side.setSpacing(2)
        more = QToolButton()
        more.setText("•••")
        more.setToolTip("Ver más")
        more.clicked.connect(lambda: self._menu(more))
        side.addWidget(more, 0, Qt.AlignmentFlag.AlignTop)
        if item.pinned:
            pin = QLabel("📌")
            pin.setObjectName("pin")
            pin.setToolTip("Fijado")
            side.addWidget(pin, 0, Qt.AlignmentFlag.AlignHCenter)
        side.addStretch(1)
        layout.addLayout(side)

    def _menu(self, anchor):
        menu = QMenu(self)
        menu.addAction("Desanclar" if self.item.pinned else "Fijar", lambda: self.popup.store.toggle_pin(self.item.id))
        menu.addAction("Eliminar", lambda: self.popup.store.remove(self.item.id))
        menu.addSeparator()
        menu.addAction("Borrar todo", self.popup.store.clear)
        self.popup.menu_open = True
        menu.exec(anchor.mapToGlobal(anchor.rect().bottomLeft()))
        self.popup.menu_open = False


class HistoryPopup(QWidget):
    def __init__(self, store: HistoryStore):
        super().__init__(None)
        self.store = store
        self.menu_open = False
        self.setWindowTitle(f"{config.APP_NAME} - Portapapeles")
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        # Las esquinas redondeadas necesitan transparencia, que en X11 sin compositor
        # se ve negra; ahí se recorta la ventana con una máscara.
        self.use_mask = QGuiApplication.platformName() == "xcb"
        if not self.use_mask:
            self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.resize(WIDTH, HEIGHT)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        frame = QFrame(self)
        frame.setObjectName("popup")
        outer.addWidget(frame)

        layout = QVBoxLayout(frame)
        layout.setContentsMargins(12, 12, 12, 12)
        header = QHBoxLayout()
        title = QLabel("Portapapeles")
        title.setObjectName("title")
        header.addWidget(title)
        header.addStretch(1)
        clear = QPushButton("Borrar todo")
        clear.setObjectName("clear")
        clear.clicked.connect(store.clear)
        header.addWidget(clear)
        layout.addLayout(header)

        self.list = QListWidget(frame)
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.list.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.list.itemActivated.connect(self._activate)
        self.list.itemClicked.connect(self._activate)
        layout.addWidget(self.list, 1)

        self.empty = QLabel("No hay nada aquí.\nCuando copies algo, lo verás en esta lista.")
        self.empty.setObjectName("empty")
        self.empty.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.empty, 1)

        QShortcut(QKeySequence(Qt.Key.Key_Escape), self, activated=self.hide)
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self, activated=self._delete_selected)
        store.changed.connect(self.refresh)
        self.refresh()

    def refresh(self):
        self.setStyleSheet(_stylesheet())
        selected = self.list.currentRow()
        self.list.clear()
        for clip in self.store.items:
            row = QListWidgetItem(self.list)
            row.setData(Qt.ItemDataRole.UserRole, clip.id)
            card = CardWidget(self, clip)
            card_width = WIDTH - 52  # ancho del panel menos márgenes y barra de desplazamiento
            height = card.layout().totalHeightForWidth(card_width) if card.layout().hasHeightForWidth() else -1
            row.setSizeHint(QSize(card_width, max(height, card.sizeHint().height())))
            self.list.setItemWidget(row, card)
        has_items = bool(self.store.items)
        self.list.setVisible(has_items)
        self.empty.setVisible(not has_items)
        if has_items:
            self.list.setCurrentRow(min(max(selected, 0), self.list.count() - 1))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        if self.use_mask:
            path = QPainterPath()
            path.addRoundedRect(QRectF(self.rect()), 10, 10)
            self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def toggle(self):
        if self.isVisible():
            self.hide()
            return
        self.refresh()
        self.list.setCurrentRow(0)
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        area = screen.availableGeometry()
        pos = QCursor.pos()
        x = min(max(pos.x() - WIDTH // 2, area.left() + 8), area.right() - WIDTH - 8)
        y = min(max(pos.y() + 12, area.top() + 8), area.bottom() - HEIGHT - 8)
        self.move(x, y)
        if config.IS_MAC:
            from . import macos

            macos.activate()
        self.show()
        self.raise_()
        self.activateWindow()
        self.list.setFocus()

    def _delete_selected(self):
        row = self.list.currentItem()
        if row is not None:
            self.store.remove(row.data(Qt.ItemDataRole.UserRole))

    def _activate(self, row: QListWidgetItem):
        item_id = row.data(Qt.ItemDataRole.UserRole)
        clip = next((c for c in self.store.items if c.id == item_id), None)
        if clip is None:
            return
        # Se copia mientras la ventana aún tiene el foco (requisito de Wayland).
        QGuiApplication.clipboard().setMimeData(self.store.mime_for(clip))
        self.hide()
        if config.IS_MAC:
            from PyQt6.QtWidgets import QApplication

            from . import macos

            # Se devuelve el foco a la app de antes para que Cmd+V llegue a ella.
            if not any(w.isVisible() for w in QApplication.topLevelWidgets() if w is not self):
                macos.hide_app()
            QTimer.singleShot(250, _paste_into_focused_app)
            return
        QTimer.singleShot(180, _paste_into_focused_app)

    def changeEvent(self, event):
        super().changeEvent(event)
        # Como en Windows: al hacer clic fuera, el panel se cierra.
        if event.type() == event.Type.ActivationChange and not self.isActiveWindow() and not self.menu_open:
            QTimer.singleShot(0, lambda: (not self.isActiveWindow() and not self.menu_open) and self.hide())


def _paste_into_focused_app():
    """Pega en la app que tenía el foco. En Wayland no hay forma estándar; queda copiado."""
    if config.IS_MAC:
        from . import macos

        macos.paste()
        return
    if config.session_type() == "x11" and shutil.which("xdotool"):
        subprocess.Popen(["xdotool", "key", "--clearmodifiers", "ctrl+v"])
