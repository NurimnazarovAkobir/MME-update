"""Interfeys: mahsulot guruhlari, soddalashtirilgan mahsulot va kirim/chiqim oynalari, sozlamalar."""

from dataclasses import replace
from unittest import mock

from ombor.models import MovementKind, Product
from ombor.session import Session
from ombor.ui.dialogs import ProductDialog
from ombor.ui.document_dialog import DocumentDialog, IssueTarget
from ombor.ui.labels import LABELS
from ombor.ui.products_page import ProductsPage
from ombor.ui.settings_page import SettingsPage
from tests.test_ui import UiTestCase


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


class SimpleProductDialogTests(UiTestCase):
    def test_rare_fields_are_folded_for_a_new_product(self):
        dialog = ProductDialog(self.warehouse)
        self.assertFalse(dialog.extras_shown)
        dialog._name.setText("Sement M400")
        dialog._unit.setCurrentText("kg")
        dialog.save()
        self.assertEqual(self.warehouse.product(dialog.saved_id).unit, "kg")

    def test_filled_rare_fields_are_open_when_editing(self):
        product = self.warehouse.product(self.pipe)
        self.warehouse.save_product(replace(product, barcode="4780001"))
        dialog = ProductDialog(self.warehouse, self.warehouse.product(self.pipe))
        self.assertTrue(dialog.extras_shown)

    def test_alt_unit_shows_the_base_unit(self):
        dialog = ProductDialog(self.warehouse)
        dialog._unit.setCurrentText("kg")
        self.assertEqual(dialog._base_unit.text(), "kg")


class SimpleDocumentDialogTests(UiTestCase):
    def test_issue_target_buttons_switch_fields(self):
        dialog = DocumentDialog(self.warehouse, self.services.sites, LABELS[MovementKind.OUT], "Rahbar")
        dialog.show()
        dialog._target_choices[IssueTarget.SALE].click()
        self.assertIs(dialog._target.currentData(), IssueTarget.SALE)
        self.assertFalse(dialog._customer_field.isHidden())
        self.assertTrue(dialog._site_field.isHidden())
        self.assertTrue(dialog._target_choices[IssueTarget.SALE].isChecked())

    def test_numbers_start_empty(self):
        dialog = DocumentDialog(self.warehouse, self.services.sites, LABELS[MovementKind.IN], "Rahbar")
        self.assertEqual(dialog.line(0).quantity.text().strip(), "")

    def test_missing_product_is_added_from_the_document(self):
        dialog = DocumentDialog(self.warehouse, self.services.sites, LABELS[MovementKind.IN], "Rahbar")
        new_id = self.warehouse.save_product(Product("Yangi bolt", "dona"))  # mahsulot oynasida saqlangandek
        with mock.patch("ombor.ui.document_dialog.ProductDialog") as product_dialog:
            product_dialog.return_value.exec.return_value = True
            product_dialog.return_value.saved_id = new_id
            dialog._add_product()
        self.assertEqual(dialog.line(0).selected().name, "Yangi bolt")


class SettingsWithoutServerTests(UiTestCase):
    def test_server_section_is_gone(self):
        page = SettingsPage(self.services, Session(self.admin), self.folder / "ombor.db")
        self.assertFalse(hasattr(page, "_server_url"))
