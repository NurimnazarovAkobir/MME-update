"""Foydalanuvchilar, parollar, zaxira nusxa va eski bazadan o'tish testlari."""

import sqlite3
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

from ombor.auth import Auth, _make_hash
from ombor.backup import AUTO_COPIES_KEPT, Backup, copy_before_upgrade
from ombor.database import connect
from ombor.errors import WarehouseError
from ombor.migrations import SCHEMA_VERSION
from ombor.models import MovementKind, Role
from ombor.warehouse import Warehouse
from tests.test_warehouse import TODAY, WarehouseTestCase


class AuthTests(WarehouseTestCase):
    def setUp(self):
        super().setUp()
        self.auth = Auth(self.conn)
        self.admin = self.auth.add_user("Rahbar", "temir2026", Role.ADMIN)

    def test_login(self):
        user = self.auth.login(self.admin.id, "temir2026")
        self.assertEqual((user.name, user.role, user.is_admin), ("Rahbar", Role.ADMIN, True))
        with self.assertRaises(WarehouseError):
            self.auth.login(self.admin.id, "Temir2026")

    def test_password_is_not_stored_in_plain_text(self):
        (stored,) = self.conn.execute("SELECT password FROM users").fetchone()
        self.assertNotIn("temir2026", stored)

    def test_short_password_and_duplicate_name_are_rejected(self):
        with self.assertRaises(WarehouseError):
            self.auth.add_user("Vali", "123", Role.KEEPER)
        with self.assertRaises(WarehouseError):
            self.auth.add_user("rahbar", "boshqa-parol", Role.KEEPER)
        self.assertEqual(len(self.auth.users()), 1)

    def test_change_requires_current_password(self):
        with self.assertRaises(WarehouseError):
            self.auth.change_password(self.admin.id, "xato", "yangi-parol")
        self.auth.change_password(self.admin.id, "temir2026", "yangi-parol")
        self.auth.login(self.admin.id, "yangi-parol")

    def test_admin_can_reset_keeper_password(self):
        keeper = self.auth.add_user("Vali", "eski-parol", Role.KEEPER)
        self.auth.set_password(keeper.id, "yangi-parol")
        self.assertFalse(self.auth.login(keeper.id, "yangi-parol").is_admin)

    def test_last_admin_cannot_be_deleted(self):
        keeper = self.auth.add_user("Vali", "parol-1", Role.KEEPER)
        with self.assertRaises(WarehouseError):
            self.auth.delete_user(self.admin.id)
        self.auth.delete_user(keeper.id)
        self.assertEqual([user.name for user in self.auth.users()], ["Rahbar"])

    def test_recovery_code_resets_password(self):
        self.assertFalse(self.auth.has_recovery_code())
        code = self.auth.new_recovery_code()
        self.assertRegex(code, r"^[A-Z2-9]{4}-[A-Z2-9]{4}-[A-Z2-9]{4}$")
        with self.assertRaises(WarehouseError):
            self.auth.reset_with_recovery_code(self.admin.id, "AAAA-BBBB-CCCC", "yangi-parol")
        self.auth.reset_with_recovery_code(self.admin.id, f" {code.lower().replace('-', ' ')} ", "yangi-parol")
        self.auth.login(self.admin.id, "yangi-parol")

    def test_new_recovery_code_cancels_old_one(self):
        old = self.auth.new_recovery_code()
        self.auth.new_recovery_code()
        with self.assertRaises(WarehouseError):
            self.auth.reset_with_recovery_code(self.admin.id, old, "yangi-parol")

    def test_reset_fails_when_no_code_was_created(self):
        with self.assertRaises(WarehouseError):
            self.auth.reset_with_recovery_code(self.admin.id, "", "yangi-parol")


class BackupTests(WarehouseTestCase):
    def setUp(self):
        super().setUp()
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.folder = Path(folder.name)
        self.backup = Backup(self.conn, self.folder / "auto")

    def test_backup_and_restore_round_trip(self):
        self.receive(10, 1000)
        self.backup.save_to(self.folder / "zaxira.db")
        self.receive(5, 1000)
        self.backup.restore_from(self.folder / "zaxira.db")
        self.assertEqual(self.warehouse.product(self.pipe).stock, 10)

    def test_restore_keeps_current_users_and_settings(self):
        auth = Auth(self.conn)
        admin = auth.add_user("Rahbar", "eski-parol", Role.ADMIN)
        self.backup.save_to(self.folder / "zaxira.db")
        auth.set_password(admin.id, "yangi-parol")
        keeper = auth.add_user("Vali", "parol-1", Role.KEEPER)
        self.backup.extra_folder = self.folder / "fleshka"
        self.backup.restore_from(self.folder / "zaxira.db")
        auth.login(admin.id, "yangi-parol")
        auth.login(keeper.id, "parol-1")
        self.assertEqual(self.backup.extra_folder, self.folder / "fleshka")

    def test_restore_rejects_foreign_file(self):
        (self.folder / "boshqa.db").write_text("bu baza emas")
        with self.assertRaises(WarehouseError):
            self.backup.restore_from(self.folder / "boshqa.db")
        self.assertEqual(len(self.warehouse.products()), 1)

    def test_automatic_backup_writes_one_file_per_day_to_each_folder(self):
        self.backup.extra_folder = self.folder / "fleshka"
        written = self.backup.run_automatic(TODAY)
        self.backup.run_automatic(TODAY)
        self.assertEqual([path.name for path in written], ["ombor-2026-10-03.db"] * 2)
        for folder in (self.folder / "auto", self.folder / "fleshka"):
            self.assertEqual([path.name for path in folder.iterdir()], ["ombor-2026-10-03.db"])
        self.assertIsNotNone(self.backup.last_automatic(self.folder / "auto"))

    def test_automatic_backup_can_be_restored(self):
        self.receive(10, 1000)
        (path,) = self.backup.run_automatic(TODAY)
        self.receive(5, 1000)
        self.backup.restore_from(path)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 10)

    def test_automatic_backup_keeps_only_recent_copies(self):
        for offset in range(AUTO_COPIES_KEPT + 5):
            self.backup.run_automatic(TODAY + timedelta(days=offset))
        names = sorted(path.name for path in (self.folder / "auto").iterdir())
        self.assertEqual(len(names), AUTO_COPIES_KEPT)
        self.assertEqual(names[0], f"ombor-{TODAY + timedelta(days=5):%Y-%m-%d}.db")

    def test_unreachable_extra_folder_is_skipped(self):
        (self.folder / "fayl").write_text("papka emas")
        self.backup.extra_folder = self.folder / "fayl" / "ichida"
        written = self.backup.run_automatic(TODAY)
        self.assertEqual([path.parent.name for path in written], ["auto"])

    def test_no_backup_yet(self):
        self.assertIsNone(self.backup.last_automatic(self.folder / "auto"))


LEGACY_SCHEMA = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, unit TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '', min_stock REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE movements (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, date TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id), quantity REAL NOT NULL, price REAL NOT NULL DEFAULT 0,
    person TEXT NOT NULL DEFAULT '', counterparty TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
INSERT INTO products (id, name, unit, category) VALUES (1, 'Truba', 'metr', 'Стройматериал');
INSERT INTO movements (kind, date, product_id, quantity, price) VALUES
    ('IN', '2026-09-01', 1, 100, 10000),
    ('OUT', '2026-09-05', 1, 40, 0),
    ('IN', '2026-09-10', 1, 100, 20000),
    ('OUT', '2026-08-01', 1, 5, 0);
"""


class LegacyDatabaseTests(unittest.TestCase):
    """1-versiya bazasi: chiqim narxi yozilmagan, bitta umumiy parol, `created_by` ustuni yo'q."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.path = Path(folder.name) / "ombor.db"
        legacy = sqlite3.connect(self.path)
        legacy.executescript(LEGACY_SCHEMA)
        legacy.execute("INSERT INTO settings VALUES ('password', ?)", (_make_hash("eski-parol"),))
        legacy.commit()
        legacy.close()
        self.copy = copy_before_upgrade(self.path, self.path.parent / "zaxira")
        self.conn = connect(self.path)
        self.addCleanup(lambda: self.conn.close())

    def test_issue_costs_are_filled_in(self):
        issues = {m.date: m for m in Warehouse(self.conn).movements(MovementKind.OUT)}
        self.assertEqual(issues[date(2026, 9, 5)].amount, 400_000)
        self.assertEqual(issues[date(2026, 9, 5)].created_by, "")

    def test_issue_dated_before_any_receipt_is_kept(self):
        warehouse = Warehouse(self.conn)
        self.assertEqual(warehouse.product(1).stock, 155)
        self.assertEqual(len(warehouse.movements()), 4)

    def test_single_password_becomes_admin_user(self):
        auth = Auth(self.conn)
        (admin,) = auth.users()
        self.assertEqual((admin.name, admin.role), ("Rahbar", Role.ADMIN))
        auth.login(admin.id, "eski-parol")

    def test_old_file_is_copied_before_upgrade(self):
        self.assertEqual(self.copy.name, "yangilashdan-oldin-v0.db")
        untouched = sqlite3.connect(self.copy)
        self.addCleanup(untouched.close)
        columns = {row[1] for row in untouched.execute("PRAGMA table_info(movements)")}
        self.assertNotIn("created_by", columns)
        self.assertIsNone(copy_before_upgrade(self.path, self.path.parent / "zaxira"))
        self.assertIsNone(copy_before_upgrade(self.path.parent / "yoq.db", self.path.parent / "zaxira"))

    def test_product_group_moves_to_its_movements(self):
        groups = {movement.category for movement in Warehouse(self.conn).movements()}
        self.assertEqual(groups, {"Стройматериал"})

    def test_migration_runs_only_once(self):
        self.conn.close()
        self.conn = connect(self.path)
        self.assertEqual(len(Auth(self.conn).users()), 1)
        self.assertEqual(self.conn.execute("PRAGMA user_version").fetchone()[0], SCHEMA_VERSION)


if __name__ == "__main__":
    unittest.main()
