"""Kirim va chiqim uchun ekrandagi yozuvlar."""

from dataclasses import dataclass

from ..i18n import tr
from ..models import MovementKind


@dataclass(frozen=True)
class KindLabels:
    kind: MovementKind
    title: str
    new_action: str
    person: str
    counterparty: str


LABELS = {
    MovementKind.IN: KindLabels(
        kind=MovementKind.IN,
        title=tr("Kirim"),
        new_action=tr("+ Yangi kirim"),
        person=tr("Kim olib keldi"),
        counterparty=tr("Yetkazib beruvchi"),
    ),
    MovementKind.OUT: KindLabels(
        kind=MovementKind.OUT,
        title=tr("Chiqim"),
        new_action=tr("+ Yangi chiqim"),
        person=tr("Kim oldi"),
        counterparty=tr("Xaridor / obyekt"),
    ),
}
