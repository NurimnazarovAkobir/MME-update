"""Excel (.xlsx) faylidan o'qish: mahsulotlar, kirim, chiqim va obyektlar.

Excelda yuritilgan hisob bir yo'la dasturga o'tkazilishi uchun o'qish iloji boricha kechirimli:

- varaq turi nomidan taniladi («Kirim», «Chiqim», «Mahsulotlar», «Obyektlar», ruscha ham), nomi tanish
  bo'lmasa — ustunlaridan (sana va miqdor bor — kirim/chiqim jurnali, faqat nom — mahsulotlar ro'yxati);
- ustunlar tartibi ixtiyoriy: sarlavha matni bo'yicha topiladi (o'zbekcha, ruscha, dasturning o'zi
  «Excelga chiqarish»da yozadigan sarlavhalar); sarlavha birinchi qatorda bo'lishi shart emas;
- sana Excel sanasi yoki «03.10.2026», «2026-10-03» ko'rinishida; sonlar «1 250 000», «12,5», «32 000 so'm»;
- xato qatorlar butun faylni to'xtatmaydi: ular `problems` ro'yxatiga varaq va qator raqami bilan yoziladi.
"""

import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from zipfile import BadZipFile

from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font
from openpyxl.utils.exceptions import InvalidFileException

from .errors import WarehouseError
from .i18n import tr
from .models import MovementKind
from .payments import is_unpaid
from .translations_ru import TRANSLATIONS

DEFAULT_UNIT = tr("dona")
HEADER_SEARCH_ROWS = 15  # sarlavha qatori shu qatorlar ichidan qidiriladi
EXCEL_EPOCH = date(1899, 12, 30)
DATE_FORMATS = ("%d.%m.%Y", "%d.%m.%y", "%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%Y.%m.%d")

# Maydon -> sarlavhalar (o'zbekcha; ruscha tarjimasi ham avtomatik qo'shiladi va qo'shimcha ruscha nomlar).
_ALIASES = {
    "name": (
        "Nomi",
        "Mahsulot",
        "Mahsulot nomi",
        "Tovar",
        "Tovar nomi",
        "Nomlanishi",
        "Наименование",
        "Товар",
        "Название",
        "Номенклатура",
        "Наименование товара",
        "Наименование расхода",
        "Наименование расходов",
        "Xarajat nomi",
        "Ismi",
        "Obyekt nomi",
    ),
    "unit": (
        "Birlik",
        "O'lchov birligi",
        "O'lchov",
        "Ед. изм.",
        "Ед.изм.",
        "Ед изм",
        "Ед.",
        "Единица",
        "Единица измерения",
    ),
    "category": ("Guruh", "Группа", "Группа расхода", "Группа расходов", "Xarajat guruhi"),
    "subcategory": ("Kategoriya", "Kichik guruh", "Категория", "Подгруппа"),
    "min_stock": ("Minimal qoldiq", "Min qoldiq", "Min. qoldiq", "Минимальный остаток", "Мин. остаток"),
    "stock": ("Qoldiq", "Boshlang'ich qoldiq", "Остаток", "Начальный остаток"),
    "price": ("Narxi", "Narx", "Narxi (1 birlik)", "Xarid narxi", "Цена", "Цена закупки", "Цена за ед."),
    "sale_price": ("Sotuv narxi", "Sotuv narxi (1 birlik)", "Цена продажи"),
    "amount": ("Summa", "Jami", "Сумма", "Итого"),
    "barcode": ("Shtrix-kod", "Shtrix kod", "Штрихкод", "Штрих-код"),
    "note": ("Izoh", "Примечание", "Комментарий"),
    "date": ("Sana", "Дата"),
    "doc_number": (
        "Hujjat №",
        "Hujjat",
        "Hujjat raqami",
        "Nakladnoy",
        "Nakladnoy №",
        "№ документа",
        "Номер документа",
        "Накладная",
        "Документ",
    ),
    "quantity": ("Miqdor", "Miqdori", "Soni", "Количество", "Кол-во", "Кол."),
    "counterparty": (
        "Yetkazib beruvchi",
        "Xaridor / obyekt",
        "Xaridor",
        "Obyekt",
        "Kontragent",
        "Kimga",
        "Kimdan",
        "Поставщик",
        "Покупатель",
        "Объект",
        "Контрагент",
    ),
    "person": (
        "Kim olib keldi",
        "Kim oldi",
        "Olib keldi",
        "Oldi",
        "Кто привёз",
        "Кто привез",
        "Кто получил",
        "Получатель",
    ),
    "warehouse": ("Ombor", "Склад"),
    "credit": ("Qarzga", "Qarz", "В долг"),
    "payment": ("To'lov turi", "Вид оплаты", "Вид оплата", "Способ оплаты", "Тип оплаты", "Форма оплаты", "Оплата"),
    "status": ("Holati", "To'lov holati", "Статус", "Статус оплаты"),
    "marks": ("Belgi", "Отметка"),
    "kind": ("Turi", "Amal", "Тип", "Операция", "Вид операции"),
    "address": ("Manzil", "Адрес"),
    "manager": ("Mas'ul shaxs", "Mas'ul", "Prorab", "Ответственный", "Прораб"),
}
_SHEET_KINDS = (
    ("receipts", ("kirim", "приход", "поступлен")),
    ("issues", ("chiqim", "расход", "rasxod", "отпуск", "списан")),
    ("sites", ("obyekt", "объект")),
    ("products", ("mahsulot", "tovar", "товар", "номенклатур", "qoldiq", "остат", "nomenklatura")),
)
_IN_WORDS = {"kirim", "приход", "in", "+", "поступление", "kelish"}
_OUT_WORDS = {"chiqim", "расход", "out", "-", "отпуск", "rasxod", "sotuv", "продажа", "списание"}
_YES_WORDS = {"ha", "xa", "yes", "1", "+", "да", "true", "x", "✓", "✔", "qarzga", "в долг", "qarz", "долг"}
_TOTAL_WORDS = ("jami", "итого", "всего", "total")
# Sarlavhasida shular bo'lsa — xarajatlar (xaridlar) hisobi: varaq nomi «Расход» bo'lsa ham, bu — kirim.
_EXPENSE_HEADERS = ("наименование расход", "группа расход", "xarajat nomi", "xarajat guruhi")


def _normalize(text) -> str:
    """Sarlavha va so'zlarni taqqoslash uchun: kichik harf, bir xil tutuq belgisi, ortiqcha belgilarsiz."""
    value = str(text).casefold()
    for apostrophe in "ʻ’‘`ʼ":
        value = value.replace(apostrophe, "'")
    value = value.replace("*", "").strip().rstrip(":").strip()
    return " ".join(value.split())


def _build_headers() -> dict[str, str]:
    headers = {}
    for name, aliases in _ALIASES.items():
        for alias in aliases:
            headers.setdefault(_normalize(alias), name)
            if alias in TRANSLATIONS:
                headers.setdefault(_normalize(TRANSLATIONS[alias]), name)
    return headers


_HEADERS = _build_headers()


@dataclass(frozen=True)
class ImportedProduct:
    """Mahsulotlar varag'idagi qator; `stock` > 0 bo'lsa, boshlang'ich qoldiq kirimi yoziladi."""

    name: str
    unit: str = ""
    min_stock: float = 0.0
    stock: float = 0.0
    price: float = 0.0
    category: str = ""
    subcategory: str = ""
    barcode: str = ""
    note: str = ""
    stock_date: date | None = None  # boshlang'ich qoldiq sanasi (ustun bo'lsa)
    source: str = ""  # «Mahsulotlar, 5-qator» — xato xabarlari uchun


@dataclass(frozen=True)
class ImportedMovement:
    kind: MovementKind
    date: date
    product: str
    quantity: float
    unit: str = ""
    price: float = 0.0  # kirimda — xarid narxi (1 birlik)
    sale_price: float = 0.0  # chiqimda — sotuv narxi (1 birlik); 0 — ichki rasxod
    category: str = ""
    subcategory: str = ""
    person: str = ""
    counterparty: str = ""
    note: str = ""
    doc_number: str = ""
    warehouse: str = ""
    on_credit: bool = False
    is_return: bool = False
    source: str = ""
    payment: str = ""  # to'lov turi, yozilganicha (warehouse.py tanish nomlarni bir xil qiladi)
    unpaid: bool = False  # «статус»: to'lanmagan


@dataclass(frozen=True)
class ImportedSite:
    name: str
    address: str = ""
    manager: str = ""
    note: str = ""


@dataclass
class ExcelBook:
    """Fayldan o'qilgan hamma narsa va o'qib bo'lmagan qatorlar."""

    products: list[ImportedProduct] = field(default_factory=list)
    movements: list[ImportedMovement] = field(default_factory=list)
    sites: list[ImportedSite] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    sheets: list[str] = field(default_factory=list)  # «Kirim: 120 ta qator» — qaysi varaq nima deb o'qilgani

    @property
    def is_empty(self) -> bool:
        return not (self.products or self.movements or self.sites)


class _RowError(ValueError):
    """Qatordagi xato: xabar `problems` ga yoziladi, qolgan qatorlar o'qilaveradi."""


def read_book(path: Path | str) -> ExcelBook:
    """Fayldagi barcha varaqlarni o'qiydi. Faylni umuman ochib bo'lmasa — WarehouseError."""
    try:
        workbook = load_workbook(path, read_only=True, data_only=True)
    except (InvalidFileException, BadZipFile, OSError, KeyError, ValueError) as error:
        raise WarehouseError(tr("Faylni o'qib bo'lmadi. Excel (.xlsx) faylini tanlang.")) from error
    book = ExcelBook()
    try:
        for sheet in workbook.worksheets:
            _read_sheet(sheet.title, list(sheet.iter_rows(values_only=True)), book)
    finally:
        workbook.close()
    if book.is_empty and not book.problems:
        raise WarehouseError(
            tr(
                "Faylda ma'lumot topilmadi. Varaqlarning birinchi qatorlarida «Nomi», «Sana», «Miqdor» kabi sarlavhalar bo'lsin."
            )
        )
    return book


def _read_sheet(title: str, rows: list[tuple], book: ExcelBook) -> None:
    found = _find_header(rows)
    if found is None:
        if any(any(cell not in (None, "") for cell in row) for row in rows):
            book.problems.append(tr("«{0}» varag'i: sarlavha qatori topilmadi — o'tkazib yuborildi.").format(title))
        return
    header_index, columns = found
    # Varaq nomi va sarlavhadan oldingi qatorlar (dastur chiqargan faylda — «Kirim», «Chiqim» kabi nom).
    caption = " ".join([title, *(_text(cell) for row in rows[:header_index] for cell in row or () if cell)])
    header = _normalize(" ".join(_text(cell) for cell in rows[header_index] or () if cell))
    if "quantity" in columns and any(word in header for word in _EXPENSE_HEADERS):
        kind = "receipts"
    else:
        kind = _sheet_kind(caption, columns)
    if kind is None:
        book.problems.append(tr("«{0}» varag'i: nima ekanini aniqlab bo'lmadi — o'tkazib yuborildi.").format(title))
        return
    readers = {
        "products": (_product, book.products),
        "receipts": (lambda values, source: _movement(values, source, MovementKind.IN), book.movements),
        "issues": (lambda values, source: _movement(values, source, MovementKind.OUT), book.movements),
        "journal": (lambda values, source: _movement(values, source, None), book.movements),
        "sites": (_site, book.sites),
    }
    reader, target = readers[kind]
    count = 0
    for number, row in enumerate(rows[header_index + 1 :], start=header_index + 2):
        values = {name: _cell(row, index) for name, index in columns.items()}
        if _is_blank_or_total(values):
            continue
        source = tr("«{0}», {1}-qator").format(title, number)
        try:
            target.append(reader(values, source))
            count += 1
        except _RowError as error:
            book.problems.append(f"{source}: {error}")
    book.sheets.append(tr("«{0}» — {1}: {2} ta qator").format(title, _SHEET_TITLES[kind], count))


_SHEET_TITLES = {
    "products": tr("mahsulotlar"),
    "receipts": tr("kirim"),
    "issues": tr("chiqim"),
    "journal": tr("kirim va chiqim"),
    "sites": tr("obyektlar"),
}


def _find_header(rows: list[tuple]) -> tuple[int, dict[str, int]] | None:
    """Sarlavha qatori va undagi tanilgan ustunlar (maydon -> ustun raqami)."""
    for index, row in enumerate(rows[:HEADER_SEARCH_ROWS]):
        columns: dict[str, int] = {}
        for position, cell in enumerate(row or ()):
            if cell is None:
                continue
            name = _HEADERS.get(_normalize(cell))
            if name and name not in columns:
                columns[name] = position
        if "name" in columns and len(columns) >= 2:
            return index, columns
    return None


def _sheet_kind(caption: str, columns: dict[str, int]) -> str | None:
    normalized = _normalize(caption)
    for kind, words in _SHEET_KINDS:
        if any(word in normalized for word in words):
            if kind in ("receipts", "issues") and "quantity" not in columns:
                continue
            return kind
    if "quantity" in columns and "date" in columns:
        return "journal" if "kind" in columns else None
    if "address" in columns or "manager" in columns:
        return "sites"
    return "products"


def _cell(row: tuple, index: int):
    return row[index] if row is not None and index < len(row) else None


def _is_blank_or_total(values: dict) -> bool:
    name = _text(values.get("name"))
    if not name:
        return True
    return _normalize(name) in _TOTAL_WORDS or (_normalize(name).startswith(_TOTAL_WORDS) and not values.get("date"))


def _product(values: dict, source: str) -> ImportedProduct:
    return ImportedProduct(
        name=_text(values.get("name")),
        unit=_text(values.get("unit")),
        min_stock=_number(values.get("min_stock"), tr("Minimal qoldiq")),
        stock=_number(values.get("stock"), tr("Qoldiq")),
        price=_number(values.get("price"), tr("Narxi")),
        category=_text(values.get("category")),
        subcategory=_text(values.get("subcategory")),
        barcode=_text(values.get("barcode")),
        note=_text(values.get("note")),
        stock_date=_date(values.get("date")) if values.get("date") not in (None, "") else None,
        source=source,
    )


def _movement(values: dict, source: str, kind: MovementKind | None) -> ImportedMovement:
    kind = kind or _kind(values.get("kind"))
    if values.get("date") in (None, ""):
        raise _RowError(tr("sana ko'rsatilmagan"))
    quantity = _number(values.get("quantity"), tr("Miqdor"))
    if quantity <= 0:
        raise _RowError(tr("miqdor noldan katta bo'lishi kerak"))
    price = _number(values.get("price"), tr("Narxi"))
    sale_price = _number(values.get("sale_price"), tr("Sotuv narxi"))
    amount = _number(values.get("amount"), tr("Summa"))
    if kind is MovementKind.IN and not price and amount:
        price = amount / quantity  # narx yozilmagan, summa bor
    marks = _normalize(values.get("marks") or "")
    return ImportedMovement(
        kind=kind,
        date=_date(values.get("date")),
        product=_text(values.get("name")),
        quantity=quantity,
        unit=_text(values.get("unit")),
        price=price if kind is MovementKind.IN else 0.0,
        sale_price=sale_price if kind is MovementKind.OUT else 0.0,
        category=_text(values.get("category")),
        subcategory=_text(values.get("subcategory")),
        person=_text(values.get("person")),
        counterparty=_text(values.get("counterparty")),
        note=_text(values.get("note")),
        doc_number=_text(values.get("doc_number")),
        warehouse=_text(values.get("warehouse")),
        on_credit=_yes(values.get("credit")) or "qarz" in marks or "долг" in marks,
        is_return="qaytarish" in marks or "возврат" in marks,
        source=source,
        payment=_text(values.get("payment")),
        unpaid=is_unpaid(_text(values.get("status"))),
    )


def _site(values: dict, source: str) -> ImportedSite:
    return ImportedSite(
        name=_text(values.get("name")),
        address=_text(values.get("address")),
        manager=_text(values.get("manager") or values.get("person")),
        note=_text(values.get("note")),
    )


def _kind(value) -> MovementKind:
    word = _normalize(value or "")
    if word in _IN_WORDS:
        return MovementKind.IN
    if word in _OUT_WORDS:
        return MovementKind.OUT
    raise _RowError(tr("«{0}» — kirim yoki chiqim ekani noma'lum").format(value or ""))


def _text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)  # «123.0» emas, «123» (hujjat raqami, shtrix-kod)
    return " ".join(str(value).split())


def _yes(value) -> bool:
    return value is True or _normalize(value or "") in _YES_WORDS


def _number(value, column: str) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, bool):
        raise _RowError(tr("«{0}» ustuni: «{1}» son emas").format(column, value))
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        text = re.sub(r"[^\d,.\-]", "", str(value))  # bo'shliq, «so'm», «сум» olib tashlanadi
        if text.count(",") > 1 or ("," in text and "." in text):
            text = text.replace(",", "")
        text = text.replace(",", ".")
        try:
            number = float(text)
        except ValueError:
            raise _RowError(tr("«{0}» ustuni: «{1}» son emas").format(column, value)) from None
    if number < 0:
        raise _RowError(tr("«{0}» ustuni: manfiy son bo'lishi mumkin emas").format(column))
    return number


def _date(value) -> date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return EXCEL_EPOCH + timedelta(days=int(value))
    text = _text(value).split(" ")[0]
    for pattern in DATE_FORMATS:
        try:
            return datetime.strptime(text, pattern).date()
        except ValueError:
            continue
    raise _RowError(tr("«{0}» — sana emas (masalan, 03.10.2026)").format(value))


# --- Namuna fayl -------------------------------------------------------------

_TEMPLATE = (
    (
        tr("Mahsulotlar"),
        (
            tr("Nomi"),
            tr("Birlik"),
            tr("Guruh"),
            tr("Kategoriya"),
            tr("Minimal qoldiq"),
            tr("Boshlang'ich qoldiq"),
            tr("Narxi"),
            tr("Shtrix-kod"),
            tr("Izoh"),
        ),
        (
            ("Truba 40x40x2", tr("metr"), "Qurilish materiallari", "Metall", 100, 250, 32000, "", ""),
            ("Sement M400", tr("kg"), "Qurilish materiallari", "Sement", 500, 0, 0, "", ""),
        ),
    ),
    (
        tr("Kirim"),
        (
            tr("Sana"),
            tr("Hujjat №"),
            tr("Mahsulot"),
            tr("Miqdor"),
            tr("Birlik"),
            tr("Narxi"),
            tr("Yetkazib beruvchi"),
            tr("Kim olib keldi"),
            tr("Guruh"),
            tr("Kategoriya"),
            tr("Ombor"),
            tr("To'lov turi"),
            tr("Holati"),
            tr("Qarzga"),
            tr("Izoh"),
        ),
        (
            (
                "01.09.2026",
                "45",
                "Sement M400",
                2000,
                tr("kg"),
                1500,
                "Qurilish bozori",
                "Ali",
                "",
                "",
                "",
                tr("Perechisleniye"),
                tr("To'langan"),
                "",
                "",
            ),
        ),
    ),
    (
        tr("Chiqim"),
        (
            tr("Sana"),
            tr("Hujjat №"),
            tr("Mahsulot"),
            tr("Miqdor"),
            tr("Birlik"),
            tr("Sotuv narxi"),
            tr("Xaridor / obyekt"),
            tr("Kim oldi"),
            tr("Guruh"),
            tr("Kategoriya"),
            tr("Ombor"),
            tr("Qarzga"),
            tr("Izoh"),
        ),
        (("05.09.2026", "", "Truba 40x40x2", 40, tr("metr"), "", "Obyekt-1", "Vali", "", "", "", "", ""),),
    ),
    (
        tr("Obyektlar"),
        (tr("Nomi"), tr("Manzil"), tr("Mas'ul shaxs"), tr("Izoh")),
        (("Obyekt-1", "Toshkent, Chilonzor 5", "Karimov", ""),),
    ),
)


def write_template(path: Path | str) -> None:
    """To'ldirish uchun namuna: to'rtta varaq (mahsulotlar, kirim, chiqim, obyektlar)."""
    workbook = Workbook()
    workbook.remove(workbook.active)
    for title, headers, samples in _TEMPLATE:
        sheet = workbook.create_sheet(title)
        sheet.append(headers)
        for cell in sheet[1]:
            cell.font = Font(bold=True)
        for row in samples:
            sheet.append(row)
        for cell in sheet[1]:
            sheet.column_dimensions[cell.column_letter].width = 18
    workbook.save(path)
