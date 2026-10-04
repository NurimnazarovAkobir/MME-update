"""MME Ombor — ombor dasturi. Ishga tushirish: python main.py"""

import sys

# Sinov ishga tushirishi: yangi versiya shu kompyuterda ochila olishini tekshirish uchun (update.can_run).
# Hech narsa yuklanmasdan va hech qanday oyna ochilmasdan darhol tugaydi.
if "--sinov" in sys.argv:
    sys.exit(0)

from ombor import i18n  # noqa: E402
from ombor.paths import DB_PATH, read_prefs  # noqa: E402

# Til boshqa modullar yuklanishidan oldin o'rnatiladi: ulardagi matnlar yuklanish paytida tarjima qilinadi.
# Til shu kompyuterning shaxsiy sozlamasida turadi; oldingi versiyalarda u bazada saqlangan.
i18n.set_language(read_prefs().get(i18n.LANGUAGE_KEY) or i18n.stored_language(DB_PATH))

from ombor.app import run  # noqa: E402

if __name__ == "__main__":
    sys.exit(run())
