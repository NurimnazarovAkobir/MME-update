"""Dasturning ishga tushish yo'li: oddiy va shifrlangan baza bilan, ekransiz rejimda."""

import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402

from ombor import app as application  # noqa: E402
from ombor.auth import Auth  # noqa: E402
from ombor.database import connect  # noqa: E402
from ombor.migrations import SCHEMA_VERSION  # noqa: E402
from ombor.models import Role  # noqa: E402
from ombor.paths import read_prefs  # noqa: E402
from ombor.vault import Vault  # noqa: E402
from tests.test_ui import discard_widgets  # noqa: E402

PASSWORD = "temir2026"


class StartupTests(unittest.TestCase):
    def setUp(self):
        QApplication.instance() or QApplication([])
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.db_path = self.folder / "baza" / "ombor.db"
        self.windows = []
        self.addCleanup(discard_widgets)
        # run() kutilmagan xatolar uchun oyna ko'rsatadigan ishlovchini o'rnatadi; testlardan keyin asl holiga qaytadi.
        self.addCleanup(setattr, sys, "excepthook", sys.excepthook)
        patches = (
            mock.patch.object(application, "DB_PATH", self.db_path),
            mock.patch.object(application, "BACKUP_DIR", self.folder / "zaxira"),
            mock.patch.object(application, "PREFS_PATH", self.folder / "sozlama.json"),
            mock.patch.object(QApplication, "exec", return_value=0),
            mock.patch.object(application.MainWindow, "showMaximized", lambda window: self.windows.append(window)),
        )
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)

    def _run(self, sign_in) -> int:
        with mock.patch.object(application, "sign_in", sign_in):
            return application.run()

    @staticmethod
    def _first_run(auth, prefs, join_shared=None):
        return auth.add_user("Rahbar", PASSWORD, Role.ADMIN)

    @staticmethod
    def _login(auth, prefs, join_shared=None):
        (admin,) = [user for user in auth.users() if user.is_admin]
        return auth.login(admin.id, PASSWORD)

    def test_first_run_creates_the_database_and_a_backup(self):
        self.assertEqual(self._run(self._first_run), 0)
        self.assertTrue(self.db_path.is_file())
        self.assertEqual(len(list((self.folder / "zaxira").glob("ombor-*.db"))), 1)
        self.assertEqual(read_prefs(self.folder / "sozlama.json")["language"], "uz")
        self.assertEqual(len(self.windows), 1)
        self.assertEqual(self._run(self._login), 0)

    def test_closing_the_login_window_exits_quietly(self):
        self.assertEqual(self._run(lambda auth, prefs, join_shared=None: None), 0)
        self.assertEqual(self.windows, [])

    def test_encrypted_database_opens_after_the_password(self):
        self._run(self._first_run)
        conn = connect(self.db_path)
        auth = Auth(conn)
        (admin,) = auth.users()
        Vault(self.db_path).encrypt(conn, admin, PASSWORD, auth.new_recovery_code())

        self.assertEqual(self._run(self._login), 0)
        self.assertEqual(len(self.windows), 2)
        self.assertTrue(self.windows[-1]._session.is_admin)
        backups = sorted((self.folder / "zaxira").glob("ombor-*.db"))
        self.assertNotIn(b"SQLite format 3", backups[-1].read_bytes()[:32])
        self.assertTrue(backups[-1].with_suffix(".kalit").is_file())

    def test_wrong_password_on_encrypted_database_never_opens_a_window(self):
        self._run(self._first_run)
        conn = connect(self.db_path)
        auth = Auth(conn)
        (admin,) = auth.users()
        Vault(self.db_path).encrypt(conn, admin, PASSWORD, auth.new_recovery_code())
        self.windows.clear()

        def give_up(auth, prefs, join_shared=None):
            with self.assertRaises(application.WarehouseError):
                auth.login(admin.id, "xato-parol")
            return None

        self.assertEqual(self._run(give_up), 0)
        self.assertEqual(self.windows, [])

    def test_database_from_a_newer_program_is_reported(self):
        self._run(self._first_run)
        conn = connect(self.db_path)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        conn.commit()
        conn.close()
        with mock.patch.object(QMessageBox, "critical") as critical:
            self.assertEqual(self._run(self._login), 1)
        critical.assert_called_once()

    def test_unreachable_shared_folder_is_reported(self):
        (self.folder / "baza").write_text("papka emas")
        with mock.patch.object(application, "_report_unreachable") as report:
            self.assertEqual(self._run(self._first_run), 1)
        report.assert_called_once()


if __name__ == "__main__":
    unittest.main()
