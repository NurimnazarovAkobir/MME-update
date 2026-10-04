"""Shtrix-kod, birliklar, guruhlar, qaytarish, qarzlar va bir nechta ombor testlari."""

from datetime import timedelta

from ombor import catalog
from ombor.analytics import Analytics
from ombor.catalog import GroupCatalog
from ombor.database import MAIN_WAREHOUSE_ID, connect
from ombor.debts import Debts
from ombor.errors import WarehouseError
from ombor.models import HistoryAction, Movement, MovementKind, Payment, Product, Transfer
from ombor.warehouse import Warehouse
from tests.test_warehouse import TODAY, WarehouseTestCase


class ExtrasTestCase(WarehouseTestCase):
    def setUp(self):
        super().setUp()
        self.warehouse = Warehouse(self.conn, today=lambda: TODAY)
        self.warehouse.actor = "Rahbar"


class BarcodeAndUnitTests(ExtrasTestCase):
    def test_product_is_found_by_barcode(self):
        nail = self.warehouse.save_product(Product("Mix 100", "kg", barcode=" 4780001234567 "))
        self.assertEqual(self.warehouse.product_by_barcode("4780001234567").id, nail)
        self.assertIsNone(self.warehouse.product_by_barcode("000"))
        self.assertIsNone(self.warehouse.product_by_barcode(""))
        self.assertEqual([p.id for p in self.warehouse.products("47800012")], [nail])

    def test_barcode_must_be_unique_but_may_stay_on_its_own_product(self):
        nail = self.warehouse.save_product(Product("Mix 100", "kg", barcode="111"))
        with self.assertRaises(WarehouseError):
            self.warehouse.save_product(Product("Mix 120", "kg", barcode="111"))
        product = self.warehouse.product(nail)
        product.note = "o'zgardi"
        self.warehouse.save_product(product)
        self.warehouse.save_product(Product("Kodsiz 1", "kg"))
        self.warehouse.save_product(Product("Kodsiz 2", "kg"))

    def test_alternative_unit(self):
        cement = self.warehouse.save_product(Product("Sement", "kg", alt_unit="tonna", alt_factor=1000))
        product = self.warehouse.product(cement)
        self.assertTrue(product.has_alt_unit)
        self.assertEqual((product.alt_unit, product.alt_factor), ("tonna", 1000))
        self.assertFalse(self.warehouse.product(self.pipe).has_alt_unit)

    def test_alternative_unit_needs_a_factor_and_must_differ(self):
        with self.assertRaises(WarehouseError):
            self.warehouse.save_product(Product("Sement", "kg", alt_unit="tonna"))
        same = self.warehouse.save_product(Product("Qum", "kg", alt_unit="KG", alt_factor=5))
        self.assertFalse(self.warehouse.product(same).has_alt_unit)


class GroupCatalogTests(ExtrasTestCase):
    def setUp(self):
        super().setUp()
        self.groups = GroupCatalog(self.conn)
        self.addCleanup(catalog._index, catalog.GROUPS)

    def test_new_database_starts_with_the_default_list(self):
        self.assertEqual([g.name.ru for g in catalog.groups()], [g.name.ru for g in catalog.GROUPS])
        self.assertEqual(len(catalog.find_group("Стройматериал").subgroups), 12)
        self.assertIsNotNone(catalog.groups()[0].id)

    def test_add_group_and_subgroup(self):
        group_id = self.groups.add("Bo'yoqlar", "Краски")
        self.groups.add("Emal", parent_id=group_id)
        group = catalog.find_group("Краски")
        self.assertEqual((group.name.uz, [s.ru for s in group.subgroups]), ("Bo'yoqlar", ["Emal"]))
        self.assertEqual(catalog.display_name("Краски"), "Bo'yoqlar")

    def test_duplicate_and_empty_names_are_rejected(self):
        with self.assertRaises(WarehouseError):
            self.groups.add("Boshqa nom", "стройматериал")
        with self.assertRaises(WarehouseError):
            self.groups.add("  ")
        parent = catalog.find_group("Стройматериал").id
        with self.assertRaises(WarehouseError):
            self.groups.add("Sement", "Цемент", parent_id=parent)

    def test_rename_updates_existing_records(self):
        self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, 1, 100, category="Стройматериал", subcategory="Метал")
        )
        group = catalog.find_group("Стройматериал")
        metal = next(s for s in group.subgroups if s.ru == "Метал")
        self.groups.rename(metal.id, "Metall prokat", "Металлопрокат")
        self.groups.rename(group.id, "Qurilish mollari", "Стройматериалы")
        (movement,) = self.warehouse.movements()
        self.assertEqual((movement.category, movement.subcategory), ("Стройматериалы", "Металлопрокат"))
        self.assertEqual(catalog.display_name("Металлопрокат"), "Metall prokat")

    def test_delete_keeps_old_records_readable(self):
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 1, 100, category="ГСМ"))
        self.groups.delete(catalog.find_group("ГСМ").id)
        self.assertIsNone(catalog.find_group("ГСМ"))
        self.assertEqual(len(catalog.groups()), 11)
        self.assertEqual(self.warehouse.movements()[0].category, "ГСМ")
        self.assertEqual(self.conn.execute("SELECT COUNT(*) FROM groups WHERE parent_id IS NULL").fetchone()[0], 11)

    def test_changes_survive_reconnect(self):
        import tempfile
        from pathlib import Path

        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ombor.db"
            conn = connect(path)
            GroupCatalog(conn).add("Bo'yoqlar")
            conn.close()
            catalog._index(catalog.GROUPS)
            conn = connect(path)
            try:
                self.assertIsNotNone(catalog.find_group("Bo'yoqlar"))
                self.assertEqual(len(catalog.groups()), 13)
            finally:
                conn.close()


class ReturnTests(ExtrasTestCase):
    def setUp(self):
        super().setUp()
        self.analytics = Analytics(self.conn)
        self.receive(10, 1000)
        self.issue(6, sale_price=1500, site="Xaridor")

    def test_customer_return_reduces_revenue_and_profit_and_restores_stock(self):
        self.warehouse.save_movement(
            Movement(
                MovementKind.IN, TODAY, self.pipe, 2, 1000, sale_price=1500, is_return=True, counterparty="Xaridor"
            )
        )
        summary = self.analytics.summary()
        self.assertEqual((summary.revenue, summary.cost, summary.profit, summary.sales_count), (6000, 4000, 2000, 1))
        self.assertEqual(self.warehouse.product(self.pipe).stock, 6)
        (line,) = self.analytics.by_product()
        self.assertEqual((line.quantity, line.revenue, line.profit), (4, 6000, 2000))

    def test_ordinary_receipt_never_keeps_a_sale_price(self):
        receipt = self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 1, 1000, sale_price=999))
        self.assertEqual(self.warehouse.movement(receipt).sale_price, 0)

    def test_return_to_supplier_is_not_a_sale(self):
        self.warehouse.save_movement(
            Movement(MovementKind.OUT, TODAY, self.pipe, 3, sale_price=1000, is_return=True, counterparty="Temir bozor")
        )
        summary = self.analytics.summary()
        self.assertEqual((summary.revenue, summary.profit, summary.internal_use), (9000, 3000, 0))
        self.assertEqual(self.warehouse.product(self.pipe).stock, 1)
        (returned,) = [m for m in self.warehouse.movements(MovementKind.OUT) if m.is_return]
        self.assertEqual((returned.price, returned.revenue, returned.is_sale), (1000, 0, False))


class DebtTests(ExtrasTestCase):
    def setUp(self):
        super().setUp()
        self.debts = Debts(self.conn)
        self.debts.actor = "Rahbar"

    def _receipt(self, quantity, price, supplier, on_credit=True):
        return self.warehouse.save_movement(
            Movement(MovementKind.IN, TODAY, self.pipe, quantity, price, counterparty=supplier, on_credit=on_credit)
        )

    def test_only_credit_records_create_debt(self):
        self._receipt(10, 1000, "Temir bozor")
        self._receipt(5, 1000, "Naqd firma", on_credit=False)
        (balance,) = self.debts.balances(MovementKind.IN)
        self.assertEqual((balance.counterparty, balance.debt), ("Temir bozor", 10_000))

    def test_payment_and_return_reduce_supplier_debt(self):
        self._receipt(10, 1000, "Temir bozor")
        self.debts.add_payment(Payment(MovementKind.IN, TODAY, "temir bozor", 4000))
        self.warehouse.save_movement(
            Movement(
                MovementKind.OUT,
                TODAY,
                self.pipe,
                2,
                sale_price=1000,
                is_return=True,
                on_credit=True,
                counterparty="Temir bozor",
            )
        )
        (balance,) = self.debts.balances(MovementKind.IN)
        self.assertEqual((balance.credited, balance.returned, balance.paid, balance.debt), (10_000, 2000, 4000, 4000))
        self.assertEqual(self.debts.total(MovementKind.IN), 4000)

    def test_customer_debt(self):
        self._receipt(10, 1000, "Temir bozor", on_credit=False)
        self.warehouse.save_movement(
            Movement(MovementKind.OUT, TODAY, self.pipe, 4, sale_price=1500, counterparty="Obyekt-1", on_credit=True)
        )
        self.debts.add_payment(Payment(MovementKind.OUT, TODAY, "Obyekt-1", 6000))
        self.assertEqual(self.debts.balances(MovementKind.OUT), [])
        (settled,) = self.debts.balances(MovementKind.OUT, include_settled=True)
        self.assertEqual((settled.credited, settled.paid, settled.debt), (6000, 6000, 0))
        self.assertEqual(self.debts.balances(MovementKind.IN), [])

    def test_deleted_record_no_longer_counts(self):
        receipt = self._receipt(10, 1000, "Temir bozor")
        self.warehouse.delete_movement(receipt)
        self.assertEqual(self.debts.balances(MovementKind.IN), [])

    def test_credit_needs_a_counterparty(self):
        with self.assertRaises(WarehouseError):
            self._receipt(10, 1000, "  ")

    def test_payment_validation_and_deletion(self):
        for payment in (
            Payment(MovementKind.IN, TODAY, "", 100),
            Payment(MovementKind.IN, TODAY, "Temir bozor", 0),
            Payment(MovementKind.IN, TODAY + timedelta(days=400), "Temir bozor", 5),
        ):
            with self.assertRaises(WarehouseError):
                self.debts.add_payment(payment)
        payment_id = self.debts.add_payment(Payment(MovementKind.IN, TODAY, "Temir bozor", 500, created_by="Rahbar"))
        self.assertEqual([p.amount for p in self.debts.payments(MovementKind.IN)], [500])
        self.assertEqual(self.debts.balances(MovementKind.IN)[0].debt, -500)  # oldindan to'langan
        self.debts.delete_payment(payment_id)
        self.assertEqual(self.debts.payments(), [])
        actions = [e.action for e in self.warehouse.history() if e.entity.startswith("payment")]
        self.assertEqual(actions, [HistoryAction.DELETE, HistoryAction.ADD])


class StoreTests(ExtrasTestCase):
    def setUp(self):
        super().setUp()
        self.site = self.warehouse.save_store("Obyekt ombori")
        self.receive(10, 1000)

    def _move(self, quantity, source=MAIN_WAREHOUSE_ID, target=None, day=TODAY):
        return self.warehouse.transfer(
            Transfer(day, self.pipe, quantity, source, self.site if target is None else target, created_by="Rahbar")
        )

    def test_main_store_always_exists(self):
        self.assertEqual(
            [(s.id, s.name) for s in self.warehouse.stores()], [(1, "Asosiy ombor"), (self.site, "Obyekt ombori")]
        )
        with self.assertRaises(WarehouseError):
            self.warehouse.delete_store(MAIN_WAREHOUSE_ID)
        with self.assertRaises(WarehouseError):
            self.warehouse.save_store("obyekt OMBORI")

    def test_transfer_moves_stock_but_not_total_or_cost(self):
        self._move(4)
        self.assertEqual(self.warehouse.product(self.pipe).stock, 10)
        self.assertEqual(self.warehouse.product(self.pipe, MAIN_WAREHOUSE_ID).stock, 6)
        site = self.warehouse.product(self.pipe, self.site)
        self.assertEqual((site.stock, site.value, site.total_stock), (4, 4000, 10))
        self.assertEqual(self.reports.stock_value(), 10_000)
        (transfer,) = self.warehouse.transfers()
        self.assertEqual(
            (transfer.from_name, transfer.to_name, transfer.quantity), ("Asosiy ombor", "Obyekt ombori", 4)
        )

    def test_cannot_issue_or_move_more_than_the_store_holds(self):
        self._move(4)
        with self.assertRaises(WarehouseError):
            self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 5, warehouse_id=self.site))
        with self.assertRaises(WarehouseError):
            self._move(7)
        with self.assertRaises(WarehouseError):
            self.issue(7)  # asosiy omborda 6 qolgan, garchi jami 10 bo'lsa ham
        self.warehouse.save_movement(Movement(MovementKind.OUT, TODAY, self.pipe, 4, warehouse_id=self.site))
        self.assertEqual(self.warehouse.product(self.pipe, self.site).stock, 0)

    def test_transfer_validation(self):
        with self.assertRaises(WarehouseError):
            self._move(1, target=MAIN_WAREHOUSE_ID)
        with self.assertRaises(WarehouseError):
            self._move(0)
        with self.assertRaises(WarehouseError):
            self._move(1, day=TODAY + timedelta(days=1))
        with self.assertRaises(WarehouseError):
            self._move(1, day=TODAY - timedelta(days=1))  # kecha omborda hali yo'q edi

    def test_receipt_cannot_be_deleted_after_it_was_moved(self):
        (receipt,) = self.warehouse.movements(MovementKind.IN)
        self._move(4)
        with self.assertRaises(WarehouseError):
            self.warehouse.delete_movement(receipt.id)

    def test_inventory_is_taken_per_store(self):
        self._move(4)
        self.warehouse.take_inventory({self.pipe: 3}, TODAY, "Rahbar", warehouse_id=self.site)
        self.assertEqual(self.warehouse.product(self.pipe, self.site).stock, 3)
        self.assertEqual(self.warehouse.product(self.pipe, MAIN_WAREHOUSE_ID).stock, 6)
        (shortage,) = self.warehouse.movements(MovementKind.OUT)
        self.assertEqual(
            (shortage.warehouse_id, shortage.warehouse_name, shortage.quantity), (self.site, "Obyekt ombori", 1)
        )

    def test_movements_can_be_filtered_by_store(self):
        self.warehouse.save_movement(Movement(MovementKind.IN, TODAY, self.pipe, 2, 1000, warehouse_id=self.site))
        self.assertEqual(len(self.warehouse.movements(warehouse_id=self.site)), 1)
        self.assertEqual(len(self.warehouse.movements()), 2)

    def test_store_with_records_cannot_be_deleted_but_empty_one_can(self):
        self._move(1)
        with self.assertRaises(WarehouseError):
            self.warehouse.delete_store(self.site)
        empty = self.warehouse.save_store("Vaqtinchalik")
        self.warehouse.save_store("Zaxira ombor", empty)
        self.warehouse.delete_store(empty)
        self.assertEqual(len(self.warehouse.stores()), 2)
