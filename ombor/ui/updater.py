"""Yangilanishni fonda tekshirish va o'rnatish; dastur bu paytda ishlayveradi.

Bu yerda oynalar yo'q: natija signallar bilan «Yangilash» sahifasiga beriladi. Internet yoki
papka yetib bo'lmaydigan bo'lsa, tekshiruv shunchaki «yangilanish yo'q» deb tugaydi.
"""

import tempfile
import threading
from pathlib import Path

from PySide6.QtCore import QObject, Signal

from .. import update
from ..errors import WarehouseError
from ..update import Offer

DOWNLOAD_NAME = "MME-Ombor-yangi.exe"


class UpdateChecker(QObject):
    """Yangilanishlar papkasi va internetdagi manzilni tekshiradi; topilgan versiyani yuklab, o'rnatadi."""

    checked = Signal(object)  # Offer yoki None (yangi versiya yo'q yoki manbalarga yetib bo'lmadi)
    progress = Signal(int, int)  # yuklab olingan va jami baytlar
    installed = Signal()  # yangi exe joyiga qo'yildi — dastur qayta ochilishi kerak
    failed = Signal(str)  # yuklash yoki o'rnatishdagi xato matni

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)
        self._busy = threading.Lock()

    def check(self, folder: str, url: str) -> None:
        """Fonda tekshiradi; natija `checked` signali bilan keladi. Avvalgisi tugamagan bo'lsa, yangisi boshlanmaydi."""
        self._start(lambda: self.checked.emit(update.find(folder, url)))

    def install(self, offer: Offer) -> None:
        """Fonda (kerak bo'lsa yuklab olib) o'rnatadi; natija `installed` yoki `failed` signali bilan keladi."""
        self._start(lambda: self._install(offer))

    def _start(self, work) -> None:
        if not self._busy.acquire(blocking=False):
            return

        def run() -> None:
            try:
                work()
            except RuntimeError:
                pass  # sahifa yopilib bo'lgan: natijani yetkazadigan joy qolmagan
            finally:
                self._busy.release()

        threading.Thread(target=run, daemon=True).start()

    def _install(self, offer: Offer) -> None:
        try:
            exe = offer.exe
            if exe is None:
                exe = update.download(offer.url, Path(tempfile.gettempdir()) / DOWNLOAD_NAME, self.progress.emit)
            update.install(exe)
        except WarehouseError as error:
            self.failed.emit(str(error))
            return
        self.installed.emit()
