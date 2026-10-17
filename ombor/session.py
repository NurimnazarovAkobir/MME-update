"""Joriy ish seansi: kim kirgan va unga nimalar ruxsat etilgan."""

from dataclasses import dataclass

from .models import MovementDetails, User


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

    def can_change(self, movement: MovementDetails) -> bool:
        """Kirim, chiqim yoki vozvratni tahrirlash va o'chirish — faqat rahbarga.

        Omborchi yozuvni faqat qo'shadi: xato kiritgan bo'lsa, rahbarga aytadi va u tuzatadi.
        """
        return self.user.is_admin
