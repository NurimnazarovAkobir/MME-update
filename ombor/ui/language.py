"""Tilni almashtirish: tanlov saqlanadi va dastur yangi tilda qayta ochiladi."""

import os
import sys

from PySide6.QtCore import QProcess
from PySide6.QtWidgets import QApplication, QComboBox

from .. import i18n
from ..settings import Settings

LANGUAGE_LABEL = "Til / Язык"  # til hali tanlanmagan foydalanuvchi ham tushunishi uchun ikki tilda
LANGUAGE_BOX_WIDTH = 220


def language_box(settings: Settings) -> QComboBox:
    """Tillar ro'yxati; boshqa til tanlansa, dastur o'sha tilda qayta ochiladi."""
    box = QComboBox()
    for code, name in i18n.LANGUAGES.items():
        box.addItem(name, code)
    box.setCurrentIndex(box.findData(i18n.language()))
    box.setFixedWidth(LANGUAGE_BOX_WIDTH)
    box.currentIndexChanged.connect(lambda: _switch(settings, box.currentData()))
    return box


def _switch(settings: Settings, code: str) -> None:
    if code == i18n.language():
        return
    settings.set(i18n.LANGUAGE_KEY, code)
    restart_application()


def restart_application() -> None:
    """Dasturning yangi nusxasini ishga tushirib, joriysini odatdagi tartibda yopadi."""
    is_frozen = getattr(sys, "frozen", False)
    arguments = sys.argv[1:] if is_frozen else sys.argv
    # Yig'ilgan (PyInstaller) dastur yangi nusxani mustaqil jarayon sifatida ochishi uchun.
    os.environ["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    QProcess.startDetached(sys.executable, arguments)
    for window in QApplication.topLevelWidgets():
        window.close()
