"""Baza drayveri: SQLCipher (shifrlangan va oddiy bazani ham ochadi).

Boshqa modullar `sqlite3` ni shu yerdan oladi, shunda xato sinflari va qator turi hamma joyda bir xil bo'ladi.
"""

from sqlcipher3 import dbapi2 as sqlite3

__all__ = ["sqlite3"]
