# Arxiv: litsenziya

Litsenziya (kompyuterga bog'langan kalit, sinov muddati, faqat ko'rish rejimi) dasturdan vaqtincha olib
tashlangan. Kodi shu yerda saqlanadi — dasturga ulanmagan va yig'ilgan exe ga kirmaydi.

| Fayl | Avval qayerda edi |
|---|---|
| `licensing.py`, `license_key.py` | `ombor/` |
| `license_dialogs.py` | `ombor/ui/` |
| `test_licensing.py` | `tests/` (LicenseTests sinfi) |
| `translations_ru.txt` | `ombor/translations_ru.py` dagi litsenziya matnlari |
| `litsenziya.py`, `litsenziya.bat`, `kalit_yaratish.py`, `SOTUVCHI.md` | `sotuvchi/` — kalit beradigan dastur |
| `maxfiy_kalit.pem` | `sotuvchi/` — **maxfiy kalit, hech kimga bermang** |

Qayta ulash uchun fayllarni joyiga qaytarish, `cryptography` ni `requirements.txt` ga qo'shish va
`app.py`, `services.py`, `session.py`, `main_window.py`, `settings_page.py` da litsenziya holatini qayta
tekshirish kerak bo'ladi. Shu kalit bilan hali hech kimga litsenziya berilmagan.
