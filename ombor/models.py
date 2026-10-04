"""Ombor ma'lumotlarining tuzilmalari."""

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from .i18n import tr


class MovementKind(str, Enum):
    IN = "IN"  # kirim — omborga keldi
    OUT = "OUT"  # chiqim — ombordan olindi (rasxod)


class Role(Enum):
    """Foydalanuvchi lavozimi. Omborchi faqat qo'shadi va ko'radi; rahbar hammasini qila oladi."""

    ADMIN = "admin"
    KEEPER = "keeper"

    @property
    def title(self) -> str:
        return {Role.ADMIN: tr("Rahbar"), Role.KEEPER: tr("Omborchi")}[self]


@dataclass(frozen=True)
class User:
    id: int
    name: str
    role: Role

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


class StockStatus(Enum):
    OK = tr("Yetarli")
    LOW = tr("Kam qoldi")
    EMPTY = tr("Tugagan")


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
    name: str
    unit: str
    min_stock: float = 0.0
    note: str = ""
    id: int | None = None


@dataclass
class ProductStock(Product):
    """Mahsulot va uning ombordagi holati."""

    qty_in: float = 0.0
    qty_out: float = 0.0
    amount_in: float = 0.0
    amount_out: float = 0.0

    @property
    def stock(self) -> float:
        return round(self.qty_in - self.qty_out, 6)

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
        if self.stock <= 0:
            return StockStatus.EMPTY
        if self.stock <= self.min_stock:
            return StockStatus.LOW
        return StockStatus.OK


@dataclass
class Movement:
    """Bitta kirim yoki chiqim yozuvi.

    `price` — kirimda sotib olish narxi; chiqimda tannarx (dastur o'zi hisoblaydi).
    `sale_price` — chiqim sotuv bo'lsa, sotuv narxi; 0 — ichki rasxod.
    `category`, `subcategory` — tovar va xizmatlar guruhi va kichik guruhi (catalog.py).
    `person` — kirimda kim olib kelgani, chiqimda kim olgani.
    `counterparty` — kirimda yetkazib beruvchi, chiqimda obyekt.
    `created_by` — yozuvni kiritgan foydalanuvchi; keyin o'zgarmaydi.
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
    id: int | None = None


@dataclass
class MovementDetails(Movement):
    """Ro'yxatda ko'rsatish uchun mahsulot nomi va summasi bilan to'ldirilgan yozuv."""

    product_name: str = ""
    unit: str = ""
    amount: float = 0.0  # kirimda xarid summasi, chiqimda tannarx summasi
    revenue: float = 0.0  # sotuv summasi
    profit: float = 0.0  # sotuv summasi minus tannarx; sotuv bo'lmasa 0

    @property
    def is_sale(self) -> bool:
        return self.sale_price > 0


@dataclass(frozen=True)
class ImportedProduct:
    """Excel faylidan o'qilgan mahsulot qatori; `stock` > 0 bo'lsa, boshlang'ich kirim yaratiladi."""

    name: str
    unit: str
    min_stock: float = 0.0
    stock: float = 0.0
    price: float = 0.0
