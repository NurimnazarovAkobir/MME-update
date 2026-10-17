"""Interfeys: mahsulot guruhlari va markaziy server sozlamalari."""

import threading
from dataclasses import replace
from unittest import mock

from ombor.models import Product
from ombor.replication import Replica
from ombor.session import Session
from ombor.sync import SyncConfig
from ombor.sync_server import ServerStore, make_server
from ombor.ui.dialogs import ProductDialog
from ombor.ui.products_page import ProductsPage
from ombor.ui.settings_page import SettingsPage
from ombor.ui.sync_controller import SyncController
from tests.test_ui import UiTestCase

TOKEN = "maxfiy-kalit-123"


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
