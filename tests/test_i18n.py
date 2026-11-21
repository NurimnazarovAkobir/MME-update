"""Tillar testlari: tarjimalar to'liqligi, o'rinbosarlar va guruhlar ro'yxati."""

import ast
import string
import tempfile
import unittest
from pathlib import Path

from ombor import catalog, i18n
from ombor.database import connect
from ombor.settings import Settings
from ombor.translations_ru import TRANSLATIONS

PACKAGE = Path(i18n.__file__).parent


def _translated_texts() -> set[str]:
    """Koddagi barcha `tr("...")` chaqiruvlaridagi matnlar."""
    texts = set()
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "tr":
                texts.add(ast.literal_eval(node.args[0]))
    return texts


def _fields(template: str) -> list[str]:
    """Shablondagi o'rinbosarlar format ko'rsatkichlari bilan, tartiblangan: ['0', '1:%d.%m.%Y']."""
    parsed = string.Formatter().parse(template)
    return sorted(f"{name}:{spec}" if spec else name for _, name, spec, _ in parsed if name is not None)


class TranslationTests(unittest.TestCase):
    def test_every_text_in_code_has_a_russian_translation(self):
        self.assertEqual(sorted(_translated_texts() - set(TRANSLATIONS)), [])

    def test_no_translation_is_left_over(self):
        self.assertEqual(sorted(set(TRANSLATIONS) - _translated_texts()), [])

    def test_placeholders_match(self):
        mismatched = [key for key, value in TRANSLATIONS.items() if _fields(key) != _fields(value)]
        self.assertEqual(mismatched, [])

    def test_no_translation_is_empty(self):
        self.assertEqual([key for key, value in TRANSLATIONS.items() if not value.strip()], [])


class LanguageSwitchTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.UZBEK)

    def test_uzbek_is_the_default_and_returns_text_unchanged(self):
        self.assertEqual(i18n.language(), i18n.UZBEK)
        self.assertEqual(i18n.tr("Saqlash"), "Saqlash")

    def test_russian(self):
        i18n.set_language(i18n.RUSSIAN)
        self.assertEqual(i18n.tr("Saqlash"), "Сохранить")
        self.assertEqual(i18n.tr("Jami: {0} ta yozuv").format(5), "Всего записей: 5")
        self.assertEqual(i18n.tr("tarjimasi yo'q matn"), "tarjimasi yo'q matn")

    def test_unknown_language_falls_back_to_uzbek(self):
        i18n.set_language("en")
        self.assertEqual(i18n.language(), i18n.UZBEK)

    def test_language_is_read_from_the_database_before_startup(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "ombor.db"
            self.assertEqual(i18n.stored_language(path), i18n.UZBEK)  # baza hali yo'q
            conn = connect(path)
            self.assertEqual(i18n.stored_language(path), i18n.UZBEK)  # til tanlanmagan
            Settings(conn).set(i18n.LANGUAGE_KEY, i18n.RUSSIAN)
            self.assertEqual(i18n.stored_language(path), i18n.RUSSIAN)
            Settings(conn).set(i18n.LANGUAGE_KEY, "xx")
            self.assertEqual(i18n.stored_language(path), i18n.UZBEK)
            conn.close()


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.addCleanup(i18n.set_language, i18n.UZBEK)

    def test_twelve_groups_as_in_the_source_list_and_other_expenses(self):
        self.assertEqual(len(catalog.GROUPS), 13)  # asl ro'yxatdagi 12 ta va «Прочие расходы»
        self.assertEqual(catalog.GROUPS[0].name.ru, "Административные расходы")
        self.assertEqual([len(group.subgroups) for group in catalog.GROUPS], [4, 6, 4, 3, 7, 4, 6, 1, 1, 1, 12, 3, 1])
        self.assertIs(catalog.GROUPS[-1], catalog.OTHER_EXPENSES)

    def test_stored_names_are_unique_within_each_group(self):
        for group in catalog.GROUPS:
            stored = [subgroup.ru for subgroup in group.subgroups]
            self.assertEqual(len(stored), len(set(stored)), group.name.ru)

    def test_display_follows_the_language(self):
        self.assertEqual(catalog.display_name("Стройматериал"), "Qurilish materiallari")
        self.assertEqual(catalog.display_name("Цемент"), "Sement")
        i18n.set_language(i18n.RUSSIAN)
        self.assertEqual(catalog.display_name("Стройматериал"), "Стройматериал")
        self.assertEqual(catalog.GROUPS[10].name.display, "Стройматериал")

    def test_values_outside_the_catalog_are_shown_as_is(self):
        self.assertEqual(catalog.display_name("O'zimning guruhim"), "O'zimning guruhim")
        self.assertEqual(catalog.display_name(""), "")
        self.assertIsNone(catalog.find_group("O'zimning guruhim"))


if __name__ == "__main__":
    unittest.main()
