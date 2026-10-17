"""Exceldan yuklash: excelda yuritilgan mahsulotlar, kirim, chiqim va obyektlar bazaga to'liq tushishi."""

import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path

from openpyxl import Workbook

from ombor.catalog import GroupCatalog
from ombor.database import connect
from ombor.errors import WarehouseError
from ombor.excel_export import write_table
from ombor.excel_import import read_book, write_template
from ombor.importer import ExcelImporter
from ombor.models import MovementKind, Product
from ombor.sites import Sites
from ombor.warehouse import OPENING_BALANCE, Warehouse

TODAY = date(2026, 10, 16)


def save_workbook(folder: Path, sheets: dict[str, list[list]]) -> Path:
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, rows in sheets.items():
        sheet = workbook.create_sheet(title)
        for row in rows:
            sheet.append(row)
    path = folder / "hisob.xlsx"
    workbook.save(path)
    return path


LEDGER = {
    "Mahsulotlar": [
        ["Nomi", "Birlik", "Guruh", "Kategoriya", "Minimal qoldiq", "Boshlang'ich qoldiq", "Narxi", "Izoh"],
        ["Truba 40x40", "metr", "Qurilish materiallari", "Metall", 50, 100, 30000, "kvadrat"],
        ["Sement M400", "kg", "Qurilish materiallari", "Sement", 500, "", "", ""],
        ["Jami", "", "", "", "", 100, "", ""],
    ],
    "Kirim": [
        ["Kirim jurnali — 2026"],  # sarlavha qatoridan oldingi nom qatori
        ["Sana", "Hujjat №", "Mahsulot", "Miqdor", "Birlik", "Narxi", "Yetkazib beruvchi", "Kim olib keldi", "Qarzga"],
        [datetime(2026, 9, 1), 45, "Sement M400", 2000, "kg", "1 500 so'm", "Qurilish bozori", "Ali", "ha"],
        ["05.09.2026", "46", "Bolt M12", 300, "dona", "1200", "Metiz", "Ali", ""],
    ],
    "Chiqim": [
        ["Sana", "Mahsulot", "Miqdor", "Sotuv narxi", "Xaridor / obyekt", "Kim oldi"],
        ["10.09.2026", "Truba 40x40", 40, "", "Obyekt-1", "Vali"],
        ["11.09.2026", "Sement M400", 500, 1800, "Karimov", "Vali"],
        ["12.09.2026", "Bolt M12", "ko'p", "", "Obyekt-1", "Vali"],
    ],
    "Obyektlar": [
        ["Nomi", "Manzil", "Mas'ul shaxs"],
        ["Obyekt-1", "Chilonzor 5", "Karimov"],
    ],
}


class ExcelImportTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.warehouse = Warehouse(self.conn, today=lambda: TODAY)
        self.sites = Sites(self.conn, self.warehouse)
        self.importer = ExcelImporter(self.warehouse, self.sites, GroupCatalog(self.conn))
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)

    def load(self, sheets: dict[str, list[list]]):
        book = read_book(save_workbook(self.folder, sheets))
        return book, self.importer.apply(book, "Rahbar", TODAY)

    def stock(self, name: str) -> float:
        return next(p.stock for p in self.warehouse.products() if p.name == name)


class ReadTests(ExcelImportTestCase):
    def test_all_sheets_are_recognized(self):
        book = read_book(save_workbook(self.folder, LEDGER))
        self.assertEqual(len(book.products), 2)  # «Jami» qatori o'tkazib yuboriladi
        self.assertEqual([m.kind for m in book.movements], [MovementKind.IN] * 2 + [MovementKind.OUT] * 2)
        self.assertEqual(len(book.sites), 1)
        self.assertEqual(len(book.problems), 1)
        self.assertIn("«Chiqim», 4-qator", book.problems[0])
        receipt = book.movements[0]
        self.assertEqual(
            (receipt.date, receipt.price, receipt.doc_number, receipt.on_credit), (date(2026, 9, 1), 1500, "45", True)
        )

    def test_russian_headers_and_any_column_order(self):
        book = read_book(
            save_workbook(
                self.folder,
                {
                    "Приход": [
                        ["Кол-во", "Наименование", "Дата", "Цена", "Поставщик", "Ед. изм."],
                        [10, "Цемент", "2026-09-03", "12,5", "Бозор", "кг"],
                    ]
                },
            )
        )
        (movement,) = book.movements
        self.assertEqual(
            (movement.product, movement.quantity, movement.price, movement.unit), ("Цемент", 10, 12.5, "кг")
        )
        self.assertEqual(movement.date, date(2026, 9, 3))

    def test_single_journal_with_kind_column(self):
        book = read_book(
            save_workbook(
                self.folder,
                {
                    "Varaq1": [
                        ["Turi", "Sana", "Mahsulot", "Miqdor", "Summa"],
                        ["Kirim", "01.09.2026", "Bolt", 10, 500],
                        ["Chiqim", "02.09.2026", "Bolt", 4, ""],
                    ]
                },
            )
        )
        self.assertEqual([m.kind for m in book.movements], [MovementKind.IN, MovementKind.OUT])
        self.assertEqual(book.movements[0].price, 50)  # summa / miqdor

    def test_template_round_trip(self):
        path = self.folder / "namuna.xlsx"
        write_template(path)
        book = read_book(path)
        self.assertEqual((len(book.products), len(book.movements), len(book.sites)), (2, 2, 1))
        self.assertEqual(book.problems, [])

    def test_file_exported_by_the_program_is_read_back(self):
        path = self.folder / "kirim.xlsx"
        headers = [
            "Sana",
            "Hujjat №",
            "Ombor",
            "Mahsulot",
            "Miqdor",
            "Birlik",
            "Narxi",
            "Summa",
            "Guruh",
            "Kategoriya",
            "Kim olib keldi",
            "Yetkazib beruvchi",
            "Belgi",
            "Izoh",
            "Kiritdi",
        ]
        rows = [
            [
                date(2026, 9, 1),
                "K-1",
                "Asosiy ombor",
                "Bolt",
                10,
                "dona",
                100,
                1000,
                "Qurilish materiallari",
                "Metall",
                "Ali",
                "Metiz",
                "Qarzga",
                "",
                "Rahbar",
            ]
        ]
        write_table(path, "Kirim — Sentabr 2026", headers, rows)
        (movement,) = read_book(path).movements
        self.assertEqual((movement.kind, movement.doc_number, movement.on_credit), (MovementKind.IN, "K-1", True))

    def test_non_excel_file_is_rejected(self):
        path = self.folder / "matn.xlsx"
        path.write_text("bu excel emas")
        with self.assertRaises(WarehouseError):
            read_book(path)


class ApplyTests(ExcelImportTestCase):
    def test_whole_ledger_goes_into_the_database(self):
        book, report = self.load(LEDGER)
        self.assertEqual((report.products, report.movements, report.sites), (3, 5, 1))
        self.assertEqual(report.failed, [])
        self.assertEqual(self.stock("Truba 40x40"), 60)  # boshlang'ich 100 − chiqim 40
        self.assertEqual(self.stock("Sement M400"), 1500)
        self.assertEqual(self.stock("Bolt M12"), 300)
        truba = next(p for p in self.warehouse.products() if p.name == "Truba 40x40")
        self.assertEqual((truba.category, truba.subcategory, truba.min_stock), ("Стройматериал", "Метал", 50))
        opening = next(m for m in self.warehouse.movements() if m.counterparty == OPENING_BALANCE)
        self.assertEqual(opening.date, date(2026, 9, 10))  # mahsulotning birinchi yozuvi sanasi
        sale = next(m for m in self.warehouse.movements(MovementKind.OUT) if m.product_name == "Sement M400")
        self.assertEqual((sale.sale_price, sale.price), (1800, 1500))  # tannarx dastur o'zi hisoblaydi
        self.assertEqual(self.sites.find("Obyekt-1").address, "Chilonzor 5")

    def test_importing_the_same_file_again_adds_nothing(self):
        self.load(LEDGER)
        before = len(self.warehouse.movements())
        _book, report = self.load(LEDGER)
        self.assertEqual((report.products, report.movements, report.duplicates), (0, 0, 5))
        self.assertEqual(len(self.warehouse.movements()), before)

    def test_plan_shows_what_will_be_added(self):
        book = read_book(save_workbook(self.folder, LEDGER))
        plan = self.importer.plan(book)
        self.assertEqual((plan.new_products, plan.new_movements, plan.duplicates, plan.new_sites), (3, 5, 0, 1))
        self.importer.apply(book, "Rahbar", TODAY)
        self.assertFalse(self.importer.plan(book).has_changes)

    def test_failed_row_does_not_stop_the_rest(self):
        _book, report = self.load(
            {
                "Chiqim": [["Sana", "Mahsulot", "Miqdor"], ["01.09.2026", "Bolt", 5]],  # qoldiq yo'q
                "Kirim": [["Sana", "Mahsulot", "Miqdor", "Narxi"], ["02.09.2026", "Bolt", 10, 100]],
            }
        )
        self.assertEqual(report.movements, 1)
        self.assertEqual(len(report.failed), 1)
        self.assertIn("«Chiqim», 2-qator", report.failed[0])

    def test_unknown_group_store_and_existing_product(self):
        self.warehouse.save_product(Product("Bolt", "dona"))
        _book, report = self.load(
            {
                "Kirim": [
                    ["Sana", "Mahsulot", "Miqdor", "Narxi", "Guruh", "Kategoriya", "Ombor"],
                    ["01.09.2026", "bolt", 10, 100, "Metiz", "Boltlar", "Ombor-2"],
                ]
            }
        )
        self.assertEqual((report.products, report.movements), (0, 1))
        (movement,) = self.warehouse.movements()
        self.assertEqual(
            (movement.category, movement.subcategory, movement.warehouse_name), ("Metiz", "Boltlar", "Ombor-2")
        )

    def test_future_date_is_reported(self):
        _book, report = self.load({"Kirim": [["Sana", "Mahsulot", "Miqdor"], ["01.01.2030", "Bolt", 1]]})
        self.assertEqual(report.movements, 0)
        self.assertEqual(len(report.failed), 1)


if __name__ == "__main__":
    unittest.main()


class ImportDialogTests(unittest.TestCase):
    """Oynalar: ko'rib chiqish → zaxira nusxa → yuklash → natija."""

    @classmethod
    def setUpClass(cls):
        import os

        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        from PySide6.QtWidgets import QApplication

        cls.app = QApplication.instance() or QApplication([])

    def test_preview_then_load_with_backup(self):
        from unittest import mock

        from ombor.models import Role
        from ombor.services import Services
        from ombor.session import Session
        from ombor.ui import import_dialog
        from ombor.ui.products_page import ProductsPage

        conn = connect(":memory:")
        self.addCleanup(conn.close)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        services = Services.create(conn, Path(folder.name) / "zaxira")
        admin = services.auth.add_user("Rahbar", "parol-1", Role.ADMIN)
        path = save_workbook(Path(folder.name), LEDGER)
        page = ProductsPage(services.warehouse, services.sites, Session(admin), services.importer, services.backup)
        with (
            mock.patch.object(import_dialog.ImportPreviewDialog, "exec", return_value=True),
            mock.patch.object(import_dialog.TableDialog, "exec") as report,
        ):
            loaded = import_dialog.load_file(page, services.importer, services.backup, "Rahbar", path)
        self.assertTrue(loaded)
        report.assert_called_once()  # bitta qator o'qilmadi — natija jadval bilan ko'rsatiladi
        self.assertEqual(len(services.warehouse.products()), 3)
        self.assertEqual(len(list((Path(folder.name) / "zaxira").glob("exceldan-yuklashdan-oldin-*.db"))), 1)
