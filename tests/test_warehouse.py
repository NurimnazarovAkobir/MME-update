"""Ombor mantiqi testlari: `python -m unittest` bilan ishga tushiriladi."""

import unittest
from datetime import date

from ombor.database import connect
from ombor.errors import WarehouseError
from ombor.formatting import fmt_period
from ombor.models import Granularity, Movement, MovementKind, Period, Product, StockStatus
from ombor.reports import GroupBy, Reports
from ombor.warehouse import Warehouse

TODAY = date(2026, 10, 3)


class WarehouseTestCase(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.warehouse = Warehouse(self.conn)
        self.reports = Reports(self.conn)
        self.pipe = self.warehouse.save_product(Product("Truba 40x40", "metr", min_stock=50))

    def receive(self, quantity, price, day=TODAY, person="Ali", supplier="Temir bozor", product_id=None):
        return self.warehouse.save_movement(
            Movement(
                MovementKind.IN, day, product_id or self.pipe, quantity, price, person=person, counterparty=supplier
            )
        )

    def issue(self, quantity, day=TODAY, person="Vali", site="Obyekt-1", product_id=None, sale_price=0):
        return self.warehouse.save_movement(
            Movement(
                MovementKind.OUT,
                day,
                product_id or self.pipe,
                quantity,
                sale_price=sale_price,
                person=person,
                counterparty=site,
            )
        )


class ProductTests(WarehouseTestCase):
    def test_new_product_is_empty(self):
        product = self.warehouse.product(self.pipe)
        self.assertEqual(product.stock, 0)
        self.assertIs(product.status, StockStatus.EMPTY)

    def test_duplicate_name_is_rejected(self):
        with self.assertRaises(WarehouseError):
            self.warehouse.save_product(Product("truba 40x40", "metr"))

    def test_empty_name_is_rejected(self):
        with self.assertRaises(WarehouseError):
            self.warehouse.save_product(Product("  ", "kg"))

    def test_update_keeps_id(self):
        product = self.warehouse.product(self.pipe)
        product.name = "Truba 40x40x2"
        self.assertEqual(self.warehouse.save_product(product), self.pipe)
        self.assertEqual(self.warehouse.product(self.pipe).name, "Truba 40x40x2")

    def test_search_ignores_case_including_cyrillic(self):
        self.warehouse.save_product(Product("Швеллер 12", "metr"))
        self.assertEqual([p.name for p in self.warehouse.products("швеллер")], ["Швеллер 12"])
        self.assertEqual([p.name for p in self.warehouse.products("TRUBA")], ["Truba 40x40"])

    def test_product_with_movements_cannot_be_deleted(self):
        self.receive(10, 1000)
        with self.assertRaises(WarehouseError):
            self.warehouse.delete_product(self.pipe)

    def test_unused_product_can_be_deleted(self):
        self.warehouse.delete_product(self.pipe)
        self.assertEqual(self.warehouse.products(), [])


class MovementTests(WarehouseTestCase):
    def test_stock_and_average_price(self):
        self.receive(100, 10_000)
        self.receive(100, 20_000)
        self.issue(50)
        product = self.warehouse.product(self.pipe)
        self.assertEqual(product.stock, 150)
        self.assertEqual(product.average_price, 15_000)
        self.assertEqual(product.value, 150 * 15_000)

    def test_status_follows_min_stock(self):
        self.receive(100, 10_000)
        self.assertIs(self.warehouse.product(self.pipe).status, StockStatus.OK)
        self.issue(60)
        product = self.warehouse.product(self.pipe)
        self.assertIs(product.status, StockStatus.LOW)

    def test_cannot_issue_more_than_stock(self):
        self.receive(10, 1000)
        with self.assertRaises(WarehouseError):
            self.issue(11)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 10)
        self.assertEqual(self.warehouse.movements(MovementKind.OUT), [])

    def test_cannot_delete_receipt_that_was_already_used(self):
        receipt = self.receive(10, 1000)
        self.issue(8)
        with self.assertRaises(WarehouseError):
            self.warehouse.delete_movement(receipt)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 2)

    def test_edit_cannot_make_stock_negative(self):
        receipt = self.receive(10, 1000)
        self.issue(8)
        edited = self.warehouse.movement(receipt)
        edited.quantity = 5
        with self.assertRaises(WarehouseError):
            self.warehouse.save_movement(edited)
        self.assertEqual(self.warehouse.movement(receipt).quantity, 10)

    def test_moving_receipt_to_another_product_checks_old_product(self):
        other = self.warehouse.save_product(Product("Ugolok 50", "metr"))
        receipt = self.receive(10, 1000)
        self.issue(8)
        edited = self.warehouse.movement(receipt)
        edited.product_id = other
        with self.assertRaises(WarehouseError):
            self.warehouse.save_movement(edited)

    def test_zero_quantity_is_rejected(self):
        with self.assertRaises(WarehouseError):
            self.receive(0, 1000)

    def test_issue_amount_uses_average_price(self):
        self.receive(100, 10_000)
        self.receive(100, 20_000)
        issue = self.warehouse.movement(self.issue(10))
        self.assertEqual(issue.amount, 150_000)
        self.assertEqual(issue.price, 15_000)

    def test_movements_filter_by_kind_period_and_search(self):
        self.receive(10, 1000, day=date(2026, 9, 15), person="Ali")
        self.receive(10, 1000, day=date(2026, 10, 1), person="Sardor")
        self.issue(5, day=date(2026, 10, 2))
        october = Period.month_of(TODAY)
        self.assertEqual(len(self.warehouse.movements()), 3)
        self.assertEqual(len(self.warehouse.movements(MovementKind.IN)), 2)
        self.assertEqual(len(self.warehouse.movements(MovementKind.IN, october)), 1)
        self.assertEqual(len(self.warehouse.movements(search="sardor")), 1)
        self.assertEqual(len(self.warehouse.movements(limit=2)), 2)

    def test_group_is_saved_per_movement_and_can_differ_between_records(self):
        receipt = Movement(MovementKind.IN, TODAY, self.pipe, 10, 1000, category="Стройматериал", subcategory="Метал")
        receipt_id = self.warehouse.save_movement(receipt)
        issue = Movement(MovementKind.OUT, TODAY, self.pipe, 4, category="Производственные расходы")
        issue_id = self.warehouse.save_movement(issue)
        saved = self.warehouse.movement(receipt_id)
        self.assertEqual((saved.category, saved.subcategory), ("Стройматериал", "Метал"))
        self.assertEqual(self.warehouse.movement(issue_id).category, "Производственные расходы")
        saved.subcategory = "Цемент"
        self.warehouse.save_movement(saved)
        self.assertEqual(self.warehouse.movement(receipt_id).subcategory, "Цемент")

    def test_search_finds_movements_by_group_name_in_either_language(self):
        self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 10, 1000, category="Стройматериал", subcategory="Цемент")
        )
        self.receive(5, 1000)
        self.assertEqual(len(self.warehouse.movements(search="sement")), 1)
        self.assertEqual(len(self.warehouse.movements(search="стройматериал")), 1)

    def test_last_group_of_a_product_is_remembered(self):
        self.assertEqual(self.warehouse.last_group(self.pipe), ("", ""))
        self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 10, 1000, category="Стройматериал", subcategory="Метал")
        )
        self.receive(5, 1000)  # guruhsiz yozuv oxirgi tanlovni o'chirmaydi
        self.assertEqual(self.warehouse.last_group(self.pipe), ("Стройматериал", "Метал"))

    def test_report_by_group(self):
        self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 10, 1000, category="Стройматериал", subcategory="Метал")
        )
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 4, category="ГСМ"))
        rows = {(r.category, r.subcategory): (r.amount_in, r.amount_out) for r in self.reports.by_category()}
        self.assertEqual(rows, {("Стройматериал", "Метал"): (10_000, 0), ("ГСМ", ""): (0, 4_000)})

    def test_suggestions_are_distinct_per_kind(self):
        self.receive(10, 1000, person="Ali")
        self.receive(10, 1000, person="Ali")
        self.issue(1, person="Vali")
        self.assertEqual(self.warehouse.suggestions(MovementKind.IN, "person"), ["Ali"])
        self.assertEqual(self.warehouse.suggestions(MovementKind.OUT, "counterparty"), ["Obyekt-1"])


class ReportTests(WarehouseTestCase):
    def setUp(self):
        super().setUp()
        self.receive(100, 10_000, day=date(2026, 9, 10), person="Ali", supplier="Temir bozor")
        self.receive(100, 20_000, day=date(2026, 10, 1), person="Sardor", supplier="Metall Savdo")
        self.issue(20, day=date(2026, 10, 2), person="Vali", site="Obyekt-1")
        self.issue(10, day=date(2026, 10, 3), person="", site="Obyekt-2")

    def test_totals_for_period(self):
        totals = self.reports.totals(Period.month_of(TODAY))
        self.assertEqual(totals.amount_in, 2_000_000)
        self.assertEqual(totals.amount_out, 30 * 15_000)
        self.assertEqual((totals.count_in, totals.count_out), (1, 2))

    def test_totals_for_all_time(self):
        self.assertEqual(self.reports.totals().amount_in, 3_000_000)

    def test_stock_value(self):
        self.assertEqual(self.reports.stock_value(), 170 * 15_000)

    def test_turnover_for_all_time(self):
        (row,) = self.reports.turnover()
        self.assertEqual((row.opening, row.qty_in, row.qty_out, row.closing), (0, 200, 30, 170))
        self.assertEqual(row.amount_in, 3_000_000)

    def test_turnover_carries_opening_balance(self):
        (row,) = self.reports.turnover(Period.month_of(TODAY))
        self.assertEqual((row.opening, row.qty_in, row.qty_out, row.closing), (100, 100, 30, 170))

    def test_turnover_keeps_idle_product_with_balance(self):
        (row,) = self.reports.turnover(Period.day_of(date(2026, 9, 20)))
        self.assertEqual((row.opening, row.qty_in, row.qty_out, row.closing), (100, 0, 0, 100))

    def test_turnover_skips_products_without_history(self):
        self.warehouse.save_product(Product("Ugolok 50", "metr"))
        self.assertEqual(self.reports.turnover(Period.day_of(date(2026, 1, 1))), [])

    def test_dynamics_by_day(self):
        days = self.reports.dynamics(Period.month_of(TODAY), Granularity.DAY)
        self.assertEqual([d.start.day for d in days], [1, 2, 3])
        self.assertEqual((days[0].amount_in, days[0].count_in, days[0].count_out), (2_000_000, 1, 0))
        self.assertEqual(days[1].amount_out, 20 * 15_000)

    def test_dynamics_by_week_starts_on_monday(self):
        weeks = self.reports.dynamics(Period(), Granularity.WEEK)
        self.assertEqual([w.start for w in weeks], [date(2026, 9, 7), date(2026, 9, 28)])

    def test_dynamics_by_month_and_year(self):
        months = self.reports.dynamics(Period(), Granularity.MONTH)
        self.assertEqual([m.start for m in months], [date(2026, 9, 1), date(2026, 10, 1)])
        (year,) = self.reports.dynamics(Period(), Granularity.YEAR)
        self.assertEqual((year.start, year.amount_in), (date(2026, 1, 1), 3_000_000))

    def test_who_brought(self):
        rows = self.reports.by_group(MovementKind.IN, GroupBy.PERSON)
        self.assertEqual([(r.name, r.amount) for r in rows], [("Sardor", 2_000_000), ("Ali", 1_000_000)])

    def test_missing_name_is_labelled(self):
        names = {r.name for r in self.reports.by_group(MovementKind.OUT, GroupBy.PERSON)}
        self.assertEqual(names, {"Vali", "(ko'rsatilmagan)"})

    def test_monthly_covers_empty_months(self):
        months = self.reports.monthly(months=6, today=TODAY)
        self.assertEqual(months[0].start, date(2026, 5, 1))
        self.assertEqual(len(months), 6)
        self.assertEqual(months[0].amount_in, 0)
        self.assertEqual(months[-2].amount_in, 1_000_000)
        self.assertEqual(months[-1].amount_out, 450_000)


class PeriodTests(unittest.TestCase):
    def test_periods_containing_a_day(self):
        self.assertEqual(Granularity.DAY.period_of(TODAY), Period(TODAY, TODAY))
        self.assertEqual(Granularity.WEEK.period_of(TODAY), Period(date(2026, 9, 28), date(2026, 10, 4)))
        self.assertEqual(Granularity.MONTH.period_of(TODAY), Period(date(2026, 10, 1), date(2026, 10, 31)))
        self.assertEqual(Granularity.YEAR.period_of(TODAY), Period(date(2026, 1, 1), date(2026, 12, 31)))

    def test_shift_moves_to_neighbouring_period(self):
        self.assertEqual(Granularity.DAY.shift(date(2026, 3, 1), -1), date(2026, 2, 28))
        self.assertEqual(Granularity.WEEK.shift(TODAY, 1), date(2026, 10, 10))
        self.assertEqual(Granularity.MONTH.shift(date(2026, 1, 31), -1), date(2025, 12, 1))
        self.assertEqual(Granularity.MONTH.shift(date(2026, 12, 31), 1), date(2027, 1, 1))
        self.assertEqual(Granularity.YEAR.shift(TODAY, -1), date(2025, 1, 1))

    def test_period_titles(self):
        self.assertEqual(fmt_period(Granularity.DAY, TODAY), "03.10.2026")
        self.assertEqual(fmt_period(Granularity.WEEK, TODAY), "28.09.2026 — 04.10.2026")
        self.assertEqual(fmt_period(Granularity.MONTH, TODAY), "Oktabr 2026")
        self.assertEqual(fmt_period(Granularity.YEAR, TODAY), "2026-yil")


if __name__ == "__main__":
    unittest.main()
