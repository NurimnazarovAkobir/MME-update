"""Interfeys: rahbar bazani Google Drive papkasiga qo'yadi, boshqa noutbukda omborchi o'z hisobi bilan kiradi."""

import tempfile
from pathlib import Path
from unittest import mock

from PySide6.QtWidgets import QPushButton

from ombor.auth import Auth
from ombor.backup import Backup
from ombor.database import connect
from ombor.folder_sync import FOLDER_KEY, FolderSynchronizer, shared_folder
from ombor.local import LocalPrefs
from ombor.models import Product, Role
from ombor.ui import shared_folder as dialogs
from ombor.ui.auth_dialogs import LoginDialog, SetupDialog
from ombor.ui.sync_controller import synchronizer_factory
from ombor.warehouse import Warehouse
from tests.test_ui import UiTestCase


def choose(folder: Path):
    """Papka tanlash oynasi va tasdiqlarni avtomatik javob bilan almashtiradi."""
    return (
        mock.patch.object(dialogs.QFileDialog, "getExistingDirectory", return_value=str(folder)),
        mock.patch.object(dialogs.QMessageBox, "information"),
        mock.patch.object(dialogs.QMessageBox, "warning"),
        mock.patch.object(dialogs, "confirm", return_value=True),
        mock.patch.object(dialogs, "restart_application"),
    )


class SharedFolderUiTests(UiTestCase):
    def setUp(self):
        super().setUp()
        drive = tempfile.TemporaryDirectory()
        self.addCleanup(drive.cleanup)
        self.drive = Path(drive.name)
        self.boss_prefs = LocalPrefs(self.folder / "rahbar.json")
        self.warehouse.save_product(Product("Sement", "kg"))

    def publish_from_boss(self) -> None:
        patches = choose(self.drive)
        with patches[0], patches[1], patches[2], patches[3], patches[4]:
            self.assertTrue(dialogs.connect_folder(None, self.conn, self.boss_prefs, self.services.backup))

    def test_keeper_logs_in_with_own_password_on_a_fresh_laptop(self):
        self.publish_from_boss()
        self.assertIsNotNone(shared_folder(self.boss_prefs))

        # Safoning noutbuki: dastur birinchi marta ochildi — baza bo'sh, kirish oynasi «yangi baza» so'raydi.
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        prefs = LocalPrefs(self.folder / "safo.json")
        auth = Auth(conn)
        joined = []
        setup = SetupDialog(auth, prefs, lambda parent: joined.append(True))
        self.assertIn("Google Drive'dagi bazaga ulanish", [b.text() for b in setup.findChildren(QPushButton)])

        patches = choose(self.drive)
        with patches[0], patches[1], patches[2], patches[3], patches[4] as restart:
            self.assertTrue(dialogs.join_folder(None, conn, prefs, Backup(conn, self.folder / "safo-zaxira")))
        restart.assert_called_once()
        self.assertEqual(prefs.get(FOLDER_KEY), str(self.drive))

        # Dastur qayta ochilganda — kirish oynasida rahbar ochgan hamma hisoblar bor.
        login = LoginDialog(auth, prefs)
        names = [login._users.itemText(i) for i in range(login._users.count())]
        self.assertEqual(names, ["Hisobchi (Kuzatuvchi)", "Rahbar (Rahbar)", "Vali (Omborchi)"])
        vali = next(user for user in auth.users() if user.name == "Vali")
        self.assertEqual(auth.login(vali.id, "parol-2").role, Role.KEEPER)
        self.assertEqual([p.name for p in Warehouse(conn).products()], ["List 2mm", "Sement", "Truba 40x40"])

    def test_empty_folder_cannot_be_joined(self):
        conn = connect(":memory:")
        self.addCleanup(conn.close)
        patches = choose(self.drive)
        with patches[0], patches[1], patches[2] as warning, patches[3], patches[4]:
            self.assertFalse(dialogs.join_folder(None, conn, LocalPrefs(), None))
        warning.assert_called_once()

    def test_background_sync_uses_the_folder(self):
        self.publish_from_boss()
        factory = synchronizer_factory(self.boss_prefs)
        self.assertIsInstance(factory(self.conn), FolderSynchronizer)
        self.assertIsNone(synchronizer_factory(LocalPrefs()))
