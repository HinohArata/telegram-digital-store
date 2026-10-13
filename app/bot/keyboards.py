from typing import List, Dict, Any
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton


def main_menu_keyboard(is_admin: bool = False) -> InlineKeyboardMarkup:
    """Keyboard navigasi menu utama."""
    buttons = [
        [InlineKeyboardButton(text="🛍️ Katalog Produk", callback_data="view_catalog")],
        [InlineKeyboardButton(text="📦 Riwayat Pembelian", callback_data="my_orders")],
        [InlineKeyboardButton(text="💬 Bantuan & CS", callback_data="help_info")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚡ Panel Admin", callback_data="admin_dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def catalog_keyboard(products: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Keyboard daftar list produk."""
    buttons = []
    for p in products:
        stock_text = f"({p['stock']} stok)" if p['stock'] > 0 else "(Habis ❌)"
        btn_text = f"{p['name']} - Rp {p['price']:,} {stock_text}"
        buttons.append([InlineKeyboardButton(text=btn_text, callback_data=f"prod_{p['id']}")])
    buttons.append([InlineKeyboardButton(text="🔙 Kembali", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def product_detail_keyboard(product_id: int, has_stock: bool) -> InlineKeyboardMarkup:
    """Keyboard detail produk dengan tombol Beli."""
    buttons = []
    if has_stock:
        buttons.append([InlineKeyboardButton(text="💳 Beli Sekarang (QRIS)", callback_data=f"buy_{product_id}")])
    else:
        buttons.append([InlineKeyboardButton(text="❌ Stok Habis", callback_data="out_of_stock")])
    buttons.append([InlineKeyboardButton(text="🔙 Kembali ke Katalog", callback_data="view_catalog")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def payment_keyboard(payment_url: str, order_id: str) -> InlineKeyboardMarkup:
    """Keyboard instruksi pembayaran & cek status."""
    buttons = []
    if payment_url:
        buttons.append([InlineKeyboardButton(text="📲 Buka Pembayaran / QRIS", url=payment_url)])
    buttons.append([InlineKeyboardButton(text="🔄 Cek Status Pembayaran", callback_data=f"check_pay_{order_id}")])
    buttons.append([InlineKeyboardButton(text="🏠 Menu Utama", callback_data="main_menu")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_dashboard_keyboard() -> InlineKeyboardMarkup:
    """Keyboard dashboard admin."""
    buttons = [
        [InlineKeyboardButton(text="➕ Tambah Produk Baru", callback_data="adm_add_product")],
        [InlineKeyboardButton(text="📥 Tambah Stok Kredensial", callback_data="adm_select_prod_stock")],
        [InlineKeyboardButton(text="📊 Laporan & Statistik", callback_data="adm_stats")],
        [InlineKeyboardButton(text="🔙 Kembali ke Toko", callback_data="main_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_select_product_for_stock_keyboard(products: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    """Pilihan produk saat admin ingin menambahkan stok."""
    buttons = []
    for p in products:
        buttons.append([
            InlineKeyboardButton(text=f"Stok: {p['name']} (Sisa: {p['stock']})", callback_data=f"adm_stock_for_{p['id']}")
        ])
    buttons.append([InlineKeyboardButton(text="🔙 Kembali ke Admin", callback_data="admin_dashboard")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
