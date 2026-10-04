"""Joriy ish seansi: kim kirgan va unga nimalar ruxsat etilgan."""

from dataclasses import dataclass

from .models import User


@dataclass(frozen=True)
class Session:
    user: User

    @property
    def author(self) -> str:
        """Yangi yozuvlarga «kiritdi» sifatida yoziladigan ism."""
        return self.user.name

    @property
    def is_admin(self) -> bool:
        return self.user.is_admin

    @property
    def can_modify(self) -> bool:
        """Tahrirlash, o'chirish, inventarizatsiya, zaxiradan tiklash — faqat rahbarga."""
        return self.user.is_admin
