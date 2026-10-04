"""Dasturni ishga tushirish."""

import sys
import traceback

from PySide6.QtCore import QLocale
from PySide6.QtWidgets import QApplication, QMessageBox

from . import i18n
from .backup import copy_before_upgrade
from .config import APP_NAME, BACKUP_DIR, DB_PATH
from .database import connect
from .i18n import tr
from .services import Services
from .session import Session
from .ui import theme
from .ui.auth_dialogs import sign_in
from .ui.icon import app_icon
from .ui.main_window import MainWindow
from .ui.settings_page import THEME_KEY

_LOCALES = {
    i18n.UZBEK: QLocale(QLocale.Language.Uzbek, QLocale.Script.LatinScript, QLocale.Country.Uzbekistan),
    i18n.RUSSIAN: QLocale(QLocale.Language.Russian, QLocale.Country.Uzbekistan),
}


def _show_unexpected_error(error_type, error, trace) -> None:
    """Kutilmagan xatoda dastur jimgina yopilib qolmasligi uchun xabar ko'rsatadi."""
    details = "".join(traceback.format_exception(error_type, error, trace))
    box = QMessageBox(
        QMessageBox.Icon.Critical, APP_NAME, tr("Kutilmagan xatolik yuz berdi. Amalni qayta bajarib ko'ring.")
    )
    box.setDetailedText(details)
    box.exec()


def run() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    QLocale.setDefault(_LOCALES[i18n.language()])  # sana tanlagichdagi oy nomlari va son yozilishi
    sys.excepthook = _show_unexpected_error

    copy_before_upgrade(DB_PATH, BACKUP_DIR)
    conn = connect(DB_PATH)
    try:
        services = Services.create(conn, BACKUP_DIR)
        theme.apply(app, services.settings.get(THEME_KEY, theme.DEFAULT_THEME))

        user = sign_in(services.auth, services.settings)
        if user is None:
            return 0

        services.backup.run_automatic()
        window = MainWindow(services, Session(user), DB_PATH)
        window.showMaximized()
        exit_code = app.exec()
        services.backup.run_automatic()
        return exit_code
    finally:
        conn.close()
