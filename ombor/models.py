"""Ombor ma'lumotlarining tuzilmalari."""

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from enum import Enum

from .i18n import tr


class MovementKind(str, Enum):
    IN = "IN"  # kirim — omborga keldi
    OUT = "OUT"  # chiqim — ombordan olindi (rasxod)


class Role(Enum):
    """Foydalanuvchi lavozimi.

    Rahbar hammasini qila oladi. Omborchi yozuv qo'shadi va o'zi bugun kiritganini tuzata oladi.
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


@dataclass
class ProductStock(Product):
    """Mahsulot va uning ombordagi holati."""

    qty_in: float = 0.0
    qty_out: float = 0.0
    amount_in: float = 0.0
    amount_out: float = 0.0

    @property
    def stock(self) -> float:
        return 0.0 if self.is_service else round(self.qty_in - self.qty_out, 6)

    @property
    def value(self) -> float:
        """Ombordagi qoldiqning qiymati: kirimlar summasi minus chiqimlar tannarxi."""
        return max(self.amount_in - self.amount_out, 0.0) if self.stock > 0 else 0.0

    @property
    def average_price(self) -> float:
        """Ombordagi qoldiqning o'rtacha tannarxi; keyingi chiqim shu narxda baholanadi."""
        return self.value / self.stock if self.stock > 0 else 0.0

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
    `category`, `subcategory` — tovar va xizmatlar guruhi va kichik guruhi (catalog.py).
    `person` — kirimda kim olib kelgani, chiqimda kim olgani.
    `counterparty` — kirimda yetkazib beruvchi, chiqimda obyekt.
    `created_by` — yozuvni kiritgan foydalanuvchi; keyin o'zgarmaydi.
    `doc_number` — hujjat (nakladnoy) raqami; bir hujjatdagi mahsulotlar bir xil raqam bilan yoziladi.
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
    id: int | None = None


@dataclass
class MovementDetails(Movement):
    """Ro'yxatda ko'rsatish uchun mahsulot nomi va summasi bilan to'ldirilgan yozuv."""

    product_name: str = ""
    unit: str = ""
    amount: float = 0.0  # kirimda xarid summasi, chiqimda tannarx summasi
    revenue: float = 0.0  # sotuv summasi
    profit: float = 0.0  # sotuv summasi minus tannarx; sotuv bo'lmasa 0

    is_service: bool = False
    created_at: str = ""  # bazaga yozilgan vaqt: 'YYYY-MM-DD HH:MM:SS'
    deleted_at: str | None = None
    deleted_by: str = ""

    @property
    def is_sale(self) -> bool:
        return self.sale_price > 0

    @property
    def created_on(self) -> date | None:
        """Yozuv bazaga kiritilgan kun (yozuvning o'z sanasi emas)."""
        return datetime.fromisoformat(self.created_at).date() if self.created_at else None


class HistoryAction(Enum):
    ADD = "add"
    EDIT = "edit"
    DELETE = "delete"
    RESTORE = "restore"

    @property
    def title(self) -> str:
        return {
            HistoryAction.ADD: tr("Qo'shildi"),
            HistoryAction.EDIT: tr("O'zgartirildi"),
            HistoryAction.DELETE: tr("O'chirildi"),
            HistoryAction.RESTORE: tr("Tiklandi"),
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


@dataclass(frozen=True)
class ImportedProduct:
    """Excel faylidan o'qilgan mahsulot qatori; `stock` > 0 bo'lsa, boshlang'ich kirim yaratiladi."""

    name: str
    unit: str
    min_stock: float = 0.0
    stock: float = 0.0
    price: float = 0.0
