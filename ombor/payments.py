"""To'lov turi va to'lov holati (Excel hisobidagi «вид оплаты» va «статус» ustunlari).

To'lov turi bazada qisqa nom bilan saqlanadi (`METHODS`), ekranda tanlangan tilda ko'rsatiladi. Ro'yxatda
yo'q tur (masalan, Excelda boshqacha yozilgani) o'zgarishsiz saqlanadi va ko'rsatiladi.
"""

from .i18n import tr

TRANSFER, CORPORATE_CARD, CASH, CARD = "Perechisleniye", "KPK", "Naqd", "Karta"
METHODS = (TRANSFER, CORPORATE_CARD, CASH, CARD)

_TITLES = {
    TRANSFER: tr("Perechisleniye"),
    CORPORATE_CARD: tr("KPK"),
    CASH: tr("Naqd"),
    CARD: tr("Karta"),
}
# Excelda va qo'lda turlicha yoziladigan nomlar (kichik harflarda).
_SYNONYMS = {
    TRANSFER: (
        "perechisleniye",
        "perechislenie",
        "перечисление",
        "перечислением",
        "pul o'tkazish",
        "o'tkazma",
        "п/п",
        "безнал",
        "безналичный",
        "безналичные",
    ),
    CORPORATE_CARD: ("kpk", "кпк", "корпоративная карта", "korporativ karta"),
    CASH: ("naqd", "naqd pul", "наличные", "наличными", "нал", "cash"),
    CARD: ("karta", "карта", "plastik", "пластик", "card", "uzcard", "humo"),
}
_BY_WORD = {word: method for method, words in _SYNONYMS.items() for word in words}

_UNPAID_WORDS = {
    "to'lanmagan",
    "tolanmagan",
    "to'lanmadi",
    "qarz",
    "qarzga",
    "не оплачено",
    "неоплачено",
    "не оплачен",
    "не оплачена",
    "не оплатили",
    "долг",
    "в долг",
    "частично",
    "частично оплачено",
    "ожидает оплаты",
    "нет",
}


def method_title(stored: str) -> str:
    """To'lov turining tanlangan tildagi nomi."""
    return _TITLES.get(stored, stored)


def normalize_method(text: str) -> str:
    """Yozilgan to'lov turi — saqlanadigan nomi («кпк» → «KPK»); tanish bo'lmasa — o'zi."""
    text = " ".join(str(text or "").split())
    key = text.casefold().replace("ʻ", "'").replace("’", "'")
    if key in _BY_WORD:
        return _BY_WORD[key]
    for method, title in _TITLES.items():
        if key == title.casefold():
            return method
    return text


def status_title(unpaid: bool) -> str:
    return tr("To'lanmagan") if unpaid else tr("To'langan")


def is_unpaid(text: str) -> bool:
    """Excel'dagi «статус» qiymati: «не оплачено», «qarz» kabilar — to'lanmagan; qolgani (bo'sh ham) — to'langan."""
    key = " ".join(str(text or "").casefold().replace("ʻ", "'").replace("’", "'").split())
    return key in _UNPAID_WORDS or key == status_title(True).casefold()
