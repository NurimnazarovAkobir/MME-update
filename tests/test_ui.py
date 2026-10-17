"""Interfeys testlari: oynalar ekransiz (offscreen) rejimda ochiladi va asosiy amallar bajarib ko'riladi."""

import os
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QDate, QEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QCheckBox, QMessageBox, QPushButton  # noqa: E402

from ombor.database import connect  # noqa: E402
from ombor.models import Movement, MovementKind, Product, Role  # noqa: E402
from ombor.services import Services  # noqa: E402
from ombor.session import Session  # noqa: E402
from ombor.ui import theme  # noqa: E402
from ombor.ui.dialogs import InventoryDialog, MovementDialog, ProductDialog  # noqa: E402
from ombor.ui.history_page import HistoryPage  # noqa: E402
from ombor.ui.labels import LABELS  # noqa: E402
from ombor.ui.main_window import MainWindow  # noqa: E402
from ombor.ui.movements_page import MovementsPage  # noqa: E402
from ombor.ui.printing import table_html, waybill_html  # noqa: E402
from ombor.ui.products_page import ProductsPage  # noqa: E402
from ombor.ui.settings_page import SettingsPage  # noqa: E402

TODAY = date.today()
RECEIPTS_ROW, PRODUCTS_ROW = 1, 4


def discard_widgets() -> None:
    """Test ochgan oynalarni yo'q qiladi: qolib ketsa, keyingi testlarda uslublar qayta qo'llanib, hammasi sekinlashadi."""
    for widget in QApplication.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


class UiTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        theme.apply(cls.app, theme.DEFAULT_THEME)

    def setUp(self):
        self.addCleanup(discard_widgets)
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.services = Services.create(self.conn, self.folder / "zaxira")
        self.warehouse = self.services.warehouse
        self.admin = self.services.auth.add_user("Rahbar", "parol-1", Role.ADMIN)
        self.keeper = self.services.auth.add_user("Vali", "parol-2", Role.KEEPER)
        self.viewer = self.services.auth.add_user("Hisobchi", "parol-3", Role.VIEWER)
        self.pipe = self.warehouse.save_product(Product("Truba 40x40", "metr", 50))
        self.sheet = self.warehouse.save_product(Product("List 2mm", "list"))
        self.by_admin = self._receive(self.pipe, 100, "Rahbar")
        self.by_keeper = self._receive(self.sheet, 20, "Vali")

    def _receive(self, product_id, quantity, author, number=""):
        return self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, product_id, quantity, 1000, created_by=author, doc_number=number)
        )

    def window(self, user) -> MainWindow:
        window = MainWindow(self.services, Session(user), self.folder / "ombor.db")
        self.addCleanup(window.deleteLater)
        return window

    @staticmethod
    def button_texts(widget) -> list[str]:
        return [button.text() for button in widget.findChildren(QPushButton)]


class IconTests(UiTestCase):
    def test_app_icon_comes_from_the_picture_and_makes_a_windows_icon_file(self):
        from ombor.ui import icon

        self.assertTrue(icon.asset_path("icon.png").is_file())
        self.assertFalse(icon.app_icon().isNull())
        self.assertEqual(icon.icon_pixmap(48).width(), 48)
        target = self.folder / "belgi.ico"
        icon.write_ico(target)
        data = target.read_bytes()
        self.assertEqual(data[:6], bytes([0, 0, 1, 0, len(icon.ICO_SIZES), 0]))


class MainWindowTests(UiTestCase):
    def test_every_page_opens_for_each_role(self):
        for user, pages in ((self.admin, 12), (self.keeper, 12), (self.viewer, 12)):
            window = self.window(user)
            self.assertEqual(window._menu.count(), pages, user.role)
            for row in range(window._menu.count()):
                window._menu.setCurrentRow(row)
                self.assertIs(window._pages.currentWidget(), window._pages.widget(row))

    def test_products_menu_shows_how_many_need_attention(self):
        window = self.window(self.admin)
        self.assertNotIn("⚠", window._menu.item(PRODUCTS_ROW).text())
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 60))  # 40 qoldi, minimal 50
        window._refresh_current()
        self.assertIn("⚠ 1", window._menu.item(PRODUCTS_ROW).text())

    def test_viewer_sees_no_buttons_for_adding(self):
        window = self.window(self.viewer)
        texts = self.button_texts(window)
        for labels in LABELS.values():
            self.assertNotIn(labels.new_action.lstrip("+ "), texts)
        self.assertIn(LABELS[MovementKind.IN].new_action.lstrip("+ "), self.button_texts(self.window(self.keeper)))
        self.assertIsNone(window._pages.widget(RECEIPTS_ROW).table.cellWidget(0, 0))


class MovementsPageTests(UiTestCase):
    def page(self, user) -> MovementsPage:
        page = MovementsPage(self.warehouse, self.services.sites, LABELS[MovementKind.IN], Session(user))
        page.refresh()
        return page

    def _row_of(self, page, movement_id) -> int:
        ids = [m.id for m in self.warehouse.movements(MovementKind.IN)]
        return ids.index(movement_id)

    def test_keeper_has_row_buttons_only_on_own_records(self):
        page = self.page(self.keeper)
        self.assertIsNotNone(page.table.cellWidget(self._row_of(page, self.by_keeper), 0))
        self.assertIsNone(page.table.cellWidget(self._row_of(page, self.by_admin), 0))
        self.assertTrue(page.can_change(self.by_keeper))
        self.assertFalse(page.can_change(self.by_admin))

    def test_keeper_is_told_why_a_foreign_record_cannot_be_changed(self):
        page = self.page(self.keeper)
        with mock.patch.object(QMessageBox, "information") as information:
            page._delete(self.by_admin)
        information.assert_called_once()
        self.assertEqual(len(self.warehouse.movements()), 2)

    def test_admin_deletes_and_the_record_goes_to_history(self):
        page = self.page(self.admin)
        with mock.patch("ombor.ui.list_page.confirm", return_value=True):
            page._delete(self.by_keeper)
        self.assertEqual(page.table.rowCount(), 1)
        self.assertEqual([m.id for m in self.warehouse.deleted_movements()], [self.by_keeper])

    def test_document_number_column_and_waybill(self):
        first = self._receive(self.pipe, 5, "Rahbar", "17")
        self._receive(self.sheet, 3, "Rahbar", "17")
        html = waybill_html(self.warehouse.document(first), LABELS[MovementKind.IN])
        for text in ("№ 17", "Truba 40x40", "List 2mm", "8 000"):
            self.assertIn(text, html)
        page = self.page(self.admin)
        self.assertIn("17", table_html(page.table, "Kirim"))


class DialogTests(UiTestCase):
    def dialog(self, kind=MovementKind.IN, movement=None) -> MovementDialog:
        return MovementDialog(self.warehouse, LABELS[kind], "Rahbar", movement)

    def test_future_date_cannot_be_picked(self):
        dialog = self.dialog()
        self.assertEqual(dialog._date.maximumDate(), QDate(TODAY))

    def test_save_and_continue_keeps_the_document_fields(self):
        dialog = self.dialog()
        dialog._doc_number.setText("25")
        dialog._counterparty.setCurrentText("Temir bozor")
        for name, quantity in (("Truba 40x40", 10), ("List 2mm", 4)):
            dialog._product.setCurrentIndex(dialog._product.findText(name))
            dialog._quantity.setValue(quantity)
            dialog._price.setValue(2000)
            dialog._save_and_continue()
        self.assertEqual(dialog.saved_count, 2)
        self.assertEqual((dialog._doc_number.text(), dialog._quantity.value()), ("25", 0))
        document = self.warehouse.movements(search="25")
        self.assertEqual(sorted(m.product_name for m in document), ["List 2mm", "Truba 40x40"])
        self.assertEqual({m.counterparty for m in document}, {"Temir bozor"})

    def test_save_and_continue_is_not_offered_when_editing(self):
        editing = self.dialog(movement=self.warehouse.movement(self.by_admin))
        self.assertNotIn("Saqlash va yana qo'shish", self.button_texts(editing))
        self.assertIn("Saqlash va yana qo'shish", self.button_texts(self.dialog()))

    def test_required_group_is_enforced_in_the_dialog(self):
        self.warehouse.group_required = True
        dialog = self.dialog()
        dialog._product.setCurrentIndex(dialog._product.findText("Truba 40x40"))
        dialog._quantity.setValue(1)
        with mock.patch.object(QMessageBox, "warning") as warning:
            dialog.accept()
        warning.assert_called_once()
        self.assertEqual(len(self.warehouse.movements()), 2)

    def test_service_product(self):
        dialog = ProductDialog(self.warehouse)
        dialog._name.setText("Yuk tashish")
        dialog._is_service.setChecked(True)
        self.assertFalse(dialog._min_stock.isEnabled())
        dialog.save()
        self.assertTrue(self.warehouse.product(dialog.saved_id).is_service)

    def test_inventory_sheet(self):
        dialog = InventoryDialog(self.warehouse, self.warehouse.products(), "Rahbar")
        self.assertEqual(dialog._sheet.rowCount(), 2)
        dialog._actual[1].setValue(90)  # nom bo'yicha tartibda: List, Truba
        dialog.save()
        self.assertEqual(dialog.adjusted, 1)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 90)


class OtherPagesTests(UiTestCase):
    def test_products_page_filter_shows_only_products_needing_attention(self):
        page = ProductsPage(self.warehouse, self.services.sites, Session(self.admin))
        page.refresh()
        self.assertEqual(page.table.rowCount(), 2)
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 60))  # 40 qoldi, minimal 50
        page._only_low.setChecked(True)
        self.assertEqual(page.table.rowCount(), 1)

    def test_history_page_restores_a_deleted_record(self):
        self.warehouse.actor = "Rahbar"
        self.warehouse.delete_movement(self.by_keeper)
        page = HistoryPage(self.warehouse, Session(self.admin))
        page.refresh()
        self.assertEqual(page._deleted.rowCount(), 1)
        self.assertGreaterEqual(page._changes.rowCount(), 5)
        page._deleted.selectRow(0)
        page._deleted.setCurrentCell(0, 0)
        page._restore()
        self.assertEqual(page._deleted.rowCount(), 0)
        self.assertEqual(self.warehouse.product(self.sheet).stock, 20)

    def test_group_rule_is_switched_in_settings(self):
        page = SettingsPage(self.services, Session(self.admin), self.folder / "ombor.db")
        page.refresh()
        (rule,) = [box for box in page.findChildren(QCheckBox) if box.text() == "Kirim va chiqimda guruh tanlash majburiy"]
        rule.setChecked(True)
        self.assertTrue(self.warehouse.group_required)
        self.assertIn("⚠", page._backup_status.text())  # qo'shimcha papka tanlanmagan

    def test_settings_for_keeper_have_no_rules(self):
        page = SettingsPage(self.services, Session(self.keeper), self.folder / "ombor.db")
        page.refresh()
        # Faqat shu kompyuterning shaxsiy sozlamasi (oyna ramkasi) qoladi.
        self.assertEqual([box.text() for box in page.findChildren(QCheckBox)], ["Windows oynasi ramkasidan foydalanish"])

    def test_table_handles_many_rows(self):
        for offset in range(300):
            self.conn.execute(
                "INSERT INTO movements (kind, date, product_id, quantity, price) VALUES ('IN', ?, ?, 1, 100)",
                ((TODAY - timedelta(days=offset % 30)).isoformat(), self.pipe),
            )
        page = MovementsPage(self.warehouse, self.services.sites, LABELS[MovementKind.IN], Session(self.admin))
        page.refresh()
        table = page.table
        # Jadval sahifalarga bo'linadi: ekranda bir sahifa, jami va chop etish — hamma qatorlar bo'yicha.
        self.assertEqual((table.rowCount(), table.total_rows(), table.page_count()), (25, 302, 13))
        self.assertEqual(len(table.displayed_data()[1]), 302)
        table.set_page(12)
        self.assertEqual((table.page(), table.rowCount()), (12, 2))
        table.set_page_size(100)
        self.assertEqual((table.page(), table.rowCount(), table.page_count()), (0, 100, 4))
        # Saralash butun ro'yxat bo'yicha: eng katta miqdor birinchi sahifaning boshiga chiqadi.
        quantity = [table.horizontalHeaderItem(c).text() for c in range(table.columnCount())].index("Miqdor")
        table._sort_by(quantity)
        table._sort_by(quantity)
        self.assertEqual(table.item(0, quantity).text(), "100")


if __name__ == "__main__":
    unittest.main()
