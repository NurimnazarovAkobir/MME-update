"""Internet orqali yangilash testlari: shu kompyuterning o'zida ochilgan kichik veb-server bilan."""

import functools
import http.server
import os
import socket
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton  # noqa: E402

from ombor import update  # noqa: E402
from ombor.database import connect  # noqa: E402
from ombor.errors import WarehouseError  # noqa: E402
from ombor.models import Role, User  # noqa: E402
from ombor.services import Services  # noqa: E402
from ombor.session import Session  # noqa: E402
from ombor.ui import update_page as update_page_module  # noqa: E402
from ombor.ui import updater as updater_module  # noqa: E402
from ombor.ui.main_window import BADGE_ROLE, MainWindow  # noqa: E402
from ombor.ui.update_page import LAST_CHECK_KEY, UpdatePage  # noqa: E402
from tests.test_ui import discard_widgets  # noqa: E402

NEW_EXE = b"MZ" + b"yangi versiya " * 120_000  # ~1.7 MB


class _QuietHandler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *args) -> None:
        pass


class OnlineTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.site = self.folder / "sayt"
        self.site.mkdir()
        handler = functools.partial(_QuietHandler, directory=str(self.site))
        self.server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}/"

    def publish(self, version: str, exe: bytes = NEW_EXE) -> None:
        (self.site / update.VERSION_FILE).write_text(version + "\n", encoding="utf-8")
        (self.site / update.EXE_NAME).write_bytes(exe)

    @staticmethod
    def dead_url() -> str:
        """Hech kim tinglamayotgan manzil — internet yo'qligi kabi."""
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            return f"http://127.0.0.1:{probe.getsockname()[1]}/"


class OnlineCheckTests(OnlineTestCase):
    def test_newer_version_is_found(self):
        self.publish("1.10")
        self.assertEqual(update.available_online(self.url, "1.3"), "1.10")
        self.assertEqual(update.available_online(self.url.rstrip("/"), "1.3"), "1.10")

    def test_same_or_older_version_is_ignored(self):
        self.publish("1.3")
        self.assertIsNone(update.available_online(self.url, "1.3"))
        self.assertIsNone(update.available_online(self.url, "2.0"))

    def test_no_internet_means_no_update_and_no_error(self):
        started = time.monotonic()
        self.assertIsNone(update.available_online(self.dead_url(), "1.3"))
        self.assertLess(time.monotonic() - started, update.CHECK_TIMEOUT_SECONDS + 2)

    def test_missing_or_garbage_version_file_is_ignored(self):
        self.assertIsNone(update.available_online(self.url, "1.3"))  # fayl yo'q (404)
        (self.site / update.VERSION_FILE).write_text("<html>xato</html>", encoding="utf-8")
        self.assertIsNone(update.available_online(self.url, "1.3"))
        self.assertIsNone(update.available_online("", "1.3"))

    def test_only_https_addresses_can_be_saved(self):
        self.assertEqual(update.check_url(" https://example.com/ombor/ "), "https://example.com/ombor/")
        self.assertEqual(update.check_url(""), "")
        with self.assertRaises(WarehouseError):
            update.check_url("http://example.com/ombor/")
        self.assertEqual(update.update_url(" https://a.b/ "), "https://a.b/")


class DownloadTests(OnlineTestCase):
    def test_download_reports_progress_and_saves_the_file(self):
        self.publish("1.10")
        seen = []
        target = update.download(self.url, self.folder / "yangi.exe", lambda done, total: seen.append((done, total)))
        self.assertEqual(target.read_bytes(), NEW_EXE)
        self.assertEqual(seen[-1], (len(NEW_EXE), len(NEW_EXE)))
        self.assertFalse((self.folder / "yangi.qism").exists())

    def test_file_that_is_not_a_program_is_rejected(self):
        self.publish("1.10", exe=b"<html>topilmadi</html>")
        with self.assertRaises(WarehouseError):
            update.download(self.url, self.folder / "yangi.exe")
        self.assertEqual(sorted(path.name for path in self.folder.iterdir()), ["sayt"])

    def test_download_without_internet_fails_cleanly(self):
        with self.assertRaises(WarehouseError):
            update.download(self.dead_url(), self.folder / "yangi.exe")
        self.assertFalse((self.folder / "yangi.exe").exists())


class UpdatePageTests(OnlineTestCase):
    """«Yangilash» sahifasi: tekshiruv → menyuda belgi va taklif → yuklab olish → o'rnatish."""

    def setUp(self):
        super().setUp()
        self.app = QApplication.instance() or QApplication([])
        self.addCleanup(discard_widgets)
        self.conn = connect(":memory:")
        self.addCleanup(self.conn.close)
        self.services = Services.create(self.conn, self.folder / "zaxira")
        self.admin = Session(User(1, "Rahbar", Role.ADMIN))
        self.keeper = Session(User(2, "Vali", Role.KEEPER))

    def page(self, session=None, url=None) -> UpdatePage:
        self.services.settings.set(update.UPDATE_URL_KEY, self.url if url is None else url)
        page = UpdatePage(self.services, session or self.admin)
        self.states = []
        page.availability_changed.connect(self.states.append)
        return page

    def _wait(self, condition, seconds: float = 15) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.02)
        return False

    def test_up_to_date_state(self):
        self.publish(update.APP_VERSION)
        page = self.page()
        self.assertIn("hali tekshirilmagan", page._status_detail.text())
        page.check()
        self.assertTrue(self._wait(lambda: page._check_button.isEnabled()))
        self.assertEqual(page._status_title.text(), "Dastur yangilangan")
        self.assertIn("bugun", page._status_detail.text())
        self.assertTrue(page._offer_card.isHidden())
        self.assertEqual(self.states, [])
        self.assertTrue(self.services.prefs.get(LAST_CHECK_KEY))

    def test_new_version_shows_the_offer_and_the_menu_badge(self):
        self.publish("99.0")
        page = self.page()
        page.check()
        self.assertTrue(self._wait(lambda: self.states))
        self.assertEqual(self.states, [True])
        self.assertEqual(page._status_title.text(), "Yangilanish mavjud")
        self.assertFalse(page._offer_card.isHidden())
        self.assertIn("99.0", page._offer_text.text())

    def test_download_and_install_from_the_offer(self):
        self.publish("99.0")
        page = self.page()
        page.check()
        self.assertTrue(self._wait(lambda: self.states))
        with (
            mock.patch.object(update_page_module.update, "is_installed_program", return_value=True),
            mock.patch.object(updater_module.update, "install") as install,
            mock.patch.object(update_page_module, "restart_application") as restart,
            mock.patch.object(QMessageBox, "information"),
            mock.patch.object(updater_module.tempfile, "gettempdir", return_value=str(self.folder)),
        ):
            page._install_link.click()
            self.assertFalse(page._install_link.isEnabled())
            self.assertTrue(self._wait(lambda: restart.called))
        self.assertEqual(Path(install.call_args.args[0]).read_bytes(), NEW_EXE)

    def test_broken_download_reports_and_lets_the_user_retry(self):
        self.publish("99.0", exe=b"buzilgan")
        page = self.page()
        page.check()
        self.assertTrue(self._wait(lambda: self.states))
        with (
            mock.patch.object(update_page_module.update, "is_installed_program", return_value=True),
            mock.patch.object(updater_module.update, "install") as install,
            mock.patch.object(QMessageBox, "warning") as warning,
            mock.patch.object(updater_module.tempfile, "gettempdir", return_value=str(self.folder)),
        ):
            page._install_link.click()
            self.assertTrue(self._wait(lambda: warning.called))
        install.assert_not_called()
        self.assertTrue(page._install_link.isEnabled())
        self.assertTrue(page._progress.isHidden())

    def test_no_internet_is_silent_unless_the_user_asked(self):
        page = self.page(url=self.dead_url())
        with mock.patch.object(QMessageBox, "information") as information:
            page.check()
            self.assertTrue(self._wait(lambda: page._check_button.isEnabled()))
            information.assert_not_called()
            page._check_button.click()
            self.assertTrue(self._wait(lambda: information.called))
        self.assertEqual(page._status_title.text(), "Dastur yangilangan")
        self.assertEqual(self.states, [])

    def test_opening_the_page_or_returning_to_the_window_rechecks_but_not_too_often(self):
        self.publish(update.APP_VERSION)
        page = self.page()
        with mock.patch.object(page, "check") as check:
            page.refresh()  # sahifa hozirgina yaratilgan — hali erta
            check.assert_not_called()
            page._last_check -= update_page_module.MIN_SECONDS_BETWEEN_CHECKS + 1
            page.refresh()
            check.assert_called_once()
            page._last_check -= update_page_module.MIN_SECONDS_BETWEEN_CHECKS + 1
            page.check_if_stale()
            self.assertEqual(check.call_count, 2)

    def test_new_release_is_noticed_without_pressing_the_button(self):
        self.publish(update.APP_VERSION)
        page = self.page()
        page.check()
        self.assertTrue(self._wait(lambda: page._check_button.isEnabled()))
        self.assertEqual(self.states, [])
        self.publish("99.0")  # dastur ochiq turganda yangi versiya chiqdi
        page._last_check -= update_page_module.MIN_SECONDS_BETWEEN_CHECKS + 1
        page.check_if_stale()  # oynaga qaytish yoki taymer
        self.assertTrue(self._wait(lambda: self.states == [True]))
        self.assertLessEqual(update_page_module.RECHECK_INTERVAL_MS, 5 * 60 * 1000)

    def test_update_folder_is_checked_before_the_internet(self):
        folder = self.folder / "papka"
        folder.mkdir()
        (folder / update.VERSION_FILE).write_text("50.0", encoding="utf-8")
        (folder / update.EXE_NAME).write_bytes(NEW_EXE)
        self.publish("99.0")
        offer = update.find(str(folder), self.url)
        self.assertEqual((offer.version, offer.exe), ("50.0", folder / update.EXE_NAME))
        self.assertEqual(update.find("", self.url).url, self.url)
        self.assertIsNone(update.find("", ""))
        self.assertIsNone(update.find(str(self.folder / "yoq"), self.dead_url()))

    def test_only_admin_sees_the_sources(self):
        admin = [b.text() for b in self.page(self.admin).findChildren(QPushButton)]
        keeper = [b.text() for b in self.page(self.keeper).findChildren(QPushButton)]
        self.assertIn("Internet manzilini kiritish", admin)
        self.assertNotIn("Internet manzilini kiritish", keeper)
        self.assertIn("Yangilanishlarni tekshirish", keeper)

    def test_main_window_marks_the_menu_item(self):
        self.publish("99.0")
        self.services.settings.set(update.UPDATE_URL_KEY, self.url)
        window = MainWindow(self.services, self.admin, self.folder / "ombor.db")
        row = window._update_row
        self.assertIsNone(window._menu.item(row).data(BADGE_ROLE))
        window._pages.widget(row).check()
        self.assertTrue(window._notice.isHidden())
        # Menyuda «Yangilash» yonida qizil doirada «1» paydo bo'ladi — foydalanuvchi o'zi tekshirishi shart emas.
        self.assertTrue(self._wait(lambda: window._menu.item(row).data(BADGE_ROLE) == 1))
        self.assertEqual(window._menu.item(row).text().strip(), "Yangilash")
        window._menu.viewport().grab()  # belgi chizilishi xatosiz o'tadi
        # Qaysi bo'lim ochiq bo'lmasin, sahifalar ustida «yangilang» degan yo'lak ko'rinadi.
        self.assertFalse(window._notice.isHidden())
        self.assertIn("99.0", window._notice_text.text())
        self.assertEqual(window._announced_version, "99.0")
        window._open_update_page()
        self.assertEqual(window._menu.currentRow(), row)
        # Tepadagi «Yangilash» tugmasi bo'limni ochibgina qolmay, o'rnatishni o'zi boshlaydi.
        window._menu.setCurrentRow(0)
        with (
            mock.patch.object(update_page_module.update, "is_installed_program", return_value=True),
            mock.patch.object(updater_module.update, "install") as install,
            mock.patch.object(update_page_module, "restart_application") as restart,
            mock.patch.object(QMessageBox, "information"),
            mock.patch.object(updater_module.tempfile, "gettempdir", return_value=str(self.folder)),
        ):
            window._update_now()
            self.assertEqual(window._menu.currentRow(), row)
            self.assertTrue(window._notice.isHidden())
            self.assertTrue(self._wait(lambda: restart.called))
        install.assert_called_once()


if __name__ == "__main__":
    unittest.main()
