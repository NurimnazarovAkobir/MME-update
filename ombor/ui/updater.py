"""Internet orqali yangilash: tekshiruv va yuklab olish fonda bajariladi, dastur bu paytda ishlayveradi.

Internet yo'q yoki uzilib qolgan bo'lsa, tekshiruv jimgina natijasiz tugaydi — foydalanuvchiga xalaqit bermaydi.
"""

import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import QMessageBox, QProgressDialog, QWidget

from .. import update
from ..config import APP_NAME
from ..errors import WarehouseError
from ..i18n import tr
from .language import restart_application
from .widgets import confirm

DOWNLOAD_NAME = "MME-Ombor-yangi.exe"


class OnlineUpdater(QObject):
    """Bitta manzil bo'yicha yangilanishni tekshiradi, taklif qiladi, yuklab oladi va o'rnatadi."""

    found = Signal(str)  # yangiroq versiya raqami
    nothing_found = Signal()  # yangi versiya yo'q yoki internetga chiqib bo'lmadi
    progress = Signal(int, int)  # yuklab olingan va jami baytlar
    downloaded = Signal(str)  # yuklab olingan fayl yo'li
    failed = Signal(str)  # yuklab olishdagi xato matni

    def __init__(self, url: str, parent: QWidget):
        super().__init__(parent)
        self._url = url
        self._parent = parent
        self._dialog: QProgressDialog | None = None
        self.found.connect(self._offer)
        self.progress.connect(self._show_progress)
        self.downloaded.connect(self._install)
        self.failed.connect(self._report_failure)

    def check(self) -> None:
        """Fonda tekshiradi; natija `found` yoki `nothing_found` signali bilan keladi."""
        threading.Thread(target=self._check, daemon=True).start()

    def _check(self) -> None:
        version = update.available_online(self._url)
        if version:
            self.found.emit(version)
        else:
            self.nothing_found.emit()

    def _offer(self, version: str) -> None:
        question = tr(
            "Dasturning yangi versiyasi bor: {0}. Hozir yuklab olib o'rnatilsinmi? "
            "Ma'lumotlar saqlanib qoladi, dastur qayta ochiladi."
        ).format(version)
        if not confirm(self._parent, APP_NAME, question, tr("Ha, yangilash")):
            return
        self._dialog = QProgressDialog(tr("Yangi versiya yuklab olinmoqda…"), "", 0, 0, self._parent)
        self._dialog.setWindowTitle(APP_NAME)
        self._dialog.setCancelButton(None)
        self._dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self._dialog.setMinimumDuration(0)
        self._dialog.show()
        threading.Thread(target=self._download, daemon=True).start()

    def _download(self) -> None:
        target = Path(tempfile.gettempdir()) / DOWNLOAD_NAME
        try:
            update.download(self._url, target, self.progress.emit)
        except WarehouseError as error:
            self.failed.emit(str(error))
            return
        self.downloaded.emit(str(target))

    def _show_progress(self, done: int, total: int) -> None:
        if self._dialog is not None and total > 0:
            self._dialog.setMaximum(total)
            self._dialog.setValue(min(done, total - 1))  # to'lib ketsa, oyna o'zi yopilib qoladi

    def _close_dialog(self) -> None:
        if self._dialog is not None:
            self._dialog.close()
            self._dialog = None

    def _report_failure(self, message: str) -> None:
        self._close_dialog()
        QMessageBox.warning(self._parent, APP_NAME, message)

    def _install(self, path: str) -> None:
        self._close_dialog()
        try:
            update.install(path)
        except WarehouseError as error:
            QMessageBox.warning(self._parent, APP_NAME, str(error))
            return
        QMessageBox.information(self._parent, APP_NAME, tr("Yangi versiya o'rnatildi. Dastur qayta ochiladi."))
        restart_application()
