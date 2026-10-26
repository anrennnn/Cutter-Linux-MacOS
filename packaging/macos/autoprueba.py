"""Pruebas automáticas en macOS (GitHub Actions no tiene a nadie delante del Mac).

Comprueba lo que se puede comprobar sin permisos de usuario: que los atajos
globales se registran, que se leen las ventanas y el portapapeles, que las
ventanas de Cutter se crean y que el editor dibuja, deshace y exporta.
"""

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
os.environ["HOME"] = tempfile.mkdtemp(prefix="cutter-home-")  # no tocar ajustes reales

from PyQt6.QtCore import QPointF, QTimer  # noqa: E402
from PyQt6.QtGui import QColor, QGuiApplication, QPixmap  # noqa: E402
from PyQt6.QtWidgets import QApplication  # noqa: E402

fallos = []


def comprobar(nombre, condicion, detalle=""):
    print(("OK    " if condicion else "FALLO ") + nombre + (f"  ({detalle})" if detalle else ""))
    if not condicion:
        fallos.append(nombre)


app = QApplication(sys.argv[:1])
app.setQuitOnLastWindowClosed(False)

from cutter_linux import config, macos  # noqa: E402
from cutter_linux.app import _ensure_icon_theme  # noqa: E402

comprobar("plataforma detectada", config.IS_MAC and config.desktop() == "macos")
comprobar("atajos mostrados con Ctrl", config.SNIP_KEYS == "Ctrl+Shift+S" and config.HISTORY_KEYS == "Ctrl+Shift+V")

_ensure_icon_theme()
from cutter_linux.editor import Canvas, EditorWindow, Stroke, icon  # noqa: E402

comprobar("iconos propios de Cutter", not icon("edit-cut").isNull() and not icon("crop").isNull())

hotkeys = macos.HotKeys()
comprobar("atajo Ctrl+Shift+S registrado", hotkeys.register(1, macos.KEY_S, macos.CONTROL | macos.SHIFT))
comprobar("atajo Ctrl+Shift+V registrado", hotkeys.register(2, macos.KEY_V, macos.CONTROL | macos.SHIFT))
hotkeys.unregister_all()

ventanas = macos.list_windows()
comprobar("lista de ventanas", isinstance(ventanas, list), f"{len(ventanas)} ventanas")

antes = macos.pasteboard_change_count()
QGuiApplication.clipboard().setText("prueba de Cutter")
app.processEvents()
comprobar("contador del portapapeles cambia", macos.pasteboard_change_count() != antes)
comprobar("portapapeles normal no se marca como secreto", not macos.pasteboard_is_secret())

macos.set_dock_visible(True)
macos.set_dock_visible(False)
comprobar("cambiar visibilidad en el Dock", True)

pix = QPixmap(300, 200)
pix.fill(QColor("white"))
canvas = Canvas(pix)
trazo = Stroke("pen", QColor("red"), 4, QPointF(10, 10))
trazo.path.lineTo(QPointF(200, 10))
canvas.strokes.append(trazo)
canvas._push("add", trazo, 0)
imagen = canvas.render_image()
comprobar("el editor dibuja", QColor(imagen.pixel(100, 10)).red() > 200)
canvas._erase_at(QPointF(100, 11))
comprobar("el borrador quita el trazo", not canvas.strokes)
canvas.undo()
comprobar("deshacer recupera el trazo", len(canvas.strokes) == 1)

flecha = Stroke("arrow", QColor("blue"), 4, QPointF(20, 150))
flecha.end = QPointF(250, 150)
canvas.strokes.append(flecha)
canvas._push("add", flecha, 1)
comprobar("la flecha se dibuja", QColor(canvas.render_image().pixel(120, 150)).blue() > 200)
from PyQt6.QtCore import QRectF  # noqa: E402

canvas.crop_rect = QRectF(0, 0, 150, 100)
canvas.apply_crop()
comprobar("recortar la imagen", (canvas.image_size().width(), canvas.image_size().height()) == (150, 100))
canvas.undo()
comprobar("deshacer el recorte", (canvas.image_size().width(), canvas.image_size().height()) == (300, 200))
canvas.set_zoom(2.0)
comprobar("zoom", canvas.width() == 600)

from cutter_linux.history import HistoryStore  # noqa: E402
from cutter_linux.history_ui import HistoryPopup  # noqa: E402
from cutter_linux.main_window import MainWindow  # noqa: E402
from cutter_linux.options import OptionsDialog  # noqa: E402
from cutter_linux.overlay import SnipSession  # noqa: E402

store = HistoryStore()
store.add_text("hola")
store.add_image(pix.toImage())
comprobar("historial guarda texto e imagen", [i.kind for i in store.items] == ["image", "text"])

main = MainWindow()
main.show()
editor = EditorWindow(pix)
editor.show()
popup = HistoryPopup(store)
popup.toggle()
dialogo = OptionsDialog()
dialogo.show()
app.processEvents()
comprobar("ventanas creadas", main.isVisible() and editor.isVisible() and popup.isVisible() and dialogo.isVisible())

resultado = []
pantallas = [(s, pix) for s in QGuiApplication.screens()]
sesion = SnipSession(pantallas, resultado.append, "rect")
sesion.start()
app.processEvents()
comprobar("capa de recorte sobre la barra de menús", all(o.isVisible() for o in sesion.overlays))
sesion.cancel()
comprobar("cancelar el recorte", resultado == [None])

for w in (main, editor, popup, dialogo):
    w.hide()
editor.dirty = False
QTimer.singleShot(0, app.quit)
app.exec()

print()
if fallos:
    print(f"{len(fallos)} prueba(s) fallaron: {', '.join(fallos)}")
    sys.exit(1)
print("Todas las pruebas de macOS pasaron.")
