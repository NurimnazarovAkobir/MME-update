# MME Ombor

Windows uchun ombor hisobi dasturi. Internet kerak emas: barcha ma'lumotlar shu kompyuterda saqlanadi.

## Ishga tushirish

`dist\MME-Ombor.exe` ni oching — o'rnatish shart emas. Xohlasangiz, yonidagi `Ornatish.bat` dasturni
kompyuterga ko'chirib, ish stoliga yorliq qo'yadi. Birinchi ochilganda dastur rahbar ismi va parolini so'raydi, so'ng **parolni tiklash
kodini** ko'rsatadi — uni qog'ozga yozib qo'ying.

## Bo'limlar

| Bo'lim | Nima qiladi |
|---|---|
| **Bosh sahifa** | Uchta katta tugma (Kirim, Chiqim, Yangi mahsulot), asosiy raqamlar, diagramma, so'nggi amallar |
| **Kirim** | Mahsulot kelishi: sana, miqdor, narx, guruh va kichik guruh, **kim olib keldi**, yetkazib beruvchi, izoh |
| **Chiqim** | Mahsulot chiqishi: sana, miqdor, **sotuv narxi** (bo'sh bo'lsa — ichki rasxod), guruh va kichik guruh, kim oldi, xaridor yoki obyekt |
| **Mahsulotlar** | Mahsulot qo'shish (nomi, birligi, minimal qoldiq), joriy qoldiq, o'rtacha narx, qiymati, holati; inventarizatsiya; Exceldan yuklash |
| **Hisobotlar** | Kunlik, haftalik, oylik, yillik yoki ixtiyoriy davr bo'yicha hisobotlar |
| **Sozlamalar** | Fon, til, parol, foydalanuvchilar, zaxira nusxa |

Tahrirlash va o'chirish har bir qatorning boshida: **✎** — tahrirlash (yoki qatorni ikki marta bosish), **✕** — o'chirish (yoki Delete tugmasi; avval tasdiq so'raladi).

Har bir jadvalni **chop etish** va **Excelga chiqarish** mumkin. Ustun sarlavhasini bosish — shu ustun bo'yicha
saralash. Har bir kirim/chiqim yonida uni **kim kiritgani** yoziladi.

## Foydalanuvchilar

| Lavozim | Nima qila oladi |
|---|---|
| **Omborchi** | Kirim, chiqim va mahsulot qo'shadi; hisobotlarni ko'radi, chop etadi; o'z parolini o'zgartiradi |
| **Rahbar** | Yuqoridagilar + tahrirlash, o'chirish, inventarizatsiya, foydalanuvchilar, zaxira nusxa |

Omborchi parolini unutsa, rahbar «Sozlamalar»da yangisini o'rnatadi. Rahbar unutsa — kirish oynasidagi
«Parolni unutdim» tugmasi va tiklash kodi orqali. Kod yo'qolgan bo'lsa, «Sozlamalar → Yangi tiklash kodi».
Parol dasturga kirishni cheklaydi; ma'lumotlar fayli shifrlanmaydi.

## Hisobotlar

Yuqoridan davr turi tanlanadi: **Kunlik / Haftalik / Oylik / Yillik / Boshqa davr**; ◀ ▶ tugmalari oldingi va
keyingi davrga o'tkazadi.

| Hisobot | Nimani ko'rsatadi |
|---|---|
| **Aylanma qaydnoma** | Har bir mahsulot: boshlang'ich qoldiq, kirim, chiqim, oxirgi qoldiq, summalar |
| **Davrlar bo'yicha** | Hafta va oy — kunma-kun, yil — oyma-oy: kirim va chiqim soni hamda summasi |
| **Kim olib keldi / Yetkazib beruvchilar** | Kim (qaysi firma) qancha summalik mahsulot keltirgan |
| **Kim oldi / Obyektlar bo'yicha rasxod** | Kim olgan va qaysi obyektga qancha rasxod bo'lgan |

## Hisoblash qoidalari

- **Qoldiq** sana tartibida hisoblanadi: biror sanada ombordagidan ko'p chiqim qilib bo'lmaydi
  (5-oktabrda kelgan molni 1-oktabr sanasi bilan chiqarib bo'lmaydi).
- **Chiqim (rasxod) summasi** = miqdor × o'sha paytdagi qoldiqning o'rtacha tannarxi. Bu narx yozuvda
  saqlanadi, shuning uchun keyin boshqa narxda kelgan mol o'tgan davrlarning rasxodini o'zgartirmaydi.
  O'tgan sanadagi yozuv tahrirlansa yoki o'chirilsa, undan keyingi chiqimlar qayta hisoblanadi.
- **Inventarizatsiya**: sanalgan haqiqiy qoldiq kiritiladi; farqni dastur «Inventarizatsiya (ortiqcha)» kirimi
  yoki «Inventarizatsiya (kamomad)» chiqimi sifatida o'zi yozadi.

## Mahsulotlarni Exceldan yuklash

«Mahsulotlar → Exceldan yuklash → Namuna faylni saqlash», namunani to'ldirib, shu yerdan yuklang.
Ustunlar: `Nomi | Birlik | Minimal qoldiq | Qoldiq | Narxi`. «Qoldiq» ko'rsatilgan mahsulotga
bugungi sana bilan «Boshlang'ich qoldiq» kirimi yoziladi. Ro'yxatda bor mahsulotlar o'zgarmaydi.

## Ma'lumotlar va zaxira nusxa

- Ma'lumotlar: `%APPDATA%\MetallMontajExpert\ombor.db` (bitta fayl).
- Dastur har ochilganda va yopilganda nusxani **o'zi** saqlaydi: `%APPDATA%\MetallMontajExpert\zaxira\`,
  oxirgi 30 kun. Bu xato kiritilgan yoki o'chirilgan ma'lumotdan himoya qiladi.
- Disk buzilishidan himoya uchun «Sozlamalar → Qo'shimcha papkani tanlash» orqali **fleshka yoki boshqa
  diskni** ko'rsating — nusxa u yerga ham yoziladi (fleshka ulanmagan bo'lsa, o'sha safar o'tkazib yuboriladi).
- «Zaxiradan tiklash» mahsulot va yozuvlarni almashtiradi; foydalanuvchilar va parollar o'zgarmaydi.

## Dasturchilar uchun

```
main.py              ishga tushirish nuqtasi
ombor/
  config.py          nomlar va doimiy qiymatlar
  paths.py           ma'lumotlar fayllarining joyi
  i18n.py            til: tr() funksiyasi
  translations_ru.py ruscha tarjimalar
  catalog.py         tovar guruhlari va kichik guruhlari (ikki tilda)
  models.py          ma'lumot tuzilmalari (Product, Movement, Period, User…)
  database.py        SQLite sxemasi
  migrations.py      eski bazani yangi versiyaga o'tkazish
  costing.py         chiqim tannarxi (sirpanuvchi o'rtacha narx)
  warehouse.py       mahsulot, kirim, chiqim, inventarizatsiya
  reports.py         statistika so'rovlari
  auth.py            foydalanuvchilar, parollar, tiklash kodi
  analytics.py       foyda va zarar hisob-kitobi
  session.py         joriy foydalanuvchi va ruxsatlar
  services.py        barcha xizmatlar to'plami
  backup.py          qo'lda va avtomatik zaxira nusxa
  settings.py        kalit-qiymat sozlamalar
  excel_export.py    Excelga chiqarish
  excel_import.py    mahsulotlarni Exceldan o'qish
  formatting.py      son va sana formati
  ui/                oynalar va sahifalar (PySide6)
tests/               mantiq testlari
toplam/              exe bilan birga beriladigan fayllar (Ornatish.bat, OQING.txt)
arxiv/litsenziya/    vaqtincha olib tashlangan litsenziya kodi (dasturga ulanmagan)
```

```bat
.venv\Scripts\python main.py                             :: manba koddan ishga tushirish
.venv\Scripts\python -m unittest discover -s tests -t .  :: testlar
build.bat                                                :: dist\MME-Ombor.exe ni qayta yig'ish
```

## Tez ishlash

- **F2** — yangi kirim, **F3** — yangi chiqim, **F4** — yangi mahsulot (istalgan sahifadan).
- Jadvalda: **✎** yoki ikki marta bosish — tahrirlash; **✕** yoki Delete — o'chirish.
- Kirim/chiqim oynasida mahsulot nomini yozib qidirish mumkin. Yangi mahsulot alohida qo'shiladi:
  bosh sahifadagi «Yangi mahsulot», F4 yoki «Mahsulotlar» bo'limi.
- Foyda: «Hisobotlar → Foyda». Foyda faqat sotuv narxi kiritilgan chiqimlardan hisoblanadi.

## Guruhlar

Har bir **kirim va chiqim yozuvida** guruh va kichik guruh tanlanadi (mahsulotda emas): bitta mahsulot bir
safar «Qurilish materiallari», boshqa safar «Ishlab chiqarish xarajatlari» sifatida yozilishi mumkin.
12 ta guruh va ularning kichik guruhlari `ombor/catalog.py` da.

- Kirim/chiqim oynasida avval guruh, keyin shu guruhning kichik guruhi tanlanadi. Tanlash ixtiyoriy.
- Mahsulot tanlanganda uning oldingi yozuvidagi guruh o'zi taklif qilinadi.
- «Hisobotlar → Guruhlar bo'yicha» — tanlangan davrda har bir guruh va kichik guruh bo'yicha kirim va chiqim summasi.
- Bazada guruhning ruscha nomi saqlanadi, ekranda tanlangan tilda ko'rsatiladi.

## Tillar

Dastur o'zbek va rus tillarida ishlaydi. Til kirish oynasida yoki «Sozlamalar → Ko'rinish» da tanlanadi;
tanlanganda dastur shu tilda qayta ochiladi. Tanlov bazada saqlanadi.

Yangi matn qo'shishda: kodda o'zbekcha yozib `tr("...")` ga o'rang va ruschasini `translations_ru.py` ga
qo'shing. `tests/test_i18n.py` tarjimasi yo'q yoki ortiqcha qolgan matnni topadi.

Tarjima qilinmaydi: foydalanuvchi kiritgan ma'lumotlar (mahsulot nomlari, o'lchov birliklari, ismlar) va
dastur o'zi yozadigan «Inventarizatsiya (ortiqcha/kamomad)» belgisi — ular bazada saqlanadi.
