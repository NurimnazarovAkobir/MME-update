"""Tovar va xizmatlar guruhlari hamda kichik guruhlari (ikki tilda).

Yozuvlarda ruscha nom saqlanadi (asl ro'yxat rus tilida berilgan); ekranda tanlangan
tilga qarab ko'rsatiladi. Ro'yxatda yo'q qiymat (eski versiyadan qolgan yoki
o'chirilgan guruh) o'zgarishsiz ko'rsatiladi.

`GROUPS` — boshlang'ich ro'yxat: yangi bazaga shu yoziladi. Amaldagi ro'yxat bazaning
`groups` jadvalida turadi va dastur ichidan tahrirlanadi (`GroupCatalog`); `load` uni
xotiraga o'qiydi, `groups()`, `find_group()` va `display_name()` shu xotiradan oladi.
"""

from dataclasses import dataclass

from . import i18n
from .driver import sqlite3
from .errors import WarehouseError
from .i18n import tr


@dataclass(frozen=True)
class Name:
    ru: str  # bazada saqlanadigan qiymat
    uz: str
    id: int | None = None  # `groups` jadvalidagi id; boshlang'ich ro'yxatda yo'q

    @property
    def display(self) -> str:
        return self.uz if i18n.language() == i18n.UZBEK else self.ru


@dataclass(frozen=True)
class Group:
    name: Name
    subgroups: tuple[Name, ...]

    @property
    def id(self) -> int | None:
        return self.name.id


def _group(ru: str, uz: str, *subgroups: tuple[str, str]) -> Group:
    return Group(Name(ru, uz), tuple(Name(*subgroup) for subgroup in subgroups))


GROUPS = (
    _group(
        "Административные расходы",
        "Ma'muriy xarajatlar",
        ("Административные расходы", "Ma'muriy xarajatlar"),
        ("Прочие админ. расходы", "Boshqa ma'muriy xarajatlar"),
        ("Хозтовары", "Xo'jalik mollari"),
        ("Канцтовары", "Kanselyariya mollari"),
    ),
    _group(
        "Грузоперевозка",
        "Yuk tashish",
        ("Грузоперевозка ГСМ", "Yuk tashish — yoqilg'i-moylash materiallari"),
        ("Грузоперевозка ЖБИ", "Yuk tashish — temir-beton buyumlari"),
        ("Грузоперевозка инерт", "Yuk tashish — inert materiallar"),
        ("Грузоперевозка метал", "Yuk tashish — metall"),
        ("Грузоперевозка прочие", "Yuk tashish — boshqa"),
        ("Грузоперевозка цемент", "Yuk tashish — sement"),
    ),
    _group(
        "ГСМ",
        "Yoqilg'i-moylash materiallari",
        ("ГСМ/бензин", "Benzin"),
        ("ГСМ/дизтопливо", "Dizel yoqilg'isi"),
        ("ГСМ/мот.масла", "Motor moylari"),
        ("ГСМ/сж-й газ", "Suyultirilgan gaz"),
    ),
    _group(
        "Обязательные платежи",
        "Majburiy to'lovlar",
        ("Гос.услуги", "Davlat xizmatlari"),
        ("Регистрация и лицензии И/Г", "Chet el fuqarolarini ro'yxatga olish va litsenziyalar"),
        ("Коммунальные платежи", "Kommunal to'lovlar"),
    ),
    _group(
        "Орг-мед-быт-техника",
        "Org-, tibbiy va maishiy texnika",
        ("Оргтехника", "Orgtexnika"),
        ("Мебель", "Mebel"),
        ("Видеонаблюдение", "Videokuzatuv"),
        ("Пожарный инвентарь", "Yong'inga qarshi inventar"),
        ("Комп-е/чернила/краска", "Kompyuter jihozlari / siyoh / bo'yoq"),
        ("Бытовая техника", "Maishiy texnika"),
        ("Измер-е и прочие приборы", "O'lchov va boshqa asboblar"),
    ),
    _group(
        "Представительские расходы",
        "Vakillik xarajatlari",
        ("Авиабилеты/иностранцы", "Aviachiptalar / chet elliklar"),
        ("Гостиничные услуги", "Mehmonxona xizmatlari"),
        ("ЖД билеты", "Temir yo'l chiptalari"),
        ("Представительские расходы прочие", "Boshqa vakillik xarajatlari"),
    ),
    _group(
        "Производственные расходы",
        "Ishlab chiqarish xarajatlari",
        ("Спец. одежда", "Maxsus kiyim"),
        ("Аренда оборуд-я и складов", "Uskuna va omborlar ijarasi"),
        ("Медикаменты", "Dori-darmonlar"),
        ("Постельный инвентарь", "Ko'rpa-to'shak inventari"),
        ("Производственные расходы прочие", "Boshqa ishlab chiqarish xarajatlari"),
        ("Основное средство", "Asosiy vosita"),
    ),
    _group("Продукты питания", "Oziq-ovqat mahsulotlari", ("Продукты питания", "Oziq-ovqat mahsulotlari")),
    _group("СМР", "Qurilish-montaj ishlari", ("СМР", "Qurilish-montaj ishlari")),
    _group(
        "Стр-е инстр-ты и малооценка",
        "Qurilish asboblari va kam baholi buyumlar",
        ("Стр-е инстр-ты и малооценка", "Qurilish asboblari va kam baholi buyumlar"),
    ),
    _group(
        "Стройматериал",
        "Qurilish materiallari",
        ("Метал", "Metall"),
        ("РЕ трубы и фитинги", "PE quvurlar va fitinglar"),
        ("Электротовары", "Elektr mollari"),
        ("ЖБИ продукция", "Temir-beton buyumlari"),
        ("Цемент", "Sement"),
        ("Изоляционный материал", "Izolyatsiya materiali"),
        ("Инертный материал", "Inert material"),
        ("Кабельная продукция", "Kabel mahsulotlari"),
        ("Пиломатериалы", "Yog'och materiallari"),
        ("Товарный Бетон", "Tovar beton"),
        ("Хим.добавки к бетону", "Betonga kimyoviy qo'shimchalar"),
        ("Стройматериалы/прочие", "Boshqa qurilish materiallari"),
    ),
    _group(
        "Транспортное обслуживание",
        "Transport xizmati",
        ("Запасные части", "Ehtiyot qismlar"),
        ("Тех.обслуживание", "Texnik xizmat ko'rsatish"),
        ("Автотранспорт", "Avtotransport"),
    ),
)

_current: tuple[Group, ...] = GROUPS
_by_stored: dict[str, Group] = {}
_display: dict[str, Name] = {}


def _index(current: tuple[Group, ...]) -> None:
    global _current, _by_stored, _display
    _current = current
    _by_stored = {group.name.ru: group for group in current}
    _display = {name.ru: name for group in current for name in (group.name, *group.subgroups)}


_index(GROUPS)


def groups() -> tuple[Group, ...]:
    """Amaldagi guruhlar ro'yxati."""
    return _current


def find_group(stored: str) -> Group | None:
    """Yozuvdagi qiymat bo'yicha guruh; ro'yxatda bo'lmasa — None."""
    return _by_stored.get(stored)


def display_name(stored: str) -> str:
    """Guruh yoki kichik guruhning tanlangan tildagi nomi; ro'yxatda yo'q qiymat o'zgarishsiz qaytadi."""
    name = _display.get(stored)
    return name.display if name else stored


def seed(conn: sqlite3.Connection) -> None:
    """Bo'sh `groups` jadvaliga boshlang'ich ro'yxatni yozadi (tranzaksiya ichida chaqiriladi)."""
    if conn.execute("SELECT 1 FROM groups LIMIT 1").fetchone():
        return
    for group in GROUPS:
        cursor = conn.execute("INSERT INTO groups (ru, uz) VALUES (?, ?)", (group.name.ru, group.name.uz))
        conn.executemany(
            "INSERT INTO groups (parent_id, ru, uz) VALUES (?, ?, ?)",
            [(cursor.lastrowid, subgroup.ru, subgroup.uz) for subgroup in group.subgroups],
        )


def load(conn: sqlite3.Connection) -> None:
    """Bazadagi guruhlarni xotiraga o'qiydi; dastur ochilganda va har bir o'zgarishdan keyin chaqiriladi."""
    rows = conn.execute("SELECT id, parent_id, ru, uz FROM groups ORDER BY id").fetchall()
    children: dict[int, list[Name]] = {}
    for row in rows:
        if row["parent_id"] is not None:
            children.setdefault(row["parent_id"], []).append(Name(row["ru"], row["uz"], row["id"]))
    _index(
        tuple(
            Group(Name(row["ru"], row["uz"], row["id"]), tuple(children.get(row["id"], ())))
            for row in rows
            if row["parent_id"] is None
        )
    )


class GroupCatalog:
    """Guruhlarni dastur ichidan tahrirlash: qo'shish, nomini o'zgartirish, o'chirish."""

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def add(self, uz: str, ru: str = "", parent_id: int | None = None) -> int:
        """Guruh (yoki `parent_id` berilsa, kichik guruh) qo'shadi; ruscha nom bo'sh bo'lsa, o'zbekchasi olinadi."""
        uz, ru = self._names(uz, ru)
        self._check_unique(ru, parent_id)
        with self._conn:
            cursor = self._conn.execute(
                "INSERT INTO groups (parent_id, ru, uz) VALUES (?, ?, ?)", (parent_id, ru, uz)
            )
        load(self._conn)
        return cursor.lastrowid

    def rename(self, group_id: int, uz: str, ru: str = "") -> None:
        """Nomini o'zgartiradi; shu guruh yozilgan kirim va chiqimlar ham yangi nomga o'tadi."""
        uz, ru = self._names(uz, ru)
        row = self._row(group_id)
        self._check_unique(ru, row["parent_id"], except_id=group_id)
        with self._conn:
            self._conn.execute("UPDATE groups SET ru = ?, uz = ? WHERE id = ?", (ru, uz, group_id))
            if row["parent_id"] is None:
                self._conn.execute("UPDATE movements SET category = ? WHERE category = ?", (ru, row["ru"]))
            else:
                parent = self._row(row["parent_id"])
                self._conn.execute(
                    "UPDATE movements SET subcategory = ? WHERE category = ? AND subcategory = ?",
                    (ru, parent["ru"], row["ru"]),
                )
        load(self._conn)

    def delete(self, group_id: int) -> None:
        """Ro'yxatdan olib tashlaydi (kichik guruhlari bilan); eski yozuvlardagi nomi o'z holicha qoladi."""
        with self._conn:
            self._conn.execute("DELETE FROM groups WHERE parent_id = ?", (group_id,))
            self._conn.execute("DELETE FROM groups WHERE id = ?", (group_id,))
        load(self._conn)

    def _row(self, group_id: int) -> sqlite3.Row:
        row = self._conn.execute("SELECT * FROM groups WHERE id = ?", (group_id,)).fetchone()
        if row is None:
            raise WarehouseError(tr("Guruh topilmadi."))
        return row

    @staticmethod
    def _names(uz: str, ru: str) -> tuple[str, str]:
        uz, ru = uz.strip(), ru.strip()
        if not uz and not ru:
            raise WarehouseError(tr("Guruh nomini kiriting."))
        return uz or ru, ru or uz

    def _check_unique(self, ru: str, parent_id: int | None, except_id: int | None = None) -> None:
        clause = "parent_id IS NULL" if parent_id is None else "parent_id = ?"
        params = [ru.casefold()] if parent_id is None else [ru.casefold(), parent_id]
        rows = self._conn.execute(f"SELECT id, ru FROM groups WHERE {clause}", params[1:]).fetchall()
        if any(row["ru"].casefold() == params[0] and row["id"] != except_id for row in rows):
            raise WarehouseError(tr("«{0}» nomli guruh allaqachon bor.").format(ru))
