"""Mahsulotlar va ularning ombordagi qoldig'i."""

from datetime import date
from pathlib import Path

from PySide6.QtCore import QStandardPaths
from PySide6.QtWidgets import QCheckBox, QComboBox, QDialog, QFileDialog, QMessageBox

from ..config import CURRENCY
from ..errors import WarehouseError
from ..excel_import import COLUMNS, read_products, write_template
from ..formatting import fmt_money
from ..i18n import tr
from ..session import Session
from ..warehouse import Warehouse
from .dialogs import InventoryDialog, ProductDialog
from .extra_dialogs import TransferDialog
from .list_page import ListPage
from .widgets import Column, ColumnKind, button

EXCEL_FILTER = tr("Excel fayli (*.xlsx)")
MAX_SKIPPED_SHOWN = 10


class ProductsPage(ListPage):
    delete_question = tr("Bu mahsulot ro'yxatdan o'chirilsinmi?")

    def __init__(self, warehouse: Warehouse, session: Session):
        columns = (
            Column(tr("Mahsulot")),
            Column(tr("Qoldiq"), ColumnKind.QUANTITY),
            Column(tr("Birlik")),
            Column(tr("Minimal qoldiq"), ColumnKind.QUANTITY),
            Column(tr("O'rtacha narx"), ColumnKind.MONEY),
            Column(tr("Qiymati"), ColumnKind.MONEY),
            Column(tr("Holati")),
        )
        super().__init__(tr("Mahsulotlar"), tr("+ Yangi mahsulot"), columns, session)
        self._warehouse = warehouse

        # Ombor tanlagich va «Ko'chirish» faqat bir nechta ombor bo'lganda ko'rinadi.
        self._store = QComboBox()
        self._store.currentIndexChanged.connect(self.refresh)
        self.header_tools.addWidget(self._store)
        self._only_low = QCheckBox(tr("Faqat kam qolgan va tugaganlar"))
        self._only_low.toggled.connect(self.refresh)
        self.header_tools.addWidget(self._only_low)
        self._transfer = button(tr("Ko'chirish"))
        self._transfer.setToolTip(tr("Mahsulotni bir ombordan boshqasiga ko'chirish"))
        self._transfer.clicked.connect(self._move_between_stores)
        if session.can_add:
            self.toolbar_tools.addWidget(self._transfer)
        if session.can_add:
            import_button = button(tr("Exceldan yuklash"))
            import_button.setToolTip(tr("Mahsulotlar ro'yxatini Excel faylidan qo'shish"))
            import_button.clicked.connect(self._import_from_excel)
            self.header_tools.addWidget(import_button)
        if session.can_modify:
            inventory = button(tr("Inventarizatsiya"))
            inventory.setToolTip(tr("Jadvaldagi mahsulotlarning sanab chiqilgan haqiqiy qoldig'ini kiritish"))
            inventory.clicked.connect(self._take_inventory)
            self.header_tools.addWidget(inventory)

    def refresh(self) -> None:
        self._fill_stores()
        products = self._shown_products()
        self.table.set_rows(
            [(p.name, p.stock, p.unit, p.min_stock, p.average_price, p.value, p.status.value) for p in products],
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

    def _shown_products(self) -> list:
        products = self._warehouse.products(self.search.text(), self._store.currentData())
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
        products = self._warehouse.products(self.search.text(), store.id)
        dialog = InventoryDialog(
            self._warehouse, products, self.session.author, self, store if len(stores) > 1 else None
        )
        if dialog.exec():
            self.refresh()
            QMessageBox.information(
                self, tr("Inventarizatsiya"), tr("{0} ta mahsulotning qoldig'i tuzatildi.").format(dialog.adjusted)
            )

    def _import_from_excel(self) -> None:
        box = QMessageBox(QMessageBox.Icon.Information, tr("Exceldan yuklash"), "", parent=self)
        box.setText(
            tr(
                "Excel faylining birinchi qatori sarlavha, ustunlari shu tartibda bo'lishi kerak:\n\n{0}\n\n"
                "«Qoldiq» ko'rsatilgan mahsulotga bugungi sana bilan boshlang'ich kirim yoziladi.\n"
                "Ro'yxatda bor mahsulotlar o'zgarmaydi."
            ).format("  |  ".join(COLUMNS))
        )
        choose = box.addButton(tr("Faylni tanlash"), QMessageBox.ButtonRole.AcceptRole)
        template = box.addButton(tr("Namuna faylni saqlash"), QMessageBox.ButtonRole.ActionRole)
        box.addButton(tr("Bekor qilish"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is template:
            self._save_template()
        elif box.clickedButton() is choose:
            self._import_file()

    def _save_template(self) -> None:
        documents = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DocumentsLocation)
        default_path = Path(documents) / tr("Mahsulotlar namuna.xlsx")
        path, _ = QFileDialog.getSaveFileName(self, tr("Namuna faylni saqlash"), str(default_path), EXCEL_FILTER)
        if not path:
            return
        try:
            write_template(path)
        except OSError:
            QMessageBox.warning(
                self, tr("Exceldan yuklash"), tr("Faylni saqlab bo'lmadi. Boshqa joyni tanlab ko'ring.")
            )
            return
        QMessageBox.information(
            self,
            tr("Exceldan yuklash"),
            tr("Namuna saqlandi:\n{0}\n\nUni to'ldirib, shu yerdan qayta yuklang.").format(path),
        )

    def _import_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, tr("Excel faylini tanlash"), "", EXCEL_FILTER)
        if not path:
            return
        try:
            result = self._warehouse.import_products(read_products(path), date.today(), self.session.author)
        except WarehouseError as error:
            QMessageBox.warning(self, tr("Yuklab bo'lmadi"), str(error))
            return
        self.refresh()
        message = tr("{0} ta mahsulot qo'shildi.").format(result.added)
        if result.skipped:
            shown = ", ".join(result.skipped[:MAX_SKIPPED_SHOWN])
            more = "…" if len(result.skipped) > MAX_SKIPPED_SHOWN else ""
            message += tr("\n\nRo'yxatda borligi uchun o'tkazib yuborildi ({0} ta): {1}{2}").format(
                len(result.skipped), shown, more
            )
        QMessageBox.information(self, tr("Exceldan yuklash"), message)
