"""Joylashuv: koordinatani matn yoki xarita havolasidan o'qish, manzil bo'yicha topish va Google Maps havolasi.

Koordinatani o'qish uchun internet kerak emas: u havolaning o'zidan olinadi. Qisqa havolalarda
(maps.app.goo.gl/…) koordinata yo'q, shuning uchun ular qabul qilinmaydi. Manzil bo'yicha topish
(`find_address`) internet orqali ishlaydi: manzil matni OpenStreetMap qidiruv xizmatiga yuboriladi.
"""

import json
import math
import re
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote_plus, unquote, urlencode

from .config import APP_VERSION
from .errors import WarehouseError
from .i18n import tr

KM_PER_DEGREE = 111.32  # bir daraja kenglik — taxminan shuncha kilometr
MAPS_SEARCH_URL = "https://www.google.com/maps/search/?api=1&query="
# Manzil bo'yicha qidiruv: OpenStreetMap ning bepul xizmati (kalit kerak emas; kam so'rov uchun mo'ljallangan).
GEOCODER_URL = "https://nominatim.openstreetmap.org/search"
GEOCODER_COUNTRIES = "uz"  # qisqa manzil («Yakkasaroy 12») boshqa davlatdan topilib qolmasligi uchun
GEOCODER_LANGUAGE = "uz,ru"
GEOCODER_AGENT = f"MME-Ombor/{APP_VERSION}"  # xizmat qoidasi: dastur o'zini tanishtirishi kerak
LOOKUP_TIMEOUT_SECONDS = 6

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


@dataclass(frozen=True)
class FoundPlace:
    """Manzil bo'yicha topilgan joy: koordinatasi va xaritadagi to'liq nomi (foydalanuvchi tekshirishi uchun)."""

    location: Location
    title: str


class LookupFailed(Exception):
    """Manzilni qidirib bo'lmadi: internet yo'q yoki xizmat javob bermadi."""


def find_address(address: str, timeout: float = LOOKUP_TIMEOUT_SECONDS) -> FoundPlace | None:
    """Manzil matni bo'yicha joyni internetdan topadi; topilmasa — None, ulanib bo'lmasa — LookupFailed."""
    query = " ".join(address.split())
    if not query:
        return None
    parameters = urlencode(
        {
            "q": query,
            "format": "jsonv2",
            "limit": 1,
            "countrycodes": GEOCODER_COUNTRIES,
            "accept-language": GEOCODER_LANGUAGE,
        }
    )
    request = urllib.request.Request(f"{GEOCODER_URL}?{parameters}", headers={"User-Agent": GEOCODER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            places = json.load(response)
        if not places:
            return None
        place = places[0]
        return FoundPlace(Location(float(place["lat"]), float(place["lon"])), place.get("display_name", query))
    except (OSError, ValueError, KeyError, TypeError) as error:  # tarmoq xatosi yoki kutilmagan javob
        raise LookupFailed(str(error)) from error


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
