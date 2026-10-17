"""Exceldan yuklash: fayl tanlash, bazaga nima tushishini ko'rsatish, yuklash va natija."""

from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QStandardPaths, Qt
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QDialog, QFileDialog, QHBoxLayout, QMessageBox, QVBoxLayout, QWidget

from ..backup import Backup
from ..driver import sqlite3
from ..errors import WarehouseError
from ..excel_import import ExcelBook, read_book, write_template
from ..i18n import tr
from ..importer import ExcelImporter, ImportPlan, ImportReport
from .site_dialogs import TableDialog
from .widgets import Column, DataTable, button, label

EXCEL_FILTER = tr("Excel fayli (*.xlsx)")
DIALOG_SIZE = (720, 560)
_PROBLEM_COLUMNS = (Column(tr("Qator va sabab")),)


class ImportPreviewDialog(QDialog):
    """Yuklashdan oldin: fayldan nima o'qildi, bazaga nima qo'shiladi va qaysi qatorlar o'qilmadi."""

    def __init__(self, path: Path, book: ExcelBook, plan: ImportPlan, parent: QWidget | None = None):
        super().__init__(parent)
        self.setWindowTitle(tr("Exceldan yuklash"))
        self.resize(*DIALOG_SIZE)
        lines = [
            tr("Fayl: {0}").format(path.name),
            *(f"•  {sheet}" for sheet in book.sheets),
            "",
            tr("Mahsulotlar: {0} ta yangi, {1} tasi bazada bor").format(plan.new_products, plan.known_products),
            tr("Faylda kirim: {0}, chiqim: {1} ta yozuv").format(plan.receipts, plan.issues),
            tr("Bazaga qo'shiladigan yozuvlar: {0}").format(plan.new_movements),
            tr("Bazada allaqachon bor (qayta qo'shilmaydi): {0}").format(plan.duplicates),
            tr("Yangi obyektlar: {0}").format(plan.new_sites),
        ]
        summary = label("\n".join(lines))
        summary.setWordWrap(True)
        summary.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(12)
        layout.addWidget(summary)
        if book.problems:
            hint = label(
                tr(
                    "Quyidagi {0} ta qator o'qilmadi va yuklanmaydi. Excelda tuzatib, faylni qayta yuklasangiz, "
                    "faqat yetishmagan yozuvlar qo'shiladi."
                ).format(len(book.problems)),
                "error",
            )
            hint.setWordWrap(True)
            problems = DataTable(_PROBLEM_COLUMNS)
            problems.set_rows([(problem,) for problem in book.problems])
            layout.addWidget(hint)
            layout.addWidget(problems, stretch=1)
        else:
            layout.addStretch()
        note = label(
            tr("Yuklashdan oldin bazaning zaxira nusxasi olinadi. Bir kunda avval kirim, keyin chiqim yoziladi."),
            "muted",
        )
        note.setWordWrap(True)
        layout.addWidget(note)

        self.load_button = button(tr("Bazaga yuklash"), "primary")
        self.load_button.setEnabled(plan.has_changes)
        self.load_button.clicked.connect(self.accept)
        cancel = button(tr("Bekor qilish"))
        cancel.clicked.connect(self.reject)
        buttons = QHBoxLayout()
        buttons.addStretch()
        buttons.addWidget(cancel)
        buttons.addWidget(self.load_button)
        layout.addLayout(buttons)


def import_from_excel(parent: QWidget, importer: ExcelImporter, backup: Backup | None, author: str) -> bool:
    """Butun jarayon: tushuntirish → fayl → ko'rib chiqish → zaxira → yuklash → natija. Biror narsa yozilsa — True."""
    box = QMessageBox(QMessageBox.Icon.Information, tr("Exceldan yuklash"), "", parent=parent)
    box.setText(
        tr(
            "Excelda yuritilgan hisob bazaga o'tkaziladi. Fayldagi varaqlar:\n\n"
            "•  «Mahsulotlar» — nomi, birlik, guruh, kategoriya, minimal va boshlang'ich qoldiq, narxi\n"
            "•  «Kirim» — sana, hujjat №, mahsulot, miqdor, narxi, yetkazib beruvchi, kim olib keldi…\n"
            "•  «Chiqim» — sana, mahsulot, miqdor, sotuv narxi, xaridor / obyekt, kim oldi…\n"
            "•  «Obyektlar» — nomi, manzil, mas'ul shaxs\n\n"
            "Ustunlar tartibi ixtiyoriy, sarlavhalar o'zbekcha yoki ruscha bo'lishi mumkin. Bazada yo'q mahsulot, "
            "guruh, ombor va obyektlar o'zi qo'shiladi. Faylni qayta yuklash xavfsiz: bor yozuvlar takrorlanmaydi."
        )
    )
    choose = box.addButton(tr("Faylni tanlash"), QMessageBox.ButtonRole.AcceptRole)
    template = box.addButton(tr("Namuna faylni saqlash"), QMessageBox.ButtonRole.ActionRole)
    box.addButton(tr("Bekor qilish"), QMessageBox.ButtonRole.RejectRole)
    box.exec()
    if box.clickedButton() is template:
        _save_template(parent)
        return False
    if box.clickedButton() is not choose:
        return False
    path, _ = QFileDialog.getOpenFileName(parent, tr("Excel faylini tanlash"), "", EXCEL_FILTER)
    return bool(path) and load_file(parent, importer, backup, author, Path(path))


def load_file(parent: QWidget, importer: ExcelImporter, backup: Backup | None, author: str, path: Path) -> bool:
    try:
        with _busy():
            book = read_book(path)
            plan = importer.plan(book)
    except WarehouseError as error:
        QMessageBox.warning(parent, tr("Yuklab bo'lmadi"), str(error))
        return False
    if not ImportPreviewDialog(path, book, plan, parent).exec():
        return False
    if backup is not None:
        try:
            backup.auto_folder.mkdir(parents=True, exist_ok=True)
            backup.save_to(backup.auto_folder / f"exceldan-yuklashdan-oldin-{datetime.now():%Y-%m-%d-%H%M}.db")
        except (OSError, sqlite3.Error) as error:
            QMessageBox.warning(parent, tr("Yuklab bo'lmadi"), tr("Zaxira nusxa olib bo'lmadi: {0}").format(error))
            return False
    with _busy():
        report = importer.apply(book, author)
    show_report(parent, report, book.problems)
    return True


def show_report(parent: QWidget, report: ImportReport, unread: list[str] = ()) -> None:
    """Natija; o'qilmagan va yozilmagan qatorlar bo'lsa — ular sababi bilan jadvalda."""
    text = tr(
        "Bazaga yuklandi:\n\n•  mahsulotlar: {0}\n•  kirim va chiqim yozuvlari: {1}\n•  obyektlar: {2}\n"
        "•  allaqachon bor bo'lgani uchun o'tkazib yuborildi: {3}"
    ).format(report.products, report.movements, report.sites, report.duplicates)
    skipped = [*unread, *report.failed]
    if not skipped:
        QMessageBox.information(parent, tr("Exceldan yuklash"), text)
        return
    TableDialog(
        tr("Exceldan yuklash"),
        text + "\n\n" + tr("{0} ta qator yozilmadi — sababi jadvalda:").format(len(skipped)),
        _PROBLEM_COLUMNS,
        [(failure,) for failure in skipped],
        parent,
    ).exec()


def _save_template(parent: QWidget) -> None:
    documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
    default_path = Path(documents) / tr("Ombor namuna.xlsx")
    path, _ = QFileDialog.getSaveFileName(parent, tr("Namuna faylni saqlash"), str(default_path), EXCEL_FILTER)
    if not path:
        return
    try:
        write_template(path)
    except OSError:
        QMessageBox.warning(parent, tr("Exceldan yuklash"), tr("Faylni saqlab bo'lmadi. Boshqa joyni tanlab ko'ring."))
        return
    QMessageBox.information(
        parent,
        tr("Exceldan yuklash"),
        tr("Namuna saqlandi:\n{0}\n\nUni to'ldirib, shu yerdan qayta yuklang.").format(path),
    )


class _busy:
    def __enter__(self) -> None:
        QApplication.setOverrideCursor(QCursor(Qt.CursorShape.WaitCursor))

    def __exit__(self, *_exc) -> None:
        QApplication.restoreOverrideCursor()
