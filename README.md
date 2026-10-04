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
| **Kirim** | Mahsulot kelishi: sana, hujjat raqami, miqdor, narx, guruh va kichik guruh, **kim olib keldi**, yetkazib beruvchi, izoh; nakladnoy chop etish |
| **Chiqim** | Mahsulot chiqishi: sana, miqdor, **sotuv narxi** (bo'sh bo'lsa — ichki rasxod), guruh va kichik guruh, kim oldi, xaridor yoki obyekt |
| **Mahsulotlar** | Mahsulot yoki xizmat qo'shish, joriy qoldiq, o'rtacha narx, qiymati, holati; «faqat kam qolganlar» filtri; inventarizatsiya varag'i; Exceldan yuklash. Menyuda kam qolgan mahsulotlar soni ko'rinadi |
| **Hisobotlar** | Kunlik, haftalik, oylik, yillik yoki ixtiyoriy davr bo'yicha hisobotlar |
| **Qarzlar** | Yetkazib beruvchilarga qarzimiz, xaridorlarning qarzi, to'lovlar («Qarzga» belgili yozuvlardan) |
| **Tarix** | Faqat rahbarga: kim, qachon, nimani qo'shgan, o'zgartirgan, o'chirgan; o'chirilgan yozuvni tiklash |
| **Sozlamalar** | Fon, til, parol, hisob qoidalari, foydalanuvchilar, zaxira nusxa, qisqa yo'riqnoma |

Tahrirlash va o'chirish har bir qatorning boshida: **✎** — tahrirlash (yoki qatorni ikki marta bosish), **✕** — o'chirish (yoki Delete tugmasi; avval tasdiq so'raladi).

Har bir jadvalni **chop etish** va **Excelga chiqarish** mumkin. Ustun sarlavhasini bosish — shu ustun bo'yicha
saralash. Har bir kirim/chiqim yonida uni **kim kiritgani** yoziladi.

## Foydalanuvchilar

| Lavozim | Nima qila oladi |
|---|---|
| **Kuzatuvchi** | Faqat ko'radi, chop etadi, Excelga chiqaradi (masalan, buxgalter) |
| **Omborchi** | Kirim, chiqim va mahsulot qo'shadi; **o'zi bugun kiritgan** yozuvni tahrirlaydi yoki o'chiradi |
| **Rahbar** | Hammasi: istalgan yozuvni tahrirlash va o'chirish, inventarizatsiya, tarix, foydalanuvchilar, zaxira nusxa |

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

- **Sana**: bugundan keyingi sana bilan yozuv kiritib bo'lmaydi.
- **Guruh**: «Sozlamalar → Hisob qoidalari»da majburiy qilish mumkin.
- **O'chirish**: yozuv bazadan yo'qolmaydi — hisobdan chiqadi va «Tarix → O'chirilgan yozuvlar»da turadi;
  rahbar uni tiklashi mumkin (tiklash qoldiqni manfiy qilsa, rad etiladi).
- **Tarix**: har bir qo'shish, tahrirlash, o'chirish va tiklash kim tomonidan va qachon qilingani bilan yoziladi.
- **Xizmat va xarajatlar** (yuk tashish, ijara, kommunal): mahsulot oynasida «Bu xizmat yoki xarajat» belgisi.
  Qoldig'i yuritilmaydi; kirimi xarajat bo'lib, «Hisobotlar»dagi **sof foyda**dan ayriladi
  (sof foyda = sotuvdan foyda − xizmat va xarajatlar).
- **Hujjat raqami**: bir nakladnoydagi mahsulotlar bir xil «Hujjat №» bilan «Saqlash va yana qo'shish» orqali
  kiritiladi; «Nakladnoy» tugmasi sanasi va raqami bir xil yozuvlarni bitta varaqda chop etadi.
- **Inventarizatsiya varag'i**: jadvaldagi barcha mahsulotlar bitta oynada; faqat o'zgartirilganlari tuzatiladi.

## Omborlar, qaytarish, qarzlar, birliklar (1.2)

- **Bir nechta ombor**: «Sozlamalar → Omborlar»da qo'shiladi. Kirim va chiqimda ombor tanlanadi; «Mahsulotlar»da
  ombor bo'yicha qoldiq ko'rinadi va «Ko'chirish» bilan mahsulot ombordan omborga o'tkaziladi. O'rtacha tannarx
  barcha omborlar uchun bitta; qoldiq har bir omborda alohida tekshiriladi. Inventarizatsiya — har bir omborda alohida.
- **Qaytarish**: kirimda «xaridordan qaytgan mahsulot» (tushum va foydani kamaytiradi), chiqimda «yetkazib
  beruvchiga qaytarilmoqda» (sotuv hisoblanmaydi).
- **Qarzlar**: yozuvda «Qarzga» belgilansa, summasi kontragent hisobiga tushadi; to'lovlar «Qarzlar» bo'limida yoziladi.
- **Qo'shimcha birlik**: mahsulotga ikkinchi birlik va nisbat beriladi (masalan, 1 tonna = 1000 kg); kirim-chiqimda
  miqdor va narxni ikkalasida kiritish mumkin, bazada asosiy birlikda saqlanadi.
- **Shtrix-kod**: mahsulotga yoziladi; kirim-chiqim oynasida mahsulot maydoniga skaner bilan o'qitilsa, mahsulot tanlanadi.
- **Guruhlar**: «Sozlamalar → Guruhlarni tahrirlash» — qo'shish, nomini o'zgartirish, o'chirish (`groups` jadvali;
  `catalog.py` dagi ro'yxat faqat yangi baza uchun boshlang'ich).

## Tarmoq, shifrlash, yangilash, o'rnatish (1.2)

- **Bir nechta kompyuter**: baza tarmoqdagi umumiy papkaga ko'chiriladi («Sozlamalar → Tarmoqda ishlash»), boshqa
  kompyuterlar kirish oynasidagi «Tarmoqdagi bazaga ulanish» bilan shu papkani ko'rsatadi. Baza joyi, til va fon
  har bir kompyuterning o'zida (`%APPDATA%\MetallMontajExpert\sozlama.json`) saqlanadi. Ochiq sahifa boshqa
  kompyuterdagi o'zgarishlarni 10 soniyada o'zi ko'rsatadi. Bu — umumiy fayl (SQLite) bilan ishlash, alohida
  server emas: 2–5 kompyuter uchun mo'ljallangan, ishonchli (simli) tarmoq va kunlik zaxira nusxa shart.
- **Shifrlash** (ixtiyoriy, «Sozlamalar → Bazani shifrlash»): SQLCipher (AES-256). Baza kaliti har bir
  foydalanuvchining paroli va tiklash kodi bilan o'ralib, baza yonidagi `ombor.kalit` faylida turadi (`vault.py`).
  Zaxira nusxalar ham shifrlanadi, yoniga `.kalit` fayli qo'yiladi. Parol ham, tiklash kodi ham yo'qolsa —
  ma'lumotni tiklab bo'lmaydi.
- **Yangilash**: «Yangilash» bo'limi — yangi `MME-Ombor.exe` ko'rsatiladi yoki yangilanishlar papkasi
  belgilanadi (`MME-Ombor.exe` + `versiya.txt`). Eski dastur yangi bazani ochmaydi.
- **Internet orqali yangilash** (1.3): shu ikki fayl internetdagi https manzilga qo'yiladi (masalan, GitHub Releases:
  `https://github.com/<foydalanuvchi>/<repo>/releases/latest/download/`). Manzil `config.py` dagi
  `DEFAULT_UPDATE_URL` ga yoziladi (hamma nusxalar uchun) yoki «Yangilash» bo'limida kiritiladi. Dastur ochilganda
  va keyin har 3 soatda fonda tekshiradi; internet bo'lmasa, tekshiruv jimgina o'tkazib yuboriladi.
- **«Yangilash» bo'limi** (Windows Update kabi): holat, oxirgi tekshiruv vaqti, «Yangilanishlarni tekshirish» tugmasi.
  Yangi versiya topilsa, oyna chiqmaydi — menyuda «Yangilash ●» belgisi va sahifada «Yuklab olish va o'rnatish»
  havolasi paydo bo'ladi. Manbalarni (manzil, papka, fayl) faqat rahbar o'zgartiradi. Yangi versiya chiqarish: `APP_VERSION` ni
  oshirish → `build.bat` → `dist\MME-Ombor.exe` va `dist\versiya.txt` ni o'sha manzilga yuklash.
- **O'rnatish**: `Ornatish.bat` dasturni ko'chiradi, ish stoli va «Pusk»ga yorliq qo'yadi va Windows ning
  «O'rnatilgan ilovalar» ro'yxatiga yozadi; u yerdan (yoki `Ochirish.bat` bilan) o'chiriladi, ma'lumotlar qoladi.

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
  warehouse.py       mahsulot, kirim, chiqim, inventarizatsiya, o'zgarishlar tarixi
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
tests/               mantiq va interfeys (ekransiz) testlari
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

Tarjima qilinmaydi: foydalanuvchi kiritgan ma'lumotlar (mahsulot nomlari, o'lchov birliklari, ismlar) — ular
bazada saqlanadi. Dastur o'zi yozadigan «Inventarizatsiya (ortiqcha/kamomad)» va «Boshlang'ich qoldiq»
belgilari bazada bitta ko'rinishda saqlanadi, ekranda esa tanlangan tilda chiqadi. Windows ning o'z oynalari
(chop etishni ko'rish) ruschada rus tilida, o'zbekchada inglizcha chiqadi — Qt da o'zbekcha tarjima yo'q.
