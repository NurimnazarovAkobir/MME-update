"""Son va sanalarni o'qishga qulay ko'rinishga keltirish."""

from datetime import date

from .i18n import tr
from .models import Granularity

MONTH_NAMES = (
    tr("Yan"),
    tr("Fev"),
    tr("Mar"),
    tr("Apr"),
    tr("May"),
    tr("Iyn"),
    tr("Iyl"),
    tr("Avg"),
    tr("Sen"),
    tr("Okt"),
    tr("Noy"),
    tr("Dek"),
)
FULL_MONTH_NAMES = (
    tr("Yanvar"),
    tr("Fevral"),
    tr("Mart"),
    tr("Aprel"),
    tr("May"),
    tr("Iyun"),
    tr("Iyul"),
    tr("Avgust"),
    tr("Sentabr"),
    tr("Oktabr"),
    tr("Noyabr"),
    tr("Dekabr"),
)

# Sana ichida yoziladigan oy nomlari («3-oktabr, 2026»).
DATE_MONTH_NAMES = (
    tr("yanvar"),
    tr("fevral"),
    tr("mart"),
    tr("aprel"),
    tr("may"),
    tr("iyun"),
    tr("iyul"),
    tr("avgust"),
    tr("sentabr"),
    tr("oktabr"),
    tr("noyabr"),
    tr("dekabr"),
)

_COMPACT_UNITS = ((1e9, tr("mlrd")), (1e6, tr("mln")), (1e3, tr("ming")))


def fmt_qty(value: float) -> str:
    """1250.5 -> '1 250,5' (ortiqcha nollarsiz, 3 xonagacha)."""
    text = f"{value:,.3f}".rstrip("0").rstrip(".")
    return text.replace(",", " ").replace(".", ",")


def fmt_money(value: float) -> str:
    """1250000.4 -> '1 250 000' (butun so'mgacha yaxlitlanadi)."""
    return f"{round(value):,}".replace(",", " ")


def fmt_compact(value: float) -> str:
    """12500000 -> '12,5 mln' — diagramma va kartochkalar uchun."""
    for limit, suffix in _COMPACT_UNITS:
        if abs(value) >= limit:
            return f"{fmt_qty(round(value / limit, 1))} {suffix}"
    return fmt_qty(round(value))


def fmt_date(day: date) -> str:
    return day.strftime("%d.%m.%Y")


def fmt_long_date(day: date) -> str:
    """date(2026, 10, 3) -> '3-oktabr, 2026'."""
    return tr("{0}-{1}, {2}").format(day.day, DATE_MONTH_NAMES[day.month - 1], day.year)


def fmt_range(start: date, end: date) -> str:
    return f"{fmt_date(start)} — {fmt_date(end)}"


def fmt_period(granularity: Granularity, day: date) -> str:
    """`day` kiradigan davrning nomi: '03.10.2026', 'Oktabr 2026', '2026-yil'…"""
    period = granularity.period_of(day)
    if granularity is Granularity.DAY:
        return fmt_date(day)
    if granularity is Granularity.WEEK:
        return fmt_range(period.start, period.end)
    if granularity is Granularity.MONTH:
        return f"{FULL_MONTH_NAMES[day.month - 1]} {day.year}"
    return tr("{0}-yil").format(day.year)
