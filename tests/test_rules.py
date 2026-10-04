"""Qoidalar testlari: sana, guruh, o'chirish va tiklash, tarix, xizmatlar, hujjat va ruxsatlar."""

import sqlite3
import tempfile
import unittest
from datetime import timedelta
from pathlib import Path

from ombor.analytics import Analytics
from ombor.auth import Auth
from ombor.database import connect
from ombor.errors import WarehouseError
from ombor.models import HistoryAction, Movement, MovementKind, Product, Role, StockStatus, User
from ombor.session import Session
from ombor.warehouse import INVENTORY_SHORTAGE, PRODUCT_ENTITY, Warehouse, display_counterparty
from tests.test_warehouse import TODAY, WarehouseTestCase


class RulesTestCase(WarehouseTestCase):
    """«Bugun» qat'iy sana bo'lgan ombor: testlar kalendarga bog'liq bo'lmaydi."""

    def setUp(self):
        super().setUp()
        self.warehouse = Warehouse(self.conn, today=lambda: TODAY)
        self.warehouse.actor = "Rahbar"


class DateTests(RulesTestCase):
    def test_future_date_is_rejected(self):
        with self.assertRaises(WarehouseError):
            self.receive(10, 1000, day=TODAY + timedelta(days=1))
        self.assertEqual(self.warehouse.movements(), [])

    def test_today_is_accepted(self):
        self.receive(10, 1000, day=TODAY)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 10)

    def test_old_future_dated_record_can_still_be_corrected(self):
        tomorrow = TODAY + timedelta(days=1)
        self.conn.execute(
            "INSERT INTO movements (kind, date, product_id, quantity, price) VALUES ('IN', ?, ?, 5, 100)",
            (tomorrow.isoformat(), self.pipe),
        )
        (movement,) = self.warehouse.movements()
        movement.quantity = 7
        self.warehouse.save_movement(movement)  # sana o'zgarmagan — ruxsat
        movement.date = tomorrow + timedelta(days=1)
        with self.assertRaises(WarehouseError):
            self.warehouse.save_movement(movement)


class GroupRequiredTests(RulesTestCase):
    def test_group_is_optional_by_default(self):
        self.assertFalse(self.warehouse.group_required)
        self.receive(10, 1000)

    def test_required_group(self):
        self.warehouse.group_required = True
        with self.assertRaises(WarehouseError):
            self.receive(10, 1000)
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 10, 1000, category="Стройматериал"))
        self.assertEqual(self.warehouse.product(self.pipe).stock, 10)

    def test_inventory_and_import_are_not_blocked(self):
        self.warehouse.group_required = True
        self.assertIsNotNone(self.warehouse.adjust_stock(self.pipe, 3, TODAY, "Rahbar"))


class DeleteAndRestoreTests(RulesTestCase):
    def test_deleted_record_leaves_the_accounts_but_can_be_restored(self):
        receipt = self.receive(10, 1000)
        self.warehouse.delete_movement(receipt)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 0)
        self.assertEqual(self.reports.totals().amount_in, 0)
        (deleted,) = self.warehouse.deleted_movements()
        self.assertEqual((deleted.id, deleted.deleted_by), (receipt, "Rahbar"))

        self.warehouse.restore_movement(receipt)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 10)
        self.assertEqual(self.warehouse.deleted_movements(), [])

    def test_receipt_cannot_be_deleted_when_it_was_already_issued(self):
        receipt = self.receive(10, 1000)
        self.issue(6)
        with self.assertRaises(WarehouseError):
            self.warehouse.delete_movement(receipt)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 4)
        self.assertEqual(self.warehouse.deleted_movements(), [])

    def test_issue_cannot_be_restored_when_stock_is_gone(self):
        self.receive(10, 1000)
        first = self.issue(6)
        self.warehouse.delete_movement(first)
        self.issue(8)
        with self.assertRaises(WarehouseError):
            self.warehouse.restore_movement(first)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 2)

    def test_deleted_issue_does_not_affect_cost(self):
        self.receive(10, 1000)
        self.warehouse.delete_movement(self.issue(4))
        self.assertEqual(self.warehouse.product(self.pipe).value, 10_000)

    def test_product_with_only_deleted_records_can_be_removed(self):
        self.warehouse.delete_movement(self.receive(10, 1000))
        self.warehouse.delete_product(self.pipe)
        self.assertEqual(self.warehouse.products(), [])
        self.assertEqual(self.warehouse.deleted_movements(), [])

    def test_restoring_unknown_record_fails(self):
        with self.assertRaises(WarehouseError):
            self.warehouse.restore_movement(999)


class HistoryTests(RulesTestCase):
    def test_every_change_is_recorded_with_its_author(self):
        receipt = self.receive(10, 1000)
        movement = self.warehouse.movement(receipt)
        movement.quantity = 12
        self.warehouse.actor = "Vali"
        self.warehouse.save_movement(movement)
        self.warehouse.delete_movement(receipt)
        self.warehouse.restore_movement(receipt)

        entries = [e for e in self.warehouse.history() if e.entity == MovementKind.IN.value]
        self.assertEqual(
            [(e.action, e.actor) for e in reversed(entries)],
            [
                (HistoryAction.ADD, "Rahbar"),
                (HistoryAction.EDIT, "Vali"),
                (HistoryAction.DELETE, "Vali"),
                (HistoryAction.RESTORE, "Vali"),
            ],
        )
        edit = entries[2]
        self.assertIn("12 metr", edit.summary)
        self.assertIn("10 metr", edit.previous)

    def test_products_are_recorded_too(self):
        (entry,) = self.warehouse.history()
        self.assertEqual((entry.action, entry.entity, entry.entity_id), (HistoryAction.ADD, PRODUCT_ENTITY, self.pipe))
        self.assertIn("Truba 40x40", entry.summary)

    def test_failed_change_leaves_no_trace(self):
        before = len(self.warehouse.history())
        with self.assertRaises(WarehouseError):
            self.issue(5)
        self.assertEqual(len(self.warehouse.history()), before)

    def test_search_and_limit(self):
        self.receive(10, 1000)
        self.assertEqual(len(self.warehouse.history(search="truba")), 2)
        self.assertEqual(len(self.warehouse.history(search="yo'q narsa")), 0)
        self.assertEqual(len(self.warehouse.history(limit=1)), 1)


class ServiceTests(RulesTestCase):
    def setUp(self):
        super().setUp()
        self.transport = self.warehouse.save_product(Product("Yuk tashish", "reys", is_service=True))

    def test_service_has_no_stock(self):
        self.receive(3, 500_000, product_id=self.transport)
        service = self.warehouse.product(self.transport)
        self.assertEqual((service.stock, service.value, service.status), (0, 0, StockStatus.SERVICE))
        self.assertFalse(service.needs_attention)
        self.assertEqual(self.reports.stock_value(), 0)

    def test_service_expense_is_counted_in_totals_and_reduces_net_profit(self):
        self.receive(10, 1000)
        self.issue(10, sale_price=1500)
        self.receive(1, 2000, product_id=self.transport)
        summary = Analytics(self.conn).summary()
        self.assertEqual((summary.profit, summary.expenses, summary.net_profit), (5000, 2000, 3000))
        self.assertEqual(self.reports.totals().amount_in, 12_000)

    def test_service_can_be_issued_without_stock(self):
        self.issue(2, product_id=self.transport, sale_price=700_000)
        (sale,) = self.warehouse.movements(MovementKind.OUT)
        self.assertEqual((sale.price, sale.profit), (0, 1_400_000))

    def test_service_is_not_in_turnover_or_inventory(self):
        self.receive(1, 2000, product_id=self.transport)
        self.assertEqual(self.reports.turnover(), [])
        with self.assertRaises(WarehouseError):
            self.warehouse.adjust_stock(self.transport, 5, TODAY, "Rahbar")

    def test_kind_cannot_change_once_there_are_records(self):
        self.receive(1, 2000, product_id=self.transport)
        service = self.warehouse.product(self.transport)
        service.is_service = False
        with self.assertRaises(WarehouseError):
            self.warehouse.save_product(service)
        service.is_service = True
        service.name = "Yuk tashish xizmati"
        self.warehouse.save_product(service)

    def test_attention_count_ignores_services(self):
        self.assertEqual(self.warehouse.attention_count(), 1)  # truba hali kelmagan
        self.receive(100, 1000)
        self.assertEqual(self.warehouse.attention_count(), 0)


class DocumentTests(RulesTestCase):
    def setUp(self):
        super().setUp()
        self.sheet = self.warehouse.save_product(Product("List 2mm", "list"))

    def _receive(self, product_id, number, day=TODAY):
        return self.warehouse.save_movement(Movement(MovementKind.IN, day, product_id, 5, 1000, doc_number=number))

    def test_records_with_the_same_number_form_one_document(self):
        first = self._receive(self.pipe, " 17 ")
        second = self._receive(self.sheet, "17")
        self._receive(self.sheet, "18")
        self._receive(self.sheet, "17", day=TODAY - timedelta(days=1))
        self.assertEqual([m.id for m in self.warehouse.document(second)], [first, second])

    def test_record_without_a_number_is_its_own_document(self):
        self._receive(self.pipe, "")
        alone = self._receive(self.sheet, "")
        self.assertEqual([m.id for m in self.warehouse.document(alone)], [alone])

    def test_number_is_searchable(self):
        self._receive(self.pipe, "A-204")
        self.assertEqual(len(self.warehouse.movements(search="a-204")), 1)


class SystemLabelTests(RulesTestCase):
    def test_inventory_marker_is_translated_only_on_display(self):
        self.receive(10, 1000)
        self.warehouse.adjust_stock(self.pipe, 8, TODAY, "Rahbar")
        (shortage,) = self.warehouse.movements(MovementKind.OUT)
        self.assertEqual(shortage.counterparty, INVENTORY_SHORTAGE)
        self.assertEqual(display_counterparty(shortage.counterparty), "Inventarizatsiya (kamomad)")
        self.assertEqual(display_counterparty("Obyekt-1"), "Obyekt-1")
        self.assertEqual(self.warehouse.suggestions(MovementKind.OUT, "counterparty"), [])

    def test_take_inventory_adjusts_only_changed_products(self):
        other = self.warehouse.save_product(Product("List 2mm", "list"))
        self.receive(10, 1000)
        self.receive(4, 500, product_id=other)
        self.assertEqual(self.warehouse.take_inventory({self.pipe: 10, other: 6}, TODAY, "Rahbar"), 1)
        self.assertEqual(self.warehouse.product(other).stock, 6)


class PermissionTests(RulesTestCase):
    def setUp(self):
        super().setUp()
        self.admin = Session(User(1, "Rahbar", Role.ADMIN))
        self.keeper = Session(User(2, "Vali", Role.KEEPER))
        self.viewer = Session(User(3, "Hisobchi", Role.VIEWER))

    def _receipt(self, author):
        movement_id = self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 1, 100, created_by=author)
        )
        return self.warehouse.movement(movement_id)

    def test_who_can_add(self):
        self.assertEqual([s.can_add for s in (self.admin, self.keeper, self.viewer)], [True, True, False])
        self.assertEqual([s.can_modify for s in (self.admin, self.keeper, self.viewer)], [True, False, False])

    def test_keeper_changes_only_own_records_entered_today(self):
        own, foreign = self._receipt("Vali"), self._receipt("Rahbar")
        entered = own.created_on
        self.assertTrue(self.keeper.can_change(own, today=entered))
        self.assertFalse(self.keeper.can_change(foreign, today=entered))
        self.assertFalse(self.keeper.can_change(own, today=entered + timedelta(days=1)))

    def test_admin_changes_everything_and_viewer_nothing(self):
        record = self._receipt("Vali")
        self.assertTrue(self.admin.can_change(record, today=record.created_on + timedelta(days=30)))
        self.assertFalse(self.viewer.can_change(record, today=record.created_on))


VERSION_3_SCHEMA = """
CREATE TABLE products (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, unit TEXT NOT NULL,
    min_stock REAL NOT NULL DEFAULT 0, note TEXT NOT NULL DEFAULT ''
);
CREATE TABLE movements (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, date TEXT NOT NULL,
    product_id INTEGER NOT NULL REFERENCES products(id), quantity REAL NOT NULL, price REAL NOT NULL DEFAULT 0,
    sale_price REAL NOT NULL DEFAULT 0, category TEXT NOT NULL DEFAULT '', subcategory TEXT NOT NULL DEFAULT '',
    person TEXT NOT NULL DEFAULT '', counterparty TEXT NOT NULL DEFAULT '', note TEXT NOT NULL DEFAULT '',
    created_by TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL DEFAULT (datetime('now', 'localtime'))
);
CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE users (
    id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE COLLATE NOCASE, password TEXT NOT NULL,
    role TEXT NOT NULL CHECK (role IN ('admin', 'keeper'))
);
INSERT INTO products (id, name, unit) VALUES (1, 'Truba', 'metr');
INSERT INTO movements (kind, date, product_id, quantity, price, counterparty) VALUES
    ('IN', '2026-09-01', 1, 100, 10000, 'Начальный остаток'),
    ('OUT', '2026-09-05', 1, 40, 10000, 'Obyekt-1');
PRAGMA user_version = 3;
"""


class Version3DatabaseTests(unittest.TestCase):
    """3-versiya bazasi: faqat ikki lavozim, tarix va o'chirilganlar yo'q."""

    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        path = Path(folder.name) / "ombor.db"
        legacy = sqlite3.connect(path)
        legacy.executescript(VERSION_3_SCHEMA)
        legacy.commit()
        legacy.close()
        self.conn = connect(path)
        self.addCleanup(self.conn.close)
        self.auth = Auth(self.conn)
        self.auth_admin = self.conn.execute(
            "INSERT INTO users (name, password, role) VALUES ('Rahbar', 'x:y', 'admin')"
        ).lastrowid
        self.conn.commit()

    def test_data_survives(self):
        warehouse = Warehouse(self.conn)
        self.assertEqual(warehouse.product(1).stock, 60)
        self.assertEqual(warehouse.deleted_movements(), [])
        self.assertEqual(warehouse.history(), [])

    def test_viewer_role_is_now_allowed(self):
        viewer = self.auth.add_user("Hisobchi", "parol-1", Role.VIEWER)
        self.assertEqual([user.role for user in self.auth.users() if user.id == viewer.id], [Role.VIEWER])

    def test_opening_balance_marker_is_unified(self):
        receipt = Warehouse(self.conn).movements(MovementKind.IN)[0]
        self.assertEqual(display_counterparty(receipt.counterparty), "Boshlang'ich qoldiq")


class ExistingUsersSurviveRoleMigrationTests(unittest.TestCase):
    def test_users_keep_their_ids_and_passwords(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ombor.db"
            legacy = sqlite3.connect(path)
            legacy.executescript(VERSION_3_SCHEMA)
            legacy.execute("INSERT INTO users (id, name, password, role) VALUES (7, 'Vali', 'tuz:xesh', 'keeper')")
            legacy.commit()
            legacy.close()
            conn = connect(path)
            try:
                self.assertEqual(
                    tuple(conn.execute("SELECT id, name, password, role FROM users").fetchone()),
                    (7, "Vali", "tuz:xesh", "keeper"),
                )
            finally:
                conn.close()


if __name__ == "__main__":
    unittest.main()
