"""Sotuvchi dasturi: mijozning kompyuter kodi bo'yicha litsenziya kaliti yaratadi.

Ishga tushirish: sotuvchi\\litsenziya.bat. Maxfiy kalit (maxfiy_kalit.pem) shu
papkada turishi kerak. Berilgan har bir kalit berilgan_litsenziyalar.csv ga yoziladi.
"""

import csv
import sys
from datetime import date, timedelta
from pathlib import Path

SELLER_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SELLER_DIR.parent))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QApplication,
    QComboBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from ombor.config import APP_NAME  # noqa: E402
from ombor.errors import WarehouseError  # noqa: E402
from ombor.formatting import fmt_date  # noqa: E402
from ombor.licensing import (  # noqa: E402
    MACHINE_CODE_ALPHABET,
    MACHINE_CODE_GROUP_SIZE,
    MACHINE_CODE_GROUPS,
    License,
    create_license,
    normalize_machine_code,
)
from ombor.ui import theme  # noqa: E402
from ombor.ui.widgets import Column, DataTable, button, card, label  # noqa: E402

PRIVATE_KEY_PATH = SELLER_DIR / "maxfiy_kalit.pem"
JOURNAL_PATH = SELLER_DIR / "berilgan_litsenziyalar.csv"
JOURNAL_HEADER = ("Berilgan sana", "Firma", "Kompyuter kodi", "Amal qilish muddati", "Kalit")
PERPETUAL = "muddatsiz"
# Muddat nomi -> kunlar soni (None — muddatsiz).
DURATIONS = {"1 oy": 30, "3 oy": 90, "6 oy": 180, "1 yil": 365, "Muddatsiz": None}
DEFAULT_DURATION = "1 yil"


def load_private_key(path: Path = PRIVATE_KEY_PATH) -> Ed25519PrivateKey:
    try:
        return serialization.load_pem_private_key(path.read_bytes(), password=None)
    except (OSError, ValueError) as error:
        raise WarehouseError(f"Maxfiy kalit topilmadi yoki buzilgan: {path}") from error


def format_machine_code(code: str) -> str:
    """Mijoz yuborgan kodni tekshiradi va 'XXXX-XXXX-XXXX' ko'rinishiga keltiradi."""
    characters = normalize_machine_code(code)
    length = MACHINE_CODE_GROUPS * MACHINE_CODE_GROUP_SIZE
    if len(characters) != length or set(characters) - set(MACHINE_CODE_ALPHABET):
        raise WarehouseError(f"Kompyuter kodi noto'g'ri. U {length} ta belgidan iborat: XXXX-XXXX-XXXX.")
    return "-".join(characters[i : i + MACHINE_CODE_GROUP_SIZE] for i in range(0, length, MACHINE_CODE_GROUP_SIZE))


def issue_license(
    private_key: Ed25519PrivateKey,
    firm: str,
    machine: str,
    days: int | None,
    today: date,
    journal: Path = JOURNAL_PATH,
) -> str:
    """Kalit yaratadi va jurnalga yozadi. `days` — None bo'lsa, muddatsiz."""
    firm = firm.strip()
    if not firm:
        raise WarehouseError("Firma nomini kiriting.")
    license = License(
        firm=firm,
        machine=format_machine_code(machine),
        expires=today + timedelta(days=days) if days else None,
        issued=today,
    )
    key = create_license(private_key, license)
    is_new = not journal.exists()
    with journal.open("a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file, delimiter=";")
        if is_new:
            writer.writerow(JOURNAL_HEADER)
        expires = fmt_date(license.expires) if license.expires else PERPETUAL
        writer.writerow((fmt_date(today), firm, license.machine, expires, key))
    return key


def read_journal(journal: Path = JOURNAL_PATH) -> list[list[str]]:
    """Berilgan litsenziyalar, eng yangisidan boshlab (kalit ustunisiz)."""
    if not journal.exists():
        return []
    with journal.open(newline="", encoding="utf-8-sig") as file:
        rows = list(csv.reader(file, delimiter=";"))[1:]
    return [row[:4] for row in reversed(rows)]


class IssuerWindow(QWidget):
    def __init__(self, private_key: Ed25519PrivateKey):
        super().__init__()
        self.setObjectName("page")
        self.setWindowTitle(f"{APP_NAME} — litsenziya berish")
        self.resize(820, 720)
        self._private_key = private_key

        self._firm = QLineEdit()
        self._firm.setPlaceholderText("Masalan: Temir Savdo MChJ")
        self._machine = QLineEdit()
        self._machine.setPlaceholderText("XXXX-XXXX-XXXX (mijoz dasturidagi «Kompyuter kodi»)")
        self._duration = QComboBox()
        self._duration.addItems(list(DURATIONS))
        self._duration.setCurrentText(DEFAULT_DURATION)
        self._key = QPlainTextEdit()
        self._key.setReadOnly(True)
        self._key.setPlaceholderText("Kalit shu yerda chiqadi. Uni mijozga yuboring.")
        self._key.setFixedHeight(110)
        self._journal = DataTable([Column(title) for title in JOURNAL_HEADER[:4]])

        form = QFormLayout()
        form.setVerticalSpacing(12)
        form.addRow("Firma nomi", self._firm)
        form.addRow("Kompyuter kodi", self._machine)
        form.addRow("Muddat", self._duration)
        form_holder = QWidget()
        form_holder.setLayout(form)

        create = button("Kalit yaratish", "primary")
        create.clicked.connect(self._create)
        copy = button("Kalitdan nusxa olish")
        copy.clicked.connect(lambda: QGuiApplication.clipboard().setText(self._key.toPlainText()))
        buttons = QHBoxLayout()
        buttons.addWidget(create)
        buttons.addWidget(copy)
        buttons.addStretch()
        buttons_holder = QWidget()
        buttons_holder.setLayout(buttons)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)
        layout.addWidget(label("Litsenziya berish", "pageTitle"))
        layout.addWidget(card(form_holder, buttons_holder, self._key))
        layout.addWidget(label("Berilgan litsenziyalar", "sectionTitle"))
        layout.addWidget(self._journal, stretch=1)
        self._show_journal()

    def _create(self) -> None:
        try:
            key = issue_license(
                self._private_key,
                self._firm.text(),
                self._machine.text(),
                DURATIONS[self._duration.currentText()],
                date.today(),
            )
        except WarehouseError as error:
            QMessageBox.warning(self, "Diqqat", str(error))
            return
        self._key.setPlainText(key)
        self._show_journal()

    def _show_journal(self) -> None:
        self._journal.set_rows(read_journal())


def main() -> int:
    app = QApplication(sys.argv)
    theme.apply(app, theme.DEFAULT_THEME)
    try:
        private_key = load_private_key()
    except WarehouseError as error:
        QMessageBox.critical(None, APP_NAME, str(error))
        return 1
    window = IssuerWindow(private_key)
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
