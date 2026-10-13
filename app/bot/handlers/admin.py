import logging
from aiogram import Router, F
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery

from app.bot.keyboards import (
    admin_dashboard_keyboard,
    admin_select_product_for_stock_keyboard,
    main_menu_keyboard
)
from app.config import settings
from app.db.session import async_session_factory
from app.services.store import store_service

logger = logging.getLogger(__name__)
admin_router = Router(name="admin_router")


# FSM States untuk pembuatan produk baru
class AddProductState(StatesGroup):
    waiting_for_name = State()
    waiting_for_price = State()
    waiting_for_description = State()


# FSM States untuk pengisian stok massal
class AddStockState(StatesGroup):
    waiting_for_credentials = State()


# Filter khusus: hanya ID di ADMIN_IDS yang diizinkan
def is_admin(user_id: int) -> bool:
    return user_id in settings.ADMIN_IDS


@admin_router.message(Command("admin"))
async def cmd_admin(message: Message, state: FSMContext):
    """Membuka dashboard admin."""
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Akses ditolak. Anda bukan admin yang terdaftar.")
        return
    await state.clear()
    await message.answer(
        "⚡ <b>PANEL ADMIN DIGITAL STORE</b>\n"
        "Kelola katalog produk, enkripsi stok kredensial, dan pantau penjualan.",
        reply_markup=admin_dashboard_keyboard(),
        parse_mode="HTML"
    )


@admin_router.callback_query(F.data == "admin_dashboard")
async def cb_admin_dashboard(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Akses ditolak.", show_alert=True)
        return
    await state.clear()
    await callback.message.edit_text(
        "⚡ <b>PANEL ADMIN DIGITAL STORE</b>\n"
        "Pilih menu manajemen di bawah:",
        reply_markup=admin_dashboard_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()


# --- FITUR TAMBAH PRODUK ---

@admin_router.callback_query(F.data == "adm_add_product")
async def cb_start_add_product(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    await state.set_state(AddProductState.waiting_for_name)
    await callback.message.answer(
        "📝 <b>Langkah 1/3:</b> Kirimkan <b>Nama Produk</b> yang ingin dijual:\n"
        "<i>(Contoh: Netflix Premium 1 Bulan Private)</i>",
        parse_mode="HTML"
    )
    await callback.answer()


@admin_router.message(AddProductState.waiting_for_name)
async def state_receive_product_name(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    product_name = message.text.strip()
    await state.update_data(name=product_name)
    await state.set_state(AddProductState.waiting_for_price)
    await message.answer(
        f"💰 <b>Langkah 2/3:</b> Kirimkan <b>Harga Produk</b> (hanya angka Rupiah):\n"
        f"<i>(Contoh: 35000)</i>",
        parse_mode="HTML"
    )


@admin_router.message(AddProductState.waiting_for_price)
async def state_receive_product_price(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    text = message.text.replace(".", "").replace(",", "").strip()
    if not text.isdigit():
        await message.answer("⚠️ Harga harus berupa angka! Silakan kirim ulang nominal harga:")
        return

    price = int(text)
    await state.update_data(price=price)
    await state.set_state(AddProductState.waiting_for_description)
    await message.answer(
        "📄 <b>Langkah 3/3:</b> Kirimkan <b>Deskripsi / Aturan Garansi</b> produk:\n"
        "<i>(Ketik '-' jika tidak ada deskripsi khusus)</i>",
        parse_mode="HTML"
    )


@admin_router.message(AddProductState.waiting_for_description)
async def state_receive_product_description(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    desc = message.text.strip()
    if desc == "-":
        desc = ""

    data = await state.get_data()
    await state.clear()

    async with async_session_factory() as session:
        product = await store_service.admin_add_product(
            session=session,
            name=data["name"],
            price=data["price"],
            description=desc
        )

    await message.answer(
        f"✅ <b>Produk Berhasil Ditambahkan!</b>\n\n"
        f"🆔 ID: <code>{product.id}</code>\n"
        f"📦 Nama: <b>{product.name}</b>\n"
        f"💰 Harga: Rp {product.price:,}\n\n"
        "Produk sekarang sudah muncul di katalog. Silakan isi stoknya.",
        reply_markup=admin_dashboard_keyboard(),
        parse_mode="HTML"
    )


# --- FITUR TAMBAH STOK KREDENSIAL MASSAL ---

@admin_router.callback_query(F.data == "adm_select_prod_stock")
async def cb_select_prod_for_stock(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    async with async_session_factory() as session:
        products = await store_service.get_catalog_with_stock(session)

    if not products:
        await callback.message.edit_text(
            "⚠️ Belum ada produk. Buat produk terlebih dahulu sebelum mengisi stok.",
            reply_markup=admin_dashboard_keyboard()
        )
        await callback.answer()
        return

    await callback.message.edit_text(
        "📥 <b>Pilih Produk yang Ingin Ditambah Stoknya:</b>",
        reply_markup=admin_select_product_for_stock_keyboard(products),
        parse_mode="HTML"
    )
    await callback.answer()


@admin_router.callback_query(F.data.startswith("adm_stock_for_"))
async def cb_prompt_stock_input(callback: CallbackQuery, state: FSMContext):
    if not is_admin(callback.from_user.id):
        return
    product_id = int(callback.data.split("_")[3])
    await state.update_data(product_id=product_id)
    await state.set_state(AddStockState.waiting_for_credentials)

    async with async_session_factory() as session:
        product = await store_service.get_product_details(session, product_id)

    prompt = (
        f"📥 <b>Input Stok untuk: {product['name']}</b>\n\n"
        "Kirimkan list akun kredensial yang ingin ditambahkan (<b>1 baris per 1 akun</b>).\n"
        "Contoh format:\n"
        "<code>user1@gmail.com:pass123 | PIN: 1234</code>\n"
        "<code>user2@gmail.com:pass456 | PIN: 5678</code>\n\n"
        "🔒 <i>Setiap baris akun akan langsung dienkripsi (AES-Fernet) saat disimpan ke database.</i>"
    )
    await callback.message.answer(prompt, parse_mode="HTML")
    await callback.answer()


@admin_router.message(AddStockState.waiting_for_credentials)
async def state_save_bulk_stocks(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        return
    data = await state.get_data()
    product_id = data.get("product_id")
    await state.clear()

    lines = [line.strip() for line in message.text.split("\n") if line.strip()]
    if not lines:
        await message.answer("⚠️ Tidak ada baris akun yang valid terdeteksi.")
        return

    async with async_session_factory() as session:
        added_count = await store_service.admin_add_bulk_stock(
            session=session,
            product_id=product_id,
            credentials=lines
        )
        product = await store_service.get_product_details(session, product_id)

    await message.answer(
        f"✅ <b>Stok Berhasil Ditambahkan!</b>\n\n"
        f"📦 Produk: <b>{product['name']}</b>\n"
        f"📥 Jumlah ditambahkan: <b>{added_count} akun</b>\n"
        f"🟢 Total stok tersedia saat ini: <b>{product['stock']} akun</b>\n"
        "🔒 <i>Semua kredensial telah terenkripsi secara aman.</i>",
        reply_markup=admin_dashboard_keyboard(),
        parse_mode="HTML"
    )


# --- FITUR LAPORAN & STATISTIK ---

@admin_router.callback_query(F.data == "adm_stats")
async def cb_admin_stats(callback: CallbackQuery):
    if not is_admin(callback.from_user.id):
        return
    async with async_session_factory() as session:
        stats = await store_service.admin_get_stats(session)

    text = (
        "📊 <b>LAPORAN BISNIS & PERFORMA TOKO</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 <b>Total Jenis Produk:</b> {stats['total_products']}\n"
        f"🟢 <b>Total Stok Tersedia:</b> {stats['available_stock']} akun\n"
        f"✅ <b>Total Transaksi Berhasil:</b> {stats['completed_orders']} pesanan\n"
        f"💰 <b>Total Pendapatan (Omset):</b> <b>Rp {stats['revenue']:,}</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━"
    )
    await callback.message.edit_text(
        text,
        reply_markup=admin_dashboard_keyboard(),
        parse_mode="HTML"
    )
    await callback.answer()
