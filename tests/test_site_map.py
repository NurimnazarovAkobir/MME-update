"""Obyektlarning joylashuvi: koordinatani o'qish, internetsiz xarita va Google Maps'da ochish."""

import unittest
from unittest import mock

from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtTest import QTest

from ombor.errors import WarehouseError
from ombor.geo import Location, maps_url, parse_location
from ombor.models import Site
from ombor.session import Session
from ombor.ui import sites_page
from ombor.ui.site_dialogs import SiteDialog
from ombor.ui.site_map import MapPoint, SiteMap
from ombor.ui.sites_page import SitesPage
from tests.test_ui import UiTestCase

CHILONZOR = Location(41.2756, 69.2034)
QIBRAY = Location(41.3890, 69.4650)


class LocationTests(unittest.TestCase):
    def test_coordinates_are_read_from_text_and_map_links(self):
        place = Location(41.2995, 69.2401)
        for text in (
            "41.2995, 69.2401",
            "  41.2995 69.2401 ",
            "https://www.google.com/maps/place/X/@41.3111,69.2797,17z/data=!3m1!4b1!8m2!3d41.2995!4d69.2401",
            "https://maps.google.com/?q=41.2995,69.2401",
            "https://www.google.com/maps/@41.2995,69.2401,15z",
            "https://yandex.uz/maps/?ll=69.2401%2C41.2995&z=12",  # Yandexda avval uzunlik
        ):
            self.assertEqual(parse_location(text), place, text)
        self.assertIsNone(parse_location("   "))

    def test_unreadable_location_is_refused(self):
        for text in ("https://maps.app.goo.gl/AbCd123", "Chilonzor 5-mavze", "141.5, 69.2"):
            with self.assertRaises(WarehouseError, msg=text):
                parse_location(text)

    def test_maps_link_uses_coordinates_or_the_address(self):
        self.assertTrue(maps_url(CHILONZOR).endswith("query=41.2756,69.2034"))
        self.assertTrue(maps_url(None, "Toshkent, Chilonzor 5").endswith("query=Toshkent%2C+Chilonzor+5"))
        self.assertIsNone(maps_url(None, "  "))

    def test_offset_is_measured_in_kilometres(self):
        east, north = QIBRAY.offset_km(CHILONZOR)
        self.assertAlmostEqual(north, 12.6, delta=0.2)
        self.assertAlmostEqual(east, 21.9, delta=0.3)


class SiteMapTests(UiTestCase):
    def setUp(self):
        super().setUp()
        self.sites = self.services.sites
        self.chilonzor = self.sites.save(
            Site("Chilonzor", "5-mavze", latitude=CHILONZOR.latitude, longitude=CHILONZOR.longitude)
        )
        self.qibray = self.sites.save(Site("Qibray", latitude=QIBRAY.latitude, longitude=QIBRAY.longitude))
        self.unplaced = self.sites.save(Site("Olmazor", "Olmazor tumani"))

    def page(self) -> SitesPage:
        page = SitesPage(self.sites, Session(self.admin))
        page.resize(1000, 600)
        page.refresh()
        return page

    def test_location_is_saved_with_the_site(self):
        self.assertEqual(self.sites.get(self.chilonzor).location, CHILONZOR)
        self.assertIsNone(self.sites.get(self.unplaced).location)
        self.assertEqual(self.sites.all("Qibray")[0].location, QIBRAY)

    def test_site_dialog_reads_the_location_and_refuses_nonsense(self):
        dialog = SiteDialog(self.sites, self.sites.get(self.unplaced))
        dialog._location.setText("https://maps.google.com/?q=41.3275,69.2298")
        dialog.save()
        self.assertEqual(self.sites.get(self.unplaced).location, Location(41.3275, 69.2298))
        again = SiteDialog(self.sites, self.sites.get(self.unplaced))
        self.assertEqual(again._location.text(), "41.327500, 69.229800")
        again._location.setText("qayerdadir")
        with self.assertRaises(WarehouseError):
            again.save()
        again._location.clear()
        again.save()  # bo'sh qoldirilsa, joylashuv olib tashlanadi
        self.assertIsNone(self.sites.get(self.unplaced).location)

    def test_map_draws_placed_sites_with_north_up(self):
        site_map = SiteMap()
        site_map.resize(400, 300)
        site_map.set_points(
            [MapPoint(self.chilonzor, "Chilonzor", CHILONZOR), MapPoint(self.qibray, "Qibray", QIBRAY)]
        )
        site_map.grab()
        south_west, north_east = site_map._positions[self.chilonzor], site_map._positions[self.qibray]
        self.assertLess(south_west.x(), north_east.x())
        self.assertGreater(south_west.y(), north_east.y())
        self.assertTrue(all(0 < p.x() < 400 and 0 < p.y() < 300 for p in (south_west, north_east)))
        self.assertIsNone(site_map.point_at(QPointF(5, 150)))
        SiteMap().grab()  # bo'sh xarita ham xatosiz chiziladi

    def test_map_and_table_select_each_other(self):
        page = self.page()
        self.assertEqual([point.id for point in page._map._points], [self.chilonzor, self.qibray])
        page.table.select_id(self.qibray)
        self.assertEqual(page._map._selected_id, self.qibray)
        page._map.selected.emit(self.chilonzor)
        self.assertEqual(page.table.selected_id(), self.chilonzor)

    def test_clicking_a_pin_selects_the_site(self):
        site_map = SiteMap()
        site_map.resize(400, 300)
        site_map.set_points([MapPoint(self.chilonzor, "Chilonzor", CHILONZOR)])
        site_map.grab()
        chosen = []
        site_map.selected.connect(chosen.append)
        tip = site_map._positions[self.chilonzor]
        head = QPoint(round(tip.x()), round(tip.y()) - 14)
        self.assertEqual(site_map.point_at(QPointF(head)).id, self.chilonzor)
        QTest.mouseClick(site_map, Qt.MouseButton.LeftButton, pos=head)
        self.assertEqual(chosen, [self.chilonzor])
        site_map.grab()  # tanlangan belgi ham xatosiz chiziladi

    def test_address_columns_give_way_to_the_map(self):
        page = self.page()
        address_column = 2  # «Amallar»dan keyingi ikkinchi ustun
        self.assertTrue(page.table.isColumnHidden(address_column))
        page._show_map.setChecked(False)
        self.assertTrue(page._map_panel.isHidden())
        self.assertFalse(page.table.isColumnHidden(address_column))

    def test_site_opens_in_google_maps_by_coordinates_or_address(self):
        page = self.page()
        with mock.patch.object(sites_page.QDesktopServices, "openUrl") as opened:
            page._open_in_maps(self.chilonzor)
            page._open_in_maps(self.unplaced)
        urls = [call.args[0].toString() for call in opened.call_args_list]
        self.assertTrue(urls[0].endswith("query=41.2756,69.2034"))
        self.assertIn("Olmazor", urls[1])
        with (
            mock.patch.object(sites_page.QDesktopServices, "openUrl") as opened,
            mock.patch.object(sites_page.QMessageBox, "information") as told,
        ):
            page._open_in_maps(self.qibray)
            page._open_in_maps(self.sites.save(Site("Manzilsiz")))
        self.assertEqual((opened.call_count, told.call_count), (1, 1))
