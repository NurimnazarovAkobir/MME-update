"""Umumiy papka (Google Drive) orqali yagona baza: bir nechta kompyuter, internetsiz ishlash, ziddiyatlar."""

import json
import tempfile
import unittest
from dataclasses import replace
from datetime import date
from pathlib import Path

from ombor.auth import Auth
from ombor.backup import Backup
from ombor.database import connect
from ombor.errors import WarehouseError
from ombor.folder_sync import FOLDER_NAME, FolderSynchronizer, SharedFolder, has_shared_data
from ombor.models import Movement, MovementKind, Product, Role
from ombor.replication import Replica
from ombor.sync import SyncError
from ombor.warehouse import Warehouse

TODAY = date(2026, 10, 17)


class Laptop:
    def __init__(self, folder: Path, device: str):
        self.conn = connect(":memory:")
        self.warehouse = Warehouse(self.conn, today=lambda: TODAY)
        self.auth = Auth(self.conn)
        self.sync = FolderSynchronizer(self.conn, SharedFolder(folder, device))

    def names(self) -> list[str]:
        return [product.name for product in self.warehouse.products()]

    def stock(self, name: str) -> float:
        return next(p.stock for p in self.warehouse.products() if p.name == name)

    def product_id(self, name: str) -> int:
        return next(p.id for p in self.warehouse.products() if p.name == name)

    def receive(self, name: str, quantity: float, price: float = 1000) -> None:
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.product_id(name), quantity, price))

    def issue(self, name: str, quantity: float) -> None:
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.product_id(name), quantity))


class FolderSyncTestCase(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.drive = Path(folder.name)
        self.boss = self.laptop("rahbar-noutbuk")
        self.boss.auth.add_user("Rahbar", "parol-1", Role.ADMIN)
        self.boss.auth.add_user("Safo", "parol-2", Role.KEEPER)
        self.boss.warehouse.save_product(Product("Truba", "metr"))
        self.boss.receive("Truba", 100)
        self.assertTrue(self.boss.sync.publish().ok)
        self.safo = self.laptop("safo-noutbuk")
        self.safo.auth.add_user("Vaqtinchalik", "parol-9", Role.ADMIN)  # birinchi ochilishda yaratilgan
        self.safo.sync.join()

    def laptop(self, device: str) -> Laptop:
        laptop = Laptop(self.drive, device)
        self.addCleanup(laptop.conn.close)
        return laptop

    def exchange(self, *laptops: Laptop) -> None:
        for laptop in (*laptops, *laptops):
            self.assertTrue(laptop.sync.run().ok)


class JoinTests(FolderSyncTestCase):
    def test_every_role_logs_in_with_own_password_on_the_other_laptop(self):
        users = {user.name: user for user in self.safo.auth.users()}
        self.assertEqual(sorted(users), ["Rahbar", "Safo"])  # vaqtinchalik hisob yo'qoldi
        self.assertEqual(self.safo.auth.login(users["Safo"].id, "parol-2").role, Role.KEEPER)
        self.assertEqual(self.safo.auth.login(users["Rahbar"].id, "parol-1").role, Role.ADMIN)
        with self.assertRaises(WarehouseError):
            self.safo.auth.login(users["Safo"].id, "parol-1")

    def test_data_arrives(self):
        self.assertEqual(self.safo.stock("Truba"), 100)

    def test_folder_layout_one_writer_per_file(self):
        root = self.drive / FOLDER_NAME
        self.assertTrue((root / "ombor.json").is_file())
        self.assertTrue(list((root / "rahbar-noutbuk").glob("*.json")))
        self.assertTrue(has_shared_data(self.drive))
        self.assertFalse(list(root.rglob("*.yozilmoqda")))

    def test_joining_an_empty_folder_is_refused(self):
        other = tempfile.TemporaryDirectory()
        self.addCleanup(other.cleanup)
        stranger = Laptop(Path(other.name), "x")
        self.addCleanup(stranger.conn.close)
        stranger.warehouse.save_product(Product("Shu yerdagi", "kg"))
        with self.assertRaises(SyncError):
            stranger.sync.join()
        self.assertEqual(stranger.names(), ["Shu yerdagi"])


class ExchangeTests(FolderSyncTestCase):
    def test_keeper_works_offline_and_boss_sees_it_later(self):
        self.safo.warehouse.actor = "Safo"
        self.safo.issue("Truba", 30)
        self.safo.warehouse.save_product(Product("Sement", "kg"))
        self.exchange(self.safo, self.boss)
        self.assertEqual(self.boss.stock("Truba"), 70)
        self.assertEqual(self.boss.names(), ["Sement", "Truba"])
        self.assertIn("Safo", [entry.actor for entry in self.boss.warehouse.history()])

    def test_both_offline_then_merged(self):
        self.boss.receive("Truba", 10, 1200)
        self.safo.issue("Truba", 5)
        self.exchange(self.boss, self.safo)
        self.assertEqual(self.boss.stock("Truba"), 105)
        self.assertEqual(self.safo.stock("Truba"), 105)
        costs = [[m.price for m in laptop.warehouse.movements(MovementKind.OUT)] for laptop in (self.boss, self.safo)]
        self.assertEqual(costs[0], costs[1])

    def test_same_row_edited_on_both_sides_converges(self):
        truba = lambda laptop: laptop.warehouse.product(laptop.product_id("Truba"))  # noqa: E731
        self.boss.warehouse.save_product(replace(truba(self.boss), note="rahbar"))
        self.safo.warehouse.save_product(replace(truba(self.safo), note="safo"))
        self.exchange(self.boss, self.safo)
        self.assertEqual(truba(self.boss).note, truba(self.safo).note)

    def test_same_name_added_on_both_sides(self):
        self.boss.warehouse.save_product(Product("Sement", "kg"))
        self.safo.warehouse.save_product(Product("sement", "qop"))
        self.exchange(self.boss, self.safo)
        self.assertEqual(sorted(self.boss.names()), sorted(self.safo.names()))
        self.assertEqual(len(self.boss.names()), 3)

    def test_third_laptop_joins_later(self):
        self.safo.warehouse.save_product(Product("Sement", "kg"))
        self.exchange(self.safo)
        third = self.laptop("uchinchi")
        third.sync.join()
        self.assertEqual(third.names(), ["Sement", "Truba"])
        third.receive("Sement", 7)
        self.exchange(third, self.boss)
        self.assertEqual(self.boss.stock("Sement"), 7)

    def test_deleted_product_returns_if_used_elsewhere(self):
        self.boss.warehouse.save_product(Product("List", "list"))
        self.exchange(self.boss, self.safo)
        self.safo.receive("List", 3)
        self.boss.warehouse.delete_product(self.boss.product_id("List"))
        self.exchange(self.boss, self.safo, self.boss)
        self.assertIn("List", self.boss.names())
        self.assertEqual(self.boss.stock("List"), 3)

    def test_nothing_is_sent_twice(self):
        self.exchange(self.boss)
        result = self.boss.sync.run()
        self.assertEqual((result.sent, result.received, result.waiting), (0, 0, 0))

    def test_partial_file_is_not_read_until_complete(self):
        self.boss.warehouse.save_product(Product("Sement", "kg"))
        self.boss.sync.run()
        folder = self.drive / FOLDER_NAME / "rahbar-noutbuk"
        newest = max(folder.glob("*.json"))
        content = newest.read_text(encoding="utf-8")
        newest.write_text(content[: len(content) // 2], encoding="utf-8")  # Drive hali ko'chirib bo'lmagan
        self.safo.sync.run()
        self.assertNotIn("Sement", self.safo.names())
        newest.write_text(content, encoding="utf-8")
        self.safo.sync.run()
        self.assertIn("Sement", self.safo.names())

    def test_folder_missing_means_offline(self):
        offline = FolderSynchronizer(self.safo.conn, SharedFolder(self.drive / "yo'q" / "papka", "safo-noutbuk"))
        self.safo.warehouse.save_product(Product("Sement", "kg"))
        result = offline.run()
        self.assertTrue(result.offline)
        self.assertGreater(result.waiting, 0)
        self.assertTrue(self.safo.sync.run().ok)

    def test_restored_backup_spreads_to_others(self):
        folder = Path(tempfile.mkdtemp())
        backup = Backup(self.boss.conn, folder)
        backup.save_to(folder / "nusxa.db")
        self.boss.warehouse.save_product(Product("Keyin", "kg"))
        self.exchange(self.boss, self.safo)
        self.assertIn("Keyin", self.safo.names())
        backup.restore_from(folder / "nusxa.db")
        self.exchange(self.boss, self.safo)
        self.assertEqual(self.safo.names(), ["Truba"])

    def test_batches_are_plain_json(self):
        files = sorted((self.drive / FOLDER_NAME / "rahbar-noutbuk").glob("*.json"))
        batch = json.loads(files[0].read_text(encoding="utf-8"))
        self.assertEqual(batch["batch"], 1)
        self.assertTrue(all(change["stamp"] for change in batch["changes"]))
        self.assertTrue(Replica(self.boss.conn).enabled)


if __name__ == "__main__":
    unittest.main()
