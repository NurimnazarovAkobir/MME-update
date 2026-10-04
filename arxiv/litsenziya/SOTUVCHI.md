# Sotuvchi uchun: litsenziya berish

Bu papka **faqat sizda** turadi. Mijozga faqat `dist\MME-Ombor.exe` yuboriladi.

## Mijozga dastur berish

1. Mijozga `dist\MME-Ombor.exe` ni yuboring. U 14 kun kalitsiz ishlaydi.
2. Mijoz dasturda «Sozlamalar → Litsenziya» dagi **kompyuter kodini** (masalan `AVD5-4JPM-9BK4`) sizga yuboradi.
3. `litsenziya.bat` ni oching, firma nomi, kod va muddatni kiriting, «Kalit yaratish» ni bosing.
4. Chiqqan kalitni (MME1.… bilan boshlanadi) mijozga yuboring. U «Litsenziya kalitini kiritish» ga qo'yadi.

Har bir berilgan kalit `berilgan_litsenziyalar.csv` ga yoziladi (Excelda ochiladi) — kimga, qaysi
kompyuterga, qachongacha berilganini shu yerdan ko'rasiz.

## Bilish kerak

- **Kalit bitta kompyuterga bog'langan.** Mijoz kompyuterni almashtirsa yoki Windowsni qayta o'rnatsa,
  kod o'zgaradi va yangi kalit kerak bo'ladi.
- **Muddat tugaganda** dastur faqat ko'rish rejimiga o'tadi; mijoz to'lagach, yangi kalit berasiz.
- **Firma nomi** kalit ichida: mijoz dasturida va chop etilgan hujjatlarda shu nom chiqadi.

## `maxfiy_kalit.pem` — eng muhim fayl

- Uni **hech kimga bermang** va internetga qo'ymang: u bilan istalgan odam litsenziya yasay oladi.
- **Zaxirasini oling** (fleshka, boshqa kompyuter). Yo'qolsa, yangi litsenziya bera olmaysiz — dasturni
  yangi kalit bilan qayta yig'ib, barcha mijozlarga qaytadan tarqatish kerak bo'ladi.
- `kalit_yaratish.py` ni qayta ishga tushirmang: u mavjud kalit ustidan yozmaydi, lekin kalitni o'chirib
  qayta yaratsangiz, avval berilgan barcha litsenziyalar ishlamay qoladi.
