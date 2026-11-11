"""Draws the placeholder app icon (a G on Gryphon green). Swap assets/icon.png for the real logo any time.

    QT_QPA_PLATFORM=offscreen python tools/make_icon.py
"""
import sys
from pathlib import Path

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath, QPen

root = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(root))
from gryphon_manager import theme  # noqa: E402

app = QGuiApplication(sys.argv)
size = 256
img = QImage(size, size, QImage.Format_ARGB32)
img.fill(Qt.transparent)
p = QPainter(img)
p.setRenderHint(QPainter.Antialiasing)
path = QPainterPath()
path.addRoundedRect(QRectF(8, 8, size - 16, size - 16), 48, 48)
p.fillPath(path, QColor(theme.BG))
p.setPen(QPen(QColor(theme.GREEN), 12))
p.drawPath(path)
p.setPen(QPen(QColor(theme.RED), 10))
p.drawLine(54, 204, 202, 204)
f = QFont("Inter", 1)
f.setPixelSize(150)
f.setWeight(QFont.Black)
p.setFont(f)
p.setPen(QColor(theme.TEXT))
p.drawText(QRectF(0, -6, size, size - 28), Qt.AlignCenter, "G")
p.end()
out = root / "gryphon_manager" / "assets"
out.mkdir(parents=True, exist_ok=True)
img.save(str(out / "icon.png"))
try:
    from PIL import Image
    Image.open(out / "icon.png").save(out / "icon.ico", sizes=[(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
except ImportError:
    print("Pillow not installed: icon.ico not updated")
print("wrote", out)
