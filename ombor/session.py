"""Joriy ish seansi: kim kirgan va unga nimalar ruxsat etilgan."""

from dataclasses import dataclass
from datetime import date

from .models import MovementDetails, Role, User


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
    def can_add(self) -> bool:
        """Kirim, chiqim va mahsulot qo'shish — rahbar va omborchiga; kuzatuvchi faqat ko'radi."""
        return self.user.can_add

    @property
    def can_modify(self) -> bool:
        """Istalgan yozuvni tahrirlash va o'chirish, inventarizatsiya, zaxiradan tiklash — faqat rahbarga."""
        return self.user.is_admin

    def can_change(self, movement: MovementDetails, today: date | None = None) -> bool:
        """Yozuvni tahrirlash yoki o'chirish mumkinmi.

        Rahbar — istalganini; omborchi — faqat o'zi bugun kiritganini (xatoni darhol tuzatishi uchun).
        """
        if self.user.is_admin:
            return True
        return (
            self.user.role is Role.KEEPER
            and movement.created_by == self.user.name
            and movement.created_on == (today or date.today())
        )
