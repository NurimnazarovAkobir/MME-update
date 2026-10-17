"""Obyektlar va vozvrat: ro'yxat, berilgan/qaytgan mahsulotlar hisobi, sahifalar va oynalar."""

from datetime import timedelta
from unittest import mock

from ombor.database import connect, open_raw
from ombor.errors import WarehouseError
from ombor.migrations import SCHEMA_VERSION
from ombor.models import HistoryAction, Movement, MovementKind, Period, Site, SiteReturn
from ombor.session import Session
from ombor.sites import SITE_ENTITY
from ombor.ui.dialogs import MovementDialog
from ombor.ui.returns_page import ReturnsPage
from ombor.ui.site_dialogs import ReturnDialog, SiteDialog, TableDialog
from ombor.ui.sites_page import SitesPage
from tests.test_ui import TODAY, UiTestCase


class SitesTestCase(UiTestCase):
    """Bitta obyekt («Chilonzor») va unga berilgan 40 metr truba (narxi 1000) bilan boshlanadi."""

    def setUp(self):
        super().setUp()
        self.sites = self.services.sites
        self.site = self.sites.save(Site("Chilonzor", "Toshkent", "Anvar"))
        self._issue(self.pipe, 40)

    def _issue(self, product_id, quantity, site="Chilonzor"):
        return self.warehouse.save_movement(
            Movement(MovementKind.OUT, TODAY, product_id, quantity, counterparty=site, created_by="Rahbar")
        )

    def _return(self, product_id, quantity, author="Rahbar", **fields):
        return self.sites.save_return(SiteReturn(TODAY, self.site, product_id, quantity, created_by=author, **fields))


class SiteRulesTests(SitesTestCase):
    def test_site_needs_a_unique_name(self):
        with self.assertRaises(WarehouseError):
            self.sites.save(Site("   "))
        with self.assertRaises(WarehouseError):
            self.sites.save(Site("chilonzor"))

    def test_site_named_in_an_issue_is_added_to_the_list_by_itself(self):
        self._issue(self.pipe, 5, site="Sergeli")
        self.assertEqual([site.name for site in self.sites.all()], ["Chilonzor", "Sergeli"])
        self.assertEqual([site.name for site in self.sites.all("serg")], ["Sergeli"])

    def test_unused_site_is_offered_when_issuing(self):
        self.sites.save(Site("Yunusobod"))
        self.assertEqual(self.warehouse.suggestions(MovementKind.OUT, "counterparty"), ["Chilonzor", "Yunusobod"])

    def test_return_comes_back_to_stock_at_the_issue_cost(self):
        returned = self.warehouse.movement(self._return(self.pipe, 15, person="Ali"))
        self.assertEqual(self.warehouse.product(self.pipe).stock, 75)
        self.assertTrue(returned.is_return)
        self.assertEqual((returned.kind, returned.counterparty, returned.price), (MovementKind.IN, "Chilonzor", 1000))
        totals = self.sites.all()[0]
        self.assertEqual((totals.issued, totals.returned, totals.remaining), (40_000, 15_000, 25_000))

    def test_products_show_what_each_site_received_and_returned(self):
        self._issue(self.sheet, 10, site="Sergeli")
        self._return(self.pipe, 15)
        rows = {(row.site, row.product_name): row for row in self.sites.products()}
        pipe = rows["Chilonzor", "Truba 40x40"]
        self.assertEqual((pipe.issued, pipe.returned, pipe.remaining, pipe.returned_amount), (40, 15, 25, 15_000))
        self.assertEqual(rows["Sergeli", "List 2mm"].returned, 0)
        self.assertEqual(len(self.sites.products(self.site)), 1)
        last_month = Period(end=TODAY - timedelta(days=30))
        self.assertEqual(self.sites.products(period=last_month), [])

    def test_return_does_not_ask_for_a_group_even_when_groups_are_required(self):
        self.warehouse.group_required = True
        self._return(self.pipe, 1)
        self.assertEqual(len(self.sites.returns()), 1)

    def test_renaming_a_site_moves_its_records(self):
        self._return(self.pipe, 5)
        self.sites.save(Site("Chilonzor-5", id=self.site))
        self.assertEqual({m.counterparty for m in self.warehouse.movements() if m.counterparty}, {"Chilonzor-5"})
        self.assertEqual(self.sites.products(self.site)[0].returned, 5)

    def test_site_with_records_cannot_be_deleted(self):
        with self.assertRaises(WarehouseError):
            self.sites.delete(self.site)
        empty = self.sites.save(Site("Yangi obyekt"))
        self.sites.delete(empty)
        self.assertIsNone(self.sites.find("Yangi obyekt"))

    def test_site_changes_are_written_to_history(self):
        self.sites.actor = "Rahbar"
        self.sites.save(Site("Chilonzor", "Yangi manzil", id=self.site))
        entry = next(entry for entry in self.warehouse.history() if entry.entity == SITE_ENTITY)
        self.assertEqual((entry.action, entry.actor), (HistoryAction.EDIT, "Rahbar"))
        self.assertIn("Yangi manzil", entry.summary)

    def test_old_database_gets_sites_from_its_issues(self):
        path = self.folder / "eski.db"
        connect(path).close()
        old = open_raw(path)
        old.execute("INSERT INTO products (name, unit) VALUES ('Truba', 'metr')")
        old.execute(
            "INSERT INTO movements (kind, date, product_id, quantity, price) VALUES ('IN', '2026-01-01', 1, 9, 5)"
        )
        for name in ("Sergeli", "Inventarizatsiya (kamomad)", ""):
            old.execute(
                "INSERT INTO movements (kind, date, product_id, quantity, counterparty)"
                " VALUES ('OUT', '2026-01-02', 1, 1, ?)",
                (name,),
            )
        old.execute("DROP TABLE sites")
        old.execute(f"PRAGMA user_version = {SCHEMA_VERSION - 1}")
        old.commit()
        old.close()
        conn = connect(path)
        self.addCleanup(conn.close)
        self.assertEqual([row[0] for row in conn.execute("SELECT name FROM sites")], ["Sergeli"])


class SitePagesTests(SitesTestCase):
    @staticmethod
    def shown_rows(open_table) -> list:
        """`open_table` ochadigan jadvalli oynaning qatorlari (oyna ekranga chiqarilmaydi)."""
        shown = []
        with mock.patch.object(TableDialog, "exec", lambda dialog: shown.append(dialog)):
            open_table()
        return shown[0].table.export_data()[1]

    def test_sites_page_lists_sites_with_totals(self):
        page = SitesPage(self.sites, Session(self.admin))
        page.refresh()
        self.assertEqual(page.table.export_data()[1], [("Chilonzor", "Toshkent", "Anvar", 40_000, 0, 40_000, "")])
        self.assertIn("Yangi obyekt", self.button_texts(page))
        self.assertNotIn("Yangi obyekt", self.button_texts(SitesPage(self.sites, Session(self.viewer))))

    def test_site_dialog_adds_and_edits(self):
        dialog = SiteDialog(self.sites)
        dialog._name.setText("Sergeli angar")
        dialog._manager.setText("Botir")
        dialog.save()
        self.assertEqual(self.sites.get(dialog.saved_id).manager, "Botir")
        edit = SiteDialog(self.sites, self.sites.get(dialog.saved_id))
        edit._address.setText("Sanoat zonasi")
        edit.save()
        self.assertEqual(self.sites.get(dialog.saved_id).address, "Sanoat zonasi")

    def test_site_products_are_shown_for_the_selected_site(self):
        self._return(self.pipe, 15)
        page = SitesPage(self.sites, Session(self.admin))
        page.refresh()
        page.table.selectRow(0)
        self.assertEqual(self.shown_rows(page._show_products), [("Truba 40x40", "metr", 40, 15, 25)])

    def test_return_dialog_shows_what_is_at_the_site_and_saves(self):
        dialog = ReturnDialog(self.sites, self.warehouse, "Vali")
        self.assertEqual(dialog._site.combo.currentIndex(), -1)
        with self.assertRaises(WarehouseError):
            dialog.save()  # obyekt tanlanmagan
        dialog._site.combo.setCurrentIndex(dialog._site.combo.findText("Chilonzor"))
        self.assertEqual(dialog._product.itemText(0), "Truba 40x40")  # obyektda turgan mahsulot — birinchi
        dialog._product.setCurrentIndex(0)
        self.assertIn("40", dialog._balance_hint.text())
        dialog._quantity.setValue(10)
        dialog.accept()
        (saved,) = self.sites.returns()
        self.assertEqual((saved.quantity, saved.counterparty, saved.created_by), (10, "Chilonzor", "Vali"))

    def test_returning_more_than_the_site_has_needs_confirmation(self):
        dialog = ReturnDialog(self.sites, self.warehouse, "Rahbar")
        dialog._site.combo.setCurrentIndex(0)
        dialog._product.setCurrentIndex(0)
        dialog._quantity.setValue(41)
        with mock.patch("ombor.ui.site_dialogs.confirm", return_value=False):
            dialog.accept()
        self.assertEqual(self.sites.returns(), [])
        with mock.patch("ombor.ui.site_dialogs.confirm", return_value=True):
            dialog.accept()
        self.assertEqual(len(self.sites.returns()), 1)

    def test_several_products_are_returned_without_closing_the_dialog(self):
        self._issue(self.sheet, 5)
        dialog = ReturnDialog(self.sites, self.warehouse, "Rahbar")
        dialog._site.combo.setCurrentIndex(0)
        for name, quantity in (("Truba 40x40", 3), ("List 2mm", 2)):
            dialog._product.setCurrentIndex(dialog._product.findText(name))
            dialog._quantity.setValue(quantity)
            dialog._save_and_continue()
        self.assertEqual(dialog.saved_count, 2)
        self.assertEqual(dialog._site.combo.currentText(), "Chilonzor")
        self.assertEqual(sorted(m.quantity for m in self.sites.returns()), [2, 3])

    def test_new_site_can_be_added_from_the_return_dialog(self):
        dialog = ReturnDialog(self.sites, self.warehouse, "Rahbar")

        def add_site(site_dialog):
            site_dialog._name.setText("Sergeli")
            site_dialog.save()
            return 1

        with mock.patch.object(SiteDialog, "exec", add_site):
            dialog._site.add_site()
        self.assertEqual(dialog._site.combo.currentText(), "Sergeli")

    def test_returns_page_lists_returns_and_summary_by_site(self):
        self._return(self.pipe, 15, person="Ali")
        page = ReturnsPage(self.sites, self.warehouse, Session(self.admin))
        page.refresh()
        self.assertEqual(
            page.table.export_data()[1],
            [(TODAY, "", "Chilonzor", "Truba 40x40", 15, "metr", 15_000, "Ali", "Asosiy ombor", "")],
        )
        self.assertIn("15 000", page.footer.text())
        self.assertEqual(self.shown_rows(page._show_by_site), [("Chilonzor", "Truba 40x40", "metr", 40, 15, 15_000)])

    def test_returns_page_edits_and_deletes(self):
        by_keeper = self._return(self.pipe, 5, author="Vali")
        by_admin = self._return(self.pipe, 5)
        keeper_page = ReturnsPage(self.sites, self.warehouse, Session(self.keeper))
        self.assertFalse(keeper_page.can_change(by_keeper))  # omborchi o'zinikini ham tahrirlamaydi
        self.assertFalse(keeper_page.can_change(by_admin))
        page = ReturnsPage(self.sites, self.warehouse, Session(self.admin))
        dialog = page.edit_dialog(by_admin)
        self.assertIsInstance(dialog, ReturnDialog)
        self.assertEqual(
            (dialog._site.combo.currentText(), dialog._product.currentText()), ("Chilonzor", "Truba 40x40")
        )
        dialog._quantity.setValue(7)
        dialog.accept()
        self.assertEqual(self.warehouse.movement(by_admin).quantity, 7)
        page.delete_item(by_admin)
        self.assertEqual([m.id for m in self.sites.returns()], [by_keeper])

    def test_return_entered_in_receipts_without_a_site_opens_in_the_receipt_dialog(self):
        other = self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 2, 1000, counterparty="Xaridor", is_return=True)
        )
        page = ReturnsPage(self.sites, self.warehouse, Session(self.admin))
        self.assertIsInstance(page.edit_dialog(other), MovementDialog)

    def test_menu_has_returns_and_sites(self):
        window = self.window(self.admin)
        titles = [window._menu.item(row).text().strip() for row in range(window._menu.count())]
        self.assertLess(titles.index("Chiqim"), titles.index("Vozvrat"))
        self.assertIn("Obyektlar", titles)
        self.assertEqual(self.sites.actor, "Rahbar")
