"""Dasturning bitta bazaga ulangan barcha xizmatlari."""

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .analytics import Analytics
from .auth import Auth
from .backup import Backup
from .catalog import GroupCatalog
from .debts import Debts
from .driver import sqlite3
from .importer import ExcelImporter
from .local import LocalPrefs
from .reports import Reports
from .settings import Settings
from .sites import Sites
from .statistics import Statistics
from .vault import Vault
from .warehouse import Warehouse


@dataclass(frozen=True)
class Services:
    warehouse: Warehouse
    reports: Reports
    analytics: Analytics
    auth: Auth
    backup: Backup
    settings: Settings
    debts: Debts
    sites: Sites
    groups: GroupCatalog
    importer: ExcelImporter  # Exceldan mahsulot, kirim, chiqim va obyektlarni yuklash
    statistics: Statistics  # mahsulotlar reytingi, narx o'zgarishi, obyektlar rasxodi
    prefs: LocalPrefs  # shu kompyuterning shaxsiy sozlamalari
    vault: Vault | None  # baza shifrlangan bo'lsa — uning kaliti
    conn: sqlite3.Connection
    # Shu bazaga yangi ulanish ochadi (fonda sinxronlash uchun); xotiradagi bazada — None.
    reconnect: Callable[[], sqlite3.Connection] | None = None

    @classmethod
    def create(
        cls,
        conn: sqlite3.Connection,
        backup_folder: Path,
        prefs: LocalPrefs | None = None,
        vault: Vault | None = None,
        reconnect: Callable[[], sqlite3.Connection] | None = None,
    ) -> "Services":
        """`prefs` berilmasa — faqat xotirada turadigan sozlamalar; `vault` — baza shifrlangan bo'lsa."""
        warehouse = Warehouse(conn)
        sites = Sites(conn, warehouse)
        groups = GroupCatalog(conn)
        return cls(
            warehouse=warehouse,
            reports=Reports(conn),
            analytics=Analytics(conn),
            auth=Auth(conn, vault),
            backup=Backup(conn, backup_folder, vault),
            settings=Settings(conn),
            debts=Debts(conn),
            sites=sites,
            groups=groups,
            importer=ExcelImporter(warehouse, sites, groups),
            statistics=Statistics(conn, sites),
            prefs=prefs or LocalPrefs(),
            vault=vault,
            conn=conn,
            reconnect=reconnect,
        )
