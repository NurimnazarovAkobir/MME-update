"""Markaziy server bilan sinxronlash testlari: haqiqiy HTTP server shu kompyuterda ochiladi."""

import json
import tempfile
import threading
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from ombor.auth import Auth
from ombor.backup import Backup
from ombor.database import connect
from ombor.models import Movement, MovementKind, Product, Role
from ombor.replication import Replica, install
from ombor.settings import Settings
from ombor.sync import OfflineError, SyncClient, SyncConfig, SyncError, Synchronizer, normalize_url
from ombor.sync_protocol import Change
from ombor.sync_server import ServerStore, make_server
from ombor.warehouse import Warehouse

TOKEN = "maxfiy-kalit-123"
TODAY = date(2026, 10, 3)


class Computer:
    """Bitta kompyuter: o'z bazasi va server bilan sinxronlovchisi."""

    def __init__(self, url: str, name: str, token: str = TOKEN):
        self.conn = connect(":memory:")
        self.warehouse = Warehouse(self.conn, today=lambda: TODAY)
        self.auth = Auth(self.conn)
        self.sync = Synchronizer(self.conn, SyncClient(SyncConfig(url, token, name), timeout=5))
        self.replica = Replica(self.conn)

    def product_names(self) -> list[str]:
        return [product.name for product in self.warehouse.products()]

    def stock(self, name: str) -> float:
        return next(p.stock for p in self.warehouse.products() if p.name == name)


class SyncTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.store = ServerStore(Path(folder.name) / "server.db")
        self.server = make_server(self.store, TOKEN, "127.0.0.1", 0, log=False)
        thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(self.store.close)
        self.addCleanup(self.server.server_close)
        self.addCleanup(self.server.shutdown)
        self.url = f"http://127.0.0.1:{self.server.server_address[1]}"

        self.main = self.computer("rahbar-pc")  # birinchi kompyuter: uning bazasi asosiy bo'ladi
        self.main.auth.add_user("Rahbar", "parol-1", Role.ADMIN)
        self.main.auth.add_user("Vali", "parol-2", Role.KEEPER)
        self.pipe = self.main.warehouse.save_product(Product("Truba 40x40", "metr"))
        self.receive(self.main, self.pipe, 100, 1000)
        self.assertTrue(self.main.sync.publish().ok)

        self.keeper = self.computer("ombor-pc")
        self.keeper.auth.add_user("Mahalliy", "parol-9", Role.ADMIN)  # serverdagisi bilan almashtiriladi
        self.keeper.sync.join()

    def computer(self, name: str, token: str = TOKEN) -> Computer:
        computer = Computer(self.url, name, token)
        self.addCleanup(computer.conn.close)
        return computer

    @staticmethod
    def receive(computer: Computer, product_id: int, quantity: float, price: float) -> int:
        return computer.warehouse.save_movement(Movement(MovementKind.IN, TODAY, product_id, quantity, price))

    @staticmethod
    def issue(computer: Computer, product_id: int, quantity: float) -> int:
        return computer.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, product_id, quantity))

    def local_id(self, computer: Computer, name: str) -> int:
        return next(p.id for p in computer.warehouse.products() if p.name == name)


class JoinTests(SyncTestCase):
    def test_joining_computer_gets_the_main_database(self):
        self.assertEqual(self.keeper.product_names(), ["Truba 40x40"])
        self.assertEqual(self.keeper.stock("Truba 40x40"), 100)
        self.assertEqual(sorted(user.name for user in self.keeper.auth.users()), ["Rahbar", "Vali"])

    def test_passwords_work_on_the_joined_computer(self):
        vali = next(user for user in self.keeper.auth.users() if user.name == "Vali")
        self.assertEqual(self.keeper.auth.login(vali.id, "parol-2").role, Role.KEEPER)

    def test_main_warehouse_keeps_its_id(self):
        self.assertEqual([store.id for store in self.keeper.warehouse.stores()], [1])

    def test_joining_a_server_without_admin_is_refused(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        empty = ServerStore(Path(folder.name) / "empty.db")
        self.addCleanup(empty.close)
        server = make_server(empty, TOKEN, "127.0.0.1", 0, log=False)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        stranger = Computer(f"http://127.0.0.1:{server.server_address[1]}", "x")
        self.addCleanup(stranger.conn.close)
        stranger.warehouse.save_product(Product("Shu yerdagi", "kg"))
        with self.assertRaises(SyncError):
            stranger.sync.join()
        self.assertEqual(stranger.product_names(), ["Shu yerdagi"])  # hech narsa o'chmadi


class ExchangeTests(SyncTestCase):
    def test_changes_reach_the_other_computer(self):
        pipe = self.local_id(self.keeper, "Truba 40x40")
        self.issue(self.keeper, pipe, 30)
        self.keeper.warehouse.save_product(Product("Sement", "kg"))
        self.assertTrue(self.keeper.sync.run().ok)
        result = self.main.sync.run()
        self.assertTrue(result.ok)
        self.assertGreater(result.received, 0)
        self.assertEqual(self.main.product_names(), ["Sement", "Truba 40x40"])
        self.assertEqual(self.main.stock("Truba 40x40"), 70)

    def test_offline_changes_from_both_sides_are_merged(self):
        self.receive(self.main, self.pipe, 10, 1200)
        self.issue(self.keeper, self.local_id(self.keeper, "Truba 40x40"), 5)
        for computer in (self.main, self.keeper, self.main):
            self.assertTrue(computer.sync.run().ok)
        self.assertEqual(self.main.stock("Truba 40x40"), 105)
        self.assertEqual(self.keeper.stock("Truba 40x40"), 105)
        main_cost = [m.price for m in self.main.warehouse.movements(MovementKind.OUT)]
        keeper_cost = [m.price for m in self.keeper.warehouse.movements(MovementKind.OUT)]
        self.assertEqual(main_cost, keeper_cost)  # tannarx ikkala kompyuterda bir xil hisoblanadi

    def test_history_shows_who_changed_what_on_the_other_computer(self):
        self.keeper.warehouse.actor = "Vali"
        self.keeper.warehouse.save_product(Product("Sement", "kg"))
        self.keeper.sync.run()
        self.main.sync.run()
        self.assertIn("Vali", [entry.actor for entry in self.main.warehouse.history()])

    def test_edit_and_delete_are_synced(self):
        product = self.main.warehouse.product(self.pipe)
        self.main.warehouse.save_product(replace(product, name="Truba 40x40x2", category="Стройматериал"))
        movement_id = self.main.warehouse.movements(MovementKind.IN)[0].id
        self.main.warehouse.delete_movement(movement_id)
        self.main.sync.run()
        self.keeper.sync.run()
        self.assertEqual(self.keeper.product_names(), ["Truba 40x40x2"])
        self.assertEqual(
            self.keeper.warehouse.product(self.local_id(self.keeper, "Truba 40x40x2")).category, "Стройматериал"
        )
        self.assertEqual(self.keeper.stock("Truba 40x40x2"), 0)
        self.assertEqual(len(self.keeper.warehouse.deleted_movements()), 1)

    def test_same_name_added_offline_on_both_computers(self):
        self.main.warehouse.save_product(Product("Sement", "kg"))
        self.keeper.warehouse.save_product(Product("sement", "qop"))
        for computer in (self.main, self.keeper, self.main):
            computer.sync.run()
        self.assertEqual(self.main.product_names(), self.keeper.product_names())
        self.assertEqual(self.main.product_names(), ["Sement", "sement (2)", "Truba 40x40"])

    def test_deleted_product_comes_back_if_used_elsewhere(self):
        sheet = self.main.warehouse.save_product(Product("List", "list"))
        self.main.sync.run()
        self.keeper.sync.run()
        self.receive(self.keeper, self.local_id(self.keeper, "List"), 3, 500)  # internetsiz
        self.main.warehouse.delete_product(sheet)
        self.main.sync.run()
        for computer in (self.keeper, self.main, self.keeper):
            computer.sync.run()
        self.assertIn("List", self.main.product_names())
        self.assertEqual(self.main.stock("List"), 3)

    def test_settings_are_shared_but_local_ones_are_not(self):
        Settings(self.main.conn).set_firm_name("MME Montaj")
        Backup(self.main.conn, Path(tempfile.gettempdir())).extra_folder = Path("D:/zaxira")
        self.main.sync.run()
        self.keeper.sync.run()
        keeper_settings = Settings(self.keeper.conn)
        self.assertEqual(keeper_settings.firm_name(""), "MME Montaj")
        self.assertEqual(keeper_settings.get("backup_folder"), "")

    def test_nothing_is_sent_twice(self):
        self.main.sync.run()
        result = self.main.sync.run()
        self.assertEqual((result.sent, result.received, result.waiting), (0, 0, 0))


class OfflineTests(SyncTestCase):
    def test_changes_wait_until_the_server_is_reachable(self):
        offline = Synchronizer(self.keeper.conn, SyncClient(SyncConfig("http://127.0.0.1:9", TOKEN, "x"), timeout=2))
        self.keeper.warehouse.save_product(Product("Sement", "kg"))
        result = offline.run()
        self.assertTrue(result.offline)
        self.assertGreater(result.waiting, 0)
        self.assertTrue(self.keeper.sync.run().ok)  # internet qaytdi
        self.main.sync.run()
        self.assertIn("Sement", self.main.product_names())

    def test_wrong_token_is_rejected(self):
        stranger = self.computer("begona", token="boshqa-kalit-1")
        result = stranger.sync.publish()
        self.assertFalse(result.ok)
        self.assertFalse(result.offline)

    def test_offline_error_type(self):
        client = SyncClient(SyncConfig("http://127.0.0.1:9", TOKEN, "x"), timeout=2)
        with self.assertRaises(OfflineError):
            client.status()


class ReplicaTests(SyncTestCase):
    def test_change_waits_for_the_row_it_refers_to(self):
        computer = self.computer("yangi")
        changes, head = self.main.sync._pull_all(0)
        products = [c for c in changes if c.table == "products"]
        rest = [c for c in changes if c.table != "products"]
        computer.replica.enable(publish_all=False)
        computer.replica.apply_remote(rest, head)  # mahsulotlar hali kelmagan
        self.assertEqual(computer.product_names(), [])
        computer.replica.apply_remote(products, head)
        self.assertEqual(computer.stock("Truba 40x40"), 100)

    def test_remote_changes_are_not_sent_back(self):
        self.main.warehouse.save_product(Product("Sement", "kg"))
        self.main.sync.run()
        self.keeper.sync.run()
        self.assertEqual(self.keeper.replica.pending_count(), 0)

    def test_restored_backup_becomes_the_shared_state(self):
        folder = Path(tempfile.mkdtemp())
        backup = Backup(self.main.conn, folder)
        backup.save_to(folder / "nusxa.db")
        self.main.warehouse.save_product(Product("Keyin qo'shilgan", "kg"))
        self.main.sync.run()
        self.keeper.sync.run()
        self.assertIn("Keyin qo'shilgan", self.keeper.product_names())
        backup.restore_from(folder / "nusxa.db")
        self.main.sync.run()
        self.keeper.sync.run()
        self.assertEqual(self.keeper.product_names(), ["Truba 40x40"])

    def test_unknown_columns_from_a_newer_version_are_ignored(self):
        data = {"name": "Yangi", "unit": "kg", "kelajakdagi_ustun": 1}
        self.keeper.replica.apply_remote([Change("products", "abc", data)], 0)
        self.assertIn("Yangi", self.keeper.product_names())


class RetiredTablesTests(SyncTestCase):
    """1.25 da sinxronlangan buxgalteriya jadvallari endi e'tiborga olinmaydi."""

    def test_old_payroll_changes_from_the_server_are_skipped(self):
        old = [Change("employees", "e1", {"name": "Ali", "salary": 100}).to_json()]
        self.store.push([Change("products", "p-new", {"name": "Sement", "unit": "kg"})], "boshqa")
        with self.store._lock, self.store._conn:  # eski (1.25) mijoz yozgan qator
            self.store._conn.execute(
                "INSERT INTO rows (tbl, uid, data, deleted, seq, at) VALUES ('employees', 'e1', ?, 0, 9999, '')",
                (json.dumps(old[0]["data"]),),
            )
        result = self.keeper.sync.run()
        self.assertTrue(result.ok, result.error)
        self.assertIn("Sement", self.keeper.product_names())
        self.assertEqual(self.keeper.replica.last_seq, 9999)

    def test_old_triggers_are_removed_on_upgrade(self):
        conn = self.keeper.conn
        conn.execute("CREATE TABLE employees (id INTEGER PRIMARY KEY, name TEXT, uid TEXT)")
        conn.execute(
            "CREATE TRIGGER sync_insert_employees AFTER INSERT ON employees"
            " BEGIN INSERT INTO sync_outbox (tbl, uid) VALUES ('employees', NEW.uid); END"
        )
        conn.execute("INSERT INTO employees (name, uid) VALUES ('Ali', 'e1')")
        conn.commit()
        install(conn, main_warehouse_id=1)
        names = {row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type = 'trigger'")}
        self.assertNotIn("sync_insert_employees", names)
        self.assertIsNone(conn.execute("SELECT 1 FROM sync_outbox WHERE tbl = 'employees'").fetchone())
        self.assertTrue(self.keeper.sync.run().ok)


class UrlTests(unittest.TestCase):
    def test_scheme_is_added(self):
        self.assertEqual(normalize_url(" 192.168.1.10:8765/ "), "http://192.168.1.10:8765")
        self.assertEqual(normalize_url("https://ombor.uz"), "https://ombor.uz")

    def test_bad_url(self):
        with self.assertRaises(SyncError):
            normalize_url("ftp://x")


if __name__ == "__main__":
    unittest.main()
