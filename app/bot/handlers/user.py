import logging
from aiogram import Router, F
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, CallbackQuery
from sqlalchemy import select

from app.bot.keyboards import (
    main_menu_keyboard,
    catalog_keyboard,
    product_detail_keyboard,
    payment_keyboard
)
from app.config import settings
from app.db.models import Order, OrderStatus
from app.db.session import async_session_factory
from app.services.store import store_service

logger = logging.getLogger(__name__)
user_router = Router(name="user_router")


@user_router.message(CommandStart())
async def cmd_start(message: Message):
    """Menyapa pembeli dan mendaftarkannya ke database."""
    async with async_session_factory() as session:
        await store_service.get_or_create_user(
            session=session,
            user_id=message.from_user.id,
            username=message.from_user.username,
            full_name=message.from_user.full_name,
        )

    is_admin = message.from_user.id in settings.ADMIN_IDS
    welcome_text = (
        f"👋 Halo, <b>{message.from_user.first_name}</b>!\n\n"
        "Selamat datang di <b>Digital Credential Store</b>.\n"
        "Kami menyediakan berbagai akun & kredensial digital premium dengan sistem pembayaran "
        "otomatis QRIS 24/7.\n\n"
        "Silakan pilih menu di bawah ini:"
    )
    await message.answer(
        welcome_text,
        reply_markup=main_menu_keyboard(is_admin=is_admin),
        parse_mode="HTML"
    )


@user_router.callback_query(F.data == "main_menu")
async def cb_main_menu(callback: CallbackQuery):
    is_admin = callback.from_user.id in settings.ADMIN_IDS
    await callback.message.edit_text(
        "🏠 <b>Menu Utama Toko</b>\nSilakan pilih layanan yang Anda inginkan:",
        reply_markup=main_menu_keyboard(is_admin=is_admin),
        parse_mode="HTML"
    )
    await callback.answer()


@user_router.callback_query(F.data == "view_catalog")
async def cb_view_catalog(callback: CallbackQuery):
    async with async_session_factory() as session:
        products = await store_service.get_catalog_with_stock(session)

    if not products:
        await callback.message.edit_text(
            "🛍️ <b>Katalog Produk</b>\n\nSaat ini belum ada produk yang tersedia.",
            reply_markup=main_menu_keyboard(is_admin=callback.from_user.id in settings.ADMIN_IDS),
            parse_mode="HTML"
        )
        await callback.answer()
        return

    text = (
        "🛍️ <b>Katalog Produk Digital</b>\n"
        "Pilih salah satu produk di bawah untuk melihat rincian dan membeli:"
    )
    await callback.message.edit_text(
        text,
        reply_markup=catalog_keyboard(products),
        parse_mode="HTML"
    )
    await callback.answer()


@user_router.callback_query(F.data.startswith("prod_"))
async def cb_product_detail(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    async with async_session_factory() as session:
        product = await store_service.get_product_details(session, product_id)

    if not product:
        await callback.answer("Produk tidak ditemukan!", show_alert=True)
        return

    stock_badge = f"🟢 Tersedia ({product['stock']} stok)" if product['stock'] > 0 else "🔴 Stok Habis"
    text = (
        f"📦 <b>{product['name']}</b>\n\n"
        f"💰 <b>Harga:</b> Rp {product['price']:,}\n"
        f"📊 <b>Status Stok:</b> {stock_badge}\n\n"
        f"📝 <b>Deskripsi / Garansi:</b>\n{product['description'] or 'Tidak ada deskripsi tambahan.'}\n\n"
        "<i>Setelah pembayaran QRIS berhasil, akun & password langsung dikirim otomatis ke chat ini.</i>"
    )
    await callback.message.edit_text(
        text,
        reply_markup=product_detail_keyboard(product_id, has_stock=product['stock'] > 0),
        parse_mode="HTML"
    )
    await callback.answer()


@user_router.callback_query(F.data.startswith("buy_"))
async def cb_buy_product(callback: CallbackQuery):
    product_id = int(callback.data.split("_")[1])
    user_id = callback.from_user.id
    customer_name = callback.from_user.full_name or callback.from_user.first_name

    await callback.answer("Memproses pembuatan invoice QRIS...")

    async with async_session_factory() as session:
        order, msg = await store_service.create_checkout_order(
            session=session,
            user_id=user_id,
            product_id=product_id,
            customer_name=customer_name
        )

        if not order:
            await callback.message.answer(f"⚠️ Gagal membuat pesanan: {msg}")
            return

        product = await store_service.get_product_details(session, product_id)

    # Format pesan instruksi invoice
    invoice_text = (
        "🧾 <b>INVOICE PEMBAYARAN DIGITAL</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Nomor Invoice:</b> <code>{order.id}</code>\n"
        f"📦 <b>Produk:</b> {product['name']}\n"
        f"💰 <b>Total Tagihan:</b> <b>Rp {order.amount:,}</b>\n"
        f"⏳ <b>Batas Waktu:</b> 15 Menit\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "<b>Cara Pembayaran:</b>\n"
        "1. Klik tombol <b>📲 Buka Pembayaran / QRIS</b> di bawah.\n"
        "2. Scan QRIS dengan aplikasi m-Banking atau E-Wallet (BCA, Mandiri, GoPay, OVO, DANA, ShopeePay, dll).\n"
        "3. Sistem akan otomatis mendeteksi ketika pembayaran berhasil dan mengirimkan kredensial akun seketika!"
    )

    await callback.message.answer(
        invoice_text,
        reply_markup=payment_keyboard(order.payment_url, order.id),
        parse_mode="HTML"
    )


@user_router.callback_query(F.data.startswith("check_pay_"))
async def cb_check_payment(callback: CallbackQuery):
    order_id = callback.data.replace("check_pay_", "")

    async with async_session_factory() as session:
        stmt = select(Order).where(Order.id == order_id)
        res = await session.execute(stmt)
        order = res.scalar_one_or_none()

    if not order:
        await callback.answer("Pesanan tidak ditemukan.", show_alert=True)
        return

    if order.status == OrderStatus.PAID.value:
        await callback.answer("✅ Pembayaran SUDAH LUNAS! Kredensial telah dikirimkan ke Anda.", show_alert=True)
    elif order.status == OrderStatus.EXPIRED.value:
        await callback.answer("❌ Pesanan ini sudah KEDALUWARSA. Silakan buat pesanan baru di katalog.", show_alert=True)
    else:
        await callback.answer("⏳ Status pembayaran: PENDING (Belum terdeteksi masuk). Mohon selesaikan via QRIS.", show_alert=True)


@user_router.callback_query(F.data == "my_orders")
async def cb_my_orders(callback: CallbackQuery):
    user_id = callback.from_user.id
    async with async_session_factory() as session:
        stmt = select(Order).where(Order.user_id == user_id).order_by(Order.created_at.desc()).limit(5)
        res = await session.execute(stmt)
        orders = res.scalars().all()

    if not orders:
        await callback.message.edit_text(
            "📦 Anda belum memiliki riwayat pembelian.",
            reply_markup=main_menu_keyboard(is_admin=user_id in settings.ADMIN_IDS)
        )
        await callback.answer()
        return

    text = "📦 <b>Riwayat 5 Transaksi Terakhir:</b>\n\n"
    for ord_item in orders:
        status_icon = "✅ LUNAS" if ord_item.status == OrderStatus.PAID.value else f"⏳ {ord_item.status}"
        text += (
            f"• <code>{ord_item.id}</code> | Rp {ord_item.amount:,}\n"
            f"  Status: {status_icon}\n\n"
        )

    await callback.message.edit_text(
        text,
        reply_markup=main_menu_keyboard(is_admin=user_id in settings.ADMIN_IDS),
        parse_mode="HTML"
    )
    await callback.answer()


@user_router.callback_query(F.data == "help_info")
async def cb_help_info(callback: CallbackQuery):
    help_text = (
        "💬 <b>Pusat Bantuan & Customer Care</b>\n\n"
        "Jika mengalami kendala transaksi atau akun bermasalah:\n"
        "• Jam Operasional Bot: 24 Jam Otomatis\n"
        "• Garansi akun berlaku sesuai ketentuan deskripsi produk.\n"
        "• Hubungi admin via kontak resmi di info bio bot."
    )
    await callback.message.edit_text(
        help_text,
        reply_markup=main_menu_keyboard(is_admin=callback.from_user.id in settings.ADMIN_IDS),
        parse_mode="HTML"
    )
    await callback.answer()
