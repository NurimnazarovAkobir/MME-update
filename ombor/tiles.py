"""Xarita bo'laklari (256×256 pikselli rasmlar): OpenStreetMap dan olinadi va diskda saqlanadi.

Bir marta yuklangan joy keyin internetsiz ham ko'rinadi. OpenStreetMap qoidasiga ko'ra bo'laklar
qayta-qayta so'ralmaydi (diskdan olinadi) va dastur o'zini tanishtiradi (`USER_AGENT`).
"""

import urllib.request
from pathlib import Path

from .geo import USER_AGENT

TILE_SIZE = 256
TILE_URL = "https://tile.openstreetmap.org/{zoom}/{x}/{y}.png"
ATTRIBUTION = "© OpenStreetMap"  # xarita egalari talabi: manba ko'rsatilishi shart
MIN_ZOOM, MAX_ZOOM = 3, 18
DOWNLOAD_TIMEOUT_SECONDS = 8

Tile = tuple[int, int, int]  # (zoom, x, y)


class TileStore:
    """Bo'laklarni diskdagi papkadan o'qiydi; yo'q bo'lsa, internetdan yuklab, shu papkaga saqlaydi."""

    def __init__(self, folder: Path):
        self._folder = folder

    def path(self, tile: Tile) -> Path:
        zoom, x, y = tile
        return self._folder / str(zoom) / str(x) / f"{y}.png"

    def read(self, tile: Tile) -> bytes | None:
        """Diskda saqlangan bo'lak; yo'q bo'lsa — None."""
        try:
            return self.path(tile).read_bytes()
        except OSError:
            return None

    def load(self, tile: Tile) -> bytes | None:
        """Bo'lak rasmi: diskdan, bo'lmasa internetdan. Internet ham bo'lmasa — None."""
        return self.read(tile) or self._download(tile)

    def _download(self, tile: Tile) -> bytes | None:
        zoom, x, y = tile
        request = urllib.request.Request(TILE_URL.format(zoom=zoom, x=x, y=y), headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(request, timeout=DOWNLOAD_TIMEOUT_SECONDS) as response:
                data = response.read()
        except (OSError, ValueError):
            return None
        try:
            self.path(tile).parent.mkdir(parents=True, exist_ok=True)
            self.path(tile).write_bytes(data)
        except OSError:
            pass  # saqlab bo'lmadi (masalan, disk to'la): bo'lak baribir ko'rsatiladi
        return data
