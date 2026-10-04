"""Shifrlash, tarmoq (umumiy baza), shaxsiy sozlamalar va yangilash testlari."""

import sqlite3 as plain_sqlite
import tempfile
import unittest
from datetime import date
from pathlib import Path

from ombor import update
from ombor.auth import Auth, LockedAuth
from ombor.backup import Backup
from ombor.database import NewerDatabaseError, connect
from ombor.driver import sqlite3
from ombor.errors import WarehouseError
from ombor.local import LocalPrefs
from ombor.migrations import SCHEMA_VERSION
from ombor.models import Movement, MovementKind, Product, Role
from ombor.vault import Vault
from ombor.warehouse import Warehouse

TODAY = date(2026, 10, 3)


class FolderTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.path = self.folder / "ombor.db"

    def open(self, key=None):
        conn = connect(self.path, key)
        self.addCleanup(conn.close)
        return conn


class EncryptionTests(FolderTestCase):
    def setUp(self):
        super().setUp()
        conn = connect(self.path)
        auth = Auth(conn)
        self.admin = auth.add_user("Rahbar", "temir2026", Role.ADMIN)
        self.keeper = auth.add_user("Vali", "vali2026", Role.KEEPER)
        warehouse = Warehouse(conn, today=lambda: TODAY)
        self.pipe = warehouse.save_product(Product("Truba", "metr"))
        warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 10, 1000))
        self.vault = Vault(self.path)
        self.assertFalse(self.vault.enabled)
        self.code = auth.new_recovery_code()
        self.vault.encrypt(conn, self.admin, "temir2026", self.code)

    def locked(self, vault=None) -> LockedAuth:
        vault = vault or Vault(self.path)
        return LockedAuth(vault, lambda key: self.open(key))

    def test_file_is_unreadable_without_the_key(self):
        self.assertTrue(self.vault.enabled)
        self.assertNotIn(b"SQLite format 3", self.path.read_bytes()[:32])
        self.assertNotIn(b"Truba", self.path.read_bytes())
        outsider = plain_sqlite.connect(self.path)
        self.addCleanup(outsider.close)
        with self.assertRaises(plain_sqlite.DatabaseError):
            outsider.execute("SELECT * FROM products").fetchall()
        self.assertNotIn(self.vault.key, self.vault.path.read_text(encoding="utf-8"))

    def test_admin_signs_in_and_data_is_intact(self):
        locked = self.locked()
        self.assertEqual([user.name for user in locked.users()], ["Rahbar"])
        user = locked.login(self.admin.id, "temir2026")
        self.assertTrue(user.is_admin)
        self.assertEqual(Warehouse(locked.conn).product(self.pipe).stock, 10)
        self.assertEqual(locked.conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)

    def test_wrong_password_does_not_open_the_database(self):
        locked = self.locked()
        with self.assertRaises(WarehouseError):
            locked.login(self.admin.id, "xato-parol")
        self.assertIsNone(locked.conn)
        with self.assertRaises(WarehouseError):
            locked.login(self.keeper.id, "vali2026")  # unga kalit hali berilmagan

    def test_other_users_get_access_when_admin_resets_their_password(self):
        vault = Vault(self.path)
        locked = self.locked(vault)
        locked.login(self.admin.id, "temir2026")
        auth = Auth(locked.conn, vault)
        auth.set_password(self.keeper.id, "yangi-parol")
        viewer = auth.add_user("Hisobchi", "hisob2026", Role.VIEWER)
        self.assertEqual([user.name for user in Vault(self.path).users()], ["Hisobchi", "Rahbar", "Vali"])
        self.assertEqual(self.locked().login(self.keeper.id, "yangi-parol").name, "Vali")
        self.assertEqual(self.locked().login(viewer.id, "hisob2026").role, Role.VIEWER)

        auth.change_password(self.admin.id, "temir2026", "boshqa-parol")
        with self.assertRaises(WarehouseError):
            self.locked().login(self.admin.id, "temir2026")
        self.locked().login(self.admin.id, "boshqa-parol")
        auth.delete_user(viewer.id)
        self.assertNotIn("Hisobchi", [user.name for user in Vault(self.path).users()])

    def test_recovery_code_restores_access(self):
        locked = self.locked()
        self.assertTrue(locked.has_recovery_code())
        with self.assertRaises(WarehouseError):
            locked.reset_with_recovery_code(self.admin.id, "AAAA-BBBB-CCCC", "yangi-parol")
        locked.reset_with_recovery_code(self.admin.id, self.code.lower(), "yangi-parol")
        self.assertEqual(self.locked().login(self.admin.id, "yangi-parol").name, "Rahbar")

    def test_new_recovery_code_replaces_the_old_one(self):
        vault = Vault(self.path)
        locked = self.locked(vault)
        locked.login(self.admin.id, "temir2026")
        new_code = locked.new_recovery_code()
        with self.assertRaises(WarehouseError):
            Vault(self.path).unlock_with_code(self.code)
        self.assertEqual(Vault(self.path).unlock_with_code(new_code), vault.key)

    def test_backup_is_encrypted_and_restores(self):
        vault = Vault(self.path)
        locked = self.locked(vault)
        locked.login(self.admin.id, "temir2026")
        backup = Backup(locked.conn, self.folder / "auto", vault)
        copy = self.folder / "zaxira.db"
        backup.save_to(copy)
        self.assertNotIn(b"Truba", copy.read_bytes())
        self.assertTrue(copy.with_suffix(".kalit").is_file())

        warehouse = Warehouse(locked.conn, today=lambda: TODAY)
        warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 5, 1000))
        backup.restore_from(copy)
        self.assertEqual(warehouse.product(self.pipe).stock, 10)
        (written,) = backup.run_automatic(TODAY)
        self.assertTrue(written.with_suffix(".kalit").is_file())

    def test_plain_backup_made_before_encryption_can_still_be_restored(self):
        old = self.folder / "eski.db"
        plain = connect(old)
        Warehouse(plain).save_product(Product("Eski mahsulot", "dona"))
        plain.close()
        vault = Vault(self.path)
        locked = self.locked(vault)
        locked.login(self.admin.id, "temir2026")
        Backup(locked.conn, self.folder / "auto", vault).restore_from(old)
        self.assertEqual([p.name for p in Warehouse(locked.conn).products()], ["Eski mahsulot"])
        Auth(locked.conn, vault).login(self.admin.id, "temir2026")  # foydalanuvchilar joyida
        self.assertFalse((self.folder / "eski.db.shifrlangan").exists())

    def test_decrypt_returns_to_a_plain_database(self):
        vault = Vault(self.path)
        locked = self.locked(vault)
        locked.login(self.admin.id, "temir2026")
        vault.decrypt(locked.conn)
        self.assertFalse(vault.enabled)
        conn = self.open()
        self.assertEqual(Warehouse(conn).product(self.pipe).stock, 10)
        Auth(conn).login(self.admin.id, "temir2026")

    def test_missing_key_file_is_reported_clearly(self):
        vault = Vault(self.path)
        text = vault.path.read_text(encoding="utf-8")
        vault.path.write_text("buzilgan", encoding="utf-8")
        with self.assertRaises(WarehouseError):
            vault.users()
        vault.path.write_text(text, encoding="utf-8")
        self.assertEqual(len(vault.users()), 1)


class SharedDatabaseTests(FolderTestCase):
    def test_two_connections_see_each_other_and_stock_is_checked_across_them(self):
        first, second = self.open(), self.open()
        office, site = Warehouse(first, today=lambda: TODAY), Warehouse(second, today=lambda: TODAY)
        pipe = office.save_product(Product("Truba", "metr"))
        version = second.execute("PRAGMA data_version").fetchone()[0]
        office.save_movement(Movement(MovementKind.IN, TODAY, pipe, 10, 1000))
        self.assertNotEqual(second.execute("PRAGMA data_version").fetchone()[0], version)
        site.save_movement(Movement(MovementKind.OUT, TODAY, pipe, 7))
        with self.assertRaises(WarehouseError):
            office.save_movement(Movement(MovementKind.OUT, TODAY, pipe, 7))
        self.assertEqual(office.product(pipe).stock, 3)

    def test_opening_a_current_database_writes_nothing(self):
        first = self.open()
        version = first.execute("PRAGMA data_version").fetchone()[0]
        self.open()
        self.assertEqual(first.execute("PRAGMA data_version").fetchone()[0], version)

    def test_database_from_a_newer_program_is_refused(self):
        conn = self.open()
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION + 1}")
        conn.commit()
        with self.assertRaises(NewerDatabaseError):
            connect(self.path)

    def test_local_prefs_remember_the_shared_folder(self):
        prefs_path = self.folder / "local" / "sozlama.json"
        prefs = LocalPrefs(prefs_path)
        self.assertFalse(prefs.uses_shared_folder)
        self.assertFalse(prefs.has_database(self.folder))
        self.open()
        self.assertTrue(prefs.has_database(self.folder))
        prefs.use_folder(self.folder)
        prefs.set("language", "ru")
        again = LocalPrefs(prefs_path)
        self.assertEqual((again.data_dir, again.uses_shared_folder, again.get("language")), (self.folder, True, "ru"))
        again.use_folder(None)
        self.assertFalse(LocalPrefs(prefs_path).uses_shared_folder)

    def test_prefs_without_a_file_live_in_memory_and_broken_file_is_ignored(self):
        prefs = LocalPrefs()
        prefs.set("theme", "light")
        self.assertEqual(prefs.get("theme"), "light")
        broken = self.folder / "sozlama.json"
        broken.write_text("{buzilgan", encoding="utf-8")
        self.assertEqual(LocalPrefs(broken).get("theme", "dark"), "dark")

    def test_unreachable_folder_raises_an_error_the_app_can_report(self):
        (self.folder / "fayl").write_text("papka emas")
        with self.assertRaises((sqlite3.OperationalError, OSError)):
            connect(self.folder / "fayl" / "ichida" / "ombor.db")


class UpdateTests(FolderTestCase):
    def setUp(self):
        super().setUp()
        self.updates = self.folder / "yangilanish"
        self.updates.mkdir()
        self.current = self.folder / "dastur" / "MME-Ombor.exe"
        self.current.parent.mkdir()
        self.current.write_bytes(b"eski versiya")

    def _publish(self, version: str, content: bytes = b"yangi versiya"):
        (self.updates / update.VERSION_FILE).write_text(version, encoding="utf-8")
        (self.updates / update.EXE_NAME).write_bytes(content)

    def test_versions_are_compared_as_numbers(self):
        self.assertLess(update.parse_version("1.9"), update.parse_version("1.10"))
        self.assertEqual(update.parse_version(" 2.0\n"), (2, 0))
        self.assertEqual(update.parse_version("beta"), ())

    def test_only_a_newer_version_is_offered(self):
        self.assertIsNone(update.available(self.updates, "1.2"))  # papka bo'sh
        self._publish("1.2")
        self.assertIsNone(update.available(self.updates, "1.2"))
        self._publish("1.10")
        self.assertEqual(update.available(self.updates, "1.2"), ("1.10", self.updates / update.EXE_NAME))
        self.assertIsNone(update.available(self.folder / "yoq-papka", "1.2"))
        (self.updates / update.EXE_NAME).unlink()
        self.assertIsNone(update.available(self.updates, "1.2"))

    def test_install_replaces_the_program_and_keeps_the_old_one_aside(self):
        self._publish("1.3")
        update.install(self.updates / update.EXE_NAME, self.current)
        self.assertEqual(self.current.read_bytes(), b"yangi versiya")
        old = self.current.with_name("MME-Ombor-eski.exe")
        self.assertEqual(old.read_bytes(), b"eski versiya")
        update.remove_old_version(self.current)
        self.assertFalse(old.exists())

    def test_install_rejects_wrong_files(self):
        with self.assertRaises(WarehouseError):
            update.install(self.updates / "yoq.exe", self.current)
        with self.assertRaises(WarehouseError):
            update.install(self.current, self.current)
        note = self.updates / "matn.txt"
        note.write_text("exe emas")
        with self.assertRaises(WarehouseError):
            update.install(note, self.current)
        self.assertEqual(self.current.read_bytes(), b"eski versiya")


if __name__ == "__main__":
    unittest.main()
