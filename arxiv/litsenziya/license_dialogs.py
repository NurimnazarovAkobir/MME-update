"""Litsenziyani faollashtirish oynasi."""

from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QHBoxLayout, QPlainTextEdit, QWidget

from ..config import SELLER_CONTACT
from ..i18n import tr
from ..licensing import LicenseState, Licensing
from .dialogs import FormDialog
from .widgets import button, label

KEY_FIELD_HEIGHT = 110


def machine_code_row(licensing: Licensing) -> QWidget:
    """Kompyuter kodi va uni xotiraga nusxalash tugmasi."""
    copy = button(tr("Nusxa olish"))
    copy.setAutoDefault(False)
    copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(licensing.machine))
    row = QWidget()
    layout = QHBoxLayout(row)
    layout.setContentsMargins(0, 0, 0, 0)
    layout.addWidget(label(licensing.machine, "code"))
    layout.addWidget(copy)
    layout.addStretch()
    return row


class ActivationDialog(FormDialog):
    """Kompyuter kodini ko'rsatadi va sotuvchi bergan kalitni qabul qiladi.

    Muvaffaqiyatli faollashtirilgach, yangi holat `self.state` da bo'ladi.
    """

    def __init__(self, licensing: Licensing, parent: QWidget | None = None, cancel_text: str = tr("Bekor qilish")):
        super().__init__(tr("Litsenziya"), parent, save_text=tr("Faollashtirish"), cancel_text=cancel_text)
        self._licensing = licensing
        self.state: LicenseState | None = None

        steps = tr(
            "1. Quyidagi kompyuter kodini sotuvchiga yuboring.\n2. Sotuvchi bergan litsenziya "
            "kalitini pastdagi maydonga qo'ying.\nKalit faqat shu kompyuterda ishlaydi."
        )
        if SELLER_CONTACT:
            steps += tr("\n\nSotuvchi: {0}").format(SELLER_CONTACT)
        explanation = label(steps)
        explanation.setWordWrap(True)
        self._key = QPlainTextEdit()
        self._key.setPlaceholderText("MME1.…")
        self._key.setFixedHeight(KEY_FIELD_HEIGHT)

        self.form.addRow(label(licensing.state().summary, "sectionTitle"))
        self.form.addRow(explanation)
        self.form.addRow(tr("Kompyuter kodi"), machine_code_row(licensing))
        self.form.addRow(tr("Litsenziya kaliti"), self._key)

    def save(self) -> None:
        self.state = self._licensing.activate(self._key.toPlainText())
