"""Joylashuv: koordinatani matn yoki xarita havolasidan o'qish, manzil bo'yicha topish va Google Maps havolasi.

Koordinatani o'qish uchun internet kerak emas: u havolaning o'zidan olinadi. Qisqa havolalarda
(maps.app.goo.gl/…) koordinata yo'q, shuning uchun ular qabul qilinmaydi. Manzil bo'yicha topish
(`find_address`) internet orqali ishlaydi: manzil matni OpenStreetMap qidiruv xizmatiga yuboriladi.
"""

import json
import math
import re
import time
import urllib.request
from dataclasses import dataclass
from urllib.parse import quote_plus, unquote, urlencode

from .config import APP_VERSION
from .errors import WarehouseError
from .i18n import tr

EQUATOR_METRES = 40_075_016.686  # yer ekvatorining uzunligi: xarita masshtabi shundan hisoblanadi
MAPS_SEARCH_URL = "https://www.google.com/maps/search/?api=1&query="
# Manzil bo'yicha qidiruv: OpenStreetMap ning bepul xizmati (kalit kerak emas; kam so'rov uchun mo'ljallangan).
GEOCODER_URL = "https://nominatim.openstreetmap.org/search"
GEOCODER_COUNTRIES = "uz"  # qisqa manzil («Yakkasaroy 12») boshqa davlatdan topilib qolmasligi uchun
GEOCODER_LANGUAGE = "uz,ru"
USER_AGENT = f"MME-Ombor/{APP_VERSION}"  # OpenStreetMap qoidasi: dastur o'zini tanishtirishi kerak
LOOKUP_TIMEOUT_SECONDS = 6
LOOKUP_PAUSE_SECONDS = 1.0  # xizmat qoidasi: soniyasiga bittadan ortiq so'rov yuborilmaydi
# Manzilda shulardan boshqa so'z bo'lmasa («12-uy», «5 xonadon»), u yolg'iz o'zi qidirilmaydi:
# bunday matn istalgan shahardan topilib qoladi.
_HOUSE_WORDS = {"uy", "uyi", "dom", "xonadon", "kv", "kvartira", "bino", "korpus", "blok", "ofis", "qavat", "etaj"}

MAX_MAP_LATITUDE = 85.0511  # Web Mercator xaritasi shu kenglikkacha chiziladi
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

    def to_unit(self) -> tuple[float, float]:
        """Xaritadagi o'rni (Web Mercator): butun dunyo 0…1 kvadratga sig'adi, (0, 0) — shimoli-g'arb."""
        latitude = math.radians(max(min(self.latitude, MAX_MAP_LATITUDE), -MAX_MAP_LATITUDE))
        x = (self.longitude + 180) / 360
        y = (1 - math.asinh(math.tan(latitude)) / math.pi) / 2
        return x, y

    @classmethod
    def from_unit(cls, x: float, y: float) -> "Location":
        latitude = math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * y))))
        return cls(latitude, x * 360 - 180)


def metres_per_unit(latitude: float) -> float:
    """Shu kenglikda xaritaning butun eni (0…1) necha metrga to'g'ri keladi."""
    return EQUATOR_METRES * math.cos(math.radians(latitude))


@dataclass(frozen=True)
class FoundPlace:
    """Manzil bo'yicha topilgan joy: koordinatasi va xaritadagi to'liq nomi (foydalanuvchi tekshirishi uchun)."""

    location: Location
    title: str


class LookupFailed(Exception):
    """Manzilni qidirib bo'lmadi: internet yo'q yoki xizmat javob bermadi."""


def place_queries(name: str, address: str) -> list[str]:
    """Obyektni xaritadan qidirish uchun matnlar — eng ishonchlisidan boshlab.

    To'liq manzil («Bobur ko'chasi 12») o'zi qidiriladi. Manzil faqat uy raqami bo'lsa («12-uy») yoki
    yozilmagan bo'lsa, obyekt nomi asos bo'ladi: aks holda «12-uy» boshqa shahardan topilib qoladi.
    """
    name, address = " ".join(name.split()), " ".join(address.split())
    words = re.findall(r"[^\W\d_]+", address.casefold())
    names_a_place = any(word not in _HOUSE_WORDS and len(word) > 2 for word in words)
    together = f"{name}, {address}" if name and address else name or address
    queries = [address, together] if names_a_place else [together, name]
    return list(dict.fromkeys(query for query in queries if query))


def find_place(name: str, address: str, timeout: float = LOOKUP_TIMEOUT_SECONDS) -> FoundPlace | None:
    """Obyektni nomi va manzili bo'yicha internetdan topadi (`place_queries` tartibida, birinchi topilgani)."""
    for attempt, query in enumerate(place_queries(name, address)):
        if attempt:
            time.sleep(LOOKUP_PAUSE_SECONDS)
        found = find_address(query, timeout)
        if found is not None:
            return found
    return None


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
    request = urllib.request.Request(f"{GEOCODER_URL}?{parameters}", headers={"User-Agent": USER_AGENT})
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
