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

from PySide6.QtWidgets import QApplication, QMessageBox, QWidget  # noqa: E402

from ombor import update  # noqa: E402
from ombor.errors import WarehouseError  # noqa: E402
from ombor.ui import updater as updater_module  # noqa: E402
from ombor.ui.updater import OnlineUpdater  # noqa: E402
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


class OnlineUpdaterTests(OnlineTestCase):
    """Fon tekshiruvi → taklif → yuklab olish → o'rnatish zanjiri (o'rnatishning o'zi almashtirilgan)."""

    def setUp(self):
        super().setUp()
        self.app = QApplication.instance() or QApplication([])
        self.addCleanup(discard_widgets)
        self.parent = QWidget()

    def _wait(self, condition, seconds: float = 15) -> bool:
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.app.processEvents()
            if condition():
                return True
            time.sleep(0.02)
        return False

    def test_found_update_is_downloaded_and_installed(self):
        self.publish("99.0")
        with (
            mock.patch.object(updater_module, "confirm", return_value=True) as question,
            mock.patch.object(updater_module.update, "install") as install,
            mock.patch.object(updater_module, "restart_application") as restart,
            mock.patch.object(QMessageBox, "information"),
            mock.patch.object(updater_module.tempfile, "gettempdir", return_value=str(self.folder)),
        ):
            OnlineUpdater(self.url, self.parent).check()
            self.assertTrue(self._wait(lambda: restart.called))
        self.assertIn("99.0", question.call_args.args[2])
        downloaded = Path(install.call_args.args[0])
        self.assertEqual(downloaded.read_bytes(), NEW_EXE)

    def test_declined_update_downloads_nothing(self):
        self.publish("99.0")
        with (
            mock.patch.object(updater_module, "confirm", return_value=False) as question,
            mock.patch.object(updater_module.update, "download") as download,
        ):
            OnlineUpdater(self.url, self.parent).check()
            self.assertTrue(self._wait(lambda: question.called))
            self._wait(lambda: False, seconds=0.3)
        download.assert_not_called()

    def test_no_internet_only_reports_nothing_found(self):
        updater = OnlineUpdater(self.dead_url(), self.parent)
        outcome = []
        updater.nothing_found.connect(lambda: outcome.append("yo'q"))
        updater.found.connect(outcome.append)
        with mock.patch.object(updater_module, "confirm") as question:
            updater.check()
            self.assertTrue(self._wait(lambda: outcome))
        self.assertEqual(outcome, ["yo'q"])
        question.assert_not_called()

    def test_broken_download_shows_a_message_and_keeps_the_program(self):
        self.publish("99.0", exe=b"buzilgan")
        with (
            mock.patch.object(updater_module, "confirm", return_value=True),
            mock.patch.object(updater_module.update, "install") as install,
            mock.patch.object(QMessageBox, "warning") as warning,
            mock.patch.object(updater_module.tempfile, "gettempdir", return_value=str(self.folder)),
        ):
            OnlineUpdater(self.url, self.parent).check()
            self.assertTrue(self._wait(lambda: warning.called))
        install.assert_not_called()


if __name__ == "__main__":
    unittest.main()
