"""Integración con macOS.

- Atajos globales con RegisterEventHotKey (Carbon), que no pide permiso de
  Accesibilidad y además «se come» la combinación para que no llegue a otras apps.
- Captura con `screencapture`, la herramienta del sistema (permiso «Grabación de pantalla»).
- Lista de ventanas, nivel de ventana, Dock y portapapeles con PyObjC.
- Pegado automático simulando Cmd+V (permiso «Accesibilidad»).

Todo se importa de forma perezosa: en Linux este módulo no se carga.
"""

import ctypes
import os
import plistlib
import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import QObject, QRect, QTimer, pyqtSignal

# --- atajos globales (Carbon) ---------------------------------------------------------

KEY_S, KEY_V = 0x01, 0x09  # kVK_ANSI_S, kVK_ANSI_V
CMD, SHIFT, OPTION, CONTROL = 0x0100, 0x0200, 0x0800, 0x1000


def _fourcc(code: str) -> int:
    return int.from_bytes(code.encode("ascii"), "big")


class _EventHotKeyID(ctypes.Structure):
    _fields_ = [("signature", ctypes.c_uint32), ("id", ctypes.c_uint32)]


class _EventTypeSpec(ctypes.Structure):
    _fields_ = [("eventClass", ctypes.c_uint32), ("eventKind", ctypes.c_uint32)]


_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int32, ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p)


class HotKeys(QObject):
    """Registra combinaciones globales; emite `pressed(id)` en el hilo principal."""

    pressed = pyqtSignal(int)

    def __init__(self):
        super().__init__()
        self._carbon = ctypes.CDLL("/System/Library/Frameworks/Carbon.framework/Carbon")
        c = self._carbon
        c.GetApplicationEventTarget.restype = ctypes.c_void_p
        c.InstallEventHandler.argtypes = [
            ctypes.c_void_p, _HANDLER, ctypes.c_ulong, ctypes.POINTER(_EventTypeSpec),
            ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p),
        ]
        c.InstallEventHandler.restype = ctypes.c_int32
        c.RegisterEventHotKey.argtypes = [
            ctypes.c_uint32, ctypes.c_uint32, _EventHotKeyID, ctypes.c_void_p,
            ctypes.c_uint32, ctypes.POINTER(ctypes.c_void_p),
        ]
        c.RegisterEventHotKey.restype = ctypes.c_int32
        c.UnregisterEventHotKey.argtypes = [ctypes.c_void_p]
        c.GetEventParameter.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_uint32, ctypes.c_void_p,
            ctypes.c_ulong, ctypes.c_void_p, ctypes.c_void_p,
        ]
        c.GetEventParameter.restype = ctypes.c_int32

        self._refs = {}
        self._callback = _HANDLER(self._on_event)  # se guarda para que no lo libere Python
        spec = _EventTypeSpec(_fourcc("keyb"), 5)  # kEventClassKeyboard, kEventHotKeyPressed
        handler_ref = ctypes.c_void_p()
        status = c.InstallEventHandler(
            c.GetApplicationEventTarget(), self._callback, 1, ctypes.byref(spec), None, ctypes.byref(handler_ref)
        )
        if status != 0:
            raise OSError(f"InstallEventHandler devolvió {status}")

    def register(self, hotkey_id: int, keycode: int, modifiers: int) -> bool:
        ref = ctypes.c_void_p()
        status = self._carbon.RegisterEventHotKey(
            keycode, modifiers, _EventHotKeyID(_fourcc("CUTR"), hotkey_id),
            self._carbon.GetApplicationEventTarget(), 0, ctypes.byref(ref),
        )
        if status == 0:
            self._refs[hotkey_id] = ref
        return status == 0

    def unregister_all(self):
        for ref in self._refs.values():
            self._carbon.UnregisterEventHotKey(ref)
        self._refs.clear()

    def _on_event(self, _call_ref, event, _user_data):
        hotkey = _EventHotKeyID()
        status = self._carbon.GetEventParameter(
            event, _fourcc("----"), _fourcc("hkid"), None,
            ctypes.sizeof(hotkey), None, ctypes.byref(hotkey),
        )
        if status == 0:
            # Se sale del callback de Carbon antes de abrir ventanas.
            QTimer.singleShot(0, lambda hid=hotkey.id: self.pressed.emit(hid))
        return 0


# --- aplicación, Dock y ventanas -----------------------------------------------------------


def _app():
    import AppKit

    return AppKit.NSApplication.sharedApplication()


def set_dock_visible(visible: bool):
    """En el Dock solo mientras hay una ventana de Cutter abierta (como las apps de barra de menús)."""
    import AppKit

    policy = AppKit.NSApplicationActivationPolicyRegular if visible else AppKit.NSApplicationActivationPolicyAccessory
    _app().setActivationPolicy_(policy)


def activate():
    _app().activateIgnoringOtherApps_(True)


def hide_app():
    """Devuelve el foco a la app que se estaba usando antes."""
    _app().hide_(None)


def raise_overlay(widget):
    """Pone la capa de recorte por encima de la barra de menús y el Dock, en el escritorio actual."""
    import AppKit
    import objc

    view = objc.objc_object(c_void_p=int(widget.winId()))
    window = view.window()
    if window is None:
        return
    window.setLevel_(getattr(AppKit, "NSScreenSaverWindowLevel", 1000))
    window.setCollectionBehavior_(
        AppKit.NSWindowCollectionBehaviorCanJoinAllSpaces
        | AppKit.NSWindowCollectionBehaviorFullScreenAuxiliary
        | AppKit.NSWindowCollectionBehaviorStationary
    )


def list_windows() -> list[QRect]:
    """Ventanas visibles de otras apps, de la de más arriba a la de más abajo."""
    import Quartz

    options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
    rects = []
    for info in Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []:
        if info.get("kCGWindowLayer", 0) != 0 or info.get("kCGWindowOwnerPID") == os.getpid():
            continue
        b = info.get("kCGWindowBounds") or {}
        rect = QRect(int(b.get("X", 0)), int(b.get("Y", 0)), int(b.get("Width", 0)), int(b.get("Height", 0)))
        if rect.width() > 1 and rect.height() > 1:
            rects.append(rect)
    return rects


# --- captura -----------------------------------------------------------------------


class PermissionError_(RuntimeError):
    pass


def ensure_screen_permission():
    """macOS 10.15+: sin «Grabación de pantalla» solo se captura el fondo de escritorio."""
    try:
        import Quartz

        if Quartz.CGPreflightScreenCaptureAccess():
            return
        Quartz.CGRequestScreenCaptureAccess()  # muestra el aviso del sistema la primera vez
    except (ImportError, AttributeError):
        return
    raise PermissionError_(
        "macOS necesita permiso para capturar la pantalla. Ve a Ajustes del Sistema → "
        "Privacidad y seguridad → Grabación de pantalla, activa Cutter y vuelve a abrirlo."
    )


def capture_displays(count: int) -> list:
    """Una imagen por pantalla, en el orden del sistema (la principal primero)."""
    from PyQt6.QtGui import QImage

    folder = tempfile.mkdtemp(prefix="cutter-")
    files = [os.path.join(folder, f"pantalla-{i}.png") for i in range(count)]
    try:
        subprocess.run(["/usr/sbin/screencapture", "-x", "-t", "png", *files], timeout=20, check=True)
        return [QImage(f) for f in files]
    except (OSError, subprocess.SubprocessError):
        return []
    finally:
        for f in files:
            try:
                os.remove(f)
            except OSError:
                pass
        try:
            os.rmdir(folder)
        except OSError:
            pass


# --- portapapeles y pegado -------------------------------------------------------------


def pasteboard_change_count() -> int:
    import AppKit

    return int(AppKit.NSPasteboard.generalPasteboard().changeCount())


def pasteboard_is_secret() -> bool:
    """Gestores de contraseñas marcan lo que copian (convención de nspasteboard.org)."""
    import AppKit

    types = AppKit.NSPasteboard.generalPasteboard().types() or []
    return any(str(t) in ("org.nspasteboard.ConcealedType", "org.nspasteboard.TransientType") for t in types)


def accessibility_trusted(prompt: bool = False) -> bool:
    try:
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt
    except ImportError:
        return False
    return bool(AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: prompt}))


def paste():
    """Cmd+V en la app que tenga el foco. Si falta el permiso, se pide y solo queda copiado."""
    if not accessibility_trusted(prompt=True):
        return
    import Quartz

    source = Quartz.CGEventSourceCreate(Quartz.kCGEventSourceStateHIDSystemState)
    for down in (True, False):
        event = Quartz.CGEventCreateKeyboardEvent(source, KEY_V, down)
        Quartz.CGEventSetFlags(event, Quartz.kCGEventFlagMaskCommand)
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)


# --- notificaciones y arranque -----------------------------------------------------------


def notify(title: str, body: str):
    script = f"display notification {_applescript(body)} with title {_applescript(title)}"
    subprocess.Popen(["/usr/bin/osascript", "-e", script])


def _applescript(text: str) -> str:
    return '"' + text.replace("\\", "\\\\").replace('"', '\\"') + '"'


LAUNCH_AGENT = Path.home() / "Library" / "LaunchAgents" / "app.cutter.Cutter.plist"


def set_autostart(enabled: bool):
    """Arranque al iniciar sesión con un LaunchAgent del usuario (solo dentro de Cutter.app)."""
    if not getattr(sys, "frozen", False):
        return
    if not enabled:
        LAUNCH_AGENT.unlink(missing_ok=True)
        return
    LAUNCH_AGENT.parent.mkdir(parents=True, exist_ok=True)
    plist = {
        "Label": "app.cutter.Cutter",
        "ProgramArguments": [sys.executable, "segundo-plano"],
        "RunAtLoad": True,
        "ProcessType": "Interactive",
    }
    data = plistlib.dumps(plist)
    if not LAUNCH_AGENT.exists() or LAUNCH_AGENT.read_bytes() != data:
        LAUNCH_AGENT.write_bytes(data)


def resource_dir() -> Path:
    """Carpeta del paquete (dentro de Cutter.app, PyInstaller la descomprime en _MEIPASS)."""
    base = getattr(sys, "_MEIPASS", None)
    return Path(base) / "cutter_linux" if base else Path(__file__).parent
