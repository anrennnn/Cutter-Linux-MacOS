# PyInstaller: genera dist/Cutter.app para la arquitectura del Mac que lo compila.
#   pyinstaller packaging/macos/cutter.spec

import re
from pathlib import Path

ROOT = Path(SPECPATH).resolve().parents[1]
SRC = ROOT / "src"
VERSION = re.search(r'VERSION = "(.+?)"', (SRC / "cutter_linux/config.py").read_text()).group(1)

a = Analysis(
    [str(ROOT / "packaging/macos/cutter_main.py")],
    pathex=[str(SRC)],
    datas=[
        (str(SRC / "cutter_linux/icons"), "cutter_linux/icons"),
        (str(SRC / "cutter_linux/cutter-linux.svg"), "cutter_linux"),
        (str(SRC / "cutter_linux/cutter-menubar.svg"), "cutter_linux"),
    ],
    hiddenimports=["AppKit", "Quartz", "ApplicationServices", "objc", "PyQt6.QtSvg"],
    excludes=["tkinter", "PyQt6.QtQml", "PyQt6.QtQuick", "PyQt6.QtWebEngineCore", "PyQt6.QtMultimedia"],
    noarchive=False,
)
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, [],
    exclude_binaries=True,
    name="Cutter",
    console=False,
    argv_emulation=False,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Cutter")
app = BUNDLE(
    coll,
    name="Cutter.app",
    icon=str(ROOT / "build/Cutter.icns"),
    bundle_identifier="app.cutter.Cutter",
    version=VERSION,
    info_plist={
        "CFBundleName": "Cutter",
        "CFBundleDisplayName": "Cutter",
        "CFBundleShortVersionString": VERSION,
        "CFBundleVersion": VERSION,
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        # Empieza como app de barra de menús; aparece en el Dock al abrir una ventana.
        "LSUIElement": True,
        "NSHumanReadableCopyright": "Licencia MIT",
    },
)
