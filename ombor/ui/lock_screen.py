"""Avtomatik qulflash (Telegram'dagi kabi): dastur belgilangan vaqt ishlatilmasa, parol so'raydigan ekran chiqadi.

Har bir foydalanuvchi (rahbar, omborchi…) o'z parolini kiritib ochadi va qulflash vaqtini «Sozlamalar»da
o'zi tanlaydi. Tanlov shu kompyuterning shaxsiy sozlamalarida, foydalanuvchi bo'yicha saqlanadi.

Qulflanganda dasturning barcha oynalari (ochiq turgan kirim-chiqim oynalari ham) ko'rinmas bo'ladi va
yozilgan ma'lumot yo'qolmaydi: parol kiritilgach hammasi o'z holiga qaytadi.
"""

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QLineEdit, QVBoxLayout, QWidget
from shiboken6 import isValid

from ..auth import Auth
from ..config import APP_NAME
from ..errors import WarehouseError
from ..i18n import tr
from ..local import LocalPrefs
from ..models import User
from .language import restart_application
from .widgets import button, label

LOCK_MINUTES = (0, 1, 5, 15, 60)  # 0 — avtomatik qulflanmaydi
DEFAULT_LOCK_MINUTES = 15
FORM_WIDTH = 300
SUBMIT_HEIGHT = 46
_ACTIVITY_EVENTS = {
    QEvent.Type.MouseButtonPress,
    QEvent.Type.MouseMove,
    QEvent.Type.KeyPress,
    QEvent.Type.Wheel,
}


def lock_key(user: User) -> str:
    return f"auto_lock_minutes:{user.name.casefold()}"


def lock_minutes(prefs: LocalPrefs, user: User) -> int:
    value = prefs.get(lock_key(user), str(DEFAULT_LOCK_MINUTES))
    return int(value) if value.isdigit() and int(value) in LOCK_MINUTES else DEFAULT_LOCK_MINUTES


def set_lock_minutes(prefs: LocalPrefs, user: User, minutes: int) -> None:
    prefs.set(lock_key(user), str(minutes))


def lock_title(minutes: int) -> str:
    if minutes == 0:
        return tr("O'chirilgan")
    if minutes == 60:
        return tr("1 soat")
    return tr("{0} daqiqa").format(minutes)


class LockScreen(QDialog):
    """Parol so'raydigan ekran: «Parolingizni kiriting», parol maydoni, «Kirish» va «Hisobdan chiqish»."""

    def __init__(self, auth: Auth, user: User, minutes: int, parent: QWidget | None = None):
        # Asosiy oyna ramkasiz bo'lsa, qulf ekrani ham ramkasiz: u o'sha oynaning o'rnini to'liq egallaydi.
        frameless = parent is not None and bool(parent.windowFlags() & Qt.WindowType.FramelessWindowHint)
        flags = Qt.WindowType.Window
        if frameless:
            flags |= Qt.WindowType.FramelessWindowHint
        super().__init__(parent, flags)
        self.setObjectName("lockScreen")
        self.setWindowTitle(f"{APP_NAME} — {tr('qulflangan')}")
        self.setModal(True)
        self._auth = auth
        self._user = user

        self._password = QLineEdit()
        self._password.setObjectName("lockInput")
        self._password.setEchoMode(QLineEdit.EchoMode.Password)
        self._password.returnPressed.connect(self._submit)
        self._password.textChanged.connect(lambda: self._error.setText(""))
        self._error = label("", "error")
        self._error.setAlignment(Qt.AlignmentFlag.AlignCenter)
        submit = button(tr("Kirish"), "primary")
        submit.setObjectName("lockSubmit")
        submit.setAutoDefault(False)
        submit.setFixedHeight(SUBMIT_HEIGHT)
        submit.clicked.connect(self._submit)
        sign_out = button(tr("Hisobdan chiqish"), "link")
        sign_out.setAutoDefault(False)
        sign_out.clicked.connect(self._sign_out)
        hint = label(
            (
                tr("{0} ({1}) hisobi. Dastur {2} ishlatilmagani uchun qulflandi.").format(
                    user.name, user.role.title, lock_title(minutes)
                )
                if minutes
                else tr("{0} ({1}) hisobi qulflangan.").format(user.name, user.role.title)
            ),
            "muted",
        )
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        hint.setMinimumHeight(hint.heightForWidth(FORM_WIDTH))  # ikki qatorli izoh kesilmasin
        title = label(tr("Parolingizni kiriting"), "lockTitle")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)

        form = QWidget()
        form.setFixedWidth(FORM_WIDTH)
        column = QVBoxLayout(form)
        column.setContentsMargins(0, 0, 0, 0)
        column.setSpacing(6)
        column.addWidget(title)
        column.addSpacing(28)
        column.addWidget(label(tr("Parolingiz"), "lockFieldTitle"))
        column.addWidget(self._password)
        column.addWidget(self._error)
        column.addSpacing(20)
        column.addWidget(submit)
        column.addSpacing(8)
        column.addWidget(sign_out, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addWidget(hint)

        layout = QVBoxLayout(self)
        layout.addStretch(2)
        layout.addWidget(form, 0, Qt.AlignmentFlag.AlignHCenter)
        layout.addStretch(3)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self._password.setFocus()

    def reject(self) -> None:
        """Esc yoki oynani yopish qulfni ochmaydi."""

    def closeEvent(self, event) -> None:
        if self.result() != QDialog.DialogCode.Accepted:
            event.ignore()

    def unlock(self, password: str) -> bool:
        try:
            self._auth.login(self._user.id, password)
        except WarehouseError:
            self._error.setText(tr("Parol noto'g'ri."))
            self._password.selectAll()
            return False
        self.accept()
        return True

    def _submit(self) -> None:
        self.unlock(self._password.text())

    def _sign_out(self) -> None:
        self.done(QDialog.DialogCode.Accepted)
        restart_application()


class AutoLock(QObject):
    """Sichqoncha va klaviaturani kuzatadi; belgilangan vaqt harakat bo'lmasa, qulf ekranini ko'rsatadi."""

    def __init__(self, window: QWidget, auth: Auth, user: User, minutes: int):
        super().__init__(window)
        self._window = window
        self._auth = auth
        self._user = user
        self._minutes = minutes
        self._screen: LockScreen | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.lock)
        QApplication.instance().installEventFilter(self)
        self._restart()

    @property
    def minutes(self) -> int:
        return self._minutes

    @property
    def is_locked(self) -> bool:
        return self._screen is not None

    def set_minutes(self, minutes: int) -> None:
        self._minutes = minutes
        self._restart()

    def eventFilter(self, watched, event) -> bool:
        if event.type() in _ACTIVITY_EVENTS and self._screen is None:
            self._restart()
        return False

    def lock(self) -> None:
        """Qulf ekranini ko'rsatadi va parol to'g'ri kiritilguncha kutadi."""
        if self._screen is not None:
            return
        self._timer.stop()
        hidden = [
            (widget, widget.windowOpacity())
            for widget in QApplication.topLevelWidgets()
            if widget.isVisible() and widget.isWindow()
        ]
        self._screen = LockScreen(self._auth, self._user, self._minutes, self._window)
        self._screen.setGeometry(self._window.geometry())
        for widget, _opacity in hidden:  # orqadagi ma'lumot ko'rinmasin (yozilgani yo'qolmaydi)
            widget.setWindowOpacity(0.0)
        try:
            if self._window.isMaximized():
                self._screen.showMaximized()
            self._screen.exec()
        finally:
            for widget, opacity in hidden:
                if isValid(widget):  # hisobdan chiqilganda oynalar yopilgan bo'lishi mumkin
                    widget.setWindowOpacity(opacity)
            self._screen = None
            self._restart()

    def _restart(self) -> None:
        if self._minutes:
            self._timer.start(self._minutes * 60_000)
        else:
            self._timer.stop()
