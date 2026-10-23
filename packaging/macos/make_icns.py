"""Genera Cutter.icns a partir de data/icons/cutter-linux.svg (necesita macOS por iconutil)."""

import subprocess
import sys
import tempfile
from pathlib import Path

from PyQt6.QtCore import Qt
from PyQt6.QtGui import QGuiApplication, QImage, QPainter
from PyQt6.QtSvg import QSvgRenderer

ROOT = Path(__file__).resolve().parents[2]


def main(output: str):
    app = QGuiApplication(["make_icns", "-platform", "offscreen"])
    renderer = QSvgRenderer(str(ROOT / "data/icons/cutter-linux.svg"))
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "Cutter.iconset"
        iconset.mkdir()
        for size in (16, 32, 128, 256, 512):
            for scale in (1, 2):
                px = size * scale
                image = QImage(px, px, QImage.Format.Format_ARGB32)
                image.fill(Qt.GlobalColor.transparent)
                painter = QPainter(image)
                painter.setRenderHint(QPainter.RenderHint.Antialiasing)
                # Margen como en los iconos de macOS (el cuadrado no llega al borde).
                margin = px * 0.08
                renderer.render(painter, image.rect().toRectF().adjusted(margin, margin, -margin, -margin))
                painter.end()
                suffix = "@2x" if scale == 2 else ""
                image.save(str(iconset / f"icon_{size}x{size}{suffix}.png"))
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", output], check=True)
    del app


if __name__ == "__main__":
    main(sys.argv[1])
