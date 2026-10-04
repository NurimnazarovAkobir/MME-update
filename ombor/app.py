"""Dasturni ishga tushirish."""

import sys
import traceback

from PySide6.QtCore import QLibraryInfo, QLocale, QTranslator
from PySide6.QtWidgets import QApplication, QMessageBox

from . import i18n, update
from .auth import Auth, LockedAuth
from .backup import copy_before_upgrade
from .config import APP_NAME, BACKUP_DIR, DB_PATH
from .database import NewerDatabaseError, connect
from .driver import sqlite3
from .errors import WarehouseError
from .i18n import tr
from .local import LocalPrefs
from .models import User
from .paths import PREFS_PATH
from .services import Services
from .session import Session
from .settings import Settings
from .ui import theme
from .ui.auth_dialogs import sign_in
from .ui.icon import app_icon
from .ui.language import restart_application
from .ui.main_window import MainWindow
from .ui.settings_page import THEME_KEY
from .ui.widgets import confirm
from .vault import Vault

_LOCALES = {
    i18n.UZBEK: QLocale(QLocale.Language.Uzbek, QLocale.Script.LatinScript, QLocale.Country.Uzbekistan),
    i18n.RUSSIAN: QLocale(QLocale.Language.Russian, QLocale.Country.Uzbekistan),
}


def _show_unexpected_error(error_type, error, trace) -> None:
    """Kutilmagan xatoda dastur jimgina yopilib qolmasligi uchun xabar ko'rsatadi."""
    if issubclass(error_type, sqlite3.OperationalError) and "locked" in str(error):
        # Tarmoqdagi umumiy bazada boshqa kompyuter uzoq yozib turgan bo'lsa.
        QMessageBox.warning(
            None, APP_NAME, tr("Baza hozir boshqa kompyuterda band. Bir ozdan keyin amalni qayta bajaring.")
        )
        return
    details = "".join(traceback.format_exception(error_type, error, trace))
    box = QMessageBox(
        QMessageBox.Icon.Critical, APP_NAME, tr("Kutilmagan xatolik yuz berdi. Amalni qayta bajarib ko'ring.")
    )
    box.setDetailedText(details)
    box.exec()


def _translate_standard_dialogs(app: QApplication) -> None:
    """Qt ning o'z oynalari (chop etishni ko'rish, «Ha / Yo'q») ruschada rus tilida chiqadi.

    Qt da o'zbekcha tarjima yo'q, shuning uchun o'zbek tilida ular inglizcha qoladi.
    """
    if i18n.language() != i18n.RUSSIAN:
        return
    translator = QTranslator(app)
    if translator.load("qtbase_ru", QLibraryInfo.path(QLibraryInfo.LibraryPath.TranslationsPath)):
        app.installTranslator(translator)


def _open_database(key: str | None = None) -> sqlite3.Connection:
    """Bazani ochadi (kerak bo'lsa, avval eski versiyasining nusxasini saqlab)."""
    try:
        copy_before_upgrade(DB_PATH, BACKUP_DIR, key)
        return connect(DB_PATH, key)
    except NewerDatabaseError:
        raise WarehouseError(
            tr("Bu baza dasturning yangiroq versiyasida ochilgan. Shu kompyuterdagi dasturni ham yangilang.")
        ) from None


def _sign_in(vault: Vault, prefs: LocalPrefs) -> tuple[sqlite3.Connection, User] | None:
    """Bazani ochadi va foydalanuvchini kiritadi; foydalanuvchi kirish oynasini yopsa — None.

    Oddiy baza darhol ochiladi; shifrlangani — parol to'g'ri kiritilgandan keyin.
    """
    if vault.enabled:
        locked = LockedAuth(vault, _open_database)
        user = sign_in(locked, prefs)
        if user is None:
            if locked.conn is not None:
                locked.conn.close()
            return None
        return locked.conn, user

    conn = _open_database()
    _keep_legacy_theme(conn, prefs)
    user = sign_in(Auth(conn), prefs)
    if user is None:
        conn.close()
        return None
    return conn, user


def _keep_legacy_theme(conn: sqlite3.Connection, prefs: LocalPrefs) -> None:
    """Oldingi versiyalarda fon bazada saqlangan; endi u har bir kompyuterning shaxsiy sozlamasi."""
    legacy = Settings(conn).get(THEME_KEY)
    if legacy and not prefs.get(THEME_KEY):
        prefs.set(THEME_KEY, legacy)
        theme.apply(QApplication.instance(), legacy)


def _report_unreachable(prefs: LocalPrefs, error: Exception) -> None:
    """Baza papkasiga yetib bo'lmadi (masalan, tarmoq uzilgan): sababini aytadi va chiqish yo'lini taklif qiladi."""
    text = tr(
        "Bazani ochib bo'lmadi:\n{0}\n\nTarmoq va umumiy papka ulanganini tekshirib, dasturni qayta oching."
    ).format(DB_PATH)
    box = QMessageBox(QMessageBox.Icon.Critical, APP_NAME, text)
    box.setDetailedText(str(error))
    box.addButton(tr("Yopish"), QMessageBox.ButtonRole.RejectRole)
    local = (
        box.addButton(tr("Shu kompyuterdagi bazaga qaytish"), QMessageBox.ButtonRole.ActionRole)
        if prefs.uses_shared_folder
        else None
    )
    box.exec()
    if local is not None and box.clickedButton() is local:
        prefs.use_folder(None)
        restart_application()


def _offer_update(services: Services) -> bool:
    """Yangilanishlar papkasida yangiroq versiya bo'lsa, o'rnatishni taklif qiladi; o'rnatilsa — True."""
    folder = services.settings.get(update.UPDATE_FOLDER_KEY)
    found = update.available(folder) if folder and update.is_installed_program() else None
    if found is None:
        return False
    version, exe = found
    question = tr("Dasturning yangi versiyasi bor: {0}. Hozir o'rnatilsinmi? Dastur qayta ochiladi.").format(version)
    if not confirm(None, APP_NAME, question, tr("Ha, yangilash")):
        return False
    try:
        update.install(exe)
    except WarehouseError as error:
        QMessageBox.warning(None, APP_NAME, str(error))
        return False
    return True


def run() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    QLocale.setDefault(_LOCALES[i18n.language()])  # sana tanlagichdagi oy nomlari va son yozilishi
    _translate_standard_dialogs(app)
    sys.excepthook = _show_unexpected_error

    prefs = LocalPrefs(PREFS_PATH)
    if not prefs.get(i18n.LANGUAGE_KEY):
        prefs.set(i18n.LANGUAGE_KEY, i18n.language())
    theme.apply(app, prefs.get(THEME_KEY, theme.DEFAULT_THEME))
    if update.is_installed_program():
        update.remove_old_version()

    vault = Vault(DB_PATH)
    try:
        opened = _sign_in(vault, prefs)
    except WarehouseError as error:
        QMessageBox.critical(None, APP_NAME, str(error))
        return 1
    except (sqlite3.OperationalError, OSError) as error:
        _report_unreachable(prefs, error)
        return 1
    if opened is None:
        return 0

    conn, user = opened
    try:
        services = Services.create(conn, BACKUP_DIR, prefs, vault)
        if _offer_update(services):
            restart_application()
            return 0

        services.backup.run_automatic()
        window = MainWindow(services, Session(user), DB_PATH)
        window.showMaximized()
        exit_code = app.exec()
        try:
            services.backup.run_automatic()
        except sqlite3.Error:
            pass  # baza shifrlash yoki ko'chirish uchun yopilgan: dastur qayta ochilmoqda
        return exit_code
    finally:
        conn.close()
