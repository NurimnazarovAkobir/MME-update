"""Foyda tahlili testlari."""

import unittest
from datetime import date

from ombor.analytics import Analytics
from ombor.models import MovementKind, Period, Product
from tests.test_warehouse import TODAY, WarehouseTestCase

OCTOBER = Period.month_of(TODAY)
SEPTEMBER = Period.previous_month_of(TODAY)


class AnalyticsTests(WarehouseTestCase):
    def setUp(self):
        super().setUp()
        self.analytics = Analytics(self.conn)
        self.bolt = self.warehouse.save_product(Product("Bolt M12", "dona"))
        self.sheet = self.warehouse.save_product(Product("List 4mm", "list"))
        self.receive(100, 10_000, day=date(2026, 9, 1))
        self.receive(1000, 1_000, day=date(2026, 9, 1), product_id=self.bolt)
        self.receive(10, 900_000, day=date(2026, 6, 1), product_id=self.sheet)
        # sentabr: truba 10 ta 12 000 dan; oktabr: truba 20 ta 15 000 dan, bolt 100 ta 900 dan (zararga)
        self.issue(10, day=date(2026, 9, 15), sale_price=12_000)
        self.issue(20, day=date(2026, 10, 1), sale_price=15_000)
        self.issue(100, day=date(2026, 10, 2), sale_price=900, product_id=self.bolt)
        self.issue(5, day=date(2026, 10, 2))  # ichki rasxod

    def test_sale_profit_is_stored_per_movement(self):
        sale = self.warehouse.movements(MovementKind.OUT, Period.day_of(date(2026, 10, 1)))[0]
        self.assertEqual((sale.revenue, sale.amount, sale.profit, sale.is_sale), (300_000, 200_000, 100_000, True))
        internal = self.warehouse.movements(MovementKind.OUT, search="")[0]
        self.assertEqual((internal.revenue, internal.profit, internal.is_sale), (0, 0, False))

    def test_summary(self):
        summary = self.analytics.summary(OCTOBER)
        self.assertEqual((summary.revenue, summary.cost, summary.profit), (390_000, 300_000, 90_000))
        self.assertEqual((summary.sales_count, summary.below_cost_loss, summary.internal_use), (2, 10_000, 50_000))
        self.assertAlmostEqual(summary.margin, 90_000 / 390_000)

    def test_by_product_is_sorted_by_profit(self):
        truba, bolt = self.analytics.by_product(OCTOBER)
        self.assertEqual((truba.name, truba.quantity, truba.profit), ("Truba 40x40", 20, 100_000))
        self.assertEqual((bolt.name, bolt.profit), ("Bolt M12", -10_000))
        self.assertAlmostEqual(truba.margin, 1 / 3)

    def test_shortage_counts_as_loss_not_sale(self):
        self.warehouse.adjust_stock(self.bolt, 890, TODAY, "Rahbar")
        summary = self.analytics.summary(OCTOBER)
        self.assertEqual((summary.shortage, summary.below_cost_loss), (10_000, 10_000))
        self.assertEqual((summary.sales_count, summary.internal_use), (2, 50_000))


if __name__ == "__main__":
    unittest.main()
