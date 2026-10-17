"""Umumiy statistika: mahsulotlar reytingi, oyma-oy narx o'zgarishi va obyektlar rasxodi."""

import unittest
from datetime import date

from ombor.database import connect
from ombor.models import Movement, MovementKind, Period, Product
from ombor.sites import Sites
from ombor.statistics import Statistics
from ombor.warehouse import INVENTORY_SURPLUS, OPENING_BALANCE, Warehouse

YEAR = Period(date(2026, 1, 1), date(2026, 12, 31))


class StatisticsTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.warehouse = Warehouse(self.conn, today=lambda: date(2026, 12, 31))
        self.sites = Sites(self.conn, self.warehouse)
        self.stats = Statistics(self.conn, self.sites)
        self.pipe = self.warehouse.save_product(Product("Truba", "metr"))
        self.cement = self.warehouse.save_product(Product("Sement", "kg"))

    def receive(self, product_id, day, quantity, price, supplier="Bozor"):
        self.warehouse.save_movement(Movement(MovementKind.IN, day, product_id, quantity, price, counterparty=supplier))

    def issue(self, product_id, day, quantity, site="Obyekt-1", sale_price=0):
        self.warehouse.save_movement(
            Movement(MovementKind.OUT, day, product_id, quantity, sale_price=sale_price, counterparty=site)
        )

    def test_top_products_by_amount(self):
        self.receive(self.pipe, date(2026, 9, 1), 10, 100_000)  # 1 000 000
        self.receive(self.cement, date(2026, 9, 1), 5000, 1_500)  # 7 500 000
        self.receive(self.pipe, date(2026, 9, 2), 5, 0, supplier=OPENING_BALANCE)  # xarid emas
        self.issue(self.pipe, date(2026, 9, 5), 8)
        self.issue(self.cement, date(2026, 9, 6), 100)
        top_in = self.stats.top_products(MovementKind.IN, YEAR)
        self.assertEqual(
            [(r.name, r.quantity, r.amount) for r in top_in], [("Sement", 5000, 7_500_000), ("Truba", 10, 1_000_000)]
        )
        top_out = self.stats.top_products(MovementKind.OUT, YEAR)
        self.assertEqual([r.name for r in top_out], ["Truba", "Sement"])  # 8 × ~66 667 > 100 × 1 500

    def test_september_100_october_120_is_a_rise(self):
        self.receive(self.pipe, date(2026, 9, 3), 10, 100_000)
        self.receive(self.pipe, date(2026, 10, 3), 10, 110_000)
        self.receive(self.pipe, date(2026, 10, 20), 10, 130_000)  # oktyabr o'rtachasi — 120 000
        self.receive(self.cement, date(2026, 9, 3), 10, 1_500)
        self.receive(self.cement, date(2026, 10, 3), 10, 1_500)  # o'zgarmagan
        (change,) = self.stats.price_changes(YEAR)
        self.assertEqual(
            (change.name, change.month, change.previous_month), ("Truba", date(2026, 10, 1), date(2026, 9, 1))
        )
        self.assertEqual((change.previous_price, change.price), (100_000, 120_000))
        self.assertAlmostEqual(change.percent, 20)

    def test_price_is_compared_with_last_purchase_before_the_period(self):
        self.receive(self.pipe, date(2025, 11, 3), 10, 100_000)
        self.receive(self.pipe, date(2026, 2, 3), 10, 90_000)
        (change,) = self.stats.price_changes(YEAR)
        self.assertEqual((change.previous_month, change.percent), (date(2025, 11, 1), -10))

    def test_inventory_surplus_is_not_a_purchase(self):
        self.receive(self.pipe, date(2026, 9, 3), 10, 100_000)
        self.receive(self.pipe, date(2026, 10, 3), 1, 5, supplier=INVENTORY_SURPLUS)
        self.assertEqual(self.stats.price_changes(YEAR), [])

    def test_site_expenses_and_overview(self):
        self.receive(self.pipe, date(2026, 9, 1), 100, 10_000)
        self.issue(self.pipe, date(2026, 9, 2), 30, site="Obyekt-1")
        self.issue(self.pipe, date(2026, 9, 3), 10, site="Obyekt-2")
        self.issue(self.pipe, date(2026, 9, 4), 5, site="Xaridor", sale_price=20_000)  # sotuv — obyekt emas
        expenses = self.stats.site_expenses(YEAR)
        self.assertEqual([(s.name, s.net) for s in expenses], [("Obyekt-1", 300_000), ("Obyekt-2", 100_000)])
        overview = self.stats.overview(YEAR)
        self.assertEqual((overview.purchased, overview.consumed, overview.site_expense), (1_000_000, 450_000, 400_000))
        self.assertEqual(overview.products_moved, 1)


if __name__ == "__main__":
    unittest.main()
