"""Dastur belgisi (ikonka). `python -m ombor.ui.icon fayl.ico` uni faylga saqlaydi."""

import sys

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPixmap

from . import theme

ICON_SIZE = 256


def _draw_icon() -> QPixmap:
    pixmap = QPixmap(ICON_SIZE, ICON_SIZE)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(theme.BRAND_COLOR))
    painter.drawRoundedRect(QRectF(0, 0, ICON_SIZE, ICON_SIZE), 48, 48)
    font = QFont("Segoe UI", 1, QFont.Weight.Bold)
    font.setPixelSize(120)
    painter.setFont(font)
    painter.setPen(QColor("white"))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "MM")
    painter.end()
    return pixmap


def app_icon() -> QIcon:
    return QIcon(_draw_icon())


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    if not _draw_icon().save(sys.argv[1], "ICO"):
        sys.exit(f"Ikonkani saqlab bo'lmadi: {sys.argv[1]}")
