import datetime
import logging
import uuid
from typing import List, Optional, Tuple, Dict, Any
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import encrypt_credential, decrypt_credential
from app.db.models import Order, OrderStatus, Product, Stock, StockStatus, User
from app.services.mayar import mayar_service

logger = logging.getLogger(__name__)


class StoreService:
    """Manajemen bisnis toko digital: Checkout, Locking stok, dan Pemenuhan Pesanan (Fulfillment)."""

    async def get_or_create_user(
        self, session: AsyncSession, user_id: int, username: Optional[str], full_name: Optional[str]
    ) -> User:
        """Mendaftarkan atau memperbarui data pembeli di database."""
        user = await session.get(User, user_id)
        if not user:
            user = User(
                id=user_id,
                username=username,
                full_name=full_name,
            )
            session.add(user)
            await session.commit()
            await session.refresh(user)
        else:
            if user.username != username or user.full_name != full_name:
                user.username = username
                user.full_name = full_name
                await session.commit()
        return user

    async def get_catalog_with_stock(self, session: AsyncSession) -> List[Dict[str, Any]]:
        """Mengambil katalog produk aktif beserta sisa stok yang tersedia."""
        stmt = (
            select(
                Product,
                func.count(Stock.id).label("stock_count")
            )
            .outerjoin(
                Stock,
                (Stock.product_id == Product.id) & (Stock.status == StockStatus.AVAILABLE.value)
            )
            .where(Product.is_active == True)
            .group_by(Product.id)
            .order_by(Product.id.asc())
        )
        result = await session.execute(stmt)
        catalog = []
        for product, stock_count in result.all():
            catalog.append({
                "id": product.id,
                "name": product.name,
                "description": product.description or "",
                "price": product.price,
                "stock": stock_count,
            })
        return catalog

    async def get_product_details(self, session: AsyncSession, product_id: int) -> Optional[Dict[str, Any]]:
        """Mengambil detail 1 produk dan sisa stoknya."""
        stmt = (
            select(
                Product,
                func.count(Stock.id).label("stock_count")
            )
            .outerjoin(
                Stock,
                (Stock.product_id == Product.id) & (Stock.status == StockStatus.AVAILABLE.value)
            )
            .where(Product.id == product_id)
            .group_by(Product.id)
        )
        result = await session.execute(stmt)
        row = result.first()
        if not row:
            return None
        product, stock_count = row
        return {
            "id": product.id,
            "name": product.name,
            "description": product.description or "",
            "price": product.price,
            "stock": stock_count,
            "is_active": product.is_active
        }

    async def create_checkout_order(
        self,
        session: AsyncSession,
        user_id: int,
        product_id: int,
        customer_name: str,
        customer_email: str = "buyer@store.local"
    ) -> Tuple[Optional[Order], str]:
        """
        Membuat pesanan baru dengan sistem Locking Stok (Row-Level Lock).
        Mencegah race condition ketika banyak user checkout bersamaan.
        """
        # Bersihkan order yang expired dulu untuk me-release stok lama
        await self.release_expired_orders(session)

        # 1. Cek produk
        product = await session.get(Product, product_id)
        if not product or not product.is_active:
            return None, "Produk tidak ditemukan atau sedang dinonaktifkan."

        # 2. Row-Level Lock stok yang available (SELECT FOR UPDATE)
        # Ambil 1 stok yang available
        stock_stmt = (
            select(Stock)
            .where(
                (Stock.product_id == product_id) &
                (Stock.status == StockStatus.AVAILABLE.value)
            )
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        stock_res = await session.execute(stock_stmt)
        stock_item = stock_res.scalar_one_or_none()

        if not stock_item:
            return None, "Maaf, stok untuk produk ini baru saja habis!"

        # 3. Generate Order ID
        date_str = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        unique_suffix = uuid.uuid4().hex[:6].upper()
        order_id = f"INV-{date_str}-{unique_suffix}"

        # 4. Kunci stok sementara (status: RESERVED) selama 15 menit
        now = datetime.datetime.now(datetime.timezone.utc)
        expired_at = now + datetime.timedelta(minutes=15)

        stock_item.status = StockStatus.RESERVED.value
        stock_item.reserved_order_id = order_id

        # 5. Request Payment ke Mayar.id
        try:
            payment_res = await mayar_service.create_payment(
                order_id=order_id,
                amount=product.price,
                product_name=product.name,
                customer_name=customer_name,
                customer_email=customer_email,
            )
        except Exception as e:
            # Rollback reservasi stok jika Mayar error
            stock_item.status = StockStatus.AVAILABLE.value
            stock_item.reserved_order_id = None
            await session.commit()
            return None, f"Gagal membuat pembayaran ke gateway: {str(e)}"

        # 6. Buat Record Order
        order = Order(
            id=order_id,
            user_id=user_id,
            product_id=product_id,
            amount=product.price,
            status=OrderStatus.PENDING.value,
            payment_link_id=payment_res.get("id"),
            payment_url=payment_res.get("payment_url"),
            qris_string=payment_res.get("qris_string"),
            created_at=now,
            expired_at=expired_at,
        )
        session.add(order)
        await session.commit()
        await session.refresh(order)

        logger.info(f"Order {order_id} dibuat. Stok ID #{stock_item.id} di-reserve untuk user {user_id}")
        return order, "OK"

    async def fulfill_order(
        self, session: AsyncSession, order_id: str
    ) -> Tuple[bool, Optional[str], Optional[Order]]:
        """
        Idempotent fulfillment: Dipanggil saat webhook pembayaran sukses diterima.
        Mengubah status stok ke SOLD dan mendekripsi akun untuk dikirimkan ke pembeli.
        """
        # Lock record order
        order_stmt = select(Order).where(Order.id == order_id).with_for_update()
        order_res = await session.execute(order_stmt)
        order = order_res.scalar_one_or_none()

        if not order:
            logger.error(f"Fulfillment gagal: Order ID {order_id} tidak ditemukan.")
            return False, None, None

        # Idempotensi: Jika sudah pernah dibayar dan diproses, jangan proses ulang
        if order.status == OrderStatus.PAID.value:
            logger.info(f"Order {order_id} sudah pernah berstatus PAID. Mengambil kredensial tersimpan.")
            if order.fulfilled_stock_id:
                sold_stock = await session.get(Stock, order.fulfilled_stock_id)
                if sold_stock:
                    return True, decrypt_credential(sold_stock.credential_encrypted), order
            return True, None, order

        # Cari stok yang sebelumnya di-reserve untuk order ini
        stock_stmt = (
            select(Stock)
            .where(
                (Stock.product_id == order.product_id) &
                ((Stock.reserved_order_id == order_id) | (Stock.status == StockStatus.AVAILABLE.value))
            )
            .with_for_update()
            .limit(1)
        )
        stock_res = await session.execute(stock_stmt)
        stock_item = stock_res.scalar_one_or_none()

        now = datetime.datetime.now(datetime.timezone.utc)

        if not stock_item:
            logger.critical(f"FATAL: Order {order_id} dibayar tapi kehabisan stok! Butuh tindakan admin.")
            order.status = "PAID_NO_STOCK"
            await session.commit()
            return False, None, order

        # Update status stok dan order secara atomik
        stock_item.status = StockStatus.SOLD.value
        stock_item.sold_at = now
        stock_item.reserved_order_id = order_id

        order.status = OrderStatus.PAID.value
        order.paid_at = now
        order.fulfilled_stock_id = stock_item.id

        await session.commit()

        # Dekripsi data kredensial
        raw_credential = decrypt_credential(stock_item.credential_encrypted)
        logger.info(f"Order {order_id} BERHASIL fulfilled! Stok #{stock_item.id} terkirim.")
        return True, raw_credential, order

    async def release_expired_orders(self, session: AsyncSession) -> int:
        """Mengembalikan stok yang di-reserve jika pembeli tidak membayar hingga batas waktu."""
        now = datetime.datetime.now(datetime.timezone.utc)
        stmt = (
            select(Order)
            .where(
                (Order.status == OrderStatus.PENDING.value) &
                (Order.expired_at < now)
            )
            .with_for_update()
        )
        res = await session.execute(stmt)
        expired_orders = res.scalars().all()

        released_count = 0
        for ord_item in expired_orders:
            ord_item.status = OrderStatus.EXPIRED.value
            
            # Kembalikan stok yang di-reserve untuk order ini
            stock_update = (
                update(Stock)
                .where(Stock.reserved_order_id == ord_item.id)
                .values(
                    status=StockStatus.AVAILABLE.value,
                    reserved_order_id=None
                )
            )
            await session.execute(stock_update)
            released_count += 1

        if released_count > 0:
            await session.commit()
            logger.info(f"Otomatis me-release {released_count} order yang kedaluwarsa.")
        return released_count

    # --- PANEL ADMIN FITUR ---

    async def admin_add_product(
        self, session: AsyncSession, name: str, price: int, description: Optional[str]
    ) -> Product:
        """Admin membuat produk baru."""
        product = Product(name=name, price=price, description=description, is_active=True)
        session.add(product)
        await session.commit()
        await session.refresh(product)
        return product

    async def admin_add_bulk_stock(
        self, session: AsyncSession, product_id: int, credentials: List[str]
    ) -> int:
        """
        Admin memasukkan stok massal (1 baris per akun).
        Setiap kredensial langsung dienkripsi sebelum disimpan ke PostgreSQL Supabase.
        """
        count = 0
        for line in credentials:
            clean_line = line.strip()
            if not clean_line:
                continue
            encrypted = encrypt_credential(clean_line)
            stock = Stock(
                product_id=product_id,
                credential_encrypted=encrypted,
                status=StockStatus.AVAILABLE.value
            )
            session.add(stock)
            count += 1
        await session.commit()
        return count

    async def admin_get_stats(self, session: AsyncSession) -> Dict[str, Any]:
        """Statistik ringkas penjualan dan omset."""
        total_products = (await session.execute(select(func.count(Product.id)))).scalar() or 0
        total_stocks_avail = (
            await session.execute(
                select(func.count(Stock.id)).where(Stock.status == StockStatus.AVAILABLE.value)
            )
        ).scalar() or 0
        total_orders_paid = (
            await session.execute(
                select(func.count(Order.id)).where(Order.status == OrderStatus.PAID.value)
            )
        ).scalar() or 0
        total_revenue = (
            await session.execute(
                select(func.sum(Order.amount)).where(Order.status == OrderStatus.PAID.value)
            )
        ).scalar() or 0

        return {
            "total_products": total_products,
            "available_stock": total_stocks_avail,
            "completed_orders": total_orders_paid,
            "revenue": total_revenue,
        }


store_service = StoreService()
