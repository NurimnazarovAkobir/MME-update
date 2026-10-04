"""Dasturning bitta bazaga ulangan barcha xizmatlari."""

from dataclasses import dataclass
from pathlib import Path

from .analytics import Analytics
from .auth import Auth
from .backup import Backup
from .catalog import GroupCatalog
from .debts import Debts
from .driver import sqlite3
from .reports import Reports
from .settings import Settings
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

    @classmethod
    def create(cls, conn: sqlite3.Connection, backup_folder: Path) -> "Services":
        return cls(
            warehouse=Warehouse(conn),
            reports=Reports(conn),
            analytics=Analytics(conn),
            auth=Auth(conn),
            backup=Backup(conn, backup_folder),
            settings=Settings(conn),
            debts=Debts(conn),
            groups=GroupCatalog(conn),
        )
