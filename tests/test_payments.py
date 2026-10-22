"""To'lov turi va holati: Excel'dagi xarajatlar hisobi (вид оплаты, статус, группа расхода) va kiritish oynalari."""

import unittest
from datetime import date
from unittest import mock

from ombor import payments
from ombor.models import Movement, MovementKind, Product
from ombor.session import Session
from ombor.errors import WarehouseError
from ombor.ui.document_dialog import DocumentDialog, IssueTarget
from ombor.ui.labels import LABELS
from ombor.ui.movements_page import MovementsPage
from tests.test_document import DocumentTestCase
from tests.test_excel_import import ExcelImportTestCase
from tests.test_ui import TODAY

# Rahbar yuborgan Excel: tepada ikkita bo'sh qator, «№» ustuni bo'sh, narxi yozilmagan qatorlarda — faqat summa.
EXPENSES = {
    "Расход": [
        [],
        [],
        [
            "№",
            "дата",
            "Наименование расхода",
            "ед изм",
            "кол-во",
            "цена",
            "сумма",
            "вид оплата",
            "статус",
            "Группа расхода",
        ],
        ["", date(2026, 8, 22), "ковролин", "м2", 35, "", 2_755_000, "кпк", "оплачено", "административный расход"],
        ["", date(2026, 8, 25), "диван-кресло", "шт", 2, "", 3_600_000, "кпк", "оплачено", "административный расход"],
        ["", "24.08.2026", "перчатки простые", "шт", 30, 3000, 90_000, "кпк", "оплачено", "прочее"],
        ["", "24.08.2026", "сварка ойна", "шт", 10, 8000, 80_000, "наличные", "не оплачено", "прочее"],
    ]
}


class PaymentWordTests(unittest.TestCase):
    def test_methods_written_differently_become_one(self):
        self.assertEqual(payments.normalize_method("кпк"), payments.CORPORATE_CARD)
        self.assertEqual(payments.normalize_method(" Перечисление "), payments.TRANSFER)
        self.assertEqual(payments.normalize_method("naqd"), payments.CASH)
        self.assertEqual(payments.normalize_method("Click"), "Click")  # tanish emas — o'zi
        self.assertEqual(payments.normalize_method(""), "")

    def test_status_words(self):
        for word in ("не оплачено", "Не оплачено", "To'lanmagan", "qarz"):
            self.assertTrue(payments.is_unpaid(word), word)
        for word in ("оплачено", "To'langan", ""):
            self.assertFalse(payments.is_unpaid(word), word)


class ExpenseLedgerImportTests(ExcelImportTestCase):
    def test_expense_sheet_is_read_as_receipts_with_payment_and_group(self):
        book, report = self.load(EXPENSES)
        self.assertEqual(report.failed, [])
        self.assertEqual([m.kind for m in book.movements], [MovementKind.IN] * 4)  # «Расход» — xarid, chiqim emas
        movements = {m.product_name: m for m in self.warehouse.movements()}
        carpet = movements["ковролин"]
        self.assertAlmostEqual(carpet.amount, 2_755_000, places=2)  # narx yo'q — summadan
        self.assertEqual((carpet.unit, carpet.quantity), ("м2", 35))
        self.assertEqual((carpet.payment, carpet.unpaid), (payments.CORPORATE_CARD, False))
        self.assertEqual(carpet.category, "административный расход")
        welding = movements["сварка ойна"]
        self.assertEqual((welding.payment, welding.unpaid, welding.price), (payments.CASH, True, 8000))
        self.assertEqual(welding.category, "прочее")

    def test_loading_the_same_expenses_again_adds_nothing(self):
        self.load(EXPENSES)
        _, again = self.load(EXPENSES)
        self.assertEqual((again.movements, again.duplicates), (0, 4))


class DocumentPaymentTests(DocumentTestCase):
    def test_amount_gives_the_price_and_payment_is_saved(self):
        dialog = self.dialog()
        line = dialog.line(0)
        line.select("Truba 40x40")
        line.price.setValue(0)
        line.quantity.setValue(35)
        line.amount.setValue(2_755_000)  # Exceldagi kabi: narx yo'q, summa bor
        self.assertAlmostEqual(line.price.value(), 78_714.29, places=2)
        dialog._payment.method.setEditText("кпк")
        dialog._payment.status.setCurrentIndex(1)
        dialog.accept()
        saved = self.warehouse.movement(dialog.saved_ids[0])
        self.assertAlmostEqual(saved.amount, 2_755_000, places=2)  # summa yaxlitlanmay saqlanadi
        self.assertEqual((saved.payment, saved.unpaid), (payments.CORPORATE_CARD, True))

    def test_status_is_not_paid_by_default_and_must_be_chosen(self):
        dialog = DocumentDialog(self.warehouse, self.sites, LABELS[MovementKind.IN], "Rahbar")
        self.assertEqual(dialog._payment.status.currentIndex(), -1)
        self.fill(dialog, ("Truba 40x40", 1, 1000))
        with self.assertRaises(WarehouseError):
            dialog.save()
        dialog._payment.status.setCurrentIndex(1)
        dialog._supplier.setCurrentText("Temir bozor")
        dialog.save()
        saved = self.warehouse.movement(dialog.saved_ids[0])
        self.assertEqual((saved.unpaid, saved.on_credit), (True, True))  # kontragent bor — «Qarzlar»ga ham

    def test_last_payment_method_is_offered(self):
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 1, 10, payment="KPK"))
        self.assertEqual(self.dialog()._payment.payment(), payments.CORPORATE_CARD)

    def test_issue_to_a_site_shows_the_cost(self):
        dialog = self.issue_to(IssueTarget.SITE)
        self.fill(dialog, ("Truba 40x40", 4))
        line = dialog.line(0)
        self.assertTrue(line.price.isReadOnly())
        self.assertEqual((line.price.value(), line.amount.value()), (1000, 4000))
        self.assertIn("4 000", dialog._total.text())
        dialog._target.setCurrentIndex(dialog._target.findData(IssueTarget.SALE))
        self.assertEqual(line.price.value(), 0)  # tannarx sotuv narxi bo'lib qolmaydi
        self.assertFalse(line.price.isReadOnly())

    def test_table_grows_with_its_lines(self):
        dialog = self.dialog()
        short = dialog._table.height()
        self.fill(dialog, ("Truba 40x40", 1, 1), ("List 2mm", 1, 1), ("Truba 40x40", 1, 1))
        self.assertGreater(dialog._table.height(), short)

    def test_marking_paid_closes_the_debt(self):
        unpaid = self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 2, 500, counterparty="Temir bozor", unpaid=True)
        )
        page = MovementsPage(self.warehouse, self.sites, LABELS[MovementKind.IN], Session(self.admin))
        page.refresh()
        page._status_filter.setCurrentIndex(page._status_filter.findData(True))
        self.assertEqual(page.table.total_rows(), 1)
        self.assertIn("to'lanmagan: 1 000", page.footer.text())
        page.table.selectRow(0)
        with mock.patch("ombor.ui.movements_page.confirm", return_value=True):
            page._mark_paid()
        saved = self.warehouse.movement(unpaid)
        self.assertEqual((saved.unpaid, saved.on_credit), (False, False))
        self.assertEqual(page.table.total_rows(), 0)

    def test_price_and_quantity_give_the_amount(self):
        dialog = self.dialog()
        self.fill(dialog, ("Truba 40x40", 30, 3000))
        self.assertEqual(dialog.line(0).amount.value(), 90_000)
        dialog.line(0).quantity.setValue(10)
        self.assertEqual(dialog.line(0).amount.value(), 30_000)

    def test_each_line_has_its_own_group_suggested_by_the_product(self):
        self.warehouse.save_product(
            Product("Gilam", "m2", category="Административные расходы", subcategory="Хозтовары")
        )
        dialog = self.dialog()
        self.fill(dialog, ("Gilam", 2, 100), ("Truba 40x40", 1, 1000))
        self.assertEqual(dialog.line(0).category(), "Административные расходы")
        dialog.line(1).group.setCurrentIndex(dialog.line(1).group.findData("Стройматериал"))
        dialog.accept()
        saved = [self.warehouse.movement(movement_id) for movement_id in dialog.saved_ids]
        self.assertEqual(
            [(m.category, m.subcategory) for m in saved],
            [("Административные расходы", "Хозтовары"), ("Стройматериал", "")],
        )

    def test_issue_to_a_site_has_no_payment(self):
        dialog = self.dialog(MovementKind.OUT)
        self.assertTrue(dialog._payment_fields.isHidden())

    def test_receipts_page_shows_payment_and_status(self):
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 2, 500, payment="кпк", unpaid=True))
        page = MovementsPage(self.warehouse, self.sites, LABELS[MovementKind.IN], Session(self.admin))
        page.refresh()
        titles = {page.table.horizontalHeaderItem(c).text(): c for c in range(page.table.columnCount())}
        self.assertEqual(page.table.item(0, titles["To'lov turi"]).text(), "KPK")
        self.assertEqual(page.table.item(0, titles["Holati"]).text(), "To'lanmagan")
