"""Kirish, parol va foydalanuvchi oynalari."""

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QFileDialog, QLineEdit, QMessageBox, QPushButton, QWidget

from ..auth import Auth
from ..config import APP_NAME
from ..errors import WarehouseError
from ..i18n import tr
from ..local import LocalPrefs
from ..models import Role, User
from .dialogs import FormDialog
from .language import LANGUAGE_LABEL, language_box, restart_application
from .widgets import button, label

DEFAULT_ADMIN_NAME = tr("Rahbar")
ROLES_HINT = tr(
    "Omborchi kirim, chiqim va mahsulot qo'shadi, o'zi bugun kiritgan yozuvni tuzata oladi. "
    "Kuzatuvchi (masalan, buxgalter) faqat ko'radi. Qolgan hammasi — tahrirlash, o'chirish, "
    "inventarizatsiya, o'chirilganni tiklash va sozlamalar — faqat rahbarda."
)


def sign_in(auth: Auth, settings: LocalPrefs) -> User | None:
    """Dastur ochilganda: birinchi marta — rahbar hisobini yaratadi, keyin — parol so'raydi.

    Rahbar kirganda tiklash kodi hali yaratilmagan bo'lsa, yaratib ko'rsatadi.
    Foydalanuvchi oynani yopsa, None qaytadi.
    """
    dialog = LoginDialog(auth, settings) if auth.users() else SetupDialog(auth, settings)
    if not dialog.exec():
        return None
    if dialog.user.is_admin and not auth.has_recovery_code():
        show_new_recovery_code(auth)
    return dialog.user


def show_new_recovery_code(auth: Auth, parent: QWidget | None = None) -> None:
    show_recovery_code(auth.new_recovery_code(), parent)


def show_recovery_code(code: str, parent: QWidget | None = None) -> None:
    box = QMessageBox(QMessageBox.Icon.Information, tr("Parolni tiklash kodi"), "", parent=parent)
    box.setText(
        tr(
            "Parolni tiklash kodi:\n\n{0}\n\nUni qog'ozga yozib, ishonchli joyda saqlang. Parol "
            "unutilsa, faqat shu kod bilan yangi parol o'rnatish mumkin. Kod boshqa ko'rsatilmaydi."
        ).format(code)
    )
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    box.addButton(tr("Yozib oldim"), QMessageBox.ButtonRole.AcceptRole)
    box.exec()


def _password_input() -> QLineEdit:
    widget = QLineEdit()
    widget.setEchoMode(QLineEdit.EchoMode.Password)
    return widget


def _join_shared_database(prefs: LocalPrefs, parent: QWidget) -> None:
    """Kirish oynasidan: boshqa kompyuter umumiy papkaga qo'ygan bazaga ulanish."""
    folder = QFileDialog.getExistingDirectory(parent, tr("Umumiy papka"))
    if not folder:
        return
    if not prefs.has_database(Path(folder)):
        QMessageBox.warning(parent, APP_NAME, tr("Bu papkada baza (ombor.db) topilmadi."))
        return
    prefs.use_folder(Path(folder))
    restart_application()


def _network_button(prefs: LocalPrefs, parent: QWidget) -> QPushButton:
    join = button(tr("Tarmoqdagi bazaga ulanish"))
    join.setAutoDefault(False)
    join.setToolTip(tr("Baza boshqa kompyuterda yoki umumiy papkada bo'lsa, shu papkani ko'rsating"))
    join.clicked.connect(lambda: _join_shared_database(prefs, parent))
    return join


class PasswordDialog(FormDialog):
    """Muhim amaldan oldin joriy foydalanuvchining parolini so'raydi; to'g'ri bo'lsa — `password` da."""

    def __init__(self, auth: Auth, user: User, parent: QWidget | None = None):
        super().__init__(tr("Parolingizni kiriting"), parent, save_text=tr("Davom etish"))
        self._auth = auth
        self._user = user
        self.password = ""
        self._input = _password_input()
        self.form.addRow(tr("Parol"), self._input)

    def save(self) -> None:
        self._auth.login(self._user.id, self._input.text())
        self.password = self._input.text()


class _NewPasswordDialog(FormDialog):
    """Yangi parol ikki marta kiritiladigan oynalar uchun asos."""

    def __init__(self, title: str, parent: QWidget | None = None, save_text: str = tr("Saqlash")):
        super().__init__(title, parent, save_text)
        self._new = _password_input()
        self._repeat = _password_input()

    def add_new_password_rows(self) -> None:
        self.form.addRow(tr("Yangi parol"), self._new)
        self.form.addRow(tr("Parolni takrorlang"), self._repeat)

    def new_password(self) -> str:
        if self._new.text() != self._repeat.text():
            raise WarehouseError(tr("Parollar bir xil emas. Qaytadan kiriting."))
        return self._new.text()


class SetupDialog(_NewPasswordDialog):
    """Birinchi ishga tushirish: rahbar hisobini yaratadi."""

    def __init__(self, auth: Auth, settings: LocalPrefs):
        super().__init__(APP_NAME, save_text=tr("Boshlash"))
        self._auth = auth
        self.user: User | None = None
        self._name = QLineEdit(DEFAULT_ADMIN_NAME)
        intro = label(tr("Dasturdan foydalanishni boshlash uchun ismingizni kiriting va parol o'ylab toping."))
        intro.setWordWrap(True)
        self.form.addRow(LANGUAGE_LABEL, language_box(settings))
        self.form.addRow(intro)
        self.form.addRow(tr("Ismingiz"), self._name)
        self.add_new_password_rows()
        self.extra_buttons.addWidget(_network_button(settings, self))

    def save(self) -> None:
        self.user = self._auth.add_user(self._name.text(), self.new_password(), Role.ADMIN)


class LoginDialog(FormDialog):
    def __init__(self, auth: Auth, settings: LocalPrefs):
        super().__init__(APP_NAME, save_text=tr("Kirish"))
        self._auth = auth
        self.user: User | None = None

        self._users = QComboBox()
        for user in auth.users():
            self._users.addItem(f"{user.name} ({user.role.title})", user)
        self._password = _password_input()
        self.form.addRow(LANGUAGE_LABEL, language_box(settings))
        self.form.addRow(tr("Foydalanuvchi"), self._users)
        self.form.addRow(tr("Parol"), self._password)
        self._password.setFocus()

        forgot = button(tr("Parolni unutdim"))
        forgot.setAutoDefault(False)
        forgot.clicked.connect(self._recover)
        self.extra_buttons.addWidget(forgot)
        self.extra_buttons.addWidget(_network_button(settings, self))

    def save(self) -> None:
        try:
            self.user = self._auth.login(self._users.currentData().id, self._password.text())
        except WarehouseError:
            self._password.clear()
            raise

    def _recover(self) -> None:
        if RecoveryDialog(self._auth, self._users.currentData(), self).exec():
            QMessageBox.information(self, APP_NAME, tr("Yangi parol o'rnatildi. Endi shu parol bilan kiring."))


class RecoveryDialog(_NewPasswordDialog):
    """Unutilgan parol o'rniga tiklash kodi orqali yangisini o'rnatadi."""

    def __init__(self, auth: Auth, user: User, parent: QWidget | None = None):
        super().__init__(tr("Parolni tiklash — {0}").format(user.name), parent)
        self._auth = auth
        self._user = user
        self._code = QLineEdit()
        self._code.setPlaceholderText("XXXX-XXXX-XXXX")
        hint = label(
            tr(
                "Tiklash kodi rahbarga birinchi kirishda berilgan. Boshqa foydalanuvchilar parolini rahbar "
                "«Sozlamalar»da almashtiradi."
            ),
            "muted",
        )
        hint.setWordWrap(True)
        self.form.addRow(tr("Tiklash kodi"), self._code)
        self.add_new_password_rows()
        self.form.addRow(hint)

    def save(self) -> None:
        self._auth.reset_with_recovery_code(self._user.id, self._code.text(), self.new_password())


class ChangePasswordDialog(_NewPasswordDialog):
    """Foydalanuvchi o'z parolini almashtiradi."""

    def __init__(self, auth: Auth, user: User, parent: QWidget | None = None):
        super().__init__(tr("Parolni o'zgartirish"), parent)
        self._auth = auth
        self._user = user
        self._current = _password_input()
        self.form.addRow(tr("Joriy parol"), self._current)
        self.add_new_password_rows()

    def save(self) -> None:
        self._auth.change_password(self._user.id, self._current.text(), self.new_password())


class ResetPasswordDialog(_NewPasswordDialog):
    """Rahbar boshqa foydalanuvchiga yangi parol o'rnatadi."""

    def __init__(self, auth: Auth, user: User, parent: QWidget | None = None):
        super().__init__(tr("Yangi parol — {0}").format(user.name), parent)
        self._auth = auth
        self._user = user
        self.add_new_password_rows()

    def save(self) -> None:
        self._auth.set_password(self._user.id, self.new_password())


class UserDialog(_NewPasswordDialog):
    """Yangi foydalanuvchi qo'shish."""

    def __init__(self, auth: Auth, parent: QWidget | None = None):
        super().__init__(tr("Yangi foydalanuvchi"), parent)
        self._auth = auth
        self._name = QLineEdit()
        self._role = QComboBox()
        for role in (Role.KEEPER, Role.VIEWER, Role.ADMIN):
            self._role.addItem(role.title, role)
        hint = label(ROLES_HINT, "muted")
        hint.setWordWrap(True)
        self.form.addRow(tr("Ismi"), self._name)
        self.form.addRow(tr("Lavozimi"), self._role)
        self.add_new_password_rows()
        self.form.addRow(hint)

    def save(self) -> None:
        self._auth.add_user(self._name.text(), self.new_password(), self._role.currentData())
