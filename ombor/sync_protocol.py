"""Sinxronlash protokoli: dastur (mijoz) va markaziy server uchun umumiy ta'riflar.

Faqat Python standart kutubxonasidan foydalanadi: server shu modul bilan dasturning
qolgan qismisiz (PySide6 va SQLCipher o'rnatilmagan kompyuterda ham) ishlaydi.

Har bir sinxronlanadigan qator butun dunyo bo'yicha yagona `uid` bilan tanilib, serverga
JSON ko'rinishida boradi. Qatorning ichki `id` si har bir kompyuterda o'ziniki bo'lgani uchun
yuborilmaydi; boshqa jadvalga bog'lanish (`product_id` kabi) o'sha qatorning `uid` si bilan beriladi.
"""

from dataclasses import dataclass, field

PROTOCOL_VERSION = 1
TOKEN_HEADER = "Authorization"
DEVICE_HEADER = "X-Ombor-Device"
PROTOCOL_HEADER = "X-Ombor-Protocol"
PULL_LIMIT = 1000  # bitta so'rovda olinadigan o'zgarishlar soni
PUSH_LIMIT = 500  # bitta so'rovda yuboriladigan o'zgarishlar soni

# «Asosiy ombor» har bir bazada id = 1 bilan bor: hamma kompyuterda bir xil uid oladi.
MAIN_WAREHOUSE_UID = "main-warehouse"

# Har bir kompyuterning o'ziga tegishli sozlamalar: sinxronlanmaydi.
LOCAL_SETTINGS = frozenset({"backup_folder", "language", "theme", "password"})


@dataclass(frozen=True)
class TableSpec:
    """Sinxronlanadigan jadval.

    `references` — boshqa jadvalga bog'langan ustunlar: ustun -> o'sha jadval nomi.
    `unique` — butun baza bo'yicha takrorlanmasligi kerak bo'lgan ustun (katta-kichik harf farqsiz):
    ikki kompyuter internetsiz bir xil nomli mahsulot qo'shsa, server ikkinchisiga « (2)» qo'shadi.
    `key` — qatorni tanituvchi ustun: odatda `uid`; sozlamalarda — kalitning o'zi.
    """

    name: str
    references: dict[str, str] = field(default_factory=dict)
    unique: str = ""
    key: str = "uid"


# Tartib muhim: bog'langan jadval (masalan, mahsulot) undan foydalanadiganidan (kirim-chiqim) oldin turadi.
TABLES = (
    TableSpec("settings", key="key"),
    TableSpec("users", unique="name"),
    TableSpec("warehouses", unique="name"),
    TableSpec("groups", references={"parent_id": "groups"}),
    TableSpec("products", unique="name"),
    TableSpec("sites", unique="name"),
    TableSpec("employees", unique="name"),
    TableSpec("movements", references={"product_id": "products", "warehouse_id": "warehouses"}),
    TableSpec("transfers", references={"product_id": "products", "from_id": "warehouses", "to_id": "warehouses"}),
    TableSpec("payments"),
    TableSpec("salary_payments", references={"employee_id": "employees"}),
    TableSpec("history"),
)
TABLES_BY_NAME = {spec.name: spec for spec in TABLES}


@dataclass(frozen=True)
class Change:
    """Bitta qatorning holati: `data` — ustunlar qiymati; `deleted` bo'lsa — qator o'chirilgan."""

    table: str
    uid: str
    data: dict | None
    deleted: bool = False
    seq: int = 0  # serverdagi tartib raqami (serverdan kelganda)

    def to_json(self) -> dict:
        return {"table": self.table, "uid": self.uid, "data": self.data, "deleted": self.deleted, "seq": self.seq}

    @classmethod
    def from_json(cls, value: dict) -> "Change":
        table, uid = value.get("table"), value.get("uid")
        if table not in TABLES_BY_NAME or not isinstance(uid, str) or not uid:
            raise ValueError(f"Noto'g'ri o'zgarish: {table!r} / {uid!r}")
        deleted = bool(value.get("deleted"))
        data = value.get("data")
        if not deleted and not isinstance(data, dict):
            raise ValueError(f"O'zgarishda ma'lumot yo'q: {table} / {uid}")
        return cls(table, uid, None if deleted else data, deleted, int(value.get("seq") or 0))


def unique_key(spec: TableSpec, data: dict | None) -> str:
    """Takrorlanmaslik tekshiriladigan qiymat (katta-kichik harf farqsiz); jadvalda bunday cheklov bo'lmasa — bo'sh."""
    if not spec.unique or not data:
        return ""
    return str(data.get(spec.unique) or "").strip().casefold()
