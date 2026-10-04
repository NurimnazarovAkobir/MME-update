"""Tannarx, sana tartibi, inventarizatsiya va Exceldan yuklash testlari."""

import tempfile
import unittest
from datetime import date
from pathlib import Path

from ombor.errors import WarehouseError
from ombor.excel_import import read_products, write_template
from ombor.models import ImportedProduct, MovementKind, Period
from ombor.warehouse import INVENTORY_SHORTAGE, INVENTORY_SURPLUS, OPENING_BALANCE
from tests.test_warehouse import TODAY, WarehouseTestCase

SEPTEMBER = date(2026, 9, 10)
OCTOBER = date(2026, 10, 1)


class CostingTests(WarehouseTestCase):
    def test_later_receipt_does_not_change_earlier_issue(self):
        self.receive(100, 10_000, day=SEPTEMBER)
        issue = self.issue(40, day=date(2026, 9, 20))
        self.receive(100, 20_000, day=OCTOBER)
        self.assertEqual(self.warehouse.movement(issue).amount, 400_000)
        self.assertEqual(self.reports.totals(Period.month_of(SEPTEMBER)).amount_out, 400_000)

    def test_issue_after_new_receipt_uses_moving_average(self):
        self.receive(100, 10_000, day=SEPTEMBER)
        self.issue(100, day=date(2026, 9, 20))
        self.receive(100, 20_000, day=OCTOBER)
        issue = self.warehouse.movement(self.issue(50, day=TODAY))
        self.assertEqual(issue.price, 20_000)
        product = self.warehouse.product(self.pipe)
        self.assertEqual((product.stock, product.value, product.average_price), (50, 1_000_000, 20_000))

    def test_stock_value_is_zero_when_everything_is_issued(self):
        self.receive(3, 1000.37)
        self.issue(3)
        self.assertEqual(self.warehouse.product(self.pipe).value, 0)
        self.assertEqual(self.reports.stock_value(), 0)

    def test_cannot_issue_before_goods_arrived(self):
        self.receive(100, 10_000, day=OCTOBER)
        with self.assertRaises(WarehouseError) as raised:
            self.issue(10, day=SEPTEMBER)
        self.assertIn("10.09.2026", str(raised.exception))
        self.assertEqual(self.warehouse.movements(MovementKind.OUT), [])

    def test_same_day_receipt_counts_regardless_of_entry_order(self):
        self.receive(10, 1000, day=SEPTEMBER)
        self.issue(10, day=SEPTEMBER)
        self.receive(5, 2000, day=OCTOBER)
        self.issue(5, day=OCTOBER)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 0)

    def test_cannot_move_receipt_after_its_issue(self):
        receipt = self.receive(10, 1000, day=SEPTEMBER)
        self.issue(10, day=date(2026, 9, 20))
        edited = self.warehouse.movement(receipt)
        edited.date = OCTOBER
        with self.assertRaises(WarehouseError):
            self.warehouse.save_movement(edited)
        self.assertEqual(self.warehouse.movement(receipt).date, SEPTEMBER)

    def test_editing_receipt_price_reprices_later_issues(self):
        receipt = self.receive(10, 1000, day=SEPTEMBER)
        issue = self.issue(4, day=OCTOBER)
        edited = self.warehouse.movement(receipt)
        edited.price = 1500
        self.warehouse.save_movement(edited)
        self.assertEqual(self.warehouse.movement(issue).amount, 6000)

    def test_author_is_recorded_and_survives_edit(self):
        receipt = self.warehouse.movement(self.receive(10, 1000))
        self.assertEqual(receipt.created_by, "")
        issue_id = self.issue(1)
        self.conn.execute("UPDATE movements SET created_by = 'Vali' WHERE id = ?", (issue_id,))
        edited = self.warehouse.movement(issue_id)
        edited.created_by = "Boshqa"
        edited.quantity = 2
        self.warehouse.save_movement(edited)
        self.assertEqual(self.warehouse.movement(issue_id).created_by, "Vali")


class InventoryTests(WarehouseTestCase):
    def setUp(self):
        super().setUp()
        self.receive(100, 10_000, day=SEPTEMBER)

    def test_shortage_creates_issue(self):
        movement = self.warehouse.movement(self.warehouse.adjust_stock(self.pipe, 92, TODAY, "Rahbar"))
        self.assertEqual((movement.kind, movement.quantity), (MovementKind.OUT, 8))
        self.assertEqual((movement.counterparty, movement.created_by), (INVENTORY_SHORTAGE, "Rahbar"))
        self.assertEqual(movement.amount, 80_000)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 92)

    def test_surplus_creates_receipt_at_current_cost(self):
        movement = self.warehouse.movement(
            self.warehouse.adjust_stock(self.pipe, 103.5, TODAY, "Rahbar", "Qayta sanaldi")
        )
        self.assertEqual((movement.kind, movement.quantity, movement.price), (MovementKind.IN, 3.5, 10_000))
        self.assertEqual(movement.counterparty, INVENTORY_SURPLUS)
        self.assertIn("Qayta sanaldi", movement.note)
        self.assertIn("hisobda 100, haqiqatda 103,5 metr", movement.note)

    def test_no_difference_creates_nothing(self):
        self.assertIsNone(self.warehouse.adjust_stock(self.pipe, 100, TODAY, "Rahbar"))
        self.assertEqual(len(self.warehouse.movements()), 1)

    def test_negative_count_is_rejected(self):
        with self.assertRaises(WarehouseError):
            self.warehouse.adjust_stock(self.pipe, -1, TODAY, "Rahbar")


class ImportTests(WarehouseTestCase):
    def test_adds_new_products_with_opening_balance(self):
        result = self.warehouse.import_products(
            [
                ImportedProduct("Shveller 12", "metr", 50, stock=200, price=85_000),
                ImportedProduct("Bolt M12", "dona"),
                ImportedProduct("TRUBA 40x40", "metr"),
                ImportedProduct("bolt m12", "dona"),
            ],
            TODAY,
            "Rahbar",
        )
        self.assertEqual((result.added, result.skipped), (2, ["TRUBA 40x40", "bolt m12"]))
        (receipt,) = self.warehouse.movements()
        self.assertEqual((receipt.product_name, receipt.quantity, receipt.amount), ("Shveller 12", 200, 17_000_000))
        self.assertEqual((receipt.counterparty, receipt.created_by), (OPENING_BALANCE, "Rahbar"))

    def test_template_round_trip(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "namuna.xlsx"
            write_template(path)
            products = read_products(path)
        self.assertEqual(products[0], ImportedProduct("Truba 40x40x2", "metr", 100, 250, 32000))
        self.assertEqual(len(products), 2)

    def test_bad_number_names_the_cell(self):
        from openpyxl import Workbook

        workbook = Workbook()
        workbook.active.append(["Nomi", "Birlik", "Minimal qoldiq", "Qoldiq", "Narxi"])
        workbook.active.append(["Bolt", "dona", "", "ko'p", 5])
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "xato.xlsx"
            workbook.save(path)
            with self.assertRaises(WarehouseError) as raised:
                read_products(path)
        self.assertIn("2-qator, «Qoldiq»", str(raised.exception))

    def test_non_excel_file_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "matn.xlsx"
            path.write_text("bu excel emas")
            with self.assertRaises(WarehouseError):
                read_products(path)


if __name__ == "__main__":
    unittest.main()
