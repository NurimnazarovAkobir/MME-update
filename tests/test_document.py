"""Nakladnoy oynasi (bir nechta mahsulotli kirim/chiqim) va u bilan bog'liq qoidalar."""

from datetime import timedelta

from PySide6.QtWidgets import QPushButton

from ombor.database import connect, open_raw
from ombor.errors import WarehouseError
from ombor.migrations import SCHEMA_VERSION
from ombor.models import Movement, MovementKind, Period, Product, Site, SiteReturn
from ombor.session import Session
from ombor.ui import printing
from ombor.ui.dashboard_page import DashboardPage
from ombor.ui.dialogs import MovementDialog
from ombor.ui.document_dialog import AMOUNT, PRICE, DocumentDialog, IssueTarget
from ombor.ui.labels import LABELS
from ombor.ui.main_window import DIVIDER_ROLE
from ombor.ui.movements_page import MovementsPage
from ombor.ui.products_page import ProductsPage
from ombor.ui.reports_page import ReportsPage
from ombor.ui.site_dialogs import ReturnDialog
from tests.test_ui import TODAY, UiTestCase


class DocumentTestCase(UiTestCase):
    """Omborda 100 metr truba va 20 ta list bor (ikkalasi 1000 dan); bitta obyekt — «Chilonzor»."""

    def setUp(self):
        super().setUp()
        self.sites = self.services.sites
        self.site = self.sites.save(Site("Chilonzor"))

    def dialog(self, kind=MovementKind.IN) -> DocumentDialog:
        return DocumentDialog(self.warehouse, self.sites, LABELS[kind], "Rahbar")

    @staticmethod
    def fill(dialog: DocumentDialog, *lines) -> None:
        """Har bir qator: (mahsulot nomi, miqdor) yoki (mahsulot nomi, miqdor, narx)."""
        for index, (name, quantity, *price) in enumerate(lines):
            dialog.line(index).select(name)
            dialog.line(index).quantity.setValue(quantity)
            if price:
                dialog.line(index).price.setValue(price[0])

    def issue_to(self, target: IssueTarget) -> DocumentDialog:
        dialog = self.dialog(MovementKind.OUT)
        dialog._target.setCurrentIndex(dialog._target.findData(target))
        return dialog


class SaveDocumentTests(DocumentTestCase):
    def test_all_lines_are_saved_together_or_not_at_all(self):
        issue = [
            Movement(MovementKind.OUT, TODAY, self.pipe, 10, counterparty="Chilonzor"),
            Movement(MovementKind.OUT, TODAY, self.sheet, 21, counterparty="Chilonzor"),  # omborda 20 ta
        ]
        with self.assertRaises(WarehouseError) as failure:
            self.warehouse.save_document(issue)
        self.assertTrue(str(failure.exception).startswith("2-qator"))
        self.assertEqual(self.warehouse.movements(MovementKind.OUT), [])
        self.assertEqual(self.warehouse.product(self.pipe).stock, 100)

    def test_empty_document_is_refused(self):
        with self.assertRaises(WarehouseError):
            self.warehouse.save_document([])

    def test_sale_customer_is_not_added_to_sites(self):
        self.warehouse.save_movement(
            Movement(MovementKind.OUT, TODAY, self.pipe, 5, sale_price=1500, counterparty="Xaridor MChJ")
        )
        self.assertEqual([site.name for site in self.sites.all()], ["Chilonzor"])
        self.assertEqual(self.warehouse.customers(), ["Xaridor MChJ"])

    def test_sale_to_a_site_name_is_not_counted_as_issued_to_the_site(self):
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 10, counterparty="Chilonzor"))
        self.warehouse.save_movement(
            Movement(MovementKind.OUT, TODAY, self.pipe, 5, sale_price=1500, counterparty="Chilonzor")
        )
        self.assertEqual(self.sites.all()[0].issued, 10_000)
        last_month = Period(end=TODAY - timedelta(days=31))
        self.assertEqual(self.sites.all(period=last_month)[0].issued, 0)

    def test_returns_are_not_counted_as_receipts(self):
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 10, counterparty="Chilonzor"))
        self.sites.save_return(SiteReturn(TODAY, self.site, self.pipe, 4))
        totals = self.services.reports.totals()
        self.assertEqual((totals.amount_in, totals.count_in), (120_000, 2))
        self.assertEqual(len(self.warehouse.movements(MovementKind.IN, returns=False)), 2)
        self.assertEqual(len(self.warehouse.movements(MovementKind.IN, returns=True)), 1)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 94)  # qoldiqqa esa qaytgan

    def test_customers_collected_as_sites_by_the_previous_version_are_dropped(self):
        path = self.folder / "eski.db"
        connect(path).close()
        old = open_raw(path)
        old.execute("INSERT INTO products (name, unit) VALUES ('Truba', 'metr')")
        old.execute(
            "INSERT INTO movements (kind, date, product_id, quantity, price) VALUES ('IN', '2026-01-01', 1, 9, 5)"
        )
        for name, sale_price in (("Xaridor", 9), ("Obyekt", 0), ("Aralash", 9), ("Aralash", 0)):
            old.execute(
                "INSERT INTO movements (kind, date, product_id, quantity, sale_price, counterparty)"
                " VALUES ('OUT', '2026-01-02', 1, 1, ?, ?)",
                (sale_price, name),
            )
        old.executemany("INSERT INTO sites (name) VALUES (?)", [("Xaridor",), ("Obyekt",), ("Aralash",)])
        old.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
        old.commit()
        old.close()
        conn = connect(path)
        self.addCleanup(conn.close)
        self.assertEqual([row[0] for row in conn.execute("SELECT name FROM sites ORDER BY name")], ["Aralash", "Obyekt"])


class ReceiptDocumentTests(DocumentTestCase):
    def test_several_products_are_saved_with_the_shared_fields(self):
        dialog = self.dialog()
        dialog._supplier.setCurrentText("Temir bozor")
        dialog._doc_number.setText("N-7")
        self.fill(dialog, ("Truba 40x40", 30, 1200), ("List 2mm", 5, 90_000))
        self.assertIn("486 000", dialog._total.text())
        dialog.accept()
        saved = [self.warehouse.movement(movement_id) for movement_id in dialog.saved_ids]
        self.assertEqual([(m.product_name, m.quantity, m.price) for m in saved], [("Truba 40x40", 30, 1200), ("List 2mm", 5, 90_000)])
        self.assertEqual({(m.counterparty, m.doc_number, m.created_by) for m in saved}, {("Temir bozor", "N-7", "Rahbar")})
        self.assertEqual(len(self.warehouse.document(saved[0].id)), 2)

    def test_new_blank_line_opens_when_the_last_one_is_filled(self):
        dialog = self.dialog()
        self.assertEqual(dialog._table.rowCount(), 1)
        dialog.line(0).select("Truba 40x40")
        self.assertEqual(dialog._table.rowCount(), 2)
        self.assertTrue(dialog.line(1).is_blank())
        dialog.line(0).remove.click()
        self.assertEqual(dialog._table.rowCount(), 1)
        with self.assertRaises(WarehouseError):
            dialog.save()  # hech narsa kiritilmagan

    def test_previous_price_is_suggested_and_the_second_unit_is_converted(self):
        cement = self.warehouse.save_product(Product("Sement", "kg", alt_unit="tonna", alt_factor=1000))
        dialog = self.dialog()
        dialog.line(0).select("Truba 40x40")
        self.assertEqual(dialog.line(0).price.value(), 1000)
        self.assertEqual(dialog.line(0).stock.text(), "100 metr")
        dialog.line(1).select("Sement")
        dialog.line(1).unit.setCurrentIndex(1)
        self.fill(dialog, ("Truba 40x40", 1), ("Sement", 2, 900_000))
        dialog.accept()
        saved = self.warehouse.movements(MovementKind.IN, search="Sement")[0]
        self.assertEqual((saved.product_id, saved.quantity, saved.price), (cement, 2000, 900))

    def test_unknown_product_is_refused_and_nothing_is_saved(self):
        dialog = self.dialog()
        self.fill(dialog, ("Truba 40x40", 1, 1000))
        dialog.line(1).product.setEditText("Yo'q mahsulot")
        dialog.line(1).quantity.setValue(3)
        with self.assertRaises(WarehouseError):
            dialog.save()
        self.assertEqual(len(self.warehouse.movements(MovementKind.IN)), 2)

    def test_scanned_barcode_selects_the_product_instead_of_saving(self):
        self.warehouse.save_product(Product("Bolt M10", "dona", barcode="4780001"))
        dialog = self.dialog()
        dialog.line(0).product.setEditText("4780001")
        dialog.accept()
        self.assertEqual(dialog.line(0).selected().name, "Bolt M10")
        self.assertEqual(dialog.saved_ids, [])

    def test_group_comes_from_the_product_unless_chosen(self):
        self.warehouse.group_required = True
        first = self.dialog()
        self.assertTrue(first.extras_shown)  # majburiy guruh darhol ko'rinadi
        self.fill(first, ("Truba 40x40", 1, 1000))
        with self.assertRaises(WarehouseError):
            first.save()
        first._groups.group.setCurrentIndex(1)
        first.accept()
        category = self.warehouse.movement(first.saved_ids[0]).category
        self.assertTrue(category)
        second = self.dialog()
        self.fill(second, ("Truba 40x40", 1, 1000))
        second.accept()  # guruh tanlanmagan — mahsulotning oxirgi guruhi olinadi
        self.assertEqual(self.warehouse.movement(second.saved_ids[0]).category, category)


class IssueDocumentTests(DocumentTestCase):
    def test_issue_to_a_site_needs_the_site_and_has_no_prices(self):
        dialog = self.dialog(MovementKind.OUT)
        self.assertIs(dialog._target.currentData(), IssueTarget.SITE)
        self.assertTrue(dialog._table.isColumnHidden(PRICE) and dialog._table.isColumnHidden(AMOUNT))
        self.fill(dialog, ("Truba 40x40", 40), ("List 2mm", 5))
        with self.assertRaises(WarehouseError):
            dialog.save()  # obyekt tanlanmagan
        dialog._site.combo.setCurrentIndex(0)
        dialog.accept()
        saved = self.warehouse.movements(MovementKind.OUT)
        self.assertEqual({(m.counterparty, m.sale_price) for m in saved}, {("Chilonzor", 0)})
        self.assertEqual(self.sites.all()[0].issued, 45_000)

    def test_sale_needs_a_price_and_goes_to_the_customer(self):
        dialog = self.issue_to(IssueTarget.SALE)
        self.assertFalse(dialog._table.isColumnHidden(PRICE))
        dialog._customer.setCurrentText("Xaridor MChJ")
        self.fill(dialog, ("Truba 40x40", 10))
        with self.assertRaises(WarehouseError):
            dialog.save()  # sotuv narxi yo'q
        dialog.line(0).price.setValue(1500)
        dialog.accept()
        (sale,) = self.warehouse.movements(MovementKind.OUT)
        self.assertEqual((sale.counterparty, sale.sale_price, sale.profit), ("Xaridor MChJ", 1500, 5000))
        self.assertEqual(self.sites.all()[0].issued, 0)

    def test_other_expense_has_no_counterparty(self):
        dialog = self.issue_to(IssueTarget.OTHER)
        self.fill(dialog, ("List 2mm", 2))
        dialog.accept()
        (issue,) = self.warehouse.movements(MovementKind.OUT)
        self.assertEqual((issue.counterparty, issue.sale_price), ("", 0))

    def test_more_than_in_stock_is_refused_for_the_whole_document(self):
        dialog = self.dialog(MovementKind.OUT)
        dialog._site.combo.setCurrentIndex(0)
        self.fill(dialog, ("Truba 40x40", 10), ("List 2mm", 21))
        with self.assertRaises(WarehouseError):
            dialog.save()
        self.assertEqual(self.warehouse.movements(MovementKind.OUT), [])


class PagesTests(DocumentTestCase):
    def page(self, kind=MovementKind.IN) -> MovementsPage:
        return MovementsPage(self.warehouse, self.sites, LABELS[kind], Session(self.admin))

    def test_new_record_opens_the_document_and_editing_opens_the_full_form(self):
        page = self.page()
        self.assertIsInstance(page.edit_dialog(None), DocumentDialog)
        self.assertIsInstance(page.edit_dialog(self.by_admin), MovementDialog)

    def test_rare_fields_are_folded_for_a_new_record_and_open_when_editing(self):
        new = MovementDialog(self.warehouse, LABELS[MovementKind.IN], "Rahbar")
        self.assertFalse(new.extras_shown)
        new.show_extras(True)
        self.assertTrue(new.extras_shown)
        editing = MovementDialog(self.warehouse, LABELS[MovementKind.IN], "Rahbar", self.warehouse.movement(self.by_admin))
        self.assertTrue(editing.extras_shown)

    def test_receipts_page_leaves_returns_to_the_returns_page(self):
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 10, counterparty="Chilonzor"))
        self.sites.save_return(SiteReturn(TODAY, self.site, self.pipe, 4))
        page = self.page()
        page.refresh()
        self.assertEqual(len(page.table.export_data()[1]), 2)
        self.assertIn("120 000", page.footer.text())

    def test_empty_table_tells_what_to_do(self):
        page = ProductsPage(self.warehouse, self.services.sites, Session(self.admin))
        page.show()
        self.assertIn("Yangi mahsulot", page.table.empty_text)
        page.search.setText("yo'q narsa")
        self.assertEqual(page.table.empty_text, "Hech narsa topilmadi")

    def test_reports_show_what_each_site_cost(self):
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 10, counterparty="Chilonzor"))
        self.sites.save_return(SiteReturn(TODAY, self.site, self.pipe, 4))
        page = ReportsPage(self.services.reports, self.services.analytics, self.warehouse, self.sites)
        page.refresh()
        tables = {page._tabs.tabText(index): page._tabs.widget(index) for index in range(page._tabs.count())}
        self.assertEqual(tables["Obyekt xarajati"].export_data()[1], [("Chilonzor", 10_000, 4000, 6000)])
        self.assertEqual(
            tables["Obyekt mahsulotlari"].export_data()[1], [("Chilonzor", "Truba 40x40", "metr", 10, 4, 6000)]
        )

    def test_dashboard_offers_a_return_and_shows_what_is_at_the_sites(self):
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 10, counterparty="Chilonzor"))
        page = DashboardPage(self.warehouse, self.services.reports, self.sites)
        page.refresh()
        asked = []
        page.return_requested.connect(lambda: asked.append(True))
        self.assertEqual(page._at_sites._value.text(), "10 ming")
        tile = next(button for button in page.findChildren(QPushButton) if "F5" in button.toolTip())
        tile.click()
        self.assertEqual(asked, [True])

    def test_return_dialog_accepts_the_second_unit(self):
        cement = self.warehouse.save_product(Product("Sement", "kg", alt_unit="tonna", alt_factor=1000))
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, cement, 5000, 900))
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, cement, 3000, counterparty="Chilonzor"))
        dialog = ReturnDialog(self.sites, self.warehouse, "Rahbar")
        dialog._site.combo.setCurrentIndex(0)
        dialog._product.setCurrentIndex(dialog._product.findText("Sement"))
        dialog._unit.setCurrentIndex(1)
        dialog._quantity.setValue(2)
        dialog.accept()
        self.assertEqual(self.sites.returns()[0].quantity, 2000)

    def test_printed_sheets_carry_the_firm_name(self):
        self.addCleanup(printing.set_firm_name, "MME Ombor")
        window = self.window(self.admin)
        window._show_firm_name("Metall Montaj Ombori")
        page = self.page()
        page.refresh()
        self.assertIn("Metall Montaj Ombori", printing.table_html(page.table, "Kirim"))
        self.assertIn(
            "Metall Montaj Ombori",
            printing.waybill_html(self.warehouse.document(self.by_admin), LABELS[MovementKind.IN]),
        )

    def test_rarely_used_sections_are_set_apart_in_the_menu(self):
        window = self.window(self.admin)
        marked = [
            window._menu.item(row).text().strip()
            for row in range(window._menu.count())
            if window._menu.item(row).data(DIVIDER_ROLE)
        ]
        self.assertEqual(marked, ["Tarix"])
        window._menu.viewport().grab()  # chiziq xatosiz chiziladi
