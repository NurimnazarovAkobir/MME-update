"""Litsenziya imzolash uchun kalit juftligini BIR MARTA yaratadi.

  maxfiy_kalit.pem      — faqat sotuvchida turadi; hech kimga berilmaydi, zaxirasi olinadi.
  ombor/license_key.py  — ochiq kalit; dastur (exe) ichiga kiradi.

Mavjud kalit ustidan yozilmaydi: yangi kalit bilan yig'ilgan dastur avval
berilgan barcha litsenziyalarni tanimay qoladi.
"""

import sys
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

SELLER_DIR = Path(__file__).resolve().parent
PRIVATE_KEY_PATH = SELLER_DIR / "maxfiy_kalit.pem"
PUBLIC_KEY_MODULE = SELLER_DIR.parent / "ombor" / "license_key.py"

MODULE_TEMPLATE = '''"""Litsenziya imzosini tekshiradigan ochiq kalit (sotuvchi/kalit_yaratish.py yozgan).

Bu maxfiy emas. Unga mos maxfiy kalit — sotuvchi/maxfiy_kalit.pem.
"""

PUBLIC_KEY_HEX = "{public_key}"
'''


def main() -> None:
    if PRIVATE_KEY_PATH.exists():
        sys.exit(f"Kalit allaqachon bor: {PRIVATE_KEY_PATH}\nUstidan yozilmadi.")
    private_key = Ed25519PrivateKey.generate()
    PRIVATE_KEY_PATH.write_bytes(
        private_key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
        )
    )
    public_bytes = private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    PUBLIC_KEY_MODULE.write_text(MODULE_TEMPLATE.format(public_key=public_bytes.hex()), encoding="utf-8")
    print(f"Maxfiy kalit: {PRIVATE_KEY_PATH}\nOchiq kalit:  {PUBLIC_KEY_MODULE}")


if __name__ == "__main__":
    main()
