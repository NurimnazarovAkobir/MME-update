"""Belgilar (ikonkalar): Windows bilan birga keladigan «Segoe MDL2 Assets» shriftidan olinadi."""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QLabel

ICON_FONT = "Segoe MDL2 Assets"
MENU_ICON_SIZE = 40  # piksel; ekranda kichraytirib ko'rsatiladi, shuning uchun tiniq chiqadi


class Glyph:
    """Shriftdagi belgilar kodlari."""

    HOME = "\ue80f"
    RECEIPT = "\ue896"  # pastga strelka: omborga kirim
    ISSUE = "\ue898"  # yuqoriga strelka: ombordan chiqim
    PRODUCTS = "\ue7b8"
    REPORTS = "\ue8a5"
    SETTINGS = "\ue713"
    ADD = "\ue710"
    REMOVE = "\ue738"
    GRID = "\ue8a9"
    CALENDAR = "\ue787"
    CLOCK = "\ue823"
    CHART = "\ue9d2"
    MONEY = "\ue8c7"
    ARROW_UP = "\ue74a"
    ARROW_DOWN = "\ue74b"
    SYNC = "\ue895"
    PRINT = "\ue749"
    EXPORT = "\uede1"
    PEOPLE = "\ue716"
    PERSON = "\ue77b"
    TAG = "\ue8ec"
    DOCUMENT = "\ue8a5"
    SWITCH = "\ue8ab"
    SHOP = "\ue719"
    PIN = "\ue707"
    WALLET = "\ue8c7"
    BOX = "\ue7b8"
    HISTORY = "\ue81c"
    PREVIOUS = "\ue76b"
    NEXT = "\ue76c"
    EDIT = "\ue70f"
    DELETE = "\ue74d"
    IMPORT = "\ue8b5"
    CLIPBOARD = "\ue9d5"
    UNDO = "\ue7a7"
    CROWN = "\ue734"
    SIGN_OUT = "\uf3b1"
    INFO = "\ue946"
    CHECK = "\ue73e"
    CHEVRON = "\ue76c"


def icon_label(glyph: str, object_name: str = "icon") -> QLabel:
    """Belgi ko'rsatadigan yozuv; rangi va o'lchami `object_name` bo'yicha uslublar jadvalidan olinadi."""
    widget = QLabel(glyph)
    widget.setObjectName(object_name)
    widget.setAlignment(Qt.AlignmentFlag.AlignCenter)
    widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
    return widget


def menu_icon(glyph: str, color: str, selected_color: str) -> QIcon:
    """Menyu qatori uchun belgi: oddiy va tanlangan holat uchun ikki xil rangda."""
    icon = QIcon()
    for mode, tint in ((QIcon.Mode.Normal, color), (QIcon.Mode.Selected, selected_color)):
        pixmap = QPixmap(MENU_ICON_SIZE, MENU_ICON_SIZE)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont(ICON_FONT)
        font.setPixelSize(int(MENU_ICON_SIZE * 0.7))
        painter.setFont(font)
        painter.setPen(QColor(tint))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
        painter.end()
        icon.addPixmap(pixmap, mode)
    return icon


def glyph_icon(glyph: str, color: str, size: int = MENU_ICON_SIZE) -> QIcon:
    """Tugma yoki yorliq uchun bitta rangdagi belgi."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.TextAntialiasing)
    font = QFont(ICON_FONT)
    font.setPixelSize(int(size * 0.7))
    painter.setFont(font)
    painter.setPen(QColor(color))
    painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, glyph)
    painter.end()
    return QIcon(pixmap)
