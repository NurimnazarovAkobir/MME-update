"""MME Ombor — ombor dasturi. Ishga tushirish: python main.py"""

import sys

from ombor import i18n
from ombor.paths import DB_PATH

# Til boshqa modullar yuklanishidan oldin o'rnatiladi: ulardagi matnlar yuklanish paytida tarjima qilinadi.
i18n.set_language(i18n.stored_language(DB_PATH))

from ombor.app import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
