"""Tovar va xizmatlar guruhlari hamda kichik guruhlari (ikki tilda).

Bazada ruscha nom saqlanadi (asl ro'yxat rus tilida berilgan); ekranda tanlangan
tilga qarab ko'rsatiladi. Ro'yxatda yo'q qiymat (eski versiyadan qolgan yoki
Exceldan yuklangan) o'zgarishsiz ko'rsatiladi.
"""

from dataclasses import dataclass

from . import i18n


@dataclass(frozen=True)
class Name:
    ru: str  # bazada saqlanadigan qiymat
    uz: str

    @property
    def display(self) -> str:
        return self.uz if i18n.language() == i18n.UZBEK else self.ru


@dataclass(frozen=True)
class Group:
    name: Name
    subgroups: tuple[Name, ...]


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

_BY_STORED = {group.name.ru: group for group in GROUPS}
_DISPLAY = {name.ru: name for group in GROUPS for name in (group.name, *group.subgroups)}


def find_group(stored: str) -> Group | None:
    """Bazadagi qiymat bo'yicha guruh; ro'yxatda bo'lmasa — None."""
    return _BY_STORED.get(stored)


def display_name(stored: str) -> str:
    """Guruh yoki kichik guruhning tanlangan tildagi nomi; ro'yxatda yo'q qiymat o'zgarishsiz qaytadi."""
    name = _DISPLAY.get(stored)
    return name.display if name else stored
