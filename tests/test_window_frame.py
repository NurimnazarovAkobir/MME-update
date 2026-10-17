"""Telegram'dagi kabi oyna ramkasi va «Exceldan yuklash» tugmasining joyi."""

from PySide6.QtCore import Qt

from ombor.session import Session
from ombor.ui.lock_screen import LockScreen
from ombor.ui.products_page import ProductsPage
from ombor.ui.window_frame import MAXIMIZE, RESTORE, set_system_frame
from tests.test_ui import UiTestCase


class WindowFrameTests(UiTestCase):
    def test_own_title_bar_by_default(self):
        window = self.window(self.admin)
        self.assertTrue(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertIsNotNone(window._frame)

    def test_maximize_button_toggles_and_shows_restore(self):
        window = self.window(self.admin)
        window.show()
        title_bar = window._frame.title_bar
        title_bar.toggle_maximized()
        self.assertTrue(window.isMaximized())
        self.assertEqual(title_bar._maximize.text(), RESTORE)
        title_bar.toggle_maximized()
        self.assertEqual(title_bar._maximize.text(), MAXIMIZE)

    def test_system_frame_setting(self):
        set_system_frame(self.services.prefs, True)
        window = self.window(self.admin)
        self.assertFalse(window.windowFlags() & Qt.WindowType.FramelessWindowHint)
        self.assertIsNone(window._frame)

    def test_lock_screen_follows_the_window_frame(self):
        window = self.window(self.admin)
        screen = LockScreen(self.services.auth, self.admin, 5, window)
        self.assertTrue(screen.windowFlags() & Qt.WindowType.FramelessWindowHint)


class ExcelButtonTests(UiTestCase):
    def test_import_button_is_next_to_new_product(self):
        page = ProductsPage(
            self.warehouse, self.services.sites, Session(self.admin), self.services.importer, self.services.backup
        )
        first = page.toolbar_tools.itemAt(0).widget()
        self.assertEqual(first.text(), "Exceldan yuklash")
        self.assertEqual(first.property("role"), "excel")

    def test_viewer_has_no_import_button(self):
        page = ProductsPage(
            self.warehouse, self.services.sites, Session(self.viewer), self.services.importer, self.services.backup
        )
        texts = [page.toolbar_tools.itemAt(i).widget().text() for i in range(page.toolbar_tools.count())]
        self.assertNotIn("Exceldan yuklash", texts)


class SidebarCollapseTests(UiTestCase):
    def test_collapse_keeps_icons_hides_texts_and_is_remembered(self):
        window = self.window(self.admin)
        window._sidebar_toggle.click()
        self.assertTrue(window._sidebar_collapsed)
        self.assertEqual(window._sidebar_panel.width(), 80)
        first = window._menu.item(0)
        self.assertEqual(first.text(), "")
        self.assertFalse(first.icon().isNull())
        self.assertEqual(first.toolTip(), "Bosh sahifa")
        self.assertTrue(window._brand_texts.isHidden())
        self.assertEqual(self.services.prefs.get("sidebar_collapsed"), "1")
        again = self.window(self.admin)  # keyingi ochilishda ham yig'iq
        self.assertTrue(again._sidebar_collapsed)
        again._sidebar_toggle.click()
        self.assertEqual(again._menu.item(0).text().strip(), "Bosh sahifa")
        self.assertFalse(again._brand_texts.isHidden())
