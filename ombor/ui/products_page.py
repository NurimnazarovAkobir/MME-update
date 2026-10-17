"""Mahsulotlar va ularning ombordagi qoldig'i."""

from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QMessageBox

from ..catalog import display_name, find_group, groups
from ..config import CURRENCY
from ..backup import Backup
from ..formatting import fmt_money
from ..i18n import tr
from ..importer import ExcelImporter
from ..models import ProductStock, StockStatus
from ..session import Session
from ..sites import Sites
from ..warehouse import Warehouse
from .dialogs import InventoryDialog, ProductDialog
from .extra_dialogs import TransferDialog
from .icons import Glyph
from .import_dialog import import_from_excel
from .list_page import ListPage
from .product_card import ProductCardDialog
from .site_dialogs import TableDialog
from .widgets import Column, ColumnKind, button

STATUS_COLUMN = 7
_PURCHASE_COLUMNS = (
    Column(tr("Mahsulot"), style="strong"),
    Column(tr("Birlik")),
    Column(tr("Qoldiq"), ColumnKind.QUANTITY),
    Column(tr("Minimal qoldiq"), ColumnKind.QUANTITY),
    Column(tr("Olish kerak"), ColumnKind.QUANTITY, "strong"),
    Column(tr("Oxirgi narx"), ColumnKind.MONEY),
    Column(tr("Taxminiy summa"), ColumnKind.MONEY),
    Column(tr("Oxirgi yetkazib beruvchi")),
)


def _group_title(product: ProductStock) -> str:
    return " / ".join(display_name(name) for name in (product.category, product.subcategory) if name)


class ProductsPage(ListPage):
    delete_question = tr("Bu mahsulot ro'yxatdan o'chirilsinmi?")

    def __init__(
        self,
        warehouse: Warehouse,
        sites: Sites,
        session: Session,
        importer: ExcelImporter | None = None,
        backup: Backup | None = None,
    ):
        """`importer` berilsa — «Exceldan yuklash» tugmasi (mahsulot, kirim, chiqim, obyektlar); `backup` — undan oldin nusxa."""
        columns = (
            Column(tr("Mahsulot"), style="strong"),
            Column(tr("Guruh / kategoriya")),
            Column(tr("Qoldiq"), ColumnKind.QUANTITY, "strong"),
            Column(tr("Birlik")),
            Column(tr("Minimal qoldiq"), ColumnKind.QUANTITY),
            Column(tr("O'rtacha narx"), ColumnKind.MONEY),
            Column(tr("Qiymati"), ColumnKind.MONEY, "strong"),
            Column(tr("Holati"), style="strong"),
        )
        super().__init__(
            tr("Mahsulotlar"),
            tr("+ Yangi mahsulot"),
            columns,
            session,
            glyph=Glyph.PRODUCTS,
            subtitle=tr("Mahsulotlar ro'yxati va ombordagi qoldiq"),
        )
        self._warehouse = warehouse
        self._sites = sites
        self._importer = importer
        self._backup = backup
        self.empty_hint = tr("Ish mahsulot qo'shishdan boshlanadi: «Yangi mahsulot» tugmasini bosing.")
        # «Holati» — rangli yorliq: yetarli yashil, kam qolgan sariq, tugagan qizil.
        self.table.set_badges(
            STATUS_COLUMN,
            {
                StockStatus.OK.value: "good",
                StockStatus.LOW.value: "warning",
                StockStatus.EMPTY.value: "danger",
                StockStatus.SERVICE.value: "accent",
            },
        )

        # Ombor tanlagich va «Ko'chirish» faqat bir nechta ombor bo'lganda ko'rinadi.
        self._store = QComboBox()
        self._store.currentIndexChanged.connect(self.refresh)
        self.header_tools.addWidget(self._store)
        self._group = QComboBox()
        self._group.setToolTip(tr("Faqat shu guruh mahsulotlari"))
        self._category = QComboBox()
        self._category.setToolTip(tr("Faqat guruhning shu kategoriyasi"))
        self._group.currentIndexChanged.connect(self._fill_categories)
        self._category.currentIndexChanged.connect(self.refresh)
        self.header_tools.addWidget(self._group)
        self.header_tools.addWidget(self._category)
        self._only_low = QCheckBox(tr("Kam qolganlar"))
        self._only_low.setToolTip(tr("Faqat kam qolgan va tugagan mahsulotlarni ko'rsatish"))
        self._only_low.toggled.connect(self.refresh)
        self.header_tools.addWidget(self._only_low)
        self._transfer = button(tr("Ko'chirish"), glyph=Glyph.SWITCH)
        self._transfer.setToolTip(tr("Mahsulotni bir ombordan boshqasiga ko'chirish"))
        self._transfer.clicked.connect(self._move_between_stores)
        if session.can_add:
            self.toolbar_tools.addWidget(self._transfer)
        purchases = button(tr("Xarid ro'yxati"), glyph=Glyph.SHOP)
        purchases.setToolTip(tr("Kam qolgan va tugagan mahsulotlar: nimani, qancha va qanchadan olish kerak"))
        purchases.clicked.connect(self._show_purchase_list)
        self.toolbar_tools.addWidget(purchases)
        self.table.setToolTip(tr("Mahsulot kartochkasi — qatorni ikki marta bosing"))
        if session.can_add and importer is not None:
            import_button = button(tr("Exceldan yuklash"), glyph=Glyph.IMPORT)
            import_button.setToolTip(tr("Excelda yuritilgan mahsulotlar, kirim, chiqim va obyektlarni bazaga yuklash"))
            import_button.clicked.connect(self._import_from_excel)
            self.header_tools.addWidget(import_button)
        if session.can_modify:
            inventory = button(tr("Inventarizatsiya"), glyph=Glyph.CLIPBOARD)
            inventory.setToolTip(tr("Jadvaldagi mahsulotlarning sanab chiqilgan haqiqiy qoldig'ini kiritish"))
            inventory.clicked.connect(self._take_inventory)
            self.header_tools.addWidget(inventory)

    def refresh(self) -> None:
        self._fill_stores()
        self._fill_groups()
        products = self._shown_products()
        self.table.set_rows(
            [
                (p.name, _group_title(p), p.stock, p.unit, p.min_stock, p.average_price, p.value, p.status.value)
                for p in products
            ],
            ids=[p.id for p in products],
            flagged=[index for index, p in enumerate(products) if p.needs_attention],
        )
        total = sum(p.value for p in products)
        self.footer.setText(
            tr("Jami: {0} ta mahsulot  ·  ombordagi qiymati {1} {2}").format(len(products), fmt_money(total), CURRENCY)
        )

    def edit_dialog(self, item_id: int | None) -> QDialog:
        product = self._warehouse.product(item_id) if item_id is not None else None
        return ProductDialog(self._warehouse, product, self)

    def delete_item(self, item_id: int) -> None:
        self._warehouse.delete_product(item_id)

    def activate(self, item_id: int) -> None:
        """Qatorni ikki marta bosish — mahsulot kartochkasi (tahrirlash — qatordagi qalam tugmasi)."""
        ProductCardDialog(self._warehouse, self._sites, item_id, self).exec()

    def _show_purchase_list(self) -> None:
        lines = self._warehouse.purchase_list()
        total = sum(line.amount for line in lines)
        TableDialog(
            tr("Xarid ro'yxati"),
            tr(
                "Kam qolgan va tugagan mahsulotlar. «Olish kerak» — qoldiqni minimal qoldiqning ikki "
                "barobarigacha to'ldirish uchun. Taxminiy jami: {0} {1}"
            ).format(fmt_money(total), CURRENCY),
            _PURCHASE_COLUMNS,
            [
                (
                    line.product.name,
                    line.product.unit,
                    line.product.stock,
                    line.product.min_stock,
                    line.quantity,
                    line.last_price,
                    line.amount,
                    line.last_supplier,
                )
                for line in lines
            ],
            self,
        ).exec()

    def _fill_stores(self) -> None:
        """Omborlar ro'yxatini yangilaydi (sozlamalarda yangi ombor qo'shilgan bo'lishi mumkin)."""
        stores = self._warehouse.stores()
        selected = self._store.currentData()
        self._store.blockSignals(True)
        self._store.clear()
        self._store.addItem(tr("Barcha omborlar"), None)
        for store in stores:
            self._store.addItem(store.name, store.id)
        self._store.setCurrentIndex(max(self._store.findData(selected), 0))
        self._store.blockSignals(False)
        self._store.setVisible(len(stores) > 1)
        self._transfer.setVisible(len(stores) > 1)

    def _fill_groups(self) -> None:
        """Guruhlar ro'yxati (sozlamalarda o'zgargan bo'lishi mumkin); tanlov saqlanadi."""
        selected = self._group.currentData()
        self._group.blockSignals(True)
        self._group.clear()
        self._group.addItem(tr("Barcha guruhlar"), "")
        for group in groups():
            self._group.addItem(group.name.display, group.name.ru)
        self._group.setCurrentIndex(max(self._group.findData(selected), 0))
        self._group.blockSignals(False)
        self._fill_categories(refresh=False)

    def _fill_categories(self, _index: int = 0, refresh: bool = True) -> None:
        """Tanlangan guruhning kategoriyalari; guruh tanlanmagan bo'lsa, ro'yxat yashirin."""
        group = find_group(self._group.currentData())
        selected = self._category.currentData()
        self._category.blockSignals(True)
        self._category.clear()
        self._category.addItem(tr("Barcha kategoriyalar"), "")
        for category in group.subgroups if group else ():
            self._category.addItem(category.display, category.ru)
        self._category.setCurrentIndex(max(self._category.findData(selected), 0))
        self._category.blockSignals(False)
        self._category.setVisible(self._category.count() > 1)
        if refresh:
            self.refresh()

    def _shown_products(self) -> list:
        products = self._warehouse.products(
            self.search.text(), self._store.currentData(), self._group.currentData(), self._category.currentData()
        )
        return [p for p in products if p.needs_attention] if self._only_low.isChecked() else products

    def _move_between_stores(self) -> None:
        if TransferDialog(self._warehouse, self.session.author, self.table.selected_id(), self).exec():
            self.refresh()

    def _take_inventory(self) -> None:
        """Jadvalda ko'rinib turgan (qidiruv va filtrga mos) mahsulotlar uchun inventarizatsiya varag'i."""
        stores = self._warehouse.stores()
        store = next((s for s in stores if s.id == self._store.currentData()), None)
        if store is None and len(stores) > 1:
            QMessageBox.information(
                self,
                tr("Inventarizatsiya"),
                tr("Avval yuqoridan omborni tanlang: inventarizatsiya har bir omborda alohida."),
            )
            return
        store = store or stores[0]
        products = self._warehouse.products(
            self.search.text(), store.id, self._group.currentData(), self._category.currentData()
        )
        dialog = InventoryDialog(
            self._warehouse, products, self.session.author, self, store if len(stores) > 1 else None
        )
        if dialog.exec():
            self.refresh()
            QMessageBox.information(
                self, tr("Inventarizatsiya"), tr("{0} ta mahsulotning qoldig'i tuzatildi.").format(dialog.adjusted)
            )

    def _import_from_excel(self) -> None:
        if import_from_excel(self, self._importer, self._backup, self.session.author):
            self.refresh()
