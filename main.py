"""MME Ombor — ombor dasturi. Ishga tushirish: python main.py"""

import sys

if "--sinov" in sys.argv:
    import ombor.app  # noqa: F401

    sys.exit(0)

from ombor import i18n  # noqa: E402
from ombor.paths import DB_PATH, read_prefs  # noqa: E402

i18n.set_language(read_prefs().get(i18n.LANGUAGE_KEY) or i18n.stored_language(DB_PATH))

from ombor.app import run  

if __name__ == "__main__":
    sys.exit(run())
