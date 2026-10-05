"""Sozlamalar: ko'rinish, til, parol, foydalanuvchilar va zaxira nusxa.

Foydalanuvchilar va zaxira nusxa faqat rahbarga ko'rinadi.
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..backup import AUTO_COPIES_KEPT
from ..config import APP_NAME, APP_VERSION
from ..driver import sqlite3
from ..errors import WarehouseError
from ..i18n import tr
from ..models import User
from ..services import Services
from ..session import Session
from . import theme
from .auth_dialogs import (
    ROLES_HINT,
    ChangePasswordDialog,
    PasswordDialog,
    ResetPasswordDialog,
    UserDialog,
    show_new_recovery_code,
    show_recovery_code,
)
from .extra_dialogs import GroupsDialog, NameDialog
from .icons import Glyph, icon_label
from .language import language_box, restart_application, sign_out
from .widgets import Column, DataTable, button, card, confirm, label, page_header

THEME_KEY = "theme"

FILE_FILTER = tr("Zaxira nusxa (*.db)")
USERS_TABLE_HEIGHT = 170
SECTION_BADGE_SIZE = 36
FIELD_WIDTH = 320


def _button_row(*buttons: QPushButton) -> QWidget:
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 8, 0, 0)
    for widget in buttons:
        layout.addWidget(widget)
    layout.addStretch()
    return row


def _text(text: str, object_name: str = "") -> QLabel:
    widget = label(text, object_name)
    widget.setWordWrap(True)
    widget.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return widget


def _action(text: str, handler, role: str = "", glyph: str = "") -> QPushButton:
    widget = button(text, role, glyph)
    widget.clicked.connect(handler)
    return widget


def _section(glyph: str, tone: str, title: str, *widgets: QWidget) -> QFrame:
    """Sozlamalar bo'limi: rangli belgi va sarlavha, ostida — mazmuni."""
    badge = icon_label(glyph, f"badge{tone}")
    badge.setFixedSize(SECTION_BADGE_SIZE, SECTION_BADGE_SIZE)
    header = QWidget()
    row = QHBoxLayout(header)
    row.setContentsMargins(0, 0, 0, 4)
    row.setSpacing(12)
    row.addWidget(badge)
    row.addWidget(label(title, "sectionTitle"), stretch=1)
    return card(header, *widgets)


def _panel(widget: QWidget) -> QFrame:
    """Ma'lumot matni uchun ichki ramka (masalan, zaxira papkalari holati)."""
    frame = QFrame()
    frame.setObjectName("infoPanel")
    layout = QVBoxLayout(frame)
    layout.setContentsMargins(14, 10, 14, 10)
    layout.addWidget(widget)
    return frame


class SettingsPage(QWidget):
    def __init__(self, services: Services, session: Session, db_path: Path):
        super().__init__()
        self.setObjectName("page")
        self._auth = services.auth
        self._warehouse = services.warehouse
        self._backup = services.backup
        self._settings = services.settings
        self._session = session
        self._user = session.user
        self._db_path = db_path
        self._users = DataTable((Column(tr("Ismi")), Column(tr("Lavozimi"))))
        self._users.setFixedHeight(USERS_TABLE_HEIGHT)
        self._stores = DataTable((Column(tr("Ombor nomi")),))
        self._stores.setFixedHeight(USERS_TABLE_HEIGHT)
        self._groups = services.groups
        self._prefs = services.prefs
        self._vault = services.vault
        self._conn = services.conn
        self._backup_status = _text("", "muted")

        content = QWidget()
        content.setObjectName("page")
        cards = QVBoxLayout(content)
        cards.setContentsMargins(24, 20, 24, 16)
        cards.setSpacing(14)
        header, _tools = page_header(
            Glyph.SETTINGS, tr("Sozlamalar"), tr("Dastur ishlashini o'zingizga qulay qilib sozlang")
        )
        cards.addLayout(header)
        cards.addWidget(self._appearance_card())
        cards.addWidget(self._account_card())
        if session.is_admin:
            cards.addWidget(self._rules_card())
            cards.addWidget(self._stores_card())
            cards.addWidget(self._users_card())
            cards.addWidget(self._backup_card())
            cards.addWidget(self._network_card())
            if self._vault is not None:
                cards.addWidget(self._encryption_card())
        elif session.can_add:
            # Omborchi ham bazaning nusxasini saqlab qo'ya oladi; papka tanlash va tiklash — rahbarda.
            cards.addWidget(self._backup_card())
        cards.addWidget(self._about_card())
        cards.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def refresh(self) -> None:
        if self._session.can_add:
            self._backup_status.setText(self._describe_backups())
        if not self._user.is_admin:
            return
        users = self._auth.users()
        self._users.set_rows([(user.name, user.role.title) for user in users], ids=[user.id for user in users])
        self._fill_stores()

    # --- Kartochkalar ------------------------------------------------------

    def _appearance_card(self) -> QFrame:
        themes = QComboBox()
        for name, palette in theme.PALETTES.items():
            themes.addItem(palette.title, name)
        themes.setCurrentIndex(max(themes.findData(self._prefs.get(THEME_KEY, theme.DEFAULT_THEME)), 0))
        themes.currentIndexChanged.connect(lambda: self._change_theme(themes.currentData()))
        languages = language_box(self._prefs)
        columns = QWidget()
        row = QHBoxLayout(columns)
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(28)
        for title, hint, control in (
            (tr("Ko'rinish"), tr("Dastur fonini tanlang."), themes),
            (tr("Dastur tili"), tr("O'zgartirilganda dastur shu tilda qayta ochiladi."), languages),
        ):
            control.setFixedWidth(FIELD_WIDTH)
            column = QVBoxLayout()
            column.setSpacing(4)
            column.addWidget(label(title, "fieldTitle"))
            column.addWidget(label(hint, "muted"))
            column.addWidget(control)
            row.addLayout(column)
        row.addStretch()
        return _section(Glyph.SETTINGS, "Accent", tr("Asosiy sozlamalar"), columns)

    def _change_theme(self, name: str) -> None:
        self._prefs.set(THEME_KEY, name)
        theme.apply(QApplication.instance(), name)

    def _account_card(self) -> QFrame:
        buttons = [_action(tr("Parolni o'zgartirish"), self._change_password)]
        if self._user.is_admin:
            buttons.append(_action(tr("Yangi tiklash kodi"), self._new_recovery_code))
        buttons.append(_action(tr("Chiqish"), self._sign_out, "danger", Glyph.SIGN_OUT))
        return _section(
            Glyph.PERSON,
            "Violet",
            tr("Mening hisobim"),
            _text(tr("Siz {0} ({1}) sifatida kirgansiz.").format(self._user.name, self._user.role.title)),
            _button_row(*buttons),
        )

    def _sign_out(self) -> None:
        """Hisobdan chiqish: dastur kirish oynasi bilan qayta ochiladi."""
        sign_out(self)

    def _clear_history(self) -> None:
        question = tr(
            "«Tarix» bo'limidagi barcha o'zgarishlar yozuvi butunlay o'chiriladi va qaytarib bo'lmaydi. "
            "Kirim, chiqim va mahsulotlarga tegilmaydi.\n\nDavom etilsinmi?"
        )
        if not confirm(self, tr("Tarixni tozalash"), question, tr("Ha, tozalash")):
            return
        if not PasswordDialog(self._auth, self._user, self).exec():
            return
        removed = self._warehouse.clear_history()
        QMessageBox.information(
            self, tr("Tarixni tozalash"), tr("Tarix tozalandi: {0} ta yozuv o'chirildi.").format(removed)
        )

    def _rules_card(self) -> QFrame:
        group_required = QCheckBox(tr("Kirim va chiqimda guruh tanlash majburiy"))
        group_required.setChecked(self._warehouse.group_required)
        group_required.toggled.connect(lambda checked: setattr(self._warehouse, "group_required", checked))
        return _section(
            Glyph.TAG,
            "Warning",
            tr("Hisob qoidalari"),
            _text(tr("Yoqilsa, guruhsiz yozuv saqlanmaydi va hisobotda «(ko'rsatilmagan)» qatori chiqmaydi.")),
            group_required,
            _button_row(
                _action(tr("Guruhlarni tahrirlash"), lambda: GroupsDialog(self._groups, self).exec()),
                _action(tr("Tarixni tozalash"), self._clear_history, "danger", Glyph.DELETE),
            ),
        )

    # --- Omborlar ----------------------------------------------------------

    def _stores_card(self) -> QFrame:
        return _section(
            Glyph.BOX,
            "Accent",
            tr("Omborlar"),
            _text(
                tr(
                    "Bir nechta ombor bo'lsa, kirim va chiqimda ombor tanlanadi, «Mahsulotlar»da esa mahsulotni "
                    "ombordan omborga ko'chirish mumkin. Tannarx barcha omborlar uchun bitta."
                )
            ),
            self._stores,
            _button_row(
                _action(tr("+ Yangi ombor"), lambda: self._edit_store(None), "primary"),
                _action(tr("Nomini o'zgartirish"), self._rename_store),
                _action(tr("O'chirish"), self._delete_store, "danger"),
            ),
        )

    def _fill_stores(self) -> None:
        stores = self._warehouse.stores()
        self._stores.set_rows([(store.name,) for store in stores], ids=[store.id for store in stores])

    def _edit_store(self, store_id: int | None, name: str = "") -> None:
        dialog = NameDialog(tr("Ombor"), {tr("Ombor nomi"): name}, self)
        if not dialog.exec():
            return
        try:
            self._warehouse.save_store(dialog.names()[0], store_id)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Diqqat"), str(error))
        self._fill_stores()

    def _selected_store(self) -> tuple[int, str] | None:
        store_id = self._stores.selected_id()
        if store_id is None:
            QMessageBox.information(self, tr("Omborlar"), tr("Avval jadvaldan omborni tanlang."))
            return None
        return store_id, next(store.name for store in self._warehouse.stores() if store.id == store_id)

    def _rename_store(self) -> None:
        selected = self._selected_store()
        if selected:
            self._edit_store(*selected)

    def _delete_store(self) -> None:
        selected = self._selected_store()
        if selected is None:
            return
        try:
            self._warehouse.delete_store(selected[0])
        except WarehouseError as error:
            QMessageBox.warning(self, tr("O'chirib bo'lmadi"), str(error))
        self._fill_stores()

    def _about_card(self) -> QFrame:
        lines = (
            tr("F2 — yangi kirim, F3 — yangi chiqim, F4 — yangi mahsulot."),
            tr("Jadvalda: ikki marta bosish — tahrirlash, Delete — o'chirish, ustun sarlavhasi — saralash."),
            tr(
                "O'chirilgan yozuvni rahbar «Tarix» bo'limida tiklaydi; u yerda kim nimani o'zgartirgani ham ko'rinadi."
            ),
            tr(
                "Bir nakladnoydagi mahsulotlarni bir xil «Hujjat №» bilan «Saqlash va yana qo'shish» orqali "
                "kiriting, keyin «Nakladnoy» tugmasi bilan chop eting."
            ),
            tr(
                "Xizmat va xarajatlar (yuk tashish, ijara, kommunal) «Yangi mahsulot»da «Bu xizmat yoki xarajat» "
                "belgisi bilan qo'shiladi va kirim qilib yoziladi — ular sof foydadan ayriladi."
            ),
        )
        return _section(
            Glyph.INFO,
            "Accent",
            tr("Dastur haqida va qisqa yo'riqnoma"),
            _text(f"{APP_NAME} — {tr('Versiya {0}').format(APP_VERSION)}", "muted"),
            *(_text(f"•  {line}") for line in lines),
        )

    def _users_card(self) -> QFrame:
        return _section(
            Glyph.PEOPLE,
            "Violet",
            tr("Foydalanuvchilar"),
            _text(ROLES_HINT),
            self._users,
            _button_row(
                _action(tr("+ Yangi foydalanuvchi"), self._add_user, "primary"),
                _action(tr("Parolini almashtirish"), self._reset_user_password),
                _action(tr("O'chirish"), self._delete_user, "danger"),
            ),
        )

    def _backup_card(self) -> QFrame:
        """Rahbarga — to'liq; omborchiga — faqat «hozir nusxa olish» va papkani ochish."""
        is_admin = self._user.is_admin
        buttons = [
            *([_action(tr("Qo'shimcha papkani tanlash"), self._choose_extra_folder, "primary")] if is_admin else []),
            _action(tr("Hozir nusxa olish"), self._save_backup, "" if is_admin else "primary"),
            *([_action(tr("Zaxiradan tiklash"), self._restore_backup)] if self._session.can_modify else []),
            _action(tr("Papkani ochish"), self._open_backup_folder),
        ]
        return _section(
            Glyph.IMPORT,
            "Good",
            tr("Zaxira nusxa"),
            _text(
                tr(
                    "Dastur har ochilganda va yopilganda ma'lumotlarning nusxasini o'zi saqlaydi (oxirgi {0} "
                    "kun). Kompyuter diski buzilsa ham ma'lumot qolishi uchun qo'shimcha papka sifatida "
                    "fleshka yoki boshqa diskni tanlang."
                ).format(AUTO_COPIES_KEPT)
            ),
            _panel(self._backup_status),
            _button_row(*buttons),
        )

    # --- Tarmoqda ishlash --------------------------------------------------

    def _network_card(self) -> QFrame:
        buttons = [
            _action(tr("Bazani umumiy papkaga ko'chirish"), self._share_database, "primary"),
            _action(tr("Umumiy papkadagi bazaga ulanish"), self._join_database),
        ]
        if self._prefs.uses_shared_folder:
            buttons.append(_action(tr("Shu kompyuterdagi bazaga qaytish"), self._use_local_database))
        return _section(
            Glyph.SWITCH,
            "Accent",
            tr("Tarmoqda bir nechta kompyuterda ishlash"),
            _text(
                tr(
                    "Baza tarmoqdagi umumiy papkaga qo'yilsa, bir nechta kompyuter bir vaqtda ishlay oladi: "
                    "asosiy kompyuterda bazani umumiy papkaga ko'chiring, qolganlarida shu papkaga ulaning. "
                    "Barcha kompyuterlarda dastur versiyasi bir xil bo'lishi kerak. Har bir kompyuter zaxira "
                    "nusxani o'zida ham saqlaydi."
                )
            ),
            _text(tr("Baza papkasi: {0}").format(self._db_path.parent), "muted"),
            _button_row(*buttons),
        )

    def _choose_shared_folder(self) -> Path | None:
        folder = QFileDialog.getExistingDirectory(self, tr("Umumiy papka"), str(self._db_path.parent))
        return Path(folder) if folder else None

    def _restart_with_folder(self, folder: Path | None, message: str) -> None:
        self._prefs.use_folder(folder)
        QMessageBox.information(self, tr("Tarmoqda ishlash"), message)
        restart_application()

    def _share_database(self) -> None:
        folder = self._choose_shared_folder()
        if folder is None:
            return
        if self._prefs.has_database(folder):
            QMessageBox.warning(
                self,
                tr("Tarmoqda ishlash"),
                tr("Bu papkada baza allaqachon bor. Unga ulanish uchun «Umumiy papkadagi bazaga ulanish»ni bosing."),
            )
            return
        try:
            self._backup.save_to(folder / self._db_path.name)
        except (OSError, sqlite3.Error):
            QMessageBox.warning(self, tr("Tarmoqda ishlash"), tr("Bu papkaga yozib bo'lmadi. Boshqa papkani tanlang."))
            return
        self._restart_with_folder(
            folder,
            tr("Baza ko'chirildi:\n{0}\n\nDastur qayta ochiladi. Boshqa kompyuterlarda shu papkaga ulaning.").format(
                folder
            ),
        )

    def _join_database(self) -> None:
        folder = self._choose_shared_folder()
        if folder is None:
            return
        if not self._prefs.has_database(folder):
            QMessageBox.warning(self, tr("Tarmoqda ishlash"), tr("Bu papkada baza (ombor.db) topilmadi."))
            return
        question = tr(
            "Dastur shu papkadagi bazadan ishlaydi. Hozirgi (shu kompyuterdagi) ma'lumotlar o'chirilmaydi, "
            "lekin ko'rinmay qoladi.\n\nDavom etilsinmi?"
        )
        if confirm(self, tr("Tarmoqda ishlash"), question, tr("Ha, ulanish")):
            self._restart_with_folder(folder, tr("Dastur qayta ochiladi va umumiy bazaga ulanadi."))

    def _use_local_database(self) -> None:
        question = tr("Dastur yana shu kompyuterdagi bazadan ishlaydi. Umumiy bazaga tegilmaydi.\n\nDavom etilsinmi?")
        if confirm(self, tr("Tarmoqda ishlash"), question, tr("Ha, qaytish")):
            self._restart_with_folder(None, tr("Dastur qayta ochiladi."))

    # --- Shifrlash ---------------------------------------------------------

    def _encryption_card(self) -> QFrame:
        is_on = self._vault.enabled
        status = (
            tr("Hozir: baza shifrlangan. Kalit fayli: {0}").format(self._vault.path)
            if is_on
            else tr("Hozir: baza shifrlanmagan — faylni boshqa dastur bilan ochish mumkin.")
        )
        toggle = (
            _action(tr("Shifrlashni o'chirish"), self._disable_encryption, "danger")
            if is_on
            else _action(tr("Bazani shifrlash"), self._enable_encryption, "primary")
        )
        return _section(
            Glyph.DOCUMENT,
            "Out",
            tr("Bazani shifrlash"),
            _text(
                tr(
                    "Shifrlangan bazani parolsiz hech qanday dastur o'qiy olmaydi. Diqqat: parol ham, tiklash kodi "
                    "ham yo'qolsa, ma'lumotlarni hech kim tiklay olmaydi. Zaxira nusxalar ham shifrlanadi va "
                    "yonida kalit fayli (.kalit) bilan saqlanadi — ikkalasini birga saqlang."
                )
            ),
            _text(status, "muted"),
            _button_row(toggle),
        )

    def _enable_encryption(self) -> None:
        question = tr(
            "Baza shifrlanadi va dastur qayta ochiladi.\n\n"
            "• Boshqa kompyuterlarda dastur yopiq bo'lishi kerak.\n"
            "• Sizga yangi tiklash kodi beriladi — uni albatta yozib oling.\n"
            "• Boshqa foydalanuvchilar kira olishi uchun ularning parolini «Parolini almashtirish» bilan "
            "qayta o'rnatasiz.\n\nDavom etilsinmi?"
        )
        if not confirm(self, tr("Bazani shifrlash"), question, tr("Ha, shifrlash")):
            return
        dialog = PasswordDialog(self._auth, self._user, self)
        if not dialog.exec():
            return
        code = self._auth.new_recovery_code()
        try:
            self._vault.encrypt(self._conn, self._user, dialog.password, code)
        except (WarehouseError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, tr("Bazani shifrlash"), tr("Shifrlab bo'lmadi: {0}").format(error))
            return
        show_recovery_code(code, self)
        restart_application()

    def _disable_encryption(self) -> None:
        question = tr(
            "Baza oddiy (shifrlanmagan) holatga qaytariladi va dastur qayta ochiladi. Boshqa kompyuterlarda "
            "dastur yopiq bo'lishi kerak.\n\nDavom etilsinmi?"
        )
        if not confirm(self, tr("Bazani shifrlash"), question, tr("Ha, o'chirish")):
            return
        try:
            self._vault.decrypt(self._conn)
        except (WarehouseError, OSError, sqlite3.Error) as error:
            QMessageBox.warning(self, tr("Bazani shifrlash"), tr("Shifrlashni o'chirib bo'lmadi: {0}").format(error))
            return
        restart_application()

    def _describe_backups(self) -> str:
        lines = [tr("Ma'lumotlar fayli: {0}").format(self._db_path)]
        folders = (
            (tr("Avtomatik nusxalar"), self._backup.auto_folder),
            (tr("Qo'shimcha papka"), self._backup.extra_folder),
        )
        for title, folder in folders:
            if folder is None:
                lines.append(tr("{0}: tanlanmagan").format(title))
                lines.append(
                    tr(
                        "⚠ Hozir barcha nusxalar shu kompyuterning o'zida. Disk buzilsa, ular ham yo'qoladi — "
                        "fleshka yoki boshqa diskdagi papkani tanlang."
                    )
                )
                continue
            last = self._backup.last_automatic(folder)
            status = (
                tr("oxirgi nusxa {0:%d.%m.%Y %H:%M}").format(last)
                if last
                else tr("hali nusxa yo'q yoki papkaga yetib bo'lmayapti")
            )
            lines.append(f"{title}: {folder} — {status}")
        return "\n".join(lines)

    # --- Hisob va foydalanuvchilar ------------------------------------------

    def _change_password(self) -> None:
        if ChangePasswordDialog(self._auth, self._user, self).exec():
            QMessageBox.information(self, tr("Parol"), tr("Parol o'zgartirildi."))

    def _new_recovery_code(self) -> None:
        question = tr("Yangi tiklash kodi yaratiladi, eskisi ishlamay qoladi. Davom etilsinmi?")
        if confirm(self, tr("Tiklash kodi"), question, tr("Ha, yangi kod")):
            show_new_recovery_code(self._auth, self)

    def _selected_user(self) -> User | None:
        user_id = self._users.selected_id()
        if user_id is None:
            QMessageBox.information(self, tr("Foydalanuvchilar"), tr("Avval jadvaldan foydalanuvchini tanlang."))
            return None
        return next(user for user in self._auth.users() if user.id == user_id)

    def _add_user(self) -> None:
        if UserDialog(self._auth, self).exec():
            self.refresh()

    def _reset_user_password(self) -> None:
        user = self._selected_user()
        if user and ResetPasswordDialog(self._auth, user, self).exec():
            QMessageBox.information(self, tr("Parol"), tr("{0} uchun yangi parol o'rnatildi.").format(user.name))

    def _delete_user(self) -> None:
        user = self._selected_user()
        if user is None:
            return
        if user.id == self._user.id:
            QMessageBox.warning(self, tr("Foydalanuvchilar"), tr("O'z hisobingizni o'chira olmaysiz."))
            return
        question = tr("{0} o'chirilsinmi? U kiritgan yozuvlar saqlanib qoladi.").format(user.name)
        if not confirm(self, tr("O'chirish"), question, tr("Ha, o'chirish")):
            return
        try:
            self._auth.delete_user(user.id)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("O'chirib bo'lmadi"), str(error))
        self.refresh()

    # --- Zaxira nusxa ------------------------------------------------------

    def _choose_extra_folder(self) -> None:
        current = self._backup.extra_folder
        folder = QFileDialog.getExistingDirectory(self, tr("Qo'shimcha zaxira papkasi"), str(current or ""))
        if not folder:
            return
        self._backup.extra_folder = Path(folder)
        self._backup.run_automatic()
        self.refresh()

    def _open_backup_folder(self) -> None:
        self._backup.auto_folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(self._backup.auto_folder)))

    def _save_backup(self) -> None:
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        default_path = Path(documents) / tr("Ombor zaxira {0:%d.%m.%Y}.db").format(date.today())
        path, _ = QFileDialog.getSaveFileName(self, tr("Zaxira nusxani saqlash"), str(default_path), FILE_FILTER)
        if not path:
            return
        if Path(path).resolve() == self._db_path.resolve():
            QMessageBox.warning(self, tr("Zaxira nusxa"), tr("Zaxira nusxa uchun boshqa joy yoki boshqa nom tanlang."))
            return
        try:
            self._backup.save_to(path)
        except OSError:
            QMessageBox.warning(self, tr("Zaxira nusxa"), tr("Faylni saqlab bo'lmadi. Boshqa joyni tanlab ko'ring."))
            return
        QMessageBox.information(self, tr("Zaxira nusxa"), tr("Zaxira nusxa saqlandi:\n{0}").format(path))

    def _restore_backup(self) -> None:
        start_folder = str(self._backup.auto_folder) if self._backup.auto_folder.exists() else ""
        path, _ = QFileDialog.getOpenFileName(self, tr("Zaxira nusxani tanlash"), start_folder, FILE_FILTER)
        if not path:
            return
        if Path(path).resolve() == self._db_path.resolve():
            QMessageBox.warning(
                self, tr("Tiklash"), tr("Bu — dasturning joriy ma'lumotlar fayli. Zaxira faylni tanlang.")
            )
            return
        question = tr(
            "Hozirgi BARCHA mahsulot, kirim va chiqim yozuvlari tanlangan zaxira nusxadagi "
            "ma'lumotlar bilan almashtiriladi. Zaxiradan keyin kiritilgan yozuvlar yo'qoladi. "
            "Foydalanuvchilar va parollar o'zgarmaydi.\n\nDavom etilsinmi?"
        )
        if not confirm(self, tr("Zaxiradan tiklash"), question, tr("Ha, tiklash")):
            return
        try:
            self._backup.restore_from(path)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Tiklab bo'lmadi"), str(error))
            return
        self.refresh()
        QMessageBox.information(self, tr("Tiklash"), tr("Ma'lumotlar zaxira nusxadan tiklandi."))
