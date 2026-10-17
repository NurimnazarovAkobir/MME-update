"""Telegram'dagi kabi oyna ramkasi: Windows sarlavhasi o'rniga dastur rangidagi ingichka qator.

Qatorda faqat «yig'ish», «kattalashtirish / tiklash» va «yopish» tugmalari bor. Qatorni sudrab oyna ko'chiriladi
(ekran chetiga olib borilsa, Windows uni o'zi joylashtiradi), ikki marta bosilsa — kattalashadi. Oyna chetlaridan
o'lchami o'zgartiriladi. «Sozlamalar → Asosiy sozlamalar»da Windows'ning odatiy ramkasiga qaytish mumkin.
"""

import ctypes
import sys
from ctypes import wintypes

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

WM_WINDOWPOSCHANGING = 0x0046
MONITOR_DEFAULTTONEAREST = 2
ABM_GETSTATE, ABM_GETTASKBARPOS, ABS_AUTOHIDE = 4, 5, 1
ABE_LEFT, ABE_TOP, ABE_RIGHT, ABE_BOTTOM = range(4)
SWP_NOSIZE = 0x0001


class _WINDOWPOS(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("hwndInsertAfter", wintypes.HWND),
        ("x", ctypes.c_int),
        ("y", ctypes.c_int),
        ("cx", ctypes.c_int),
        ("cy", ctypes.c_int),
        ("flags", wintypes.UINT),
    ]


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


class _APPBARDATA(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("hWnd", wintypes.HWND),
        ("uCallbackMessage", wintypes.UINT),
        ("uEdge", wintypes.UINT),
        ("rc", wintypes.RECT),
        ("lParam", wintypes.LPARAM),
    ]


if sys.platform == "win32":
    _user32, _shell32 = ctypes.windll.user32, ctypes.windll.shell32
    _user32.MonitorFromWindow.restype = wintypes.HANDLE
    _user32.MonitorFromWindow.argtypes = (wintypes.HWND, wintypes.DWORD)
    _user32.GetMonitorInfoW.argtypes = (wintypes.HANDLE, ctypes.POINTER(_MONITORINFO))
    _user32.IsZoomed.argtypes = (wintypes.HWND,)

    _shell32.SHAppBarMessage.restype = ctypes.c_size_t
    _shell32.SHAppBarMessage.argtypes = (wintypes.DWORD, ctypes.POINTER(_APPBARDATA))

MINIMIZE, MAXIMIZE, RESTORE, CLOSE ="", "", "", ""


AUTOHIDE_GAP = 2  # avtomatik yashirinadigan panel tomonida bo'sh qoladigan joy (piksel)


def maximized_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """Kattalashtirilgan ramkasiz oyna egallashi kerak bo'lgan joy: monitorning ish maydoni (vazifalar paneli
    ustiga chiqmaydi). Panel avtomatik yashirinadigan bo'lsa, uning tomonida 2 piksel qoldiriladi — aks holda
    Windows oynani «to'liq ekran» deb hisoblaydi va sichqoncha pastga borganda panelni chiqarmaydi.

    Qaytadi: (x, y, kenglik, balandlik) — monitorning chap yuqori burchagiga nisbatan; Windows emas — None.
    """
    if sys.platform != "win32":
        return None
    monitor = _user32.MonitorFromWindow(wintypes.HWND(hwnd), MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if not _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        return None
    screen, work = info.rcMonitor, info.rcWork
    left, top, right, bottom = work.left, work.top, work.right, work.bottom
    bar = _APPBARDATA()
    bar.cbSize = ctypes.sizeof(bar)
    autohide = _shell32.SHAppBarMessage(ABM_GETSTATE, ctypes.byref(bar)) & ABS_AUTOHIDE
    if autohide and _shell32.SHAppBarMessage(ABM_GETTASKBARPOS, ctypes.byref(bar)):
        on_this_monitor = not (
            bar.rc.right <= screen.left
            or bar.rc.left >= screen.right
            or bar.rc.bottom <= screen.top
            or bar.rc.top >= screen.bottom
        )
        if on_this_monitor:
            edge = bar.uEdge
            left += AUTOHIDE_GAP if edge == ABE_LEFT else 0
            top += AUTOHIDE_GAP if edge == ABE_TOP else 0
            right -= AUTOHIDE_GAP if edge == ABE_RIGHT else 0
            bottom -= AUTOHIDE_GAP if edge == ABE_BOTTOM else 0
    return left - screen.left, top - screen.top, right - left, bottom - top


def clamp_maximized_size(event_type, message) -> None:
    """`QWidget.nativeEvent` uchun: kattalashtirilgan oynaning o'lchamini `maximized_rect` bilan cheklaydi.

    Qt ramkasiz oynani butun monitorga yoyadi (keyin qo'lda o'zgartirilsa ham qaytaradi), shuning uchun har bir
    WM_WINDOWPOSCHANGING da o'lcham tuzatiladi. Xabar baribir Qt'ga uzatiladi.
    """
    if sys.platform != "win32" or bytes(event_type) != b"windows_generic_MSG":
        return
    msg = wintypes.MSG.from_address(int(message))
    if msg.message != WM_WINDOWPOSCHANGING or not _user32.IsZoomed(msg.hWnd):
        return
    position = _WINDOWPOS.from_address(msg.lParam)
    if position.flags & SWP_NOSIZE:
        return
    rect = maximized_rect(msg.hWnd)
    if rect is None:
        return
    monitor = _user32.MonitorFromWindow(msg.hWnd, MONITOR_DEFAULTTONEAREST)
    info = _MONITORINFO()
    info.cbSize = ctypes.sizeof(info)
    if _user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
        position.x, position.y = info.rcMonitor.left + rect[0], info.rcMonitor.top + rect[1]
        position.cx, position.cy = rect[2], rect[3]


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
