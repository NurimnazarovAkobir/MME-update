"""Profil rasmi (Telegram'dagi kabi doira): rasm bo'lsa — rasmning o'zi, bo'lmasa — ismning bosh harfi."""

import base64

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageReader, QPainter, QPainterPath, QPixmap

from ..errors import WarehouseError
from ..i18n import tr
from . import theme

PHOTO_SIZE = 256  # saqlanadigan rasm: kvadrat, piksel
PHOTO_QUALITY = 85


def load_photo(path: str) -> QImage:
    """Rasm faylini o'qiydi (telefonda olingan rasm qanday burilgan bo'lsa, shunday ko'rinadi)."""
    reader = QImageReader(path)
    reader.setAutoTransform(True)
    image = reader.read()
    if image.isNull():
        raise WarehouseError(tr("Bu faylni rasm sifatida ochib bo'lmadi. JPG yoki PNG rasm tanlang."))
    return image


def encode_photo(path: str) -> str:
    """Rasm faylini o'qiydi, o'rtasidan kvadrat qilib qirqadi — base64 JPEG (`encode_square`)."""
    image = load_photo(path)
    side = min(image.width(), image.height())
    return encode_square(image.copy((image.width() - side) // 2, (image.height() - side) // 2, side, side))


def encode_square(square: QImage) -> str:
    """Kvadrat rasmni 256×256 gacha kichraytiradi va base64 JPEG qilib qaytaradi."""
    square = square.scaled(
        PHOTO_SIZE, PHOTO_SIZE, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation
    )
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    square.convertToFormat(QImage.Format.Format_RGB32).save(buffer, "JPG", PHOTO_QUALITY)
    return base64.b64encode(bytes(data)).decode("ascii")


def avatar_pixmap(name: str, photo: str, size: int) -> QPixmap:
    """Doira shaklidagi profil belgisi (ekran o'lchamiga moslab tiniq chiziladi)."""
    scale = 2  # yuqori aniqlikdagi ekranlarda xira chiqmasligi uchun
    pixmap = QPixmap(size * scale, size * scale)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
    circle = QRectF(0, 0, size * scale, size * scale)
    clip = QPainterPath()
    clip.addEllipse(circle)
    painter.setClipPath(clip)
    image = QImage.fromData(base64.b64decode(photo)) if photo else QImage()
    if not image.isNull():
        painter.drawImage(circle, image)
    else:
        painter.fillRect(circle, QColor(theme.palette().accent))
        font = QFont()
        font.setBold(True)
        font.setPixelSize(int(size * scale * 0.42))
        painter.setFont(font)
        painter.setPen(QColor("#ffffff"))
        painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, (name[:1] or "?").upper())
    painter.end()
    pixmap.setDevicePixelRatio(scale)
    return pixmap
