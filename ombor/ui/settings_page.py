"""Sozlamalar: ko'rinish, til, parol, foydalanuvchilar va zaxira nusxa.

Foydalanuvchilar va zaxira nusxa faqat rahbarga ko'rinadi.
"""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
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
from ..errors import WarehouseError
from ..i18n import tr
from ..models import User
from ..services import Services
from ..session import Session
from . import theme
from .auth_dialogs import ChangePasswordDialog, ResetPasswordDialog, UserDialog, show_new_recovery_code
from .language import language_box
from .widgets import Column, DataTable, button, card, confirm, label

THEME_KEY = "theme"

FILE_FILTER = tr("Zaxira nusxa (*.db)")
USERS_TABLE_HEIGHT = 150


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


def _action(text: str, handler, role: str = "") -> QPushButton:
    widget = button(text, role)
    widget.clicked.connect(handler)
    return widget


class SettingsPage(QWidget):
    def __init__(self, services: Services, session: Session, db_path: Path):
        super().__init__()
        self.setObjectName("page")
        self._auth = services.auth
        self._backup = services.backup
        self._settings = services.settings
        self._session = session
        self._user = session.user
        self._db_path = db_path
        self._users = DataTable((Column(tr("Ismi")), Column(tr("Lavozimi"))))
        self._users.setFixedHeight(USERS_TABLE_HEIGHT)
        self._backup_status = _text("", "muted")

        content = QWidget()
        content.setObjectName("page")
        cards = QVBoxLayout(content)
        cards.setContentsMargins(24, 20, 24, 16)
        cards.setSpacing(14)
        cards.addWidget(label(tr("Sozlamalar"), "pageTitle"))
        cards.addWidget(self._appearance_card())
        cards.addWidget(self._account_card())
        if session.is_admin:
            cards.addWidget(self._users_card())
            cards.addWidget(self._backup_card())
        cards.addStretch()

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(content)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(scroll)

    def refresh(self) -> None:
        if not self._user.is_admin:
            return
        users = self._auth.users()
        self._users.set_rows([(user.name, user.role.title) for user in users], ids=[user.id for user in users])
        self._backup_status.setText(self._describe_backups())

    # --- Kartochkalar ------------------------------------------------------

    def _appearance_card(self) -> QFrame:
        themes = QComboBox()
        for name, palette in theme.PALETTES.items():
            themes.addItem(palette.title, name)
        themes.setCurrentIndex(max(themes.findData(self._settings.get(THEME_KEY, theme.DEFAULT_THEME)), 0))
        themes.currentIndexChanged.connect(lambda: self._change_theme(themes.currentData()))
        themes.setFixedWidth(220)
        return card(
            label(tr("Ko'rinish"), "sectionTitle"),
            _text(tr("Dastur fonini tanlang.")),
            themes,
            _text(tr("Dastur tili. O'zgartirilganda dastur shu tilda qayta ochiladi.")),
            language_box(self._settings),
        )

    def _change_theme(self, name: str) -> None:
        self._settings.set(THEME_KEY, name)
        theme.apply(QApplication.instance(), name)

    def _account_card(self) -> QFrame:
        buttons = [_action(tr("Parolni o'zgartirish"), self._change_password)]
        if self._user.is_admin:
            buttons.append(_action(tr("Yangi tiklash kodi"), self._new_recovery_code))
        return card(
            label(tr("Mening hisobim"), "sectionTitle"),
            _text(tr("Siz {0} ({1}) sifatida kirgansiz.").format(self._user.name, self._user.role.title)),
            _button_row(*buttons),
        )

    def _users_card(self) -> QFrame:
        return card(
            label(tr("Foydalanuvchilar"), "sectionTitle"),
            _text(
                tr(
                    "Omborchi kirim, chiqim va mahsulot qo'shadi, hisobotlarni ko'radi. Tahrirlash, "
                    "o'chirish, inventarizatsiya va sozlamalar faqat rahbarda."
                )
            ),
            self._users,
            _button_row(
                _action(tr("+ Yangi foydalanuvchi"), self._add_user, "primary"),
                _action(tr("Parolini almashtirish"), self._reset_user_password),
                _action(tr("O'chirish"), self._delete_user, "danger"),
            ),
        )

    def _backup_card(self) -> QFrame:
        return card(
            label(tr("Zaxira nusxa"), "sectionTitle"),
            _text(
                tr(
                    "Dastur har ochilganda va yopilganda ma'lumotlarning nusxasini o'zi saqlaydi (oxirgi {0} "
                    "kun). Kompyuter diski buzilsa ham ma'lumot qolishi uchun qo'shimcha papka sifatida "
                    "fleshka yoki boshqa diskni tanlang."
                ).format(AUTO_COPIES_KEPT)
            ),
            self._backup_status,
            _button_row(
                _action(tr("Qo'shimcha papkani tanlash"), self._choose_extra_folder, "primary"),
                _action(tr("Hozir nusxa olish"), self._save_backup),
                *([_action(tr("Zaxiradan tiklash"), self._restore_backup)] if self._session.can_modify else []),
                _action(tr("Papkani ochish"), self._open_backup_folder),
            ),
        )

    def _describe_backups(self) -> str:
        lines = [tr("Ma'lumotlar fayli: {0}").format(self._db_path)]
        folders = (
            (tr("Avtomatik nusxalar"), self._backup.auto_folder),
            (tr("Qo'shimcha papka"), self._backup.extra_folder),
        )
        for title, folder in folders:
            if folder is None:
                lines.append(tr("{0}: tanlanmagan").format(title))
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
