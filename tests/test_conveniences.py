"""Qulayliklar: nakladnoy raqami, nakladnoyni butunligicha tahrirlash va o'chirish, mahsulot kartochkasi,
xarid ro'yxati va obyektlar joylashuvini bir yo'la topish."""

from unittest import mock

from PySide6.QtWidgets import QMessageBox

from ombor import geo
from ombor.geo import FoundPlace, Location, LookupFailed
from ombor.models import Movement, MovementKind, Product, Site, SiteReturn
from ombor.session import Session
from ombor.ui import document_dialog, movements_page, sites_page
from ombor.ui.dialogs import MovementDialog
from ombor.ui.document_dialog import DocumentDialog, can_edit_as_document
from ombor.ui.labels import LABELS
from ombor.ui.movements_page import MovementsPage
from ombor.ui.product_card import ProductCardDialog, movement_kind
from ombor.ui.products_page import ProductsPage
from ombor.ui.site_dialogs import TableDialog
from ombor.ui.sites_page import SitesPage
from tests.test_site_map import wait_until
from tests.test_ui import TODAY, UiTestCase


class ConveniencesTestCase(UiTestCase):
    """Omborda 100 metr truba va 20 ta list; «Chilonzor» obyektiga ikkalasidan bitta nakladnoy bilan berilgan."""

    def setUp(self):
        super().setUp()
        self.sites = self.services.sites
        self.site = self.sites.save(Site("Chilonzor"))
        self.issue = self.warehouse.save_document(
            [
                Movement(MovementKind.OUT, TODAY, self.pipe, 30, counterparty="Chilonzor", created_by="Rahbar"),
                Movement(MovementKind.OUT, TODAY, self.sheet, 5, counterparty="Chilonzor", created_by="Rahbar"),
            ]
        )

    def page(self, user=None) -> MovementsPage:
        return MovementsPage(self.warehouse, self.sites, LABELS[MovementKind.OUT], Session(user or self.admin))


class DocumentNumberTests(ConveniencesTestCase):
    def test_document_without_a_number_gets_the_next_one(self):
        self.assertEqual({self.warehouse.movement(i).doc_number for i in self.issue}, {"CH-1"})
        receipt = self.warehouse.save_document([Movement(MovementKind.IN, TODAY, self.pipe, 1, 1000)])
        self.assertEqual(self.warehouse.movement(receipt[0]).doc_number, "K-1")
        second = self.warehouse.save_document([Movement(MovementKind.OUT, TODAY, self.pipe, 1)])
        self.assertEqual(self.warehouse.movement(second[0]).doc_number, "CH-2")
        typed = self.warehouse.save_document([Movement(MovementKind.OUT, TODAY, self.pipe, 1, doc_number="A-7")])
        self.assertEqual(self.warehouse.movement(typed[0]).doc_number, "A-7")

    def test_whole_document_is_deleted_together(self):
        self.warehouse.delete_document(self.issue)
        self.assertEqual(self.warehouse.movements(MovementKind.OUT), [])
        self.assertEqual(self.warehouse.product(self.pipe).stock, 100)
        self.assertEqual(len(self.warehouse.deleted_movements()), 2)  # tiklash mumkin


class DocumentEditTests(ConveniencesTestCase):
    def test_document_of_several_products_opens_in_the_document_dialog(self):
        page = self.page()
        dialog = page.edit_dialog(self.issue[1])
        self.assertIsInstance(dialog, DocumentDialog)
        self.assertEqual([dialog.line(i).selected().name for i in range(2)], ["Truba 40x40", "List 2mm"])
        self.assertEqual(dialog.line(0).quantity.value(), 30)
        self.assertEqual(dialog._site.site_name(), "Chilonzor")
        self.assertEqual(dialog._doc_number.text(), "CH-1")
        single = self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 1, counterparty="Chilonzor"))
        self.assertIsInstance(page.edit_dialog(single), MovementDialog)  # bitta yozuv — to'liq shaklda

    def test_editing_changes_adds_and_removes_lines_in_one_go(self):
        dialog = self.page().edit_dialog(self.issue[0])
        dialog.line(0).quantity.setValue(40)
        dialog.line(1).remove.click()
        bolt = self.warehouse.save_product(Product("Bolt", "dona"))
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, bolt, 50, 100))
        dialog._reload_products()
        dialog.line(1).select("Bolt")
        dialog.line(1).quantity.setValue(10)
        dialog.accept()
        document = self.warehouse.document(self.issue[0])
        self.assertEqual([(m.product_name, m.quantity) for m in document], [("Truba 40x40", 40), ("Bolt", 10)])
        self.assertEqual({m.doc_number for m in document}, {"CH-1"})
        self.assertEqual(self.warehouse.product(self.sheet).stock, 20)  # olib tashlangan qator o'chdi
        self.assertEqual(self.warehouse.movement(self.issue[0]).id, self.issue[0])  # yozuv o'sha, yangilandi

    def test_failed_edit_changes_nothing(self):
        dialog = self.page().edit_dialog(self.issue[0])
        dialog.line(1).remove.click()
        dialog.line(0).quantity.setValue(500)  # omborda yo'q
        with mock.patch.object(QMessageBox, "warning"):
            dialog.accept()
        self.assertEqual([m.quantity for m in self.warehouse.document(self.issue[0])], [30, 5])

    def test_keeper_cannot_open_even_own_document_for_editing(self):
        page = self.page(self.keeper)
        own = self.warehouse.save_document(
            [
                Movement(MovementKind.OUT, TODAY, self.pipe, 1, created_by="Vali"),
                Movement(MovementKind.OUT, TODAY, self.sheet, 1, created_by="Vali"),
            ]
        )
        self.assertFalse(page.can_change(own[0]))
        with mock.patch.object(QMessageBox, "information") as told:  # «faqat rahbar o'zgartira oladi»
            page._open(own[0])
        told.assert_called_once()

    def test_documents_with_returns_or_mixed_details_are_edited_line_by_line(self):
        document = self.warehouse.document(self.issue[0])
        self.assertTrue(can_edit_as_document(document))
        self.assertFalse(can_edit_as_document(document[:1]))
        mixed = self.warehouse.save_document(
            [
                Movement(MovementKind.OUT, TODAY, self.pipe, 1, counterparty="Chilonzor"),
                Movement(MovementKind.OUT, TODAY, self.sheet, 1, counterparty="Boshqa"),
            ]
        )
        self.assertFalse(can_edit_as_document(self.warehouse.document(mixed[0])))

    def test_save_and_print_opens_the_waybill_of_the_saved_document(self):
        dialog = DocumentDialog(self.warehouse, self.sites, LABELS[MovementKind.OUT], "Rahbar")
        dialog._site.combo.setCurrentIndex(0)
        dialog.line(0).select("Truba 40x40")
        dialog.line(0).quantity.setValue(2)
        with mock.patch.object(document_dialog, "print_waybill") as printed:
            dialog._save_and_print()
        printed.assert_called_once()
        self.assertEqual([m.id for m in printed.call_args.args[1]], dialog.saved_ids)
        self.assertEqual(dialog.result(), DocumentDialog.DialogCode.Accepted)

    def delete_choosing(self, movement_id: int, choice: str) -> None:
        """Qatorni o'chiradi; «nimani o'chiramiz?» savoliga `choice` tugmasi bilan javob beriladi."""

        def answer(box):
            box.clickedButton = lambda: next(button for button in box.buttons() if button.text() == choice)
            return 0

        with mock.patch.object(movements_page.QMessageBox, "exec", answer):
            self.page()._delete(movement_id)

    def test_deleting_a_line_offers_the_whole_document(self):
        self.delete_choosing(self.issue[1], "Faqat shu qatorni")
        self.assertEqual([m.id for m in self.warehouse.movements(MovementKind.OUT)], [self.issue[0]])
        other = self.warehouse.save_document(
            [Movement(MovementKind.OUT, TODAY, self.pipe, 1), Movement(MovementKind.OUT, TODAY, self.sheet, 1)]
        )
        self.delete_choosing(other[0], "Butun nakladnoyni")
        self.assertEqual([m.id for m in self.warehouse.movements(MovementKind.OUT)], [self.issue[0]])


class ProductCardTests(ConveniencesTestCase):
    def test_card_shows_the_history_and_where_the_product_is(self):
        self.sites.save_return(SiteReturn(TODAY, self.site, self.pipe, 4))
        card = ProductCardDialog(self.warehouse, self.sites, self.pipe)
        kinds = [row[1] for row in card._history.export_data()[1]]
        self.assertEqual(sorted(kinds), ["Chiqim", "Kirim", "Vozvrat"])
        self.assertEqual(card._site_table.export_data()[1], [("Chilonzor", 30, 4, 26)])
        card.grab()

    def test_movement_kinds_are_named_for_people(self):
        sale = self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 1, sale_price=2000))
        back = self.warehouse.save_movement(
            Movement(MovementKind.OUT, TODAY, self.pipe, 1, is_return=True, counterparty="Temir bozor")
        )
        self.assertEqual(movement_kind(self.warehouse.movement(sale)), "Sotuv")
        self.assertEqual(movement_kind(self.warehouse.movement(back)), "Qaytarildi")

    def test_double_click_opens_the_card_for_every_role(self):
        for user in (self.admin, self.viewer):
            page = ProductsPage(self.warehouse, self.sites, Session(user))
            with mock.patch("ombor.ui.products_page.ProductCardDialog") as card:
                page.table.row_activated.emit(self.pipe)
            card.assert_called_once()


class PurchaseListTests(ConveniencesTestCase):
    def test_low_products_are_listed_with_quantity_and_last_purchase(self):
        self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 10, 1200, counterparty="Temir bozor")
        )
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 40, counterparty="Chilonzor"))
        lines = {line.product.name: line for line in self.warehouse.purchase_list()}
        pipe = lines["Truba 40x40"]  # qoldiq 40, minimal 50 → 100 gacha to'ldirish
        self.assertEqual((pipe.quantity, pipe.last_price, pipe.last_supplier, pipe.amount), (60, 1200, "Temir bozor", 72_000))
        self.assertNotIn("List 2mm", lines)  # minimal qoldig'i yo'q va tugamagan

    def test_purchase_list_is_shown_from_the_products_page(self):
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 60, counterparty="Chilonzor"))
        page = ProductsPage(self.warehouse, self.sites, Session(self.admin))
        shown = []
        with mock.patch.object(TableDialog, "exec", lambda dialog: shown.append(dialog)):
            page._show_purchase_list()
        self.assertEqual(shown[0].table.export_data()[1][0][:5], ("Truba 40x40", "metr", 10, 50, 90))


class FindPlacesTests(ConveniencesTestCase):
    def page(self, user=None) -> SitesPage:
        page = SitesPage(self.sites, Session(user or self.admin))
        page.refresh()
        return page

    def test_missing_locations_are_found_in_one_go(self):
        self.sites.save(Site("Sergeli", "Sergeli tumani"))
        place = FoundPlace(Location(41.2756, 69.2034), "Toshkent")
        page = self.page()
        self.assertFalse(page._find_places.isHidden())
        with (
            mock.patch.object(geo, "find_place", side_effect=[place, None]) as asked,
            mock.patch.object(geo.time, "sleep"),
            mock.patch.object(sites_page.time, "sleep"),
            mock.patch.object(sites_page, "confirm", return_value=True),
            mock.patch.object(sites_page.QMessageBox, "information") as told,
        ):
            page._find_missing_places()
            wait_until(self.app, lambda: told.called)
        self.assertEqual([call.args for call in asked.call_args_list], [("Chilonzor", ""), ("Sergeli", "Sergeli tumani")])
        self.assertEqual(self.sites.get(self.site).location, place.location)
        self.assertIn("1", told.call_args.args[2])
        self.assertTrue(page._find_places.isEnabled())

    def test_search_stops_without_internet_and_is_offered_only_to_the_head(self):
        page = self.page()
        with (
            mock.patch.object(geo, "find_place", side_effect=LookupFailed("tarmoq yo'q")),
            mock.patch.object(sites_page, "confirm", return_value=True),
            mock.patch.object(sites_page.QMessageBox, "information") as told,
        ):
            page._find_missing_places()
            wait_until(self.app, lambda: told.called)
        self.assertIn("Internet", told.call_args.args[2])
        self.assertIsNone(self.sites.get(self.site).location)
        keeper = SitesPage(self.sites, Session(self.keeper))
        self.assertNotIn("Joylashuvlarni topish", self.button_texts(keeper))

    def test_map_returns_to_showing_every_site(self):
        page = self.page()
        page._map._fitted = True
        page._map.show_all()
        self.assertFalse(page._map._fitted)
