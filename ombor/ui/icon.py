"""Dastur belgisi (ikonka): `ombor/assets/icon.png`.

`python -m ombor.ui.icon fayl.ico` belgini Windows uchun bir nechta o'lchamli .ico fayliga yozadi —
u exe faylining, ish stoli yorlig'ining va vazifalar panelining belgisi bo'ladi.
"""

import struct
import sys
from pathlib import Path

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap

ICO_SIZES = (16, 24, 32, 48, 64, 128, 256)


def asset_path(name: str) -> Path:
    """Dastur bilan birga keladigan fayl: yig'ilgan exe da — vaqtinchalik ochilgan papkadan."""
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent.parent))
    return base / "ombor" / "assets" / name


def icon_pixmap(size: int = 256) -> QPixmap:
    pixmap = QPixmap(str(asset_path("icon.png")))
    return pixmap.scaled(size, size, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)


def app_icon() -> QIcon:
    return QIcon(str(asset_path("icon.png")))


def _png_bytes(size: int) -> bytes:
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    icon_pixmap(size).save(buffer, "PNG")
    return bytes(data.data())


def write_ico(path: Path | str) -> None:
    """Har bir o'lcham PNG ko'rinishida saqlanadigan .ico fayl (Windows Vista va undan yangisi o'qiydi)."""
    images = [_png_bytes(size) for size in ICO_SIZES]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = len(header) + 16 * len(images)
    entries, body = b"", b""
    for size, image in zip(ICO_SIZES, images):
        side = 0 if size >= 256 else size  # 0 — 256 piksel degani
        entries += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(image), offset + len(body))
        body += image
    Path(path).write_bytes(header + entries + body)


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    write_ico(sys.argv[1])
