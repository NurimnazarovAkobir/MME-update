"""Buxgalteriya (oyliklar, bo'lim paroli) va narx nazorati testlari."""

import unittest
from datetime import date

from ombor.auth import Auth
from ombor.database import connect
from ombor.errors import WarehouseError
from ombor.models import Employee, Movement, MovementKind, PaymentMethod, Period, Product, SalaryPayment
from ombor.payroll import Payroll
from ombor.pricing import PriceControl, add_months, review_period
from ombor.warehouse import OPENING_BALANCE, Warehouse

OCTOBER = date(2026, 10, 1)


class PayrollTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.payroll = Payroll(self.conn)
        self.ali = self.payroll.save_employee(Employee("Ali Valiyev", "Omborchi", 5_000_000))
        self.olim = self.payroll.save_employee(Employee("Olim", "Haydovchi", 4_000_000))

    def pay(self, employee_id, amount, method, month=OCTOBER, day=date(2026, 10, 10)):
        return self.payroll.save_payment(
            SalaryPayment(employee_id, day, month, amount, method), today=date(2026, 10, 16)
        )

    def test_salary_is_paid_in_parts_by_different_methods(self):
        self.pay(self.ali, 2_000_000, PaymentMethod.TRANSFER)
        self.pay(self.ali, 1_000_000, PaymentMethod.CARD)
        self.pay(self.ali, 500_000, PaymentMethod.CASH)
        line = next(line for line in self.payroll.month_sheet(OCTOBER) if line.employee_id == self.ali)
        self.assertEqual(line.total_paid, 3_500_000)
        self.assertEqual(line.remaining, 1_500_000)
        self.assertEqual(line.paid[PaymentMethod.CARD], 1_000_000)
        self.assertEqual(self.payroll.remaining(self.ali, OCTOBER), 1_500_000)

    def test_totals_by_method(self):
        self.pay(self.ali, 5_000_000, PaymentMethod.TRANSFER)
        self.pay(self.olim, 4_000_000, PaymentMethod.CASH)
        self.pay(self.olim, 100_000, PaymentMethod.CASH, month=date(2026, 9, 1))  # boshqa oy
        totals = self.payroll.totals_by_method(OCTOBER)
        self.assertEqual(totals[PaymentMethod.TRANSFER], 5_000_000)
        self.assertEqual(totals[PaymentMethod.CASH], 4_000_000)
        self.assertEqual(totals[PaymentMethod.CARD], 0)

    def test_former_employee_with_payments_stays_in_that_month(self):
        self.pay(self.olim, 1_000_000, PaymentMethod.CASH)
        self.payroll.save_employee(Employee("Olim", "Haydovchi", 4_000_000, active=False, id=self.olim))
        self.assertEqual([e.name for e in self.payroll.employees()], ["Ali Valiyev"])
        names = [line.name for line in self.payroll.month_sheet(OCTOBER)]
        self.assertEqual(names, ["Ali Valiyev", "Olim"])
        self.assertEqual([line.name for line in self.payroll.month_sheet(date(2026, 11, 1))], ["Ali Valiyev"])

    def test_employee_with_payments_cannot_be_deleted(self):
        self.pay(self.ali, 1_000, PaymentMethod.CASH)
        with self.assertRaises(WarehouseError):
            self.payroll.delete_employee(self.ali)
        self.payroll.delete_employee(self.olim)
        self.assertEqual(len(self.payroll.employees(include_inactive=True)), 1)

    def test_validation(self):
        with self.assertRaises(WarehouseError):
            self.payroll.save_employee(Employee("ali valiyev"))
        with self.assertRaises(WarehouseError):
            self.pay(self.ali, 0, PaymentMethod.CASH)
        with self.assertRaises(WarehouseError):
            self.pay(self.ali, 10, PaymentMethod.CASH, day=date(2026, 10, 17))

    def test_payment_edit_and_delete(self):
        payment_id = self.pay(self.ali, 1_000, PaymentMethod.CASH)
        payment = self.payroll.payment(payment_id)
        self.payroll.save_payment(
            SalaryPayment(self.ali, payment.date, OCTOBER, 2_000, PaymentMethod.CARD, id=payment_id),
            today=date(2026, 10, 16),
        )
        self.assertEqual(self.payroll.payment(payment_id).method, PaymentMethod.CARD)
        self.payroll.delete_payment(payment_id)
        self.assertEqual(self.payroll.payments(), [])


class AccountingPasswordTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.auth = Auth(self.conn)

    def test_password_must_be_set_first(self):
        self.assertFalse(self.auth.has_accounting_password())
        with self.assertRaises(WarehouseError):
            self.auth.check_accounting_password("1234")

    def test_check(self):
        self.auth.set_accounting_password("buxgalter")
        self.assertTrue(self.auth.has_accounting_password())
        self.auth.check_accounting_password("buxgalter")
        with self.assertRaises(WarehouseError):
            self.auth.check_accounting_password("boshqa")

    def test_short_password_is_rejected(self):
        with self.assertRaises(WarehouseError):
            self.auth.set_accounting_password("12")


class PriceControlTests(unittest.TestCase):
    def setUp(self):
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.warehouse = Warehouse(self.conn, today=lambda: date(2026, 12, 31))
        self.prices = PriceControl(self.conn)
        self.pipe = self.warehouse.save_product(Product("Truba", "metr"))
        self.cement = self.warehouse.save_product(Product("Sement", "kg"))

    def buy(self, product_id, day, price, supplier="Bozor"):
        self.warehouse.save_movement(Movement(MovementKind.IN, day, product_id, 10, price, counterparty=supplier))

    def test_september_100_october_120_is_plus_20_percent(self):
        self.buy(self.pipe, date(2026, 9, 5), 100_000)
        self.buy(self.pipe, date(2026, 10, 7), 120_000, supplier="Yangi firma")
        self.buy(self.cement, date(2026, 9, 5), 1_000)
        self.buy(self.cement, date(2026, 10, 5), 1_000)  # narx o'zgarmagan
        changes = self.prices.changes(Period(date(2026, 4, 17), date(2026, 10, 16)))
        self.assertEqual([change.name for change in changes], ["Truba"])
        change = changes[0]
        self.assertEqual((change.first_price, change.last_price), (100_000, 120_000))
        self.assertAlmostEqual(change.percent, 20)
        self.assertEqual(change.last_supplier, "Yangi firma")
        all_purchases = self.prices.changes(Period(date(2026, 4, 17), date(2026, 10, 16)), only_changed=False)
        self.assertEqual(len(all_purchases), 2)

    def test_opening_balance_and_purchases_outside_the_period_are_ignored(self):
        self.buy(self.pipe, date(2026, 1, 5), 50_000)
        self.buy(self.pipe, date(2026, 9, 5), 100_000, supplier=OPENING_BALANCE)
        self.buy(self.pipe, date(2026, 10, 5), 100_000)
        self.assertEqual(self.prices.changes(review_period(date(2026, 10, 16))), [])

    def test_review_is_due_every_six_months(self):
        self.assertTrue(self.prices.is_due(date(2026, 10, 16)))
        self.prices.mark_reviewed(date(2026, 10, 16))
        self.assertEqual(self.prices.next_review(), date(2027, 4, 16))
        self.assertFalse(self.prices.is_due(date(2027, 4, 15)))
        self.assertTrue(self.prices.is_due(date(2027, 4, 16)))

    def test_add_months(self):
        self.assertEqual(add_months(date(2026, 8, 31), 6), date(2027, 2, 28))
        self.assertEqual(add_months(date(2026, 10, 16), -6), date(2026, 4, 16))
        self.assertEqual(review_period(date(2026, 10, 16)), Period(date(2026, 4, 17), date(2026, 10, 16)))


if __name__ == "__main__":
    unittest.main()
