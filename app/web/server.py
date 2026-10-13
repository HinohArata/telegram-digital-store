import logging
import re
from typing import Any, Dict
from fastapi import FastAPI, Header, HTTPException, Request, Response
from sqlalchemy import select

from app.bot.setup import bot
from app.config import settings
from app.db.models import Order, Product
from app.db.session import async_session_factory
from app.services.mayar import mayar_service
from app.services.store import store_service

logger = logging.getLogger(__name__)

app = FastAPI(title="Digital Store Webhook Listener", debug=settings.DEBUG)


@app.get("/")
@app.get("/health")
async def health_check():
    """Endpoint untuk Railway health check probe."""
    return {"status": "ok", "service": "telegram-digital-store"}


@app.post("/webhook/mayar")
async def mayar_webhook_handler(
    request: Request,
    authorization: str = Header(None),
    x_mayar_token: str = Header(None)
):
    """
    Penerima Webhook resmi dari Mayar.id saat pembayaran QRIS berhasil.
    Idempotent & aman terhadap spam / request berulang.
    """
    token_candidate = x_mayar_token or (authorization.replace("Bearer ", "") if authorization else None)
    if not mayar_service.verify_webhook_token(token_candidate):
        logger.warning("Webhook ditolak: Token tidak valid.")
        raise HTTPException(status_code=401, detail="Unauthorized token")

    try:
        payload: Dict[str, Any] = await request.json()
    except Exception as e:
        logger.error(f"Gagal parse JSON webhook Mayar: {e}")
        return Response(status_code=400, content="Invalid JSON")

    logger.info(f"Menerima Webhook Mayar: {payload}")

    event = payload.get("event", "")
    data = payload.get("data", {})
    payment_status = str(data.get("status", "")).lower()

    # Cek apakah status pembayaran sukses
    is_success = (
        payment_status in ("paid", "completed", "success") or
        event in ("payment.received", "transaction.success", "payment.paid")
    )

    if not is_success:
        logger.info(f"Event/status diabaikan: event={event}, status={payment_status}")
        return {"status": "ignored"}

    payment_id = data.get("id") or data.get("paymentId")
    description = data.get("description", "")

    # Cari Order ID dari payment_link_id atau regex [INV-XXXX]
    order_id = None
    async with async_session_factory() as session:
        if payment_id:
            stmt = select(Order).where(Order.payment_link_id == str(payment_id))
            res = await session.execute(stmt)
            found_order = res.scalar_one_or_none()
            if found_order:
                order_id = found_order.id

        # Fallback pencarian via regex di deskripsi
        if not order_id and description:
            match = re.search(r"INV-\d{8}-[A-Za-z0-9]+", description)
            if match:
                order_id = match.group(0)

        if not order_id:
            logger.error(f"Tidak dapat memetakan webhook Mayar ke Order lokal: {payload}")
            return {"status": "order_not_found"}

        # Proses fulfillment secara atomik (Row-Level Locking)
        success, credential, order = await store_service.fulfill_order(session, order_id)
        if not success or not order:
            logger.error(f"Gagal memproses fulfillment order {order_id}")
            return {"status": "fulfillment_failed"}

        product = await session.get(Product, order.product_id)
        product_name = product.name if product else "Produk Digital"

    # Kirim kredensial secara privat ke chat Telegram pembeli
    try:
        success_msg = (
            "🎉 <b>PEMBAYARAN DITERIMA & SUKSES!</b>\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n"
            f"🆔 <b>Nomor Invoice:</b> <code>{order.id}</code>\n"
            f"📦 <b>Produk:</b> {product_name}\n"
            f"💰 <b>Nominal:</b> Rp {order.amount:,}\n"
            "━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "🔐 <b>KREDENSIAL AKUN ANDA:</b>\n"
            f"<code>{credential}</code>\n\n"
            "⚠️ <b>Perhatian:</b>\n"
            "• Segera simpan dan amankan akun Anda.\n"
            "• Jika ada kendala, hubungi admin melalui menu Bantuan.\n\n"
            "<i>Terima kasih telah berbelanja di Digital Store kami!</i>"
        )
        await bot.send_message(chat_id=order.user_id, text=success_msg, parse_mode="HTML")
        logger.info(f"Kredensial berhasil dikirimkan ke Telegram user ID {order.user_id}")
    except Exception as e:
        logger.error(f"Gagal mengirim pesan bot ke Telegram user {order.user_id}: {e}")

    # Kirim notifikasi ringkas ke Admin
    for admin_id in settings.ADMIN_IDS:
        try:
            admin_alert = (
                "🔔 <b>PENJUALAN BARU BERHASIL!</b>\n"
                f"• Invoice: <code>{order.id}</code>\n"
                f"• Produk: {product_name}\n"
                f"• Nominal: Rp {order.amount:,}\n"
                f"• Pembeli: <code>{order.user_id}</code>"
            )
            await bot.send_message(chat_id=admin_id, text=admin_alert, parse_mode="HTML")
        except Exception as e:
            logger.warning(f"Gagal notif admin {admin_id}: {e}")

    return {"status": "ok", "order_id": order_id}


# Endpoint pengujian simulasi bayar (berguna untuk testing mandiri tanpa potong saldo)
@app.post("/api/dev/simulate-payment/{order_id}")
async def dev_simulate_payment(order_id: str):
    """Simulasi pembayaran instan untuk testing alur bot lokal / staging."""
    async with async_session_factory() as session:
        success, credential, order = await store_service.fulfill_order(session, order_id)
        if not success or not order:
            raise HTTPException(status_code=400, detail="Order tidak ditemukan atau stok kosong")

        product = await session.get(Product, order.product_id)
        product_name = product.name if product else "Produk Digital"

    # Kirim ke pembeli
    success_msg = (
        "🎉 <b>[SIMULASI TEST] PEMBAYARAN SUKSES!</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🆔 <b>Nomor Invoice:</b> <code>{order.id}</code>\n"
        f"📦 <b>Produk:</b> {product_name}\n\n"
        "🔐 <b>KREDENSIAL AKUN ANDA:</b>\n"
        f"<code>{credential}</code>"
    )
    await bot.send_message(chat_id=order.user_id, text=success_msg, parse_mode="HTML")
    return {"status": "success", "order_id": order_id, "credential": credential}
