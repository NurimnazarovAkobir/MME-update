"""Telegram'dagi kabi oyna ramkasi: Windows sarlavhasi o'rniga dastur rangidagi ingichka qator.

Qatorda faqat «yig'ish», «kattalashtirish / tiklash» va «yopish» tugmalari bor. Qatorni sudrab oyna ko'chiriladi
(ekran chetiga olib borilsa, Windows uni o'zi joylashtiradi), ikki marta bosilsa — kattalashadi. Oyna chetlaridan
o'lchami o'zgartiriladi. «Sozlamalar → Asosiy sozlamalar»da Windows'ning odatiy ramkasiga qaytish mumkin.
"""

from PySide6.QtCore import QEvent, QObject, QPoint, Qt
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QHBoxLayout, QMainWindow, QPushButton, QVBoxLayout, QWidget

from ..i18n import tr
from ..local import LocalPrefs
from .icons import ICON_FONT

SYSTEM_FRAME_KEY = "system_frame"  # "1" — Windows'ning odatiy ramkasi (shu kompyuterning shaxsiy sozlamasi)
TITLE_BAR_HEIGHT = 32
BUTTON_WIDTH = 46
RESIZE_MARGIN = 6  # oyna chetidagi shu kenglikdagi joydan o'lchami o'zgartiriladi
GLYPH_POINT_SIZE = 8

MINIMIZE, MAXIMIZE, RESTORE, CLOSE = "", "", "", ""


def uses_system_frame(prefs: LocalPrefs) -> bool:
    return prefs.get(SYSTEM_FRAME_KEY) == "1"


def set_system_frame(prefs: LocalPrefs, enabled: bool) -> None:
    prefs.set(SYSTEM_FRAME_KEY, "1" if enabled else "")


def _caption_button(glyph: str, object_name: str, tooltip: str) -> QPushButton:
    widget = QPushButton(glyph)
    widget.setObjectName(object_name)
    widget.setToolTip(tooltip)
    widget.setFixedSize(BUTTON_WIDTH, TITLE_BAR_HEIGHT)
    widget.setFocusPolicy(Qt.FocusPolicy.NoFocus)
    font = QFont(ICON_FONT)
    font.setPointSize(GLYPH_POINT_SIZE)
    widget.setFont(font)
    return widget


class TitleBar(QWidget):
    """Oynaning yuqori qatori: bo'sh joyini sudrab ko'chiriladi, o'ngda uchta tugma."""

    def __init__(self, window: QMainWindow):
        super().__init__(window)
        self.setObjectName("titleBar")
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground)
        self.setFixedHeight(TITLE_BAR_HEIGHT)
        self._window = window
        minimize = _caption_button(MINIMIZE, "captionButton", tr("Yig'ish"))
        minimize.clicked.connect(window.showMinimized)
        self._maximize = _caption_button(MAXIMIZE, "captionButton", tr("Kattalashtirish"))
        self._maximize.clicked.connect(self.toggle_maximized)
        close = _caption_button(CLOSE, "closeButton", tr("Yopish"))
        close.clicked.connect(window.close)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addStretch()
        for widget in (minimize, self._maximize, close):
            layout.addWidget(widget)

    def toggle_maximized(self) -> None:
        if self._window.isMaximized():
            self._window.showNormal()
        else:
            self._window.showMaximized()

    def update_state(self) -> None:
        """Kattalashtirilgan oynada tugma «tiklash» belgisini ko'rsatadi."""
        maximized = self._window.isMaximized()
        self._maximize.setText(RESTORE if maximized else MAXIMIZE)
        self._maximize.setToolTip(tr("Tiklash") if maximized else tr("Kattalashtirish"))

    def mousePressEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton and self._window.windowHandle() is not None:
            self._window.windowHandle().startSystemMove()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self.toggle_maximized()
            return
        super().mouseDoubleClickEvent(event)


class FramelessFrame(QObject):
    """Oynani Windows ramkasisiz qiladi: tepaga `TitleBar` qo'yiladi, chetlardan o'lcham o'zgartiriladi.

    Chetlar — oyna ichidagi `RESIZE_MARGIN` kenglikdagi hoshiya (oyna kattalashtirilganda yo'qoladi).
    """

    def __init__(self, window: QMainWindow, content: QWidget):
        super().__init__(window)
        self._window = window
        window.setWindowFlag(Qt.WindowType.FramelessWindowHint, True)
        self.title_bar = TitleBar(window)
        self._root = QWidget()
        self._root.setObjectName("framelessRoot")
        self._root.setMouseTracking(True)
        self._root.installEventFilter(self)
        self._layout = QVBoxLayout(self._root)  # hoshiyalari — o'lcham o'zgartiriladigan chetlar
        self._layout.setSpacing(0)
        self._layout.addWidget(self.title_bar)
        self._layout.addWidget(content, stretch=1)
        window.setCentralWidget(self._root)
        window.installEventFilter(self)
        self._apply_margins()

    def eventFilter(self, watched, event) -> bool:
        if watched is self._window and event.type() == QEvent.Type.WindowStateChange:
            self._apply_margins()
            self.title_bar.update_state()
        elif watched is self._root:
            if event.type() == QEvent.Type.MouseMove:
                self._root.setCursor(_CURSORS.get(self._edges(event.position().toPoint()), Qt.CursorShape.ArrowCursor))
            elif event.type() == QEvent.Type.MouseButtonPress and event.button() == Qt.MouseButton.LeftButton:
                edges = self._edges(event.position().toPoint())
                if edges and self._window.windowHandle() is not None:
                    self._window.windowHandle().startSystemResize(edges)
                    return True
            elif event.type() == QEvent.Type.Leave:
                self._root.unsetCursor()
        return False

    def _apply_margins(self) -> None:
        margin = 0 if self._window.isMaximized() or self._window.isFullScreen() else RESIZE_MARGIN
        self._layout.setContentsMargins(margin, margin, margin, margin)
        self._root.setProperty("framed", margin > 0)  # oddiy holatda oyna atrofida ingichka chiziq
        self._root.style().unpolish(self._root)
        self._root.style().polish(self._root)

    def _edges(self, point: QPoint) -> Qt.Edge:
        if self._window.isMaximized():
            return Qt.Edge(0)
        rect = self._root.rect()
        edges = Qt.Edge(0)
        if point.x() <= RESIZE_MARGIN:
            edges |= Qt.Edge.LeftEdge
        elif point.x() >= rect.width() - RESIZE_MARGIN:
            edges |= Qt.Edge.RightEdge
        if point.y() <= RESIZE_MARGIN:
            edges |= Qt.Edge.TopEdge
        elif point.y() >= rect.height() - RESIZE_MARGIN:
            edges |= Qt.Edge.BottomEdge
        return edges


_CURSORS = {
    Qt.Edge.LeftEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.RightEdge: Qt.CursorShape.SizeHorCursor,
    Qt.Edge.TopEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.BottomEdge: Qt.CursorShape.SizeVerCursor,
    Qt.Edge.LeftEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeFDiagCursor,
    Qt.Edge.RightEdge | Qt.Edge.TopEdge: Qt.CursorShape.SizeBDiagCursor,
    Qt.Edge.LeftEdge | Qt.Edge.BottomEdge: Qt.CursorShape.SizeBDiagCursor,
}
