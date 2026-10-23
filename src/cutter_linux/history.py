"""Historial del portapapeles (lo que se abre con Super+V).

Guarda textos e imágenes en disco para que sobrevivan a reinicios. Se vigila el
portapapeles con Qt (X11 y XWayland) y, en Wayland, también con `wl-paste --watch`,
que funciona en KDE Plasma y en compositores wlroots.
"""

import hashlib
import json
import shutil
import subprocess
import time
import uuid
from dataclasses import asdict, dataclass, field

from PyQt6.QtCore import QBuffer, QByteArray, QIODevice, QMimeData, QObject, QProcess, QTimer, pyqtSignal
from PyQt6.QtGui import QClipboard, QGuiApplication, QImage

from . import config


@dataclass
class ClipItem:
    id: str
    kind: str  # "text" o "image"
    digest: str
    created: float
    pinned: bool = False
    text: str = ""
    html: str = ""
    image_file: str = ""
    width: int = 0
    height: int = 0
    extra: dict = field(default_factory=dict)

    def image_path(self):
        return config.HISTORY_DIR / self.image_file if self.image_file else None


def _digest(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _image_bytes(image: QImage) -> bytes:
    ba = QByteArray()
    buf = QBuffer(ba)
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    image.save(buf, "PNG")
    return bytes(ba)


class HistoryStore(QObject):
    changed = pyqtSignal()

    def __init__(self):
        super().__init__()
        config.HISTORY_DIR.mkdir(parents=True, exist_ok=True)
        self.items: list[ClipItem] = []
        self._load()

    # --- persistencia --------------------------------------------------------

    def _load(self):
        try:
            raw = json.loads(config.HISTORY_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = []
        known = set(ClipItem.__dataclass_fields__)
        for entry in raw:
            try:
                item = ClipItem(**{k: v for k, v in entry.items() if k in known})
            except TypeError:
                continue
            if item.kind == "image" and not (item.image_path() and item.image_path().exists()):
                continue
            self.items.append(item)

    def _save(self):
        tmp = config.HISTORY_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(i) for i in self.items], ensure_ascii=False), encoding="utf-8")
        tmp.replace(config.HISTORY_FILE)

    # --- operaciones -------------------------------------------------------

    def add_text(self, text: str, html: str = ""):
        if not text.strip():
            return
        digest = _digest(text.encode("utf-8"))
        if self._bump(digest):
            return
        self._insert(ClipItem(uuid.uuid4().hex, "text", digest, time.time(), text=text, html=html))

    def add_image(self, image: QImage):
        if image.isNull():
            return
        data = _image_bytes(image)
        digest = _digest(data)
        if self._bump(digest):
            return
        name = f"{digest}.png"
        (config.HISTORY_DIR / name).write_bytes(data)
        self._insert(
            ClipItem(
                uuid.uuid4().hex, "image", digest, time.time(),
                image_file=name, width=image.width(), height=image.height(),
            )
        )

    def _bump(self, digest: str) -> bool:
        """Si el elemento ya existe lo sube arriba, como hace Windows."""
        for i, item in enumerate(self.items):
            if item.digest == digest:
                if i != 0:
                    self.items.insert(0, self.items.pop(i))
                    item.created = time.time()
                    self._save()
                    self.changed.emit()
                return True
        return False

    def _insert(self, item: ClipItem):
        self.items.insert(0, item)
        unpinned = [i for i in self.items if not i.pinned]
        for old in unpinned[config.HISTORY_LIMIT:]:
            self._drop(old)
        self._save()
        self.changed.emit()

    def _drop(self, item: ClipItem):
        self.items.remove(item)
        path = item.image_path()
        if path and not any(i.image_file == item.image_file for i in self.items):
            path.unlink(missing_ok=True)

    def remove(self, item_id: str):
        for item in list(self.items):
            if item.id == item_id:
                self._drop(item)
        self._save()
        self.changed.emit()

    def toggle_pin(self, item_id: str):
        for item in self.items:
            if item.id == item_id:
                item.pinned = not item.pinned
        self._save()
        self.changed.emit()

    def clear(self):
        """«Borrar todo»: elimina todo excepto lo fijado."""
        for item in [i for i in self.items if not i.pinned]:
            self._drop(item)
        self._save()
        self.changed.emit()

    def mime_for(self, item: ClipItem) -> QMimeData:
        mime = QMimeData()
        if item.kind == "text":
            mime.setText(item.text)
            if item.html:
                mime.setHtml(item.html)
        else:
            mime.setImageData(QImage(str(item.image_path())))
        return mime


class ClipboardWatcher(QObject):
    """Envía al historial todo lo que se copia."""

    def __init__(self, store: HistoryStore):
        super().__init__()
        self.store = store
        self.clipboard = QGuiApplication.clipboard()
        self._pending = QTimer(self)
        self._pending.setSingleShot(True)
        self._pending.setInterval(150)  # algunas apps publican varios formatos seguidos
        self._pending.timeout.connect(self._read_qt)
        self.clipboard.changed.connect(self._on_changed)
        self.wl_watchers: list[QProcess] = []
        if config.session_type() == "wayland" and QGuiApplication.platformName() != "xcb":
            self._start_wl_paste()

    def _on_changed(self, mode):
        if mode == QClipboard.Mode.Clipboard:
            self._pending.start()

    def _read_qt(self):
        mime = self.clipboard.mimeData(QClipboard.Mode.Clipboard)
        if mime is None:
            return
        self.ingest(mime)

    def ingest(self, mime: QMimeData):
        # Las contraseñas copiadas desde gestores (KeePassXC, etc.) no se guardan.
        if mime.hasFormat("x-kde-passwordManagerHint"):
            return
        if mime.hasImage():
            image = self.clipboard.image()
            if not image.isNull():
                self.store.add_image(image)
                return
        if mime.hasText():
            self.store.add_text(mime.text(), mime.html() if mime.hasHtml() else "")

    # --- Wayland ------------------------------------------------------------

    def _start_wl_paste(self):
        """En Wayland una app sin foco no recibe avisos de Qt; wl-paste --watch sí (KDE, wlroots)."""
        if not shutil.which("wl-paste"):
            return
        proc = QProcess(self)
        proc.readyReadStandardOutput.connect(lambda: self._on_wl_event(proc))
        # Por cada cambio wl-paste ejecuta `echo`, y entonces leemos el portapapeles.
        proc.start("wl-paste", ["--watch", "echo", "cambio"])
        self.wl_watchers.append(proc)

    def _on_wl_event(self, proc: QProcess):
        proc.readAllStandardOutput()
        types = self._wl_read(["--list-types"]).decode("utf-8", "replace").split()
        if "x-kde-passwordManagerHint" in types:
            return
        if "image/png" in types:
            data = self._wl_read(["--type", "image/png"])
            image = QImage.fromData(data, "PNG") if data else QImage()
            if not image.isNull():
                self.store.add_image(image)
                return
        if any(t.startswith("text/") or t in ("UTF8_STRING", "STRING", "TEXT") for t in types):
            data = self._wl_read(["--no-newline", "--type", "text"])
            if data:
                self.store.add_text(data.decode("utf-8", "replace"))

    @staticmethod
    def _wl_read(args) -> bytes:
        try:
            return subprocess.run(["wl-paste", *args], capture_output=True, timeout=3).stdout
        except (OSError, subprocess.SubprocessError):
            return b""
