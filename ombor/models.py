"""Ombor ma'lumotlarining tuzilmalari."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

from .geo import Location
from .i18n import tr


class MovementKind(str, Enum):
    IN = "IN"  # kirim — omborga keldi
    OUT = "OUT"  # chiqim — ombordan olindi (rasxod)


class Role(Enum):
    """Foydalanuvchi lavozimi.

    Rahbar hammasini qila oladi. Omborchi yozuv qo'shadi, lekin tahrirlay va o'chira olmaydi.
    Kuzatuvchi (masalan, buxgalter) faqat ko'radi.
    """

    ADMIN = "admin"
    KEEPER = "keeper"
    VIEWER = "viewer"

    @property
    def title(self) -> str:
        return {Role.ADMIN: tr("Rahbar"), Role.KEEPER: tr("Omborchi"), Role.VIEWER: tr("Kuzatuvchi")}[self]


@dataclass(frozen=True)
class User:
    id: int
    name: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN

    @property
    def can_add(self) -> bool:
        return self.role is not Role.VIEWER


class StockStatus(Enum):
    OK = tr("Yetarli")
    LOW = tr("Kam qoldi")
    EMPTY = tr("Tugagan")
    SERVICE = tr("Xizmat")  # qoldig'i yuritilmaydi


@dataclass(frozen=True)
class Period:
    """Sana oralig'i; chegara `None` bo'lsa, o'sha tomoni cheklanmagan."""

    start: date | None = None
    end: date | None = None

    @classmethod
    def day_of(cls, day: date) -> "Period":
        return cls(day, day)

    @classmethod
    def week_of(cls, day: date) -> "Period":
        """Dushanbadan yakshanbagacha."""
        monday = day - timedelta(days=day.weekday())
        return cls(monday, monday + timedelta(days=6))

    @classmethod
    def month_of(cls, day: date) -> "Period":
        first = day.replace(day=1)
        next_month = (first + timedelta(days=32)).replace(day=1)
        return cls(first, next_month - timedelta(days=1))

    @classmethod
    def previous_month_of(cls, day: date) -> "Period":
        return cls.month_of(day.replace(day=1) - timedelta(days=1))

    @classmethod
    def year_of(cls, day: date) -> "Period":
        return cls(date(day.year, 1, 1), date(day.year, 12, 31))


class Granularity(Enum):
    """Hisobot davrining uzunligi: kun, hafta, oy yoki yil."""

    DAY = tr("Kunlik")
    WEEK = tr("Haftalik")
    MONTH = tr("Oylik")
    YEAR = tr("Yillik")

    def period_of(self, day: date) -> Period:
        """`day` kiradigan davr."""
        builders = {
            Granularity.DAY: Period.day_of,
            Granularity.WEEK: Period.week_of,
            Granularity.MONTH: Period.month_of,
            Granularity.YEAR: Period.year_of,
        }
        return builders[self](day)

    def shift(self, day: date, steps: int) -> date:
        """`day` dan `steps` davr keyingi (manfiy bo'lsa — oldingi) davrga tegishli kun."""
        if self is Granularity.DAY:
            return day + timedelta(days=steps)
        if self is Granularity.WEEK:
            return day + timedelta(weeks=steps)
        if self is Granularity.MONTH:
            months = day.year * 12 + day.month - 1 + steps
            return date(months // 12, months % 12 + 1, 1)
        return date(day.year + steps, 1, 1)


@dataclass
class Product:
    """`is_service` — xizmat yoki xarajat (yuk tashish, kommunal to'lov…): omborda qoldig'i yuritilmaydi."""

    name: str
    unit: str
    min_stock: float = 0.0
    note: str = ""
    id: int | None = None
    is_service: bool = False
    barcode: str = ""
    alt_unit: str = ""  # qo'shimcha o'lchov birligi (masalan, asosiysi kg bo'lsa — tonna)
    alt_factor: float = 0.0  # 1 qo'shimcha birlik = shuncha asosiy birlik
    category: str = ""  # mahsulot guruhi (catalog.py; ruscha nomi saqlanadi)
    subcategory: str = ""  # guruh ichidagi kategoriya

    @property
    def has_alt_unit(self) -> bool:
        return bool(self.alt_unit) and self.alt_factor > 0


@dataclass
class ProductStock(Product):
    """Mahsulot va uning ombordagi holati."""

    qty_in: float = 0.0
    qty_out: float = 0.0
    amount_in: float = 0.0
    amount_out: float = 0.0
    # Bitta ombor bo'yicha ko'rilayotganda — shu ombordagi qoldiq; None — barcha omborlar bo'yicha.
    local_stock: float | None = None

    @property
    def total_stock(self) -> float:
        """Barcha omborlardagi qoldiq."""
        return 0.0 if self.is_service else round(self.qty_in - self.qty_out, 6)

    @property
    def stock(self) -> float:
        """Ko'rilayotgan ombordagi qoldiq (ombor tanlanmagan bo'lsa — hammasi)."""
        if self.is_service:
            return 0.0
        return self.total_stock if self.local_stock is None else round(self.local_stock, 6)

    @property
    def average_price(self) -> float:
        """Qoldiqning o'rtacha tannarxi (barcha omborlar uchun bitta); keyingi chiqim shu narxda baholanadi."""
        total = self.total_stock
        return max(self.amount_in - self.amount_out, 0.0) / total if total > 0 else 0.0

    @property
    def value(self) -> float:
        """Qoldiqning qiymati: kirimlar summasi minus chiqimlar tannarxi."""
        if self.stock <= 0:
            return 0.0
        if self.local_stock is None:
            return max(self.amount_in - self.amount_out, 0.0)
        return self.stock * self.average_price

    @property
    def status(self) -> StockStatus:
        if self.is_service:
            return StockStatus.SERVICE
        if self.stock <= 0:
            return StockStatus.EMPTY
        if self.stock <= self.min_stock:
            return StockStatus.LOW
        return StockStatus.OK

    @property
    def needs_attention(self) -> bool:
        """Kam qolgan yoki tugagan (xizmatlarga taalluqli emas)."""
        return self.status in (StockStatus.LOW, StockStatus.EMPTY)


@dataclass
class Movement:
    """Bitta kirim yoki chiqim yozuvi.

    `price` — kirimda sotib olish narxi; chiqimda tannarx (dastur o'zi hisoblaydi).
    `sale_price` — chiqim sotuv bo'lsa, sotuv narxi; 0 — ichki rasxod.
    `category`, `subcategory` — tovar va xizmatlar guruhi va kategoriyasi (catalog.py).
    `person` — kirimda kim olib kelgani, chiqimda kim olgani.
    `counterparty` — kirimda yetkazib beruvchi, chiqimda obyekt.
    `created_by` — yozuvni kiritgan foydalanuvchi; keyin o'zgarmaydi.
    `doc_number` — hujjat (nakladnoy) raqami; bir hujjatdagi mahsulotlar bir xil raqam bilan yoziladi.
    `is_return` — qaytarish: kirimda xaridordan qaytgan mahsulot (`price` — omborga qaytadigan tannarx,
    `sale_price` — xaridorga qaytariladigan narx); chiqimda yetkazib beruvchiga qaytarilgan mahsulot
    (`sale_price` — yetkazib beruvchi qaytaradigan narx).
    `on_credit` — qarzga: summasi kontragent bilan hisob-kitobga (debts.py) tushadi.
    `payment` — to'lov turi (payments.py); `unpaid` — to'lov holati: to'lanmagan.
    """

    kind: MovementKind
    date: date
    product_id: int
    quantity: float
    price: float = 0.0
    sale_price: float = 0.0
    category: str = ""
    subcategory: str = ""
    person: str = ""
    counterparty: str = ""
    note: str = ""
    created_by: str = ""
    doc_number: str = ""
    is_return: bool = False
    on_credit: bool = False
    warehouse_id: int = 1
    id: int | None = None
    payment: str = ""
    unpaid: bool = False


@dataclass
class MovementDetails(Movement):
    """Ro'yxatda ko'rsatish uchun mahsulot nomi va summasi bilan to'ldirilgan yozuv."""

    product_name: str = ""
    unit: str = ""
    amount: float = 0.0  # kirimda xarid summasi, chiqimda tannarx summasi
    revenue: float = 0.0  # sotuv summasi
    profit: float = 0.0  # sotuv summasi minus tannarx; sotuv bo'lmasa 0

    is_service: bool = False
    warehouse_name: str = ""
    cost_of_sales: float = 0.0  # sotilgan mahsulot tannarxi (qaytarishda manfiy)
    created_at: str = ""  # bazaga yozilgan vaqt: 'YYYY-MM-DD HH:MM:SS'
    deleted_at: str | None = None
    deleted_by: str = ""

    @property
    def is_sale(self) -> bool:
        return self.kind is MovementKind.OUT and not self.is_return and self.sale_price > 0

    @property
    def created_on(self) -> date | None:
        """Yozuv bazaga kiritilgan kun (yozuvning o'z sanasi emas)."""
        return datetime.fromisoformat(self.created_at).date() if self.created_at else None


class HistoryAction(Enum):
    ADD = "add"
    EDIT = "edit"
    DELETE = "delete"
    RESTORE = "restore"
    CLEAR = "clear"

    @property
    def title(self) -> str:
        return {
            HistoryAction.ADD: tr("Qo'shildi"),
            HistoryAction.EDIT: tr("O'zgartirildi"),
            HistoryAction.DELETE: tr("O'chirildi"),
            HistoryAction.RESTORE: tr("Tiklandi"),
            HistoryAction.CLEAR: tr("Tarix tozalandi"),
        }[self]


@dataclass(frozen=True)
class HistoryEntry:
    """O'zgarishlar tarixidagi bitta qator. `entity` — 'IN', 'OUT' yoki 'product'."""

    id: int
    at: datetime
    actor: str
    action: HistoryAction
    entity: str
    entity_id: int | None
    summary: str
    previous: str
    actor_role: str = ""  # lavozimi (Role qiymati); eski yozuvlarda bo'sh bo'lishi mumkin

    @property
    def role_title(self) -> str:
        try:
            return Role(self.actor_role).title
        except ValueError:
            return self.actor_role


@dataclass(frozen=True)
class Store:
    """Ombor (sklad). Bittasi — «Asosiy ombor» — har doim bor."""

    id: int
    name: str


@dataclass(frozen=True)
class Site:
    """Obyekt — mahsulot beriladigan va ortgani omborga qaytadigan qurilish (montaj) joyi."""

    name: str
    address: str = ""
    manager: str = ""  # mas'ul shaxs (masalan, prorab)
    note: str = ""
    id: int | None = None
    latitude: float | None = None  # xaritadagi joyi; kiritilmagan bo'lsa — None
    longitude: float | None = None

    @property
    def location(self) -> Location | None:
        if self.latitude is None or self.longitude is None:
            return None
        return Location(self.latitude, self.longitude)


@dataclass(frozen=True)
class SiteTotals(Site):
    """Obyekt va unga berilgan hamda undan qaytgan mahsulotlarning tannarxi."""

    issued: float = 0.0
    returned: float = 0.0

    @property
    def remaining(self) -> float:
        """Obyektda qolgan (ishlatilgan yoki hali qaytmagan) mahsulotlar tannarxi."""
        return self.issued - self.returned


@dataclass(frozen=True)
class SiteProduct:
    """Bitta obyektdagi bitta mahsulot: qancha berilgan va qancha qaytgan."""

    site: str
    product_id: int
    product_name: str
    unit: str
    issued: float
    returned: float
    issued_amount: float  # berilgan mahsulotning tannarxi
    returned_amount: float  # qaytgan mahsulotning tannarxi

    @property
    def remaining(self) -> float:
        return round(self.issued - self.returned, 6)

    @property
    def net_amount(self) -> float:
        """Obyektning shu mahsulot bo'yicha sof xarajati: berilgan minus qaytgan."""
        return self.issued_amount - self.returned_amount


@dataclass(frozen=True)
class SiteReturn:
    """Obyektdan omborga qaytgan mahsulot (vozvrat); narxi va guruhini dastur o'zi to'ldiradi."""

    date: date
    site_id: int
    product_id: int
    quantity: float
    person: str = ""  # kim olib keldi
    note: str = ""
    doc_number: str = ""
    created_by: str = ""
    warehouse_id: int = 1
    id: int | None = None


@dataclass(frozen=True)
class Transfer:
    """Mahsulotni bir ombordan boshqasiga ko'chirish."""

    date: date
    product_id: int
    quantity: float
    from_id: int
    to_id: int
    note: str = ""
    created_by: str = ""
    id: int | None = None
    product_name: str = ""
    unit: str = ""
    from_name: str = ""
    to_name: str = ""


@dataclass(frozen=True)
class Payment:
    """To'lov. `kind`: IN — yetkazib beruvchiga to'ladik; OUT — xaridor bizga to'ladi."""

    kind: MovementKind
    date: date
    counterparty: str
    amount: float
    note: str = ""
    created_by: str = ""
    id: int | None = None


@dataclass(frozen=True)
class Balance:
    """Bitta kontragent bilan hisob-kitob: qarzga berilgan/olingan, qaytarilgan, to'langan."""

    counterparty: str
    credited: float
    returned: float
    paid: float

    @property
    def debt(self) -> float:
        """Qolgan qarz; manfiy bo'lsa — ortiqcha to'langan."""
        return self.credited - self.returned - self.paid


@dataclass(frozen=True)
class PurchaseLine:
    """Xarid ro'yxatining qatori: kam qolgan mahsulot, qancha olish kerakligi va oxirgi xaridi."""

    product: ProductStock
    quantity: float  # olish tavsiya qilinadigan miqdor
    last_price: float  # oxirgi kirim narxi (1 birlik); xarid bo'lmagan bo'lsa — 0
    last_supplier: str

    @property
    def amount(self) -> float:
        """Taxminiy summa: oxirgi narx bo'yicha."""
        return self.quantity * self.last_price
