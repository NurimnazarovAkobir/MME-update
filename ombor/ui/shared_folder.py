"""Google Drive (yoki boshqa umumiy papka) orqali yagona bazaga ulanish oynalari."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QWidget

from ..backup import Backup
from ..driver import sqlite3
from ..folder_sync import FolderSynchronizer, SharedFolder, has_shared_data, remember_folder
from ..i18n import tr
from ..local import LocalPrefs
from ..sync import SyncError, device_name
from .language import restart_application
from .widgets import confirm

TITLE = tr("Google Drive orqali umumiy baza")
CHOOSE_HINT = tr(
    "Google Drive papkasini tanlang (masalan, «G:\\Mening Diskim» yoki rahbar ulashgan papka). "
    "Barcha kompyuterlarda xuddi shu papka tanlanishi kerak."
)


def choose_folder(parent: QWidget) -> Path | None:
    QMessageBox.information(parent, TITLE, CHOOSE_HINT)
    folder = QFileDialog.getExistingDirectory(parent, TITLE)
    return Path(folder) if folder else None


def join_folder(parent: QWidget, conn: sqlite3.Connection, prefs: LocalPrefs, backup: Backup | None) -> bool:
    """Ma'lumoti bor papkaga ulanadi: shu kompyuterdagi ma'lumotlar umumiy bazadagi bilan almashtiriladi va
    dastur qayta ochiladi (keyin har kim o'z login va paroli bilan kiradi). Ulansa — True."""
    folder = choose_folder(parent)
    if folder is None:
        return False
    if not has_shared_data(folder):
        QMessageBox.warning(
            parent,
            TITLE,
            tr(
                "Bu papkada umumiy baza topilmadi.\n\nAvval rahbar kompyuterida «Sozlamalar → Google Drive orqali "
                "umumiy baza» bo'limidan shu papkaga ulang, Google Drive uni bu kompyuterga ko'chirib bo'lgach "
                "qayta urining."
            ),
        )
        return False
    return _join(parent, conn, prefs, backup, folder)


def connect_folder(parent: QWidget, conn: sqlite3.Connection, prefs: LocalPrefs, backup: Backup) -> bool:
    """Sozlamalardan: papka bo'sh bo'lsa — shu kompyuterdagi baza umumiy bo'ladi; ma'lumot bo'lsa — unga ulanadi."""
    folder = choose_folder(parent)
    if folder is None:
        return False
    if has_shared_data(folder):
        return _join(parent, conn, prefs, backup, folder)
    question = tr(
        "Papka bo'sh. Shu kompyuterdagi barcha ma'lumotlar (foydalanuvchilar va parollar ham) umumiy baza sifatida "
        "shu papkaga yoziladi. Keyin boshqa kompyuterlarda dasturni o'rnatib, xuddi shu papkaga ulanasiz.\n\n"
        "Davom etilsinmi?"
    )
    if not confirm(parent, TITLE, question, tr("Ha, ulash")):
        return False
    with _busy():
        result = FolderSynchronizer(conn, SharedFolder(folder, device_name(prefs))).publish()
    remember_folder(prefs, folder)
    if result.ok:
        QMessageBox.information(parent, TITLE, tr("Ulandi. {0} ta yozuv umumiy papkaga yozildi.").format(result.sent))
    else:
        QMessageBox.warning(
            parent,
            TITLE,
            tr("Ulanish saqlandi, lekin hammasi yozilmadi: {0}\nPapka ko'ringanda dastur o'zi davom ettiradi.").format(
                result.error
            ),
        )
    return True


def _join(parent: QWidget, conn: sqlite3.Connection, prefs: LocalPrefs, backup: Backup | None, folder: Path) -> bool:
    question = tr(
        "Bu papkada umumiy baza bor. Shu kompyuterdagi ma'lumotlar umumiy bazadagi bilan ALMASHTIRILADI (avval zaxira "
        "nusxa olinadi). Keyin dastur qayta ochiladi — rahbar bergan login va parolingiz bilan kirasiz.\n\n"
        "Davom etilsinmi?"
    )
    if not confirm(parent, TITLE, question, tr("Ha, ulanish")):
        return False
    try:
        if backup is not None:
            backup.auto_folder.mkdir(parents=True, exist_ok=True)
            backup.save_to(backup.auto_folder / f"umumiy-bazaga-ulanishdan-oldin-{datetime.now():%Y-%m-%d-%H%M}.db")
        with _busy():
            FolderSynchronizer(conn, SharedFolder(folder, device_name(prefs))).join()
    except (SyncError, OSError, sqlite3.Error) as error:
        QMessageBox.warning(parent, TITLE, tr("Ulanib bo'lmadi: {0}").format(error))
        return False
    remember_folder(prefs, folder)
    QMessageBox.information(parent, TITLE, tr("Umumiy baza olindi. Dastur qayta ochiladi."))
    restart_application()
    return True


class _busy:
    def __enter__(self) -> None:
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

    def __exit__(self, *_exc) -> None:
        QApplication.restoreOverrideCursor()
