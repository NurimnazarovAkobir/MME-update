# MME Ombor

Windows uchun ombor hisobi dasturi. Internet kerak emas: barcha ma'lumotlar shu kompyuterda saqlanadi.
Xohlasangiz, bir nechta kompyuter internet orqali **yagona bazada** ishlaydi — internetsiz qilingan
o'zgarishlar ulanish tiklanganda o'zi yuboriladi (pastda: «Markaziy server»).

## Ishga tushirish

`dist\MME-Ombor.exe` ni oching — o'rnatish shart emas. Xohlasangiz, yonidagi `Ornatish.bat` dasturni
kompyuterga ko'chirib, ish stoliga yorliq qo'yadi. Birinchi ochilganda dastur rahbar ismi va parolini so'raydi, so'ng **parolni tiklash
kodini** ko'rsatadi — uni qog'ozga yozib qo'ying.

## Bo'limlar

| Bo'lim | Nima qiladi |
|---|---|
| **Bosh sahifa** | Uchta katta tugma (Kirim, Chiqim, Yangi mahsulot), asosiy raqamlar, diagramma, so'nggi amallar |
| **Kirim** | Mahsulot kelishi: sana, hujjat raqami, miqdor, narx, guruh va kategoriya, **kim olib keldi**, yetkazib beruvchi, izoh; nakladnoy chop etish |
| **Chiqim** | Mahsulot chiqishi: sana, miqdor, **sotuv narxi** (bo'sh bo'lsa — ichki rasxod), guruh va kategoriya, kim oldi, xaridor yoki obyekt |
| **Mahsulotlar** | Mahsulot yoki xizmat qo'shish, **guruh → kategoriya**, joriy qoldiq, o'rtacha narx, qiymati, holati; guruh, kategoriya va «faqat kam qolganlar» filtri; inventarizatsiya varag'i; Exceldan yuklash. Menyuda kam qolgan mahsulotlar soni ko'rinadi |
| **Hisobotlar** | Kunlik, haftalik, oylik, yillik yoki ixtiyoriy davr bo'yicha hisobotlar |
| **Statistika** | Umumiy ko'rinish: eng ko'p chiqqan va sotib olingan mahsulotlar (top-10), kirim-chiqim dinamikasi, obyektlar bo'yicha rasxod, qaysi oyda qaysi mahsulot narxi oshgani yoki tushgani (oldingi xarid oyiga nisbatan, %) |
| **Qarzlar** | Yetkazib beruvchilarga qarzimiz, xaridorlarning qarzi, to'lovlar («Qarzga» belgili yozuvlardan) |
| **Tarix** | Faqat rahbarga: kim, qachon, nimani qo'shgan, o'zgartirgan, o'chirgan; o'chirilgan yozuvni tiklash |
| **Sozlamalar** | Fon, til, parol, avtomatik qulflash, hisob qoidalari, foydalanuvchilar, zaxira nusxa, markaziy server, qisqa yo'riqnoma |

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

**Avtomatik qulflash** (Telegram'dagi kabi): dastur belgilangan vaqt ishlatilmasa, ochiq oynalari bilan birga
yashiriladi va «Parolingizni kiriting» ekrani chiqadi — har kim (rahbar, omborchi…) o'z paroli bilan ochadi, yozilgan
ma'lumot yo'qolmaydi. Vaqtni har bir foydalanuvchi «Sozlamalar → Mening hisobim»da tanlaydi: o'chirilgan, 1, 5, 15
daqiqa yoki 1 soat (odatda 15 daqiqa). Darhol qulflash — yon menyudagi «Qulflash» tugmasi yoki **Ctrl+L**.

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
  va keyin har 5 daqiqada, shuningdek oynaga qaytilganda fonda tekshiradi; internet bo'lmasa, tekshiruv jimgina o'tkazib yuboriladi.
- **«Yangilash» bo'limi** (Windows Update kabi): holat, oxirgi tekshiruv vaqti, «Yangilanishlarni tekshirish» tugmasi.
  Yangi versiya topilsa, oyna chiqmaydi — menyuda «Yangilash» yonida qizil doirada «1» belgisi va sahifada «Yuklab olish va o'rnatish»
  havolasi paydo bo'ladi. Manbalarni (manzil, papka, fayl) faqat rahbar o'zgartiradi. Yangi versiya chiqarish: `APP_VERSION` ni
  oshirish → `build.bat` → `dist\MME-Ombor.exe` va `dist\versiya.txt` ni o'sha manzilga yuklash.
- **O'rnatish**: `Ornatish.bat` dasturni ko'chiradi, ish stoli va «Pusk»ga yorliq qo'yadi va Windows ning
  «O'rnatilgan ilovalar» ro'yxatiga yozadi; u yerdan (yoki `Ochirish.bat` bilan) o'chiriladi, ma'lumotlar qoladi.

## Google Drive orqali yagona baza (1.28) — server kerak emas

Hisoblar (login, parol, lavozim) exe ichida emas, bazada saqlanadi. Shuning uchun boshqa noutbukda rahbar va omborchi
o'z login-paroli bilan kirishi uchun noutbuklar bitta umumiy bazaga ulanadi. Eng oson yo'li — Google Drive papkasi:

1. **Ikkala noutbukka** «Google Drive for desktop» o'rnatiladi (Drive kompyuterda disk sifatida ko'rinadi, masalan `G:`).
2. **Rahbar noutbukida**: dasturda rahbar hisobini yarating, «Sozlamalar → Foydalanuvchilar»da omborchi va boshqa
   hisoblarni oching, keyin «Sozlamalar → Google Drive orqali umumiy baza → Papkani tanlab ulanish» — Drive ichidagi
   bo'sh papkani tanlang. Baza (hisoblar va parollar bilan) shu papkaga yoziladi.
3. Papkani Google Drive'da omborchi bilan **ulashing** (omborchi uni «Mening Diskim»ga yorliq qilib qo'shadi).
4. **Omborchi noutbukida**: dasturni oching va kirish oynasidagi **«Google Drive'dagi bazaga ulanish»** tugmasi bilan
   xuddi shu papkani tanlang. Dastur qayta ochiladi — omborchi rahbar bergan o'z login-paroli bilan kiradi.

Shundan keyin har kim o'z bazasida ishlaydi — internet bo'lmasa ham. Internet bo'lganda o'zgarishlar har 30 soniyada
Drive orqali hamma noutbukka yetib boradi; yon menyu pastida holat ko'rinadi.

Ichki tuzilish (`ombor/folder_sync.py`): papkada har bir noutbukning o'z papkachasi bor, u yerga faqat shu noutbuk
o'zgarishlar faylini yozadi (`000001.json`, `000002.json`…). Bitta faylga ikki kompyuter hech qachon yozmaydi, shuning
uchun Drive faylni buzmaydi yoki «nusxa (1)» qilmaydi. **Bazaning o'zini (`ombor.db`) Drive papkasiga qo'ymang.**
Bitta yozuvni ikki noutbuk internetsiz o'zgartirsa, keyinroq yuborgani qoladi; bir xil nomli mahsulot qo'shilsa,
birining nomiga « (a3f9)» kabi belgi qo'shiladi.

## Markaziy server: yagona baza va internetsiz ishlash (1.25)

Har bir kompyuter **o'z bazasida** ishlaydi — internet bo'lmasa ham hamma narsa odatdagidek. Server ulangach:

- har bir qo'shish, o'zgartirish va o'chirish navbatga yoziladi; internet bo'lishi bilan (har 30 soniyada va dastur
  ochilganda) serverga o'zi yuboriladi, boshqa kompyuterlardagi o'zgarishlar esa shu yerga keladi. Omborchi internetsiz
  kiritgan kirim-chiqim ulanish tiklanganda rahbarning kompyuterida ham paydo bo'ladi;
- yon menyuning pastida holat ko'rinadi: «☁ Sinxronlandi 14:32», «☁ Internet yo'q» (nechta o'zgarish kutayotgani bilan);
- tarix (kim, qachon, nimani o'zgartirgani) ham umumiy: rahbar boshqa kompyuterdagi amallarni «Tarix»da ko'radi.

**Serverni ishga tushirish** (doim yoqiq, internetdan ko'rinadigan kompyuter yoki VPS; faqat Python 3.10+ kerak):

```bat
sinxron_server.bat                                         :: Windows: kalitni so'raydi, 8765-portda ishlaydi
python -m ombor.sync_server --token MAXFIY-KALIT --port 8765 --data ombor-server.db
python -m ombor.sync_server --token ... --cert cert.pem --key key.pem   :: HTTPS
```

Internet orqali ishlaganda HTTPS ishlating (`--cert/--key` yoki server nginx/Caddy ortida). Kirish kaliti uzun va
tasodifiy bo'lsin: u bazaga kirish kaliti hisoblanadi. Server bazasi (`ombor-server.db`) — barcha kompyuterlarning
umumiy nusxasi; uni ham zaxiralang.

**Ulash** («Sozlamalar → Markaziy server», rahbar): server manzili va kalitni kiritib «Ulanish».

1. Birinchi kompyuter (odatda rahbarniki): server bo'sh — shu kompyuterdagi baza serverga yuboriladi va asosiy bo'ladi.
2. Qolgan kompyuterlar: serverda ma'lumot bor — shu kompyuterdagi ma'lumotlar serverdagilari bilan **almashtiriladi**
   (avval zaxira nusxa `zaxira\serverga-ulanishdan-oldin-….db` saqlanadi), dastur qayta ochiladi va serverdagi
   foydalanuvchi bilan kiriladi.

**Qoidalar:**

- Ikki kompyuter bitta yozuvni internetsiz o'zgartirsa, serverga **oxirgi yetib borgani** qoladi.
- Ikki kompyuter internetsiz bir xil nomli mahsulot (ombor, obyekt, xodim, foydalanuvchi) qo'shsa, ikkinchisining
  nomiga « (2)» qo'shiladi — keyin birlashtirish yoki nomini o'zgartirish mumkin.
- Bir kompyuterda o'chirilgan mahsulot boshqasida internetsiz ishlatilgan bo'lsa, u o'chmaydi va qaytib keladi.
- Ikki kompyuterda internetsiz bir vaqtda chiqim qilinsa, umumiy qoldiq minusga tushishi mumkin: sinxronlangach
  «Mahsulotlar»da ko'rinadi, inventarizatsiya yoki tuzatish bilan to'g'rilanadi.
- Har bir kompyuterning shaxsiy sozlamalari (til, fon, qo'shimcha zaxira papkasi, server manzili) almashilmaydi.
- «Zaxiradan tiklash» server ulangan kompyuterda bajarilsa, tiklangan holat hamma kompyuterlarga tarqaladi.
- Server bilan **shifrlangan baza** va **umumiy tarmoq papkasi** ishlatilmaydi (ular bir-birini istisno qiladi).
- Dastur va server versiyasi mos kelmasa (protokol), server rad etadi — dasturni yangilang.

## Exceldan yuklash: Excelda yuritilgan hisobni bazaga o'tkazish

«Mahsulotlar → Exceldan yuklash». Fayldagi har bir varaq o'qiladi (`ombor/excel_import.py`, `ombor/importer.py`):

| Varaq | Ustunlar (tartibi ixtiyoriy, o'zbekcha yoki ruscha) |
|---|---|
| **Mahsulotlar** | Nomi, Birlik, Guruh, Kategoriya, Minimal qoldiq, Boshlang'ich qoldiq, Narxi, Shtrix-kod, Izoh |
| **Kirim** | Sana, Hujjat №, Mahsulot, Miqdor, Birlik, Narxi (yoki Summa), Yetkazib beruvchi, Kim olib keldi, Guruh, Kategoriya, Ombor, Qarzga, Izoh |
| **Chiqim** | Sana, Hujjat №, Mahsulot, Miqdor, Sotuv narxi, Xaridor / obyekt, Kim oldi, Guruh, Kategoriya, Ombor, Qarzga, Izoh |
| **Obyektlar** | Nomi, Manzil, Mas'ul shaxs, Izoh |

- Varaq turi nomidan («Kirim», «Приход», «Chiqim», «Расход»…) yoki ustunlaridan taniladi; bitta jurnal varag'ida
  «Turi» ustuni (Kirim/Chiqim) bo'lsa ham bo'ladi. Sarlavha birinchi qatorda bo'lishi shart emas, «Jami» qatorlari
  o'tkazib yuboriladi. Dasturning o'zi «Excelga chiqarish»da yozgan fayl ham qayta yuklanadi.
- Sana — Excel sanasi yoki `03.10.2026`, `2026-10-03`; sonlar `1 250 000`, `12,5`, `32 000 so'm` ko'rinishida ham o'qiladi.
- Bazada yo'q mahsulot, guruh, kategoriya, ombor va obyektlar o'zi qo'shiladi; bor mahsulotning bo'sh guruhi to'ldiriladi.
- Yozuvlar sana tartibida yoziladi (bir kunda avval kirim, keyin chiqim), chiqim tannarxi o'zi hisoblanadi.
  Boshlang'ich qoldiq kirimi sanasi — ustunda berilgan bo'lsa o'sha, aks holda mahsulotning birinchi yozuvi sanasi.
- Yuklashdan oldin oyna nimalar qo'shilishini va o'qilmagan qatorlarni ko'rsatadi; bazaning zaxira nusxasi
  (`zaxira\exceldan-yuklashdan-oldin-….db`) olinadi.
- Xato qator (sana yo'q, son emas, qoldiq yetmaydi) qolganlarini to'xtatmaydi — natijada varaq va qator raqami bilan
  ko'rsatiladi. Excelda tuzatib, faylni **qayta yuklash xavfsiz**: bazada bor yozuvlar takrorlanmaydi.
- «Namuna faylni saqlash» — to'rtta varaqli to'ldirish namunasi.

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
  catalog.py         tovar guruhlari va kategoriyalari (ikki tilda)
  models.py          ma'lumot tuzilmalari (Product, Movement, Period, User…)
  database.py        SQLite sxemasi
  migrations.py      eski bazani yangi versiyaga o'tkazish
  costing.py         chiqim tannarxi (sirpanuvchi o'rtacha narx)
  sync_protocol.py   sinxronlash protokoli (mijoz va server uchun umumiy, faqat standart kutubxona)
  replication.py     o'zgarishlarni kuzatish (triggerlar, navbat) va serverdagilarni qo'llash
  sync.py            server bilan HTTP orqali almashish (mijoz)
  sync_server.py     markaziy server: python -m ombor.sync_server
  warehouse.py       mahsulot, kirim, chiqim, inventarizatsiya, o'zgarishlar tarixi
  reports.py         statistika so'rovlari
  statistics.py      «Statistika» bo'limi: reytinglar, oyma-oy narx o'zgarishi, obyektlar rasxodi
  auth.py            foydalanuvchilar, parollar, tiklash kodi
  analytics.py       foyda va zarar hisob-kitobi
  session.py         joriy foydalanuvchi va ruxsatlar
  services.py        barcha xizmatlar to'plami
  backup.py          qo'lda va avtomatik zaxira nusxa
  settings.py        kalit-qiymat sozlamalar
  excel_export.py    Excelga chiqarish
  excel_import.py    Excel faylini o'qish (mahsulotlar, kirim, chiqim, obyektlar)
  importer.py        o'qilgan hisobni bazaga yozish
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

## Guruhlar va kategoriyalar

Tuzilma ikki pog'onali: **guruh → kategoriya** (masalan, «Qurilish materiallari → Sement»).
12 ta boshlang'ich guruh va ularning kategoriyalari `ombor/catalog.py` da; «Sozlamalar → Guruhlarni tahrirlash»da o'zgartiriladi.

- **Mahsulotning o'z guruhi**: mahsulot oynasida guruh va kategoriya tanlanadi. «Mahsulotlar» bo'limida avval guruh,
  keyin uning kategoriyasi bo'yicha filtrlanadi; inventarizatsiya varag'i ham shu filtrga bo'ysunadi.
- Har bir **kirim va chiqim yozuvida** ham guruh saqlanadi: kirim/chiqim oynasida mahsulot tanlanganda mahsulotning
  guruhi o'zi taklif qilinadi (berilmagan bo'lsa — oldingi yozuvdagisi), kerak bo'lsa o'zgartiriladi.
- 1.25 ga yangilanganda har bir mahsulotga oxirgi yozuvidagi guruh o'zi beriladi.
- «Hisobotlar → Guruhlar bo'yicha» — tanlangan davrda har bir guruh va kategoriya bo'yicha kirim va chiqim summasi.
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
