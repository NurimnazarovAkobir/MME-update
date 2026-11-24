"""O'lchov birliklari: turlicha yozilgan nomlarni («шт», «м2», «кг.») dasturdagi bitta nomga keltirish.

Excel'dan kelgan «шт» va dasturda tanlangan «dona» bir xil birlik bo'lib qolsin — ro'yxatlar va hisobotlarda
bitta mahsulot turi ikki xil birlikda ko'rinmasin. Tanish bo'lmagan birlik yozilganicha qoladi.
"""

from .i18n import tr

# Dasturdagi nomi (config.UNITS dagi kabi) -> boshqacha yozilishi (kichik harflarda).
_SYNONYMS = (
    (tr("dona"), ("dona", "ta", "шт", "шт.", "штук", "штука", "pcs", "pc")),
    (tr("kg"), ("kg", "кг", "кг.", "kilogramm", "килограмм")),
    (tr("tonna"), ("tonna", "t", "т", "т.", "тн", "тонна")),
    (tr("metr"), ("metr", "m", "м", "м.", "метр", "п.м", "пм", "пог.м")),
    (tr("m²"), ("m²", "m2", "м2", "м²", "кв.м", "кв.м.", "кв м", "kv.m", "kv m")),
    (tr("list"), ("list", "лист")),
    (tr("litr"), ("litr", "l", "л", "л.", "литр")),
    (tr("komplekt"), ("komplekt", "kompl", "компл", "компл.", "комплект", "к-т")),
    (tr("quti"), ("quti", "кор", "кор.", "коробка", "упак", "упак.", "упаковка")),
    # Xarajatlar hisobida uchraydigan birliklar (saytdagi src/lib/normalize.ts bilan bir xil).
    (tr("gramm"), ("gramm", "g", "gr", "г", "г.", "гр", "гр.", "грамм")),
    (tr("m³"), ("m³", "m3", "м3", "м³", "куб", "куб.м", "куб.м.", "кубометр", "kub", "kub.m")),
    (tr("santimetr"), ("santimetr", "sm", "cm", "см", "см.", "сантиметр")),
    (tr("millimetr"), ("millimetr", "mm", "мм", "мм.", "миллиметр")),
    (tr("kilometr"), ("kilometr", "km", "км", "км.", "километр")),
    (tr("qop"), ("qop", "мешок", "меш", "меш.", "meshok")),
    (tr("rulon"), ("rulon", "рулон", "рул", "рул.")),
    (tr("pachka"), ("pachka", "пачка", "пач", "пач.")),
    (tr("juft"), ("juft", "пара", "пар", "para")),
    (tr("reys"), ("reys", "рейс", "рейса", "reis")),
    (tr("soat"), ("soat", "час", "ч", "ч.", "chas")),
    (tr("mashina-soat"), ("mashina-soat", "маш/час", "маш-час", "машино-час", "машиночас", "м/ч", "mashina/soat")),
    (tr("kun"), ("kun", "день", "дн", "дн.", "сутки")),
    (tr("oy"), ("oy", "мес", "мес.", "месяц")),
    (tr("xizmat"), ("xizmat", "услуга", "усл", "усл.")),
)
_BY_SPELLING = {spelling: unit for unit, spellings in _SYNONYMS for spelling in (*spellings, unit.casefold())}
# Excel jadvalidagi (rus tilidagi) qisqa yozilishi: har bir ro'yxatdagi birinchi kirillcha nom.
_RUSSIAN = {
    unit: next(spelling for spelling in spellings if "а" <= spelling[0] <= "я") for unit, spellings in _SYNONYMS
}


def normalize_unit(text: str) -> str:
    """«шт» → «dona», «м2» → «m²»; tanish bo'lmasa — ortiqcha bo'shliqlarsiz o'zi."""
    unit = " ".join(str(text or "").split())
    return _BY_SPELLING.get(unit.casefold(), unit)


def russian_unit(unit: str) -> str:
    """«dona» → «шт», «m²» → «м2» (Excel jadvalidagi kabi); tanish bo'lmasa — o'zi."""
    return _RUSSIAN.get(normalize_unit(unit), unit)
