"""Asosiy oyna: chapda menyu, o'ngda tanlangan sahifa."""

from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QHBoxLayout,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from ..config import APP_NAME, APP_VERSION
from ..driver import sqlite3
from ..i18n import tr
from ..models import MovementKind
from ..services import Services
from ..session import Session
from . import theme
from .dashboard_page import DashboardPage, Destination
from .debts_page import DebtsPage
from .dialogs import MovementDialog, ProductDialog
from .history_page import HistoryPage
from .icon import app_icon
from .icons import Glyph, icon_label, menu_icon
from .labels import LABELS
from .movements_page import MovementsPage
from .products_page import ProductsPage
from .reports_page import ReportsPage
from .settings_page import SettingsPage
from .update_page import UpdatePage
from .widgets import button, label

SIDEBAR_WIDTH = 250
LOGO_SIZE = 48
LOGO_TEXT = "MME"
MENU_ICON_SIZE = 20
# Istalgan sahifadan yangi yozuv ochadigan tugmalar (bosh sahifadagi katta tugmalar yordam yozuvida ham bor).
NEW_RECEIPT_KEY, NEW_ISSUE_KEY, NEW_PRODUCT_KEY = "F2", "F3", "F4"
REFRESH_INTERVAL_MS = 10_000
NOTIFICATION_MS = 15_000


class MainWindow(QMainWindow):
    def __init__(self, services: Services, session: Session, db_path: Path):
        super().__init__()
        self.setWindowTitle(f"{APP_NAME} — {session.user.name} ({session.user.role.title})")
        self.resize(1280, 800)
        self.setMinimumSize(1100, 680)
        self._warehouse = services.warehouse
        self._warehouse.actor = session.author  # o'zgarishlar tarixiga shu ism yoziladi
        services.debts.actor = session.author
        self._session = session

        dashboard = DashboardPage(self._warehouse, services.reports, services.analytics, session.can_add)
        dashboard.movement_requested.connect(self._new_movement)
        dashboard.product_requested.connect(self._new_product)
        dashboard.page_requested.connect(self._open_destination)
        self._products_page = ProductsPage(self._warehouse, session)
        self._products_title = tr("Mahsulotlar")
        # (menyu nomi, belgi, sahifa, bosh sahifadan shu bo'limga o'tish kaliti)
        pages = [
            (tr("Bosh sahifa"), Glyph.HOME, dashboard, None),
            (
                tr("Kirim"),
                Glyph.RECEIPT,
                MovementsPage(self._warehouse, LABELS[MovementKind.IN], session),
                Destination.RECEIPTS,
            ),
            (
                tr("Chiqim"),
                Glyph.ISSUE,
                MovementsPage(self._warehouse, LABELS[MovementKind.OUT], session),
                Destination.ISSUES,
            ),
            (self._products_title, Glyph.PRODUCTS, self._products_page, Destination.PRODUCTS),
            (
                tr("Hisobotlar"),
                Glyph.REPORTS,
                ReportsPage(services.reports, services.analytics, self._warehouse),
                Destination.REPORTS,
            ),
            (tr("Qarzlar"), Glyph.MONEY, DebtsPage(services.debts, session), None),
        ]
        if session.is_admin:
            pages.append((tr("Tarix"), Glyph.CLOCK, HistoryPage(self._warehouse), None))
        self._update_title = tr("Yangilash")
        self._update_page = UpdatePage(services, session)
        update_page = self._update_page
        update_page.availability_changed.connect(self._show_update_badge)
        self._announced_version = ""  # shu versiya haqida Windows bildirishnomasi ko'rsatilgan
        self._tray: QSystemTrayIcon | None = None
        self._update_row = len(pages)
        pages.append((self._update_title, Glyph.SYNC, update_page, None))
        pages.append((tr("Sozlamalar"), Glyph.SETTINGS, SettingsPage(services, session, db_path), None))

        colors = theme.palette()
        self._pages = QStackedWidget()
        self._menu = QListWidget()
        self._menu.setObjectName("sidebar")
        self._menu.setIconSize(QSize(MENU_ICON_SIZE, MENU_ICON_SIZE))
        self._menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._rows: dict[Destination, int] = {}
        for row, (title, glyph, page, destination) in enumerate(pages):
            self._menu.addItem(QListWidgetItem(menu_icon(glyph, colors.sidebar_text, "#ffffff"), f"  {title}"))
            self._pages.addWidget(page)
            if destination is not None:
                self._rows[destination] = row
        self._menu.currentRowChanged.connect(self._show_page)

        version = label(tr("Versiya {0}").format(APP_VERSION), "firm")
        version.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sidebar_panel = QWidget()
        sidebar_panel.setObjectName("sidebarPanel")
        sidebar_panel.setFixedWidth(SIDEBAR_WIDTH)
        sidebar = QVBoxLayout(sidebar_panel)
        sidebar.setContentsMargins(16, 20, 16, 16)
        sidebar.setSpacing(18)
        sidebar.addLayout(self._brand(session))
        sidebar.addWidget(self._menu, stretch=1)
        sidebar.addWidget(version)

        central = QWidget()
        layout = QHBoxLayout(central)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(sidebar_panel)
        content = QVBoxLayout()
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(0)
        content.addWidget(self._build_update_notice())
        content.addWidget(self._pages)
        layout.addLayout(content)
        self.setCentralWidget(central)

        if session.can_add:
            QShortcut(QKeySequence(NEW_RECEIPT_KEY), self, lambda: self._new_movement(MovementKind.IN))
            QShortcut(QKeySequence(NEW_ISSUE_KEY), self, lambda: self._new_movement(MovementKind.OUT))
            QShortcut(QKeySequence(NEW_PRODUCT_KEY), self, self._new_product)
        self._menu.setCurrentRow(0)

        # Tarmoqda boshqa kompyuter bazani o'zgartirsa, ochiq sahifa o'zi yangilanadi.
        self._conn = services.conn
        self._data_version = self._read_data_version()
        self._watcher = QTimer(self)
        self._watcher.timeout.connect(self._refresh_if_changed_elsewhere)
        self._watcher.start(REFRESH_INTERVAL_MS)

    def _read_data_version(self) -> int:
        """Bazani boshqa ulanish (boshqa kompyuter) o'zgartirganda o'zgaradigan son."""
        return self._conn.execute("PRAGMA data_version").fetchone()[0]

    def _refresh_if_changed_elsewhere(self) -> None:
        if QApplication.activeModalWidget() is not None:
            return  # oyna ochiq turganda jadval ostidan o'zgarib ketmasin
        try:
            version = self._read_data_version()
        except sqlite3.Error:
            return  # tarmoq vaqtincha uzilgan yoki baza band — keyingi safar
        if version != self._data_version:
            self._data_version = version
            self._refresh_current()

    @staticmethod
    def _brand(session: Session) -> QHBoxLayout:
        """Yuqoridagi belgi, dastur nomi va uning ostida foydalanuvchi lavozimi."""
        logo = label(LOGO_TEXT, "logo")
        logo.setFixedSize(LOGO_SIZE, LOGO_SIZE)
        logo.setAlignment(Qt.AlignmentFlag.AlignCenter)
        owner = label(tr("{0} paneli").format(session.user.role.title), "firm")
        owner.setWordWrap(True)
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addStretch()
        names.addWidget(label(APP_NAME, "brand"))
        names.addWidget(owner)
        names.addStretch()
        brand = QHBoxLayout()
        brand.setSpacing(12)
        brand.addWidget(logo)
        brand.addLayout(names, stretch=1)
        return brand

    def _show_page(self, index: int) -> None:
        """Sahifa har ochilganda ma'lumotlari yangilanadi."""
        page = self._pages.widget(index)
        page.refresh()
        self._pages.setCurrentWidget(page)
        self._update_attention_badge()

    def _update_attention_badge(self) -> None:
        """«Mahsulotlar» yonida kam qolgan yoki tugagan mahsulotlar soni — bosh sahifani band qilmaydigan eslatma."""
        count = self._warehouse.attention_count()
        item = self._menu.item(self._rows[Destination.PRODUCTS])
        item.setText(f"  {self._products_title}  ⚠ {count}" if count else f"  {self._products_title}")
        item.setToolTip(tr("{0} ta mahsulot kam qolgan yoki tugagan").format(count) if count else "")

    def _show_update_badge(self, available: bool) -> None:
        """Yangi versiya chiqqanda «Yangilash» yonida belgi — oyna chiqarib ishni to'xtatmaydi."""
        item = self._menu.item(self._update_row)
        item.setText(f"  {self._update_title}  ●" if available else f"  {self._update_title}")
        item.setToolTip(tr("Dasturning yangi versiyasi bor") if available else "")
        version = self._update_page.offered_version
        self._notice_text.setText(tr("Dasturning yangi versiyasi chiqdi: {0}. Dasturni yangilang.").format(version))
        self._notice.setVisible(available)
        if available and version != self._announced_version:
            self._announced_version = version
            self._notify_in_windows(self._notice_text.text())
        elif not available and self._tray is not None:
            self._tray.hide()

    def _build_update_notice(self) -> QFrame:
        """Sahifalar ustidagi yo'lak: qaysi bo'lim ochiq bo'lmasin, yangi versiya chiqqani ko'rinib turadi."""
        self._notice = QFrame()
        self._notice.setObjectName("notice")
        self._notice_text = label("", "noticeText")
        open_page = button(tr("Yangilash"), "primary")
        open_page.clicked.connect(self._open_update_page)
        later = button(tr("Keyinroq"), "link")
        later.clicked.connect(self._notice.hide)
        row = QHBoxLayout(self._notice)
        row.setContentsMargins(24, 10, 24, 10)
        row.setSpacing(12)
        row.addWidget(icon_label(Glyph.SYNC, "iconAccent"))
        row.addWidget(self._notice_text, stretch=1)
        row.addWidget(open_page)
        row.addWidget(later)
        self._notice.hide()
        return self._notice

    def _open_update_page(self) -> None:
        if self.isMinimized():
            self.showNormal()
        self.raise_()
        self.activateWindow()
        self._menu.setCurrentRow(self._update_row)

    def _notify_in_windows(self, text: str) -> None:
        """Windows bildirishnomasi (ekran burchagida): dastur orqada turgan bo'lsa ham ko'rinadi."""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        if self._tray is None:
            self._tray = QSystemTrayIcon(app_icon(), self)
            self._tray.setToolTip(APP_NAME)
            self._tray.messageClicked.connect(self._open_update_page)
            self._tray.activated.connect(lambda _reason: self._open_update_page())
        self._tray.show()
        self._tray.showMessage(APP_NAME, text, QSystemTrayIcon.MessageIcon.Information, NOTIFICATION_MS)

    def _open_destination(self, destination: Destination) -> None:
        self._menu.setCurrentRow(self._rows[destination])

    def _refresh_current(self) -> None:
        self._pages.currentWidget().refresh()
        self._update_attention_badge()

    def _new_movement(self, kind: MovementKind) -> None:
        MovementDialog(self._warehouse, LABELS[kind], self._session.author, parent=self).exec()
        self._refresh_current()  # oyna bekor qilinsa ham, «Saqlash va yana qo'shish» bilan yozilganlari bo'lishi mumkin

    def _new_product(self) -> None:
        if ProductDialog(self._warehouse, parent=self).exec():
            self._refresh_current()
