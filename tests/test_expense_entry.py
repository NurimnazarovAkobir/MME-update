"""Xarajatlar jadvalini (Excel'dagi kabi) kiritish: yangi nom shu qatorda, guruh va birliklar, qidiruv,
to'lov turlari hisoboti va jadval shaklida Excel'ga chiqarish."""

from unittest import mock

from ombor import catalog, payments
from ombor.database import connect, prepare
from ombor.excel_export import LEDGER_HEADERS, ledger_rows, write_table
from ombor.excel_import import read_book
from ombor.models import Movement, MovementKind, Period, Product
from ombor.reports import Reports
from ombor.ui.document_dialog import IssueTarget
from tests.test_document import DocumentTestCase
from tests.test_excel_import import ExcelImportTestCase
from tests.test_payments import EXPENSES
from tests.test_ui import TODAY


class NewNameInTheLineTests(DocumentTestCase):
    def test_new_expense_name_is_added_with_its_unit_and_group(self):
        dialog = self.dialog()
        line = dialog.line(0)
        line.product.setEditText("ковролин")
        self.assertEqual(line.stock.text(), "yangi")
        line.unit.setCurrentIndex(line.unit.findText("m²"))
        line.quantity.setValue(35)
        line.amount.setValue(2_755_000)
        line.group.setCurrentIndex(line.group.findData("Административные расходы"))
        with mock.patch("ombor.ui.document_dialog.confirm", return_value=True) as asked:
            dialog.accept()
        self.assertIn("«ковролин»", asked.call_args.args[2])
        product = next(p for p in self.warehouse.products() if p.name == "ковролин")
        self.assertEqual((product.unit, product.category), ("m²", "Административные расходы"))
        saved = self.warehouse.movement(dialog.saved_ids[0])
        self.assertAlmostEqual(saved.amount, 2_755_000, places=2)

    def test_refusing_keeps_the_dialog_open_and_adds_nothing(self):
        dialog = self.dialog()
        dialog.line(0).product.setEditText("диван-кресло")
        dialog.line(0).quantity.setValue(2)
        with mock.patch("ombor.ui.document_dialog.confirm", return_value=False):
            dialog.accept()
        self.assertEqual(dialog.saved_ids, [])
        self.assertNotIn("диван-кресло", [p.name for p in self.warehouse.products()])

    def test_issue_does_not_offer_new_names(self):
        dialog = self.issue_to(IssueTarget.SITE)
        dialog.line(0).product.setEditText("Yo'q mahsulot")
        self.assertEqual(dialog.line(0).new_name(), "")  # omborda yo'q narsa chiqim qilinmaydi


class GroupAndUnitTests(DocumentTestCase):
    def test_group_chosen_in_a_record_is_remembered_by_the_product(self):
        sheet = self.warehouse.product(self.sheet)
        self.assertEqual(sheet.category, "")
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.sheet, 1, 10, category="Прочие расходы"))
        self.assertEqual(self.warehouse.product(self.sheet).category, "Прочие расходы")
        # Mahsulotning o'z guruhi bo'lsa, boshqa guruhli yozuv uni o'zgartirmaydi.
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.sheet, 1, 10, category="ГСМ"))
        self.assertEqual(self.warehouse.product(self.sheet).category, "Прочие расходы")

    def test_units_written_differently_become_one(self):
        gloves = self.warehouse.save_product(Product("Перчатки", "шт"))
        self.assertEqual(self.warehouse.product(gloves).unit, "dona")

    def test_old_database_gets_the_other_expenses_group_once(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        conn.execute("DELETE FROM groups WHERE ru = ?", (catalog.OTHER_EXPENSES.name.ru,))
        conn.execute("PRAGMA user_version = 15")
        prepare(conn)
        prepare(conn)
        rows = conn.execute("SELECT COUNT(*) FROM groups WHERE ru = ? AND parent_id IS NULL", ("Прочие расходы",))
        self.assertEqual(rows.fetchone()[0], 1)


class SearchAndReportTests(DocumentTestCase):
    def setUp(self):
        super().setUp()
        self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 2, 500, payment="KPK", counterparty="Metiz", unpaid=True)
        )
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.sheet, 3, 100, payment="Naqd"))

    def test_search_finds_payment_method_and_status(self):
        self.assertEqual([m.quantity for m in self.warehouse.movements(MovementKind.IN, search="kpk")], [2])
        unpaid = self.warehouse.movements(MovementKind.IN, search="to'lanmagan")
        self.assertEqual([m.quantity for m in unpaid], [2])

    def test_report_by_payment_method(self):
        rows = {row.method: row for row in Reports(self.warehouse._conn).by_payment(Period(TODAY, TODAY))}
        self.assertEqual((rows["KPK"].paid, rows["KPK"].unpaid), (0, 1000))
        self.assertEqual((rows["Naqd"].paid, rows["Naqd"].total), (300, 300))


class LedgerExportTests(ExcelImportTestCase):
    def test_exported_ledger_looks_like_the_excel_and_loads_back_without_duplicates(self):
        self.load(EXPENSES)
        rows = ledger_rows(self.warehouse.movements(MovementKind.IN))
        self.assertEqual(
            rows[0],
            (1, rows[0][1], "ковролин", "м2", 35, 78_714.29, 2_755_000, "кпк", "оплачено", "Административные расходы"),
        )
        self.assertEqual([row[1] for row in rows], sorted(row[1] for row in rows))  # sana tartibida
        welding = next(row for row in rows if row[2] == "сварка ойна")
        self.assertEqual(welding[7:9], ("наличные", "не оплачено"))
        path = self.folder / "jadval.xlsx"
        write_table(path, "Xarajatlar jadvali", LEDGER_HEADERS, rows)
        plan = self.importer.plan(read_book(path))
        self.assertEqual((plan.new_movements, plan.duplicates, plan.new_products), (0, 4, 0))

    def test_russian_payment_names(self):
        self.assertEqual(payments.method_russian(payments.TRANSFER), "перечисление")
        self.assertEqual(payments.method_russian("Click"), "Click")
