"""Joylashuv: koordinatani matn yoki xarita havolasidan o'qish va Google Maps havolasini tuzish.

Internet kerak emas: koordinata havolaning o'zidan olinadi. Qisqa havolalarda (maps.app.goo.gl/…)
koordinata yo'q — ularni faqat internet orqali ochish mumkin, shuning uchun ular qabul qilinmaydi.
"""

import math
import re
from dataclasses import dataclass
from urllib.parse import quote_plus, unquote

from .errors import WarehouseError
from .i18n import tr

KM_PER_DEGREE = 111.32  # bir daraja kenglik — taxminan shuncha kilometr
MAPS_SEARCH_URL = "https://www.google.com/maps/search/?api=1&query="

_NUMBER = r"(-?\d{1,3}(?:\.\d+)?)"
_PAIR = rf"{_NUMBER}\s*[,;\s]\s*{_NUMBER}"
_PLAIN = re.compile(rf"^{_PAIR}$")
# Havoladagi koordinata: aniq joy belgisi (!3d…!4d…), keyin so'rov parametrlari, oxirida xarita markazi (@…).
_IN_LINK = (
    re.compile(rf"!3d{_NUMBER}!4d{_NUMBER}"),
    re.compile(rf"[?&](?:q|query|ll|pt)={_PAIR}"),
    re.compile(rf"@{_PAIR}"),
)
_LONGITUDE_FIRST = "yandex"  # Yandex havolalarida avval uzunlik, keyin kenglik yoziladi


@dataclass(frozen=True)
class Location:
    """Yer yuzidagi nuqta: kenglik va uzunlik (daraja)."""

    latitude: float
    longitude: float

    def __str__(self) -> str:
        return f"{self.latitude:.6f}, {self.longitude:.6f}"

    def offset_km(self, origin: "Location") -> tuple[float, float]:
        """`origin` dan sharqqa va shimolga necha kilometr (kichik masofalar uchun yetarli aniqlikda)."""
        east = (self.longitude - origin.longitude) * KM_PER_DEGREE * math.cos(math.radians(origin.latitude))
        north = (self.latitude - origin.latitude) * KM_PER_DEGREE
        return east, north


def parse_location(text: str) -> Location | None:
    """Matndan joylashuvni o'qiydi: «41.2856, 69.2034» yoki Google/Yandex xarita havolasi.

    Bo'sh matn — joylashuv yo'q (None). Tushunib bo'lmaydigan matnda xato ko'tariladi.
    """
    text = unquote(text.strip())
    if not text:
        return None
    match = _PLAIN.match(text) or next(filter(None, (pattern.search(text) for pattern in _IN_LINK)), None)
    if match is None:
        raise WarehouseError(
            tr(
                "Joylashuvni tushunib bo'lmadi. Koordinatani «41.2856, 69.2034» ko'rinishida yozing: "
                "Google Maps'da joyni sichqonchaning o'ng tugmasi bilan bosing va birinchi qatorni nusxalang."
            )
        )
    first, second = float(match.group(1)), float(match.group(2))
    is_link = not _PLAIN.match(text)
    latitude, longitude = (second, first) if is_link and _LONGITUDE_FIRST in text.casefold() else (first, second)
    if not (-90 <= latitude <= 90 and -180 <= longitude <= 180):
        raise WarehouseError(tr("Koordinata noto'g'ri: kenglik −90…90, uzunlik −180…180 oralig'ida bo'ladi."))
    return Location(latitude, longitude)


def maps_url(location: Location | None, address: str = "") -> str | None:
    """Joyni Google Maps'da ochadigan havola: koordinata bo'yicha, u bo'lmasa — manzil matni bo'yicha."""
    query = f"{location.latitude},{location.longitude}" if location else quote_plus(address.strip())
    return MAPS_SEARCH_URL + query if query else None
