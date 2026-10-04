"""Dasturning bitta bazaga ulangan barcha xizmatlari."""

from dataclasses import dataclass
from pathlib import Path

from .analytics import Analytics
from .auth import Auth
from .backup import Backup
from .catalog import GroupCatalog
from .debts import Debts
from .driver import sqlite3
from .local import LocalPrefs
from .reports import Reports
from .settings import Settings
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
    groups: GroupCatalog
    prefs: LocalPrefs  # shu kompyuterning shaxsiy sozlamalari
    vault: Vault | None  # baza shifrlangan bo'lsa — uning kaliti
    conn: sqlite3.Connection

    @classmethod
    def create(
        cls,
        conn: sqlite3.Connection,
        backup_folder: Path,
        prefs: LocalPrefs | None = None,
        vault: Vault | None = None,
    ) -> "Services":
        """`prefs` berilmasa — faqat xotirada turadigan sozlamalar; `vault` — baza shifrlangan bo'lsa."""
        return cls(
            warehouse=Warehouse(conn),
            reports=Reports(conn),
            analytics=Analytics(conn),
            auth=Auth(conn, vault),
            backup=Backup(conn, backup_folder, vault),
            settings=Settings(conn),
            debts=Debts(conn),
            groups=GroupCatalog(conn),
            prefs=prefs or LocalPrefs(),
            vault=vault,
            conn=conn,
        )
