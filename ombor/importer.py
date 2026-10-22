"""Exceldan o'qilgan hisobni bazaga yozish: guruhlar, omborlar, obyektlar, mahsulotlar, kirim va chiqim.

Tartib: avval bog'lanadigan narsalar (guruh, ombor, obyekt, mahsulot), keyin yozuvlar sana bo'yicha —
bir kunda avval kirim, keyin chiqim, shunda qoldiq to'g'ri hisoblanadi va chiqim tannarxi o'zi chiqadi.

Bir faylni qayta yuklash xavfsiz: bazada aynan shunday yozuv (turi, sanasi, mahsuloti, miqdori, narxi,
hujjat raqami va kontragenti bir xil) bo'lsa, u qayta qo'shilmaydi. Shuning uchun Excelni tuzatib,
qayta yuklash mumkin — faqat yetishmagan yozuvlar qo'shiladi.

Bitta qator xato bo'lsa (masalan, chiqimga qoldiq yetmasa), qolganlari baribir yoziladi; xato qatorlar
hisobotda varaq va qator raqami bilan ko'rsatiladi.
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import date

from . import catalog
from .catalog import GroupCatalog
from .database import MAIN_WAREHOUSE_ID
from .errors import WarehouseError
from .excel_import import DEFAULT_UNIT, ExcelBook, ImportedMovement, ImportedProduct
from .models import Movement, MovementKind, Product, ProductStock, Site
from .sites import Sites
from .warehouse import OPENING_BALANCE, Warehouse

_DuplicateKey = tuple


@dataclass(frozen=True)
class ImportPlan:
    """Yuklashdan oldin ko'rsatiladigan xulosa."""

    new_products: int
    known_products: int
    new_movements: int
    duplicates: int  # bazada allaqachon bor — qo'shilmaydi
    new_sites: int
    receipts: int
    issues: int

    @property
    def has_changes(self) -> bool:
        return bool(self.new_products or self.new_movements or self.new_sites)


@dataclass
class ImportReport:
    products: int = 0
    movements: int = 0
    sites: int = 0
    duplicates: int = 0
    failed: list[str] = field(default_factory=list)  # «Kirim», 7-qator: sababi


class ExcelImporter:
    def __init__(self, warehouse: Warehouse, sites: Sites, groups: GroupCatalog):
        self._warehouse = warehouse
        self._sites = sites
        self._groups = groups

    # --- Xulosa ------------------------------------------------------------

    def plan(self, book: ExcelBook) -> ImportPlan:
        products = self._products_by_name()
        names = {item.name.casefold() for item in book.products} | {m.product.casefold() for m in book.movements}
        known_sites = {site.name.casefold() for site in self._sites.all()}
        movements = self._all_movements(book)
        existing = self._existing_keys()
        new = 0
        for movement in movements:
            product = products.get(movement.product.casefold())
            key = self._key(movement, product.id) if product else None
            if key is not None and existing[key] > 0:
                existing[key] -= 1
            else:
                new += 1
        return ImportPlan(
            new_products=len(names - products.keys()),
            known_products=len(names & products.keys()),
            new_movements=new,
            duplicates=len(movements) - new,
            new_sites=len({site.name.casefold() for site in book.sites} - known_sites),
            receipts=sum(m.kind is MovementKind.IN for m in book.movements),
            issues=sum(m.kind is MovementKind.OUT for m in book.movements),
        )

    # --- Yozish ------------------------------------------------------------

    def apply(self, book: ExcelBook, author: str, today: date | None = None) -> ImportReport:
        report = ImportReport()
        self._add_sites(book, report)
        self._add_products(book, report)
        products = self._products_by_name()
        stores = {store.name.casefold(): store.id for store in self._warehouse.stores()}
        existing = self._existing_keys()
        for movement in sorted(self._all_movements(book), key=lambda m: (m.date, m.kind is MovementKind.OUT)):
            try:
                product = products[movement.product.casefold()]
                key = self._key(movement, product.id)
                if existing[key] > 0:
                    existing[key] -= 1
                    report.duplicates += 1
                    continue
                self._warehouse.save_movement(self._to_movement(movement, product, stores, author), require_group=False)
                report.movements += 1
            except WarehouseError as error:
                report.failed.append(f"{movement.source}: {error}")
        return report

    def _add_sites(self, book: ExcelBook, report: ImportReport) -> None:
        known = {site.name.casefold() for site in self._sites.all()}
        for site in book.sites:
            if site.name.casefold() in known:
                continue
            try:
                self._sites.save(Site(site.name, site.address, site.manager, site.note))
            except WarehouseError as error:
                report.failed.append(f"{site.name}: {error}")
                continue
            known.add(site.name.casefold())
            report.sites += 1

    def _add_products(self, book: ExcelBook, report: ImportReport) -> None:
        """Yangi mahsulotlar qo'shiladi; bor mahsulotning bo'sh guruhi Exceldagi bilan to'ldiriladi."""
        products = self._products_by_name()
        rows: dict[str, ImportedProduct] = {}
        for item in book.products:
            rows.setdefault(item.name.casefold(), item)
        for movement in book.movements:  # faqat kirim-chiqimda uchragan mahsulotlar ham qo'shiladi
            rows.setdefault(
                movement.product.casefold(),
                ImportedProduct(
                    movement.product,
                    movement.unit,
                    category=movement.category,
                    subcategory=movement.subcategory,
                    source=movement.source,
                ),
            )
        for key, item in rows.items():
            existing = products.get(key)
            try:
                category, subcategory = self._group(item.category, item.subcategory)
                if existing is None:
                    self._warehouse.save_product(
                        Product(
                            name=item.name,
                            unit=item.unit or DEFAULT_UNIT,
                            min_stock=item.min_stock,
                            note=item.note,
                            barcode=item.barcode,
                            category=category,
                            subcategory=subcategory,
                        )
                    )
                    report.products += 1
                elif category and not existing.category:
                    self._warehouse.save_product(
                        Product(**{**_product_fields(existing), "category": category, "subcategory": subcategory})
                    )
            except WarehouseError as error:
                report.failed.append(f"{item.source}: {error}")

    def _all_movements(self, book: ExcelBook) -> list[ImportedMovement]:
        """Excel yozuvlari va mahsulotlar varag'idagi boshlang'ich qoldiqlar (kirim sifatida).

        Boshlang'ich qoldiq sanasi: ustunda berilgan bo'lsa — o'sha, aks holda shu mahsulotning
        Exceldagi eng birinchi yozuvi sanasi (yozuvlari bo'lmasa — bugun).
        """
        first_dates: dict[str, date] = {}
        for movement in book.movements:
            name = movement.product.casefold()
            first_dates[name] = min(first_dates.get(name, movement.date), movement.date)
        openings = [
            ImportedMovement(
                kind=MovementKind.IN,
                date=item.stock_date or first_dates.get(item.name.casefold(), date.today()),
                product=item.name,
                quantity=item.stock,
                price=item.price,
                counterparty=OPENING_BALANCE,
                category=item.category,
                subcategory=item.subcategory,
                source=item.source,
            )
            for item in book.products
            if item.stock > 0
        ]
        return openings + list(book.movements)

    def _to_movement(
        self, movement: ImportedMovement, product: ProductStock, stores: dict[str, int], author: str
    ) -> Movement:
        factor = _unit_factor(movement.unit, product)
        category, subcategory = self._group(movement.category, movement.subcategory)
        if not category:
            category, subcategory = self._warehouse.default_group(product.id)
        return Movement(
            kind=movement.kind,
            date=movement.date,
            product_id=product.id,
            quantity=round(movement.quantity * factor, 6),
            price=movement.price / factor,
            sale_price=movement.sale_price / factor,
            category=category,
            subcategory=subcategory,
            person=movement.person,
            counterparty=movement.counterparty,
            note=movement.note,
            created_by=author,
            doc_number=movement.doc_number,
            is_return=movement.is_return,
            on_credit=movement.on_credit,
            warehouse_id=self._store(movement.warehouse, stores),
            payment=movement.payment,
            unpaid=movement.unpaid,
        )

    def _store(self, name: str, stores: dict[str, int]) -> int:
        """Ombor nomi bo'yicha; ro'yxatda bo'lmasa — yangi ombor qo'shiladi; bo'sh bo'lsa — asosiy ombor."""
        if not name:
            return MAIN_WAREHOUSE_ID
        if name.casefold() not in stores:
            stores[name.casefold()] = self._warehouse.save_store(name)
        return stores[name.casefold()]

    def _group(self, category: str, subcategory: str) -> tuple[str, str]:
        """Exceldagi guruh nomi (o'zbekcha yoki ruscha) — bazadagi nomi; yangi guruh va kategoriya qo'shiladi."""
        if not category and not subcategory:
            return "", ""
        group = _find(category, catalog.groups()) if category else None
        if group is None and category:
            self._groups.add(category)
            group = _find(category, catalog.groups())
        if group is None:  # faqat kategoriya yozilgan: u qaysi guruhda bo'lsa, o'sha
            group = next((g for g in catalog.groups() if _find_name(subcategory, g.subgroups)), None)
            if group is None:
                return "", ""
        if not subcategory:
            return group.name.ru, ""
        name = _find_name(subcategory, group.subgroups)
        if name is None:
            self._groups.add(subcategory, parent_id=group.id)
            group = _find(group.name.ru, catalog.groups())
            name = _find_name(subcategory, group.subgroups)
        return group.name.ru, name.ru

    def _products_by_name(self) -> dict[str, ProductStock]:
        return {product.name.casefold(): product for product in self._warehouse.products()}

    def _existing_keys(self) -> Counter:
        return Counter(
            self._key_of(
                m.kind,
                m.date,
                m.product_id,
                m.quantity,
                m.price if m.kind is MovementKind.IN else m.sale_price,
                m.doc_number,
                m.counterparty,
            )
            for m in self._warehouse.movements()
        )

    def _key(self, movement: ImportedMovement, product_id: int) -> _DuplicateKey:
        price = movement.price if movement.kind is MovementKind.IN else movement.sale_price
        return self._key_of(
            movement.kind,
            movement.date,
            product_id,
            movement.quantity,
            price,
            movement.doc_number,
            movement.counterparty,
        )

    @staticmethod
    def _key_of(kind, day, product_id, quantity, price, doc_number, counterparty) -> _DuplicateKey:
        return (
            kind,
            day,
            product_id,
            round(quantity, 6),
            round(price, 2),
            doc_number.strip(),
            counterparty.strip().casefold(),
        )


def _find(name: str, groups) -> "catalog.Group | None":
    key = name.strip().casefold()
    return next((g for g in groups if key in (g.name.ru.casefold(), g.name.uz.casefold())), None)


def _find_name(name: str, names) -> "catalog.Name | None":
    key = name.strip().casefold()
    return next((n for n in names if key in (n.ru.casefold(), n.uz.casefold())), None)


def _unit_factor(unit: str, product: ProductStock) -> float:
    """Yozuv mahsulotning qo'shimcha birligida (masalan, tonna) berilgan bo'lsa — asosiy birlikka o'tkazish."""
    if unit and product.has_alt_unit and unit.casefold() == product.alt_unit.casefold():
        return product.alt_factor
    return 1.0


def _product_fields(product: ProductStock) -> dict:
    return {name: getattr(product, name) for name in Product.__dataclass_fields__}
