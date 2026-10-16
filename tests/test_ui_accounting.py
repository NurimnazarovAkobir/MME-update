"""Yangi bo'limlar interfeysi: buxgalteriya, narx nazorati, mahsulot guruhlari va markaziy server."""

import threading
from dataclasses import replace
from datetime import date, timedelta
from unittest import mock

from PySide6.QtGui import QHideEvent

from ombor.models import Employee, Movement, MovementKind, PaymentMethod, Product
from ombor.replication import Replica
from ombor.session import Session
from ombor.sync import SyncConfig
from ombor.sync_server import ServerStore, make_server
from ombor.ui.accounting_page import AccountingPage, EmployeeDialog, SalaryPaymentDialog
from ombor.ui.dialogs import ProductDialog
from ombor.ui.main_window import BADGE_ROLE
from ombor.ui.prices_page import PricesPage
from ombor.ui.products_page import ProductsPage
from ombor.ui.settings_page import SettingsPage
from ombor.ui.sync_controller import SyncController
from tests.test_ui import UiTestCase

TOKEN = "maxfiy-kalit-123"


class AccountingPageTests(UiTestCase):
    def page(self, user) -> AccountingPage:
        page = AccountingPage(self.services.payroll, self.services.auth, Session(user))
        page.refresh()
        return page

    def test_admin_is_asked_to_set_a_password_first(self):
        page = self.page(self.admin)
        self.assertFalse(page._set_password.isHidden())
        self.assertTrue(page._password.isHidden())
        keeper_page = self.page(self.keeper)
        self.assertTrue(keeper_page._set_password.isHidden())

    def test_page_opens_only_with_the_accounting_password(self):
        self.services.auth.set_accounting_password("buxgalter")
        page = self.page(self.viewer)  # kuzatuvchi ham parolni bilsa kira oladi
        self.assertFalse(page.unlock("noto'g'ri"))
        self.assertTrue(page._lock_error.text())
        self.assertEqual(page._stack.currentIndex(), 0)
        self.assertTrue(page.unlock("buxgalter"))
        self.assertEqual(page._stack.currentIndex(), 1)

    def test_page_locks_again_when_leaving_it(self):
        self.services.auth.set_accounting_password("buxgalter")
        page = self.page(self.admin)
        page.unlock("buxgalter")
        page.hideEvent(QHideEvent())
        self.assertFalse(page.is_unlocked)

    def test_salary_payment_flow(self):
        self.services.auth.set_accounting_password("buxgalter")
        dialog = EmployeeDialog(self.services.payroll)
        dialog._name.setText("Ali Valiyev")
        dialog._position.setText("Omborchi")
        dialog._salary.setValue(5_000_000)
        dialog.save()
        payment = SalaryPaymentDialog(self.services.payroll, "Rahbar", date.today().replace(day=1))
        self.assertEqual(payment._amount.value(), 5_000_000)  # qolgan summa taklif qilinadi
        payment._amount.setValue(2_000_000)
        payment._method.setCurrentIndex(payment._method.findData(PaymentMethod.CARD))
        payment.save()

        page = self.page(self.admin)
        page.unlock("buxgalter")
        sheet = page._sheet
        self.assertEqual(sheet.rowCount(), 1)
        headers = [sheet.horizontalHeaderItem(column).text() for column in range(sheet.columnCount())]
        self.assertEqual(sheet.item(0, headers.index("Karta")).text(), "2 000 000")
        self.assertEqual(sheet.item(0, headers.index("Qolgan")).text(), "3 000 000")
        self.assertEqual(page._payments.total_rows(), 1)

    def test_former_employee_is_not_offered_for_new_payment(self):
        payroll = self.services.payroll
        payroll.save_employee(Employee("Ali", salary=100))
        olim = payroll.save_employee(Employee("Olim", salary=100))
        payroll.save_employee(Employee("Olim", salary=100, active=False, id=olim))
        dialog = SalaryPaymentDialog(payroll, "Rahbar", date.today())
        self.assertEqual([dialog._employee.itemText(i) for i in range(dialog._employee.count())], ["Ali"])


class PricesPageTests(UiTestCase):
    def test_price_rise_is_shown(self):
        cement = self.warehouse.save_product(Product("Sement", "kg"))
        old, new = date.today() - timedelta(days=40), date.today() - timedelta(days=5)
        for day, price in ((old, 100_000), (new, 120_000)):
            self.warehouse.save_movement(Movement(MovementKind.IN, day, cement, 1, price, counterparty="Bozor"))
        page = PricesPage(self.services.prices, Session(self.admin))
        page.refresh()
        rows = {
            page._table.item(row, 0).text(): page._table.item(row, 8).text() for row in range(page._table.rowCount())
        }
        self.assertEqual(rows["Sement"], "+20,0 %")

    def test_review_badge_disappears_after_review(self):
        window = self.window(self.admin)
        item = window._menu.item(window._prices_row)
        self.assertEqual(item.data(BADGE_ROLE), 1)
        with mock.patch("ombor.ui.prices_page.QMessageBox.information"):
            window._prices_page._mark_reviewed()
        self.assertIsNone(item.data(BADGE_ROLE))

    def test_only_admin_marks_review(self):
        page = PricesPage(self.services.prices, Session(self.keeper))
        self.assertTrue(page._reviewed.isHidden())


class ProductGroupUiTests(UiTestCase):
    def test_product_dialog_saves_group_and_category(self):
        dialog = ProductDialog(self.warehouse, self.warehouse.product(self.pipe))
        dialog._groups.select("Стройматериал", "Метал")
        dialog.save()
        product = self.warehouse.product(self.pipe)
        self.assertEqual((product.category, product.subcategory), ("Стройматериал", "Метал"))

    def test_products_page_filters_by_group_then_category(self):
        pipe = self.warehouse.product(self.pipe)
        self.warehouse.save_product(replace(pipe, category="Стройматериал", subcategory="Метал"))
        self.warehouse.save_product(Product("Sement", "kg", category="Стройматериал", subcategory="Цемент"))
        page = ProductsPage(self.warehouse, self.services.sites, Session(self.admin))
        page.refresh()
        self.assertTrue(page._category.isHidden())
        page._group.setCurrentIndex(page._group.findData("Стройматериал"))
        self.assertFalse(page._category.isHidden())
        self.assertEqual(page.table.total_rows(), 2)
        page._category.setCurrentIndex(page._category.findData("Цемент"))
        self.assertEqual(page.table.total_rows(), 1)
        self.assertEqual(page.table.item(0, 2).text(), "Qurilish materiallari / Sement")


class ServerSettingsTests(UiTestCase):
    def setUp(self):
        super().setUp()
        self.store = ServerStore(self.folder / "server.db")
        self.server = make_server(self.store, TOKEN, "127.0.0.1", 0, log=False)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.store.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.sync = SyncController(self.services.prefs, lambda: None, None)

    def settings_page(self) -> SettingsPage:
        page = SettingsPage(self.services, Session(self.admin), self.folder / "ombor.db", self.sync)
        page.refresh()
        return page

    def test_first_computer_publishes_its_database(self):
        page = self.settings_page()
        page._server_url.setText(f"127.0.0.1:{self.server.server_address[1]}")
        page._server_token.setText(TOKEN)
        with (
            mock.patch("ombor.ui.settings_page.confirm", return_value=True),
            mock.patch("ombor.ui.settings_page.QMessageBox.information") as information,
            mock.patch.object(SyncController, "start"),
        ):
            page._connect_server()
        self.assertIn("serverga yuborildi", information.call_args.args[2])
        self.assertIsNotNone(SyncConfig.load(self.services.prefs))
        self.assertTrue(Replica(self.conn).enabled)
        self.assertGreater(self.store.status()["rows"], 0)
        self.assertIn("Server:", page._sync_status.text())

    def test_wrong_token_is_reported(self):
        page = self.settings_page()
        page._server_url.setText(f"127.0.0.1:{self.server.server_address[1]}")
        page._server_token.setText("boshqa-kalit")
        with (
            mock.patch("ombor.ui.settings_page.QMessageBox.warning") as warning,
            mock.patch.object(SyncController, "start"),
        ):
            page._connect_server()
        self.assertIn("kalit", warning.call_args.args[2])
        self.assertIsNone(SyncConfig.load(self.services.prefs))

    def test_server_card_is_hidden_without_a_database_file(self):
        page = SettingsPage(self.services, Session(self.admin), self.folder / "ombor.db")
        self.assertFalse(hasattr(page, "_server_url"))
