"""Interfeys testlari: shtrix-kod, birlik, qaytarish, qarzlar, omborlar, guruhlar va sozlamalar."""

from unittest import mock

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox

from ombor import catalog
from ombor.database import MAIN_WAREHOUSE_ID
from ombor.models import Movement, MovementKind, Product, Transfer
from ombor.session import Session
from ombor.ui.debts_page import DebtsPage
from ombor.ui.dialogs import InventoryDialog, MovementDialog, ProductDialog
from ombor.ui.extra_dialogs import GroupsDialog, NameDialog, PaymentDialog, TransferDialog
from ombor.ui.history_page import HistoryPage
from ombor.ui.labels import LABELS
from ombor.ui.movements_page import STORE_COLUMN, MovementsPage
from ombor.ui.products_page import ProductsPage
from ombor.ui.settings_page import SettingsPage
from tests.test_ui import TODAY, UiTestCase


class ProductAndMovementDialogTests(UiTestCase):
    def setUp(self):
        super().setUp()
        self.cement = self.warehouse.save_product(
            Product("Sement", "kg", barcode="4780001", alt_unit="tonna", alt_factor=1000)
        )

    def dialog(self, kind=MovementKind.IN, movement=None) -> MovementDialog:
        return MovementDialog(self.warehouse, LABELS[kind], "Rahbar", movement)

    def test_product_dialog_saves_barcode_and_second_unit(self):
        dialog = ProductDialog(self.warehouse)
        dialog._name.setText("Armatura 12")
        dialog._unit.setCurrentText("metr")
        dialog._barcode.setText("999")
        dialog._alt_unit.setCurrentText("tonna")
        dialog._alt_factor.setValue(1126)
        dialog.save()
        product = self.warehouse.product(dialog.saved_id)
        self.assertEqual((product.barcode, product.alt_unit, product.alt_factor), ("999", "tonna", 1126))

    def test_scanned_barcode_selects_the_product_instead_of_saving(self):
        dialog = self.dialog()
        dialog._product.setEditText("4780001")
        dialog.accept()
        self.assertEqual(dialog._selected_product().id, self.cement)
        self.assertEqual(len(self.warehouse.movements()), 2)  # hech narsa saqlanmadi

    def test_quantity_entered_in_the_second_unit_is_converted(self):
        dialog = self.dialog()
        dialog._product.setCurrentIndex(dialog._product.findText("Sement"))
        self.assertEqual([dialog._unit.itemText(i) for i in range(dialog._unit.count())], ["kg", "tonna"])
        dialog._unit.setCurrentIndex(1)
        dialog._quantity.setValue(2)
        dialog._price.setValue(900_000)
        dialog.save()
        product = self.warehouse.product(self.cement)
        self.assertEqual((product.stock, product.average_price), (2000, 900))

    def test_product_without_second_unit_has_no_unit_choice(self):
        dialog = self.dialog()
        dialog._product.setCurrentIndex(dialog._product.findText("Truba 40x40"))
        self.assertEqual(dialog._unit.count(), 1)
        self.assertEqual(dialog._quantity.suffix(), " metr")

    def test_customer_return_and_credit_are_saved(self):
        dialog = self.dialog()
        dialog._product.setCurrentIndex(dialog._product.findText("Truba 40x40"))
        dialog._quantity.setValue(2)
        dialog._price.setValue(1000)
        dialog._is_return.setChecked(True)
        dialog._sale_price.setValue(1500)
        dialog._on_credit.setChecked(True)
        dialog._counterparty.setCurrentText("Obyekt-1")
        dialog.save()
        saved = max(self.warehouse.movements(MovementKind.IN), key=lambda m: m.id)
        self.assertEqual((saved.is_return, saved.on_credit, saved.sale_price, saved.revenue), (True, True, 1500, -3000))

    def test_credit_without_counterparty_is_refused(self):
        dialog = self.dialog()
        dialog._product.setCurrentIndex(dialog._product.findText("Truba 40x40"))
        dialog._quantity.setValue(1)
        dialog._on_credit.setChecked(True)
        with mock.patch.object(QMessageBox, "warning") as warning:
            dialog.accept()
        warning.assert_called_once()

    def test_editing_keeps_return_credit_and_store(self):
        site = self.warehouse.save_store("Obyekt ombori")
        movement_id = self.warehouse.save_movement(
            Movement(
                MovementKind.IN,
                TODAY,
                self.pipe,
                3,
                1000,
                counterparty="Temir bozor",
                on_credit=True,
                warehouse_id=site,
            )
        )
        dialog = self.dialog(movement=self.warehouse.movement(movement_id))
        self.assertTrue(dialog._on_credit.isChecked())
        self.assertEqual(dialog._store.currentData(), site)
        dialog._quantity.setValue(4)
        dialog.save()
        saved = self.warehouse.movement(movement_id)
        self.assertEqual((saved.quantity, saved.on_credit, saved.warehouse_id), (4, True, site))


class StoreUiTests(UiTestCase):
    def setUp(self):
        super().setUp()
        self.site = self.warehouse.save_store("Obyekt ombori")

    def test_store_column_appears_only_with_several_stores(self):
        page = MovementsPage(self.warehouse, LABELS[MovementKind.IN], Session(self.admin))
        page.refresh()
        self.assertFalse(page.table.isColumnHidden(STORE_COLUMN + 1))
        self.warehouse.delete_store(self.site)
        page.refresh()
        self.assertTrue(page.table.isColumnHidden(STORE_COLUMN + 1))

    def test_transfer_dialog_and_per_store_stock_on_the_products_page(self):
        dialog = TransferDialog(self.warehouse, "Rahbar", self.pipe)
        self.assertIn("100", dialog._stock_hint.text())
        dialog._quantity.setValue(30)
        dialog.save()
        page = ProductsPage(self.warehouse, Session(self.admin))
        page.refresh()
        self.assertEqual(page._store.count(), 3)  # «Barcha omborlar» + ikkita ombor
        page._store.setCurrentIndex(page._store.findData(self.site))
        stocks = {
            page.table.item(row, 1).text(): page.table.item(row, 2).text() for row in range(page.table.rowCount())
        }
        self.assertEqual(stocks["Truba 40x40"], "30")
        self.assertEqual(stocks["List 2mm"], "0")

    def test_inventory_needs_a_store_to_be_chosen(self):
        page = ProductsPage(self.warehouse, Session(self.admin))
        page.refresh()
        with mock.patch.object(QMessageBox, "information") as information:
            page._take_inventory()
        information.assert_called_once()

    def test_inventory_dialog_adjusts_the_chosen_store(self):
        self.warehouse.transfer(Transfer(TODAY, self.pipe, 30, MAIN_WAREHOUSE_ID, self.site))
        store = next(s for s in self.warehouse.stores() if s.id == self.site)
        dialog = InventoryDialog(self.warehouse, self.warehouse.products(warehouse_id=self.site), "Rahbar", None, store)
        truba = [p.name for p in dialog._products].index("Truba 40x40")
        dialog._actual[truba].setValue(28)
        dialog.save()
        self.assertEqual(self.warehouse.product(self.pipe, self.site).stock, 28)
        self.assertEqual(self.warehouse.product(self.pipe, MAIN_WAREHOUSE_ID).stock, 70)

    def test_stores_are_managed_in_settings(self):
        page = SettingsPage(self.services, Session(self.admin), self.folder / "ombor.db")
        page.refresh()
        self.assertEqual(page._stores.rowCount(), 2)
        with mock.patch.object(NameDialog, "exec", return_value=1), mock.patch.object(
            NameDialog, "names", return_value=["Zaxira ombor"]
        ):
            page._edit_store(None)
        self.assertEqual([store.name for store in self.warehouse.stores()][-1], "Zaxira ombor")
        self.assertEqual(page._stores.rowCount(), 3)


class FitAndHistoryTests(UiTestCase):
    def page(self, user=None) -> MovementsPage:
        page = MovementsPage(self.warehouse, LABELS[MovementKind.IN], Session(user or self.admin))
        page.resize(1100, 600)
        page.show()
        page.refresh()
        self.app.processEvents()
        return page

    def test_table_fits_its_width_without_horizontal_scrolling(self):
        self.warehouse.save_movement(
            Movement(
                MovementKind.IN,
                TODAY,
                self.pipe,
                40_000,
                6000,
                category="Стройматериал",
                subcategory="Метал",
                person="Juda uzun ismli olib kelgan odam",
                counterparty="Juda uzun nomli yetkazib beruvchi firma",
                note="Bu yerda ancha uzun izoh yozilgan, u ustunga sig'maydi",
                doc_number="84758834528",
            )
        )
        page = self.page()
        table = page.table
        visible = [c for c in range(table.columnCount()) if not table.isColumnHidden(c)]
        total = sum(table.columnWidth(c) for c in visible)
        self.assertLessEqual(total, table.viewport().width())
        self.assertEqual(table.horizontalScrollBar().maximum(), 0)
        # Sonlar kesilmaydi: summa ustuni o'z mazmunidan tor emas.
        amount = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())].index("Summa")
        self.assertGreaterEqual(table.columnWidth(amount), table.sizeHintForColumn(amount))
        note = table.item(0, table.columnCount() - 2)
        self.assertEqual(note.toolTip(), "Bu yerda ancha uzun izoh yozilgan, u ustunga sig'maydi")

    def test_columns_nobody_filled_are_hidden(self):
        page = self.page()
        titles = {page.table.horizontalHeaderItem(c).text(): c for c in range(page.table.columnCount())}
        for title in ("Hujjat №", "Guruh", "Kichik guruh", "Belgi", "Izoh"):
            self.assertTrue(page.table.isColumnHidden(titles[title]), title)
        self.assertFalse(page.table.isColumnHidden(titles["Mahsulot"]))
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 1, 10, doc_number="7"))
        page.refresh()
        self.assertFalse(page.table.isColumnHidden(titles["Hujjat №"]))

    def test_history_shows_who_added_what_with_role_and_date(self):
        window = self.window(self.keeper)
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 3, 100, created_by="Vali"))
        (entry,) = self.warehouse.history(limit=1)
        self.assertEqual((entry.actor, entry.actor_role, entry.role_title), ("Vali", "keeper", "Omborchi"))
        self.assertEqual(entry.at.date(), TODAY)
        row = [window._menu.item(i).text().strip() for i in range(window._menu.count())].index("Tarix")
        window._menu.setCurrentRow(row)
        table = window._pages.widget(row)._changes
        headers = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())]
        self.assertEqual(headers[:4], ["Vaqti", "Kim", "Lavozimi", "Amal"])
        self.assertEqual([table.item(0, c).text() for c in (1, 2, 3)], ["Vali", "Omborchi", "Qo'shildi"])

    def test_only_admin_can_see_deleted_records_and_restore(self):
        keeper = HistoryPage(self.warehouse, Session(self.keeper))
        admin = HistoryPage(self.warehouse, Session(self.admin))
        self.assertEqual((keeper._tabs.count(), admin._tabs.count()), (1, 2))
        self.assertNotIn("Tanlangan yozuvni tiklash", self.button_texts(keeper))
        self.assertIn("Tanlangan yozuvni tiklash", self.button_texts(admin))

    def test_old_history_rows_take_the_role_from_the_user(self):
        self.conn.execute("INSERT INTO history (actor, action, entity, summary) VALUES ('Rahbar', 'add', 'IN', 'eski')")
        entry = self.warehouse.history(search="eski")[0]
        self.assertEqual(entry.role_title, "Rahbar")
        self.assertEqual(len(self.warehouse.history(search="omborchi")), 0)


class DebtUiTests(UiTestCase):
    def setUp(self):
        super().setUp()
        self.debts = self.services.debts
        self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 10, 1000, counterparty="Temir bozor", on_credit=True)
        )

    def test_page_shows_balances_and_totals(self):
        page = DebtsPage(self.debts, Session(self.admin))
        page.refresh()
        suppliers = page._balances[MovementKind.IN]
        self.assertEqual(suppliers.rowCount(), 1)
        self.assertEqual((suppliers.item(0, 0).text(), suppliers.item(0, 4).text()), ("Temir bozor", "10 000"))
        self.assertIn("10 000", page._footer.text())
        self.assertEqual(page._balances[MovementKind.OUT].rowCount(), 0)

    def test_payment_dialog_reduces_the_debt(self):
        dialog = PaymentDialog(self.debts, MovementKind.IN, "Rahbar", "Temir bozor")
        self.assertIn("10 000", dialog._debt_hint.text())
        dialog._amount.setValue(4000)
        dialog.save()
        self.assertEqual(self.debts.total(MovementKind.IN), 6000)
        page = DebtsPage(self.debts, Session(self.admin))
        page.refresh()
        self.assertEqual(page._payments.rowCount(), 1)

    def test_viewer_cannot_add_payments(self):
        page = DebtsPage(self.debts, Session(self.viewer))
        self.assertEqual([text for text in self.button_texts(page) if "To'lov" in text], [])


class GroupUiTests(UiTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(catalog._index, catalog.GROUPS)

    def test_groups_dialog_lists_and_adds_groups(self):
        dialog = GroupsDialog(self.services.groups)
        self.assertEqual(dialog._tree.topLevelItemCount(), 12)
        with mock.patch.object(dialog, "_ask_names", return_value=["Bo'yoqlar", "Краски"]):
            dialog._add_group()
        self.assertEqual(dialog._tree.topLevelItemCount(), 13)
        dialog._tree.setCurrentItem(dialog._tree.topLevelItem(12))
        with mock.patch.object(dialog, "_ask_names", return_value=["Emal", ""]):
            dialog._add_subgroup()
        self.assertEqual([s.uz for s in catalog.find_group("Краски").subgroups], ["Emal"])

    def test_new_group_is_offered_in_the_movement_dialog(self):
        self.services.groups.add("Bo'yoqlar", "Краски")
        dialog = MovementDialog(self.warehouse, LABELS[MovementKind.IN], "Rahbar")
        self.assertGreaterEqual(dialog._groups.group.findData("Краски"), 0)

    def test_duplicate_group_shows_a_warning(self):
        dialog = GroupsDialog(self.services.groups)
        with mock.patch.object(dialog, "_ask_names", return_value=["", "ГСМ"]), mock.patch.object(
            QMessageBox, "warning"
        ) as warning:
            dialog._add_group()
        warning.assert_called_once()
        self.assertEqual(dialog._tree.topLevelItemCount(), 12)
        self.assertEqual(dialog._tree.topLevelItem(0).data(0, Qt.ItemDataRole.UserRole), catalog.groups()[0].id)


class SettingsCardsTests(UiTestCase):
    def test_admin_sees_network_and_update_cards_but_keeper_does_not(self):
        admin = self.button_texts(SettingsPage(self.services, Session(self.admin), self.folder / "ombor.db"))
        keeper = self.button_texts(SettingsPage(self.services, Session(self.keeper), self.folder / "ombor.db"))
        for text in ("Bazani umumiy papkaga ko'chirish", "Guruhlarni tahrirlash", "+ Yangi ombor"):
            self.assertIn(text, admin)
            self.assertNotIn(text, keeper)

    def test_keeper_can_save_a_backup_but_not_restore_or_choose_folders(self):
        page = SettingsPage(self.services, Session(self.keeper), self.folder / "ombor.db")
        page.refresh()
        texts = self.button_texts(page)
        self.assertIn("Hozir nusxa olish", texts)
        self.assertIn("Papkani ochish", texts)
        self.assertNotIn("Zaxiradan tiklash", texts)
        self.assertNotIn("Qo'shimcha papkani tanlash", texts)
        self.assertIn("ombor.db", page._backup_status.text())
        target = self.folder / "omborchi-nusxa.db"
        with (
            mock.patch("ombor.ui.settings_page.QFileDialog.getSaveFileName", return_value=(str(target), "")),
            mock.patch.object(QMessageBox, "information"),
        ):
            page._save_backup()
        self.assertTrue(target.is_file())

    def test_viewer_has_no_backup_card(self):
        page = SettingsPage(self.services, Session(self.viewer), self.folder / "ombor.db")
        page.refresh()
        self.assertNotIn("Hozir nusxa olish", self.button_texts(page))

    def test_theme_is_saved_in_local_prefs_not_in_the_shared_database(self):
        page = SettingsPage(self.services, Session(self.admin), self.folder / "ombor.db")
        page._change_theme("light")
        self.assertEqual(self.services.prefs.get("theme"), "light")
        self.assertEqual(self.services.settings.get("theme"), "")
        page._change_theme("dark")
