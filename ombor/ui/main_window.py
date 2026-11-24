"""Asosiy oyna: chapda menyu, o'ngda tanlangan sahifa."""

from pathlib import Path

from PySide6.QtCore import QEvent, QRect, QRectF, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QIcon, QKeySequence, QPainter, QShortcut
from PySide6.QtWidgets import (
    QApplication,
    QFrame,
    QMessageBox,
    QPushButton,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QStackedWidget,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)

from .. import catalog
from ..config import APP_NAME
from ..driver import sqlite3
from ..i18n import tr
from ..models import MovementKind
from ..services import Services
from ..session import Session
from ..tiles import TileStore
from . import theme
from .dashboard_page import DashboardPage, Destination
from .debts_page import DebtsPage
from .dialogs import ProductDialog
from .document_dialog import DocumentDialog
from .history_page import HistoryPage
from .icon import app_icon, icon_pixmap
from .avatar import avatar_pixmap
from .icons import Glyph, icon_label, menu_icon
from .labels import LABELS
from .language import restart_application
from .lock_screen import AutoLock, lock_minutes
from .movements_page import MovementsPage
from .printing import set_firm_name
from .products_page import ProductsPage
from .reports_page import ReportsPage
from .returns_page import ReturnsPage
from .settings_page import PROFILE, SettingsPage
from .return_dialog import ReturnDialog
from .sites_page import SitesPage
from .sync_controller import SyncController, describe
from .tile_loader import TileLoader
from .update_page import UpdatePage
from .window_frame import FramelessFrame, clamp_maximized_size, uses_system_frame
from .widgets import button, label

SIDEBAR_WIDTH = 250
COLLAPSED_WIDTH = 80  # yig'ilgan yon menyu: faqat belgilar
SIDEBAR_COLLAPSED_KEY = "sidebar_collapsed"  # shu kompyuterning shaxsiy sozlamasi
TOGGLE_HEIGHT = 40
BRAND_WIDTH = 150  # yon menyu tepasidagi nom uchun joy (piksel)
LOGO_SIZE = 48
MENU_ICON_SIZE = 26
COLLAPSED_ICON_SIZE = 20  # yig'ilgan menyuda belgi kichikroq
COLLAPSED_TILE = 42  # yig'ilgan menyuda tanlangan qator — belgi atrofidagi o'rtadagi kvadrat
# Istalgan sahifadan yangi yozuv ochadigan tugmalar (bosh sahifadagi katta tugmalar yordam yozuvida ham bor).
NEW_RECEIPT_KEY, NEW_ISSUE_KEY, NEW_PRODUCT_KEY, NEW_RETURN_KEY = "F2", "F3", "F4", "F5"
LOCK_KEY = "Ctrl+L"
CHIP_AVATAR_SIZE, CHIP_HEIGHT = 36, 58
REFRESH_INTERVAL_MS = 10_000
MAP_FOLDER = "xarita"  # yuklab olingan xarita rasmlari (shu kompyuterning shaxsiy papkasida)
NOTIFICATION_MS = 15_000
BADGE_ROLE = Qt.ItemDataRole.UserRole + 1  # menyu qatoridagi belgi soni
BADGE_SIZE, BADGE_MARGIN = 22, 14
DIVIDER_ROLE = Qt.ItemDataRole.UserRole + 2  # shu qator ustida ajratuvchi chiziq chiziladi
DIVIDER_GAP, DIVIDER_INSET = 15, 10  # chiziq uchun qator ustidagi joy va chetlardan masofa


class MenuBadgeDelegate(QStyledItemDelegate):
    """Menyu qatorini chizadi: o'ng chetida qizil doira ichida son (masalan, yangilanish kelganda «1»)
    va, belgilangan qator ustida, kam ishlatiladigan bo'limlarni ajratib turuvchi chiziq.

    Menyu yig'ilganda (`collapsed`) son belgi ustiga, kichik doira bo'lib chiziladi."""

    collapsed = False

    def sizeHint(self, option: QStyleOptionViewItem, index):
        hint = super().sizeHint(option, index)
        if self.collapsed:
            hint.setHeight(COLLAPSED_TILE + 4)
        if index.data(DIVIDER_ROLE):
            hint.setHeight(hint.height() + DIVIDER_GAP)
        return hint

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        if index.data(DIVIDER_ROLE):
            line_y = option.rect.top() + DIVIDER_GAP // 2
            painter.save()
            painter.setPen(QColor(theme.palette().sidebar_hover))
            painter.drawLine(option.rect.left() + DIVIDER_INSET, line_y, option.rect.right() - DIVIDER_INSET, line_y)
            painter.restore()
            option = QStyleOptionViewItem(option)
            option.rect = option.rect.adjusted(0, DIVIDER_GAP, 0, 0)  # qatorning o'zi chiziqdan pastda
        if self.collapsed:
            self._paint_tile(painter, option, index)
        else:
            super().paint(painter, option, index)
        count = index.data(BADGE_ROLE)
        if not count:
            return
        if self.collapsed:
            size = BADGE_SIZE * 0.75
            circle = QRectF(option.rect.center().x() + 2, option.rect.top() + 4, size, size)
        else:
            size = BADGE_SIZE
            circle = QRectF(
                option.rect.right() - size - BADGE_MARGIN, option.rect.center().y() - size / 2 + 1, size, size
            )
        font = QFont(option.font)
        font.setPointSize(7 if self.collapsed else 9)
        font.setBold(True)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(theme.palette().danger))
        painter.drawEllipse(circle)
        painter.setPen(QColor("#ffffff"))
        painter.setFont(font)
        painter.drawText(circle, Qt.AlignmentFlag.AlignCenter, str(count))
        painter.restore()

    @staticmethod
    def _paint_tile(painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        """Yig'ilgan menyu qatori: o'rtada kvadrat (tanlangan — urg'u rangida, sichqoncha ustida — och) va belgi."""
        colors = theme.palette()
        center = option.rect.center()
        tile = QRect(0, 0, COLLAPSED_TILE, COLLAPSED_TILE)
        tile.moveCenter(center)
        selected = bool(option.state & QStyle.StateFlag.State_Selected)
        hovered = bool(option.state & QStyle.StateFlag.State_MouseOver)
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        if selected or hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(colors.accent if selected else colors.sidebar_hover))
            painter.drawRoundedRect(QRectF(tile), 10, 10)
        icon_rect = QRect(0, 0, COLLAPSED_ICON_SIZE, COLLAPSED_ICON_SIZE)
        icon_rect.moveCenter(center)
        icon = index.data(Qt.ItemDataRole.DecorationRole)
        if isinstance(icon, QIcon):
            mode = QIcon.Mode.Selected if selected else QIcon.Mode.Normal
            icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, mode)
        painter.restore()


class MainWindow(QMainWindow):
    def __init__(self, services: Services, session: Session, db_path: Path):
        super().__init__()
        self._settings = services.settings
        self._title_suffix = f"{session.user.name} ({session.user.role.title})"
        self._name_labels: list[QLabel] = []  # ombor nomi ko'rinadigan yozuvlar
        self._brand_name: QLabel | None = None  # rahbar bosib nomini o'zgartiradigan sarlavha
        self.resize(1280, 800)
        self.setMinimumSize(1100, 680)
        self._warehouse = services.warehouse
        for service in (self._warehouse, services.debts, services.sites):
            service.actor = session.author  # o'zgarishlar tarixiga shu ism va lavozim yoziladi
            service.actor_role = session.user.role.value
        self._session = session
        self._auth = services.auth

        self._sites = services.sites
        dashboard = DashboardPage(self._warehouse, services.reports, services.sites, session.can_add)
        dashboard.movement_requested.connect(self._new_movement)
        dashboard.return_requested.connect(self._new_return)
        dashboard.product_requested.connect(self._new_product)
        dashboard.page_requested.connect(self._open_destination)
        self._products_page = ProductsPage(self._warehouse, services.sites, session, services.importer, services.backup)
        self._products_title = tr("Mahsulotlar")
        self._sync = SyncController(services.prefs, services.reconnect, self)
        self._sync.finished.connect(self._show_sync_result)
        # (menyu nomi, belgi, sahifa, bosh sahifadan shu bo'limga o'tish kaliti)
        pages = [
            (tr("Bosh sahifa"), Glyph.HOME, dashboard, None),
            (
                tr("Kirim"),
                Glyph.RECEIPT,
                MovementsPage(self._warehouse, services.sites, LABELS[MovementKind.IN], session),
                Destination.RECEIPTS,
            ),
            (
                tr("Chiqim"),
                Glyph.ISSUE,
                MovementsPage(self._warehouse, services.sites, LABELS[MovementKind.OUT], session),
                Destination.ISSUES,
            ),
            (tr("Vozvrat"), Glyph.UNDO, ReturnsPage(services.sites, self._warehouse, session), None),
            (self._products_title, Glyph.PRODUCTS, self._products_page, Destination.PRODUCTS),
            (
                tr("Obyektlar"),
                Glyph.PIN,
                SitesPage(services.sites, session, self._map_tiles(services)),
                Destination.SITES,
            ),
            (
                tr("Hisobotlar"),
                Glyph.REPORTS,
                ReportsPage(services.reports, services.analytics, self._warehouse, services.sites),
                Destination.REPORTS,
            ),
            (tr("Qarzlar"), Glyph.MONEY, DebtsPage(services.debts, session), None),
        ]
        service_row = len(pages)  # shu qatordan boshlab — kam ishlatiladigan bo'limlar (chiziq bilan ajratiladi)
        pages.append((tr("Tarix"), Glyph.CLOCK, HistoryPage(self._warehouse, session), None))
        self._update_title = tr("Yangilash")
        self._update_page = UpdatePage(services, session)
        update_page = self._update_page
        update_page.availability_changed.connect(self._show_update_badge)
        self._announced_version = ""  # shu versiya haqida Windows bildirishnomasi ko'rsatilgan
        self._tray: QSystemTrayIcon | None = None
        self._update_row = len(pages)
        pages.append((self._update_title, Glyph.SYNC, update_page, None))
        settings_page = SettingsPage(services, session, db_path, self._sync)
        settings_page.firm_name_changed.connect(self._show_firm_name)
        settings_page.lock_minutes_changed.connect(lambda minutes: self._auto_lock.set_minutes(minutes))
        settings_page.lock_requested.connect(lambda: self._auto_lock.lock())
        settings_page.photo_changed.connect(self._show_chip_photo)
        self._settings_page = settings_page
        self._settings_row = len(pages)
        pages.append((tr("Sozlamalar"), Glyph.SETTINGS, settings_page, None))

        colors = theme.palette()
        self._pages = QStackedWidget()
        self._menu = QListWidget()
        self._menu.setObjectName("sidebar")
        self._menu.setIconSize(QSize(MENU_ICON_SIZE, MENU_ICON_SIZE))
        self._menu.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._menu.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self._menu_delegate = MenuBadgeDelegate(self._menu)
        self._menu.setItemDelegate(self._menu_delegate)
        self._rows: dict[Destination, int] = {}
        self._menu_titles = [title for title, *_rest in pages]
        for row, (title, glyph, page, destination) in enumerate(pages):
            self._menu.addItem(QListWidgetItem(menu_icon(glyph, colors.sidebar_text, "#ffffff"), f"  {title}"))
            self._pages.addWidget(page)
            if destination is not None:
                self._rows[destination] = row
        self._menu.item(service_row).setData(DIVIDER_ROLE, True)
        self._menu.currentRowChanged.connect(self._show_page)

        sidebar_panel = QWidget()
        sidebar_panel.setObjectName("sidebarPanel")
        self._sidebar_panel = sidebar_panel
        sidebar = QVBoxLayout(sidebar_panel)
        self._sidebar_layout = sidebar
        sidebar.setSpacing(12)
        self._sidebar_toggle = button("", "sidebarToggle", Glyph.MENU)
        self._sidebar_toggle.setFixedHeight(TOGGLE_HEIGHT)
        self._sidebar_toggle.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self._sidebar_toggle.clicked.connect(lambda: self.set_sidebar_collapsed(not self._sidebar_collapsed))
        sidebar.addWidget(self._sidebar_toggle)
        sidebar.addLayout(self._brand(session))
        sidebar.addWidget(self._menu, stretch=1)
        self._sync_status = label("", "syncStatus")
        self._sync_status.setVisible(self._sync.configured)
        self._sync_text = ""  # to'liq holat yozuvi: yig'ilgan menyuda faqat belgisi ko'rinadi
        sidebar.addWidget(self._sync_status)
        sidebar.addWidget(self._user_chip(session))
        self._prefs = services.prefs
        self._sidebar_collapsed = False

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
        # Telegram'dagi kabi o'z sarlavha qatori; «Sozlamalar»da Windows ramkasiga qaytish mumkin.
        self._frame = None if uses_system_frame(services.prefs) else FramelessFrame(self, central)
        if self._frame is None:
            self.setCentralWidget(central)

        if session.can_add:
            QShortcut(QKeySequence(NEW_RECEIPT_KEY), self, lambda: self._new_movement(MovementKind.IN))
            QShortcut(QKeySequence(NEW_ISSUE_KEY), self, lambda: self._new_movement(MovementKind.OUT))
            QShortcut(QKeySequence(NEW_PRODUCT_KEY), self, self._new_product)
            QShortcut(QKeySequence(NEW_RETURN_KEY), self, self._new_return)
        QShortcut(QKeySequence(LOCK_KEY), self, lambda: self._auto_lock.lock())
        self._auto_lock = AutoLock(self, services.auth, session.user, lock_minutes(services.prefs, session.user))
        self.set_sidebar_collapsed(self._prefs.get(SIDEBAR_COLLAPSED_KEY) == "1")
        self._menu.setCurrentRow(0)
        self._show_firm_name(self._settings.firm_name(APP_NAME))

        # Tarmoqda boshqa kompyuter bazani o'zgartirsa, ochiq sahifa o'zi yangilanadi.
        self._conn = services.conn
        self._data_version = self._read_data_version()
        self._watcher = QTimer(self)
        self._watcher.timeout.connect(self._refresh_if_changed_elsewhere)
        self._watcher.start(REFRESH_INTERVAL_MS)
        if self._sync.configured:
            self._show_sync_text(describe(None)[0])
            self._sync.start()

    def nativeEvent(self, event_type, message):
        """Ramkasiz oyna kattalashtirilganda vazifalar paneli ustiga chiqmasin (avtomatik yashirinsa ham chiqsin)."""
        if getattr(self, "_frame", None) is not None:
            clamp_maximized_size(event_type, message)
        return super().nativeEvent(event_type, message)

    def closeEvent(self, event) -> None:
        """Boshlangan sinxronlash tugashi kutiladi: baza yopilayotganda u yarim qolmasligi kerak."""
        self._sync.stop()
        super().closeEvent(event)

    def _show_sync_result(self, result) -> None:
        """Yon menyudagi holat; boshqa kompyuterlardan o'zgarish kelgan bo'lsa — ochiq sahifa darhol yangilanadi."""
        text, details = describe(result)
        self._sync_status.setVisible(self._sync.configured)
        self._sync_status.setToolTip(details)
        self._show_sync_text(text)
        if result.received:
            self._refresh_if_changed_elsewhere()

    def changeEvent(self, event) -> None:
        """Foydalanuvchi dastur oynasiga qaytganda yangi versiya chiqqan-chiqmagani tekshiriladi."""
        super().changeEvent(event)
        if event.type() == QEvent.Type.ActivationChange and self.isActiveWindow():
            self._update_page.check_if_stale()

    def _read_data_version(self) -> int:
        """Bazani boshqa ulanish (boshqa kompyuter) o'zgartirganda o'zgaradigan son."""
        return self._conn.execute("PRAGMA data_version").fetchone()[0]

    def _session_is_current(self) -> bool:
        """Kirgan hisob bazada hali o'sha ism va lavozim bilan turibdimi.

        Hisob boshqa kompyuterda o'chirilgan yoki lavozimi o'zgargan bo'lsa, yoki baza umumiy bazaga ulanib
        almashtirilgan bo'lsa (ochiq seans eskirib qoladi) — False: foydalanuvchi qayta kirishi kerak.
        """
        current = self._auth.user(self._session.user.id)
        user = self._session.user
        return current is not None and (current.name, current.role) == (user.name, user.role)

    def _require_sign_in_if_stale(self) -> bool:
        """Seans eskirgan bo'lsa — xabar beradi va dasturni kirish oynasi bilan qayta ochadi. Eskirgan — True."""
        if not hasattr(self, "_watcher"):
            return False  # oyna hali qurilmoqda: seans hozirgina kirish oynasida tekshirilgan
        try:
            if self._session_is_current():
                return False
        except sqlite3.Error:
            return False  # baza vaqtincha band — keyingi safar
        self._watcher.stop()
        QMessageBox.information(
            self,
            APP_NAME,
            tr(
                "Hisobingiz o'zgardi (yoki baza umumiy bazaga ulandi). Iltimos, o'z login va parolingiz bilan qayta kiring."
            ),
        )
        restart_application()
        return True

    def _refresh_if_changed_elsewhere(self) -> None:
        if QApplication.activeModalWidget() is not None:
            return  # oyna ochiq turganda jadval ostidan o'zgarib ketmasin
        if self._require_sign_in_if_stale():
            return
        try:
            version = self._read_data_version()
        except sqlite3.Error:
            return  # tarmoq vaqtincha uzilgan yoki baza band — keyingi safar
        if version != self._data_version:
            self._data_version = version
            catalog.load(self._conn)  # guruhlar boshqa kompyuterda o'zgargan bo'lishi mumkin
            self._show_chip_photo()  # rasm boshqa kompyuterda qo'yilgan bo'lishi mumkin
            self._refresh_current()

    def _map_tiles(self, services: Services) -> TileLoader | None:
        """Xarita rasmlarini yuklovchi; ular shu kompyuterdagi «xarita» papkasida saqlanadi.

        Shaxsiy papka bo'lmasa (sozlamalar faqat xotirada), xarita rasmsiz ishlaydi.
        """
        folder = services.prefs.folder
        return TileLoader(TileStore(folder / MAP_FOLDER), self) if folder else None

    def _user_chip(self, session: Session) -> QPushButton:
        """Yon menyu pastida: kim kirgani. Bosilsa — Sozlamalarning «Profil» bo'limi (parol, qulflash, chiqish)."""
        chip = QPushButton()
        chip.setObjectName("userChip")
        chip.setCursor(Qt.CursorShape.PointingHandCursor)
        chip.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        chip.setToolTip(tr("Profil: parol, qulflash ({0}) va chiqish").format(LOCK_KEY))
        avatar = QLabel()
        avatar.setFixedSize(CHIP_AVATAR_SIZE, CHIP_AVATAR_SIZE)
        self._chip_avatar = avatar
        self._show_chip_photo()
        self._chip_texts = QWidget()
        names = QVBoxLayout(self._chip_texts)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(0)
        names.addWidget(label(session.user.name, "chipName"))
        names.addWidget(label(session.user.role.title, "firm"))
        self._chip_chevron = icon_label(Glyph.CHEVRON, "chevron")
        row = QHBoxLayout(chip)
        row.setContentsMargins(10, 8, 10, 8)
        row.setSpacing(10)
        row.addWidget(avatar)
        row.addWidget(self._chip_texts, stretch=1)
        row.addWidget(self._chip_chevron)
        for widget in (avatar, self._chip_texts, *chip.findChildren(QLabel)):
            widget.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        chip.setFixedHeight(CHIP_HEIGHT)
        chip.clicked.connect(self._open_profile)
        return chip

    def _show_chip_photo(self) -> None:
        """Yon menyu kartochkasidagi profil rasmi (boshqa kompyuterda o'zgarsa ham yangilanadi)."""
        user = self._session.user
        self._chip_avatar.setPixmap(avatar_pixmap(user.name, self._auth.photo(user.id), CHIP_AVATAR_SIZE))

    def _open_profile(self) -> None:
        self._menu.setCurrentRow(self._settings_row)
        self._settings_page.show_section(PROFILE)

    def _brand(self, session: Session) -> QHBoxLayout:
        """Yuqoridagi belgi, dastur nomi va uning ostida foydalanuvchi lavozimi."""
        logo = QLabel()
        logo.setPixmap(icon_pixmap(LOGO_SIZE))
        logo.setFixedSize(LOGO_SIZE, LOGO_SIZE)
        owner = label(tr("{0} paneli").format(session.user.role.title), "firm")
        owner.setWordWrap(True)
        self._brand_texts = QWidget()  # yig'ilgan menyuda yashiriladi, belgi qoladi
        names = QVBoxLayout(self._brand_texts)
        names.setContentsMargins(0, 0, 0, 0)
        names.setSpacing(2)
        names.addStretch()
        brand_name = label(APP_NAME, "brand")
        self._name_labels.append(brand_name)
        if session.is_admin:  # rahbar nomni bosib o'zgartiradi
            brand_name.setCursor(Qt.CursorShape.PointingHandCursor)
            brand_name.installEventFilter(self)
            self._brand_name = brand_name
        names.addWidget(brand_name)
        names.addWidget(owner)
        names.addStretch()
        brand = QHBoxLayout()
        brand.setSpacing(12)
        brand.addWidget(logo)
        brand.addWidget(self._brand_texts, stretch=1)
        return brand

    def _show_page(self, index: int) -> None:
        """Sahifa har ochilganda ma'lumotlari yangilanadi."""
        if self._require_sign_in_if_stale():
            return
        page = self._pages.widget(index)
        page.refresh()
        self._pages.setCurrentWidget(page)
        self._update_attention_badge()

    def _update_attention_badge(self) -> None:
        """«Mahsulotlar» yonida kam qolgan yoki tugagan mahsulotlar soni — bosh sahifani band qilmaydigan eslatma."""
        count = self._warehouse.attention_count()
        row = self._rows[Destination.PRODUCTS]
        self._menu_titles[row] = f"{self._products_title}  ⚠ {count}" if count else self._products_title
        self._show_menu_item(row)
        hint = tr("{0} ta mahsulot kam qolgan yoki tugagan").format(count) if count else ""
        if hint:
            self._menu.item(row).setToolTip(f"{self._products_title}\n{hint}" if self._sidebar_collapsed else hint)

    # --- Yon menyuni yig'ish ---------------------------------------------------

    def set_sidebar_collapsed(self, collapsed: bool) -> None:
        """Yon menyuni toraytiradi (faqat belgilar; nomlari — sichqoncha ustida) yoki to'liq ko'rsatadi."""
        self._sidebar_collapsed = collapsed
        self._prefs.set(SIDEBAR_COLLAPSED_KEY, "1" if collapsed else "")
        self._sidebar_panel.setFixedWidth(COLLAPSED_WIDTH if collapsed else SIDEBAR_WIDTH)
        side = 10 if collapsed else 16
        self._sidebar_layout.setContentsMargins(side, 12, side, 16)
        self._sidebar_toggle.setToolTip(tr("Menyuni yoyish") if collapsed else tr("Menyuni yig'ish"))
        self._sidebar_toggle.setProperty("collapsed", collapsed)  # yig'ilganda belgi o'rtada
        self._sidebar_toggle.style().unpolish(self._sidebar_toggle)
        self._sidebar_toggle.style().polish(self._sidebar_toggle)
        for widget in (self._brand_texts, self._chip_texts, self._chip_chevron):
            widget.setVisible(not collapsed)
        self._menu_delegate.collapsed = collapsed
        # Yig'ilgan menyuda aylantirish chizig'i belgilarni chetga surmasin (g'ildirak bilan baribir aylanadi).
        self._menu.setVerticalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff if collapsed else Qt.ScrollBarPolicy.ScrollBarAsNeeded
        )
        for row in range(self._menu.count()):
            self._show_menu_item(row)
        self._menu.doItemsLayout()  # qator balandligi o'zgardi
        self._show_sync_text(self._sync_text)
        self._menu.viewport().update()

    def _show_menu_item(self, row: int) -> None:
        item = self._menu.item(row)
        title = self._menu_titles[row]
        item.setText("" if self._sidebar_collapsed else f"  {title}")
        item.setToolTip(title if self._sidebar_collapsed else "")

    def _show_sync_text(self, text: str) -> None:
        """Sinxronlash holati; yig'ilgan menyuda — faqat belgisi (☁ yoki ⚠), to'liq matn — sichqoncha ustida."""
        self._sync_text = text
        self._sync_status.setText(text.split(" ")[0] if self._sidebar_collapsed else text)
        self._sync_status.setAlignment(
            Qt.AlignmentFlag.AlignCenter if self._sidebar_collapsed else Qt.AlignmentFlag.AlignLeft
        )

    def eventFilter(self, watched, event) -> bool:
        if watched is self._brand_name and event.type() == QEvent.Type.MouseButtonRelease:
            self._settings_page.rename_firm()
            return True
        return super().eventFilter(watched, event)

    def _show_firm_name(self, name: str) -> None:
        """Rahbar bergan ombor nomini sarlavha va yon menyuda ko'rsatadi."""
        for name_label in self._name_labels:
            hint = tr("Nomini o'zgartirish uchun bosing") if name_label is self._brand_name else ""
            name_label.setToolTip(f"{name}\n{hint}" if hint else name)
            if name_label.wordWrap():
                name_label.setText(name)
            else:  # yuqoridagi sarlavha bir qatorda: uzun nom «…» bilan qisqaradi, menyu pastga surilmaydi
                name_label.ensurePolished()  # uslublar jadvalidagi shrift (13pt, qalin) bilan o'lchash uchun
                name_label.setText(name_label.fontMetrics().elidedText(name, Qt.TextElideMode.ElideRight, BRAND_WIDTH))
        self.setWindowTitle(f"{name} — {self._title_suffix}")
        set_firm_name(name)  # chop etiladigan varaqlarda ham shu nom chiqadi

    def _show_update_badge(self, available: bool) -> None:
        """Yangi versiya chiqqanda «Yangilash» yonida belgi — oyna chiqarib ishni to'xtatmaydi."""
        item = self._menu.item(self._update_row)
        item.setData(BADGE_ROLE, 1 if available else None)  # qizil doiradagi «1» — MenuBadgeDelegate chizadi
        item.setToolTip(tr("Dasturning yangi versiyasi bor") if available else "")
        self._menu.viewport().update()
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
        open_page.clicked.connect(self._update_now)
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

    def _update_now(self) -> None:
        """Tepadagi «Yangilash» tugmasi: bo'limni ochadi va yuklab olib o'rnatishni darhol boshlaydi."""
        self._open_update_page()
        self._notice.hide()
        self._update_page.start_install()

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
        DocumentDialog(self._warehouse, self._sites, LABELS[kind], self._session.author, self).exec()
        self._refresh_current()  # oyna bekor qilinsa ham, «To'liq shakl»da saqlangan yozuvlar bo'lishi mumkin

    def _new_return(self) -> None:
        ReturnDialog(self._sites, self._warehouse, self._session.author, parent=self).exec()
        self._refresh_current()  # «Saqlash va yana qo'shish» bilan yozilganlari bo'lishi mumkin

    def _new_product(self) -> None:
        if ProductDialog(self._warehouse, parent=self).exec():
            self._refresh_current()
