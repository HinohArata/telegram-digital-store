import datetime
import logging
from typing import Any, Dict, Optional
import httpx
from app.config import settings

logger = logging.getLogger(__name__)


class MayarPaymentService:
    """Service untuk integrasi API dan Webhook Mayar.id."""

    def __init__(self):
        self.api_key = settings.MAYAR_API_KEY.strip()
        self.base_url = settings.MAYAR_BASE_URL.rstrip("/")
        self.headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key and not self.api_key.startswith("your_"))

    async def create_payment(
        self,
        order_id: str,
        amount: int,
        product_name: str,
        customer_name: str,
        customer_email: str = "buyer@store.local",
        customer_mobile: str = "08123456789",
        expired_in_minutes: int = 15
    ) -> Dict[str, Any]:
        """
        Membuat tagihan pembayaran / QRIS di Mayar.id.
        Jika API key belum diset (mode dev), mengembalikan simulasi link pembayaran.
        """
        if not self.is_configured:
            logger.warning(
                "MAYAR_API_KEY belum diset. Menggunakan mock invoice untuk testing lokal."
            )
            return {
                "id": f"mock_mayar_{order_id}",
                "payment_url": f"https://sandbox.mayar.id/pay/mock-{order_id}",
                "status": "unpaid",
                "is_mock": True
            }

        endpoint = f"{self.base_url}/hl/v1/payment/create"
        
        # Mayar payload format
        payload = {
            "name": customer_name or f"User-{order_id[-6:]}",
            "email": customer_email,
            "mobile": customer_mobile,
            "amount": int(amount),
            "description": f"Pembelian {product_name} [{order_id}]",
            "redirectUrl": f"https://t.me/your_bot",
        }

        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.post(endpoint, json=payload, headers=self.headers)
                data = response.json()

                if response.status_code not in (200, 201):
                    logger.error(f"Gagal request pembayaran Mayar.id: {data}")
                    raise RuntimeError(f"Mayar API error: {data.get('messages', 'Unknown error')}")

                res_data = data.get("data", {})
                payment_id = res_data.get("id") or res_data.get("paymentId")
                payment_url = res_data.get("link") or res_data.get("url")

                return {
                    "id": payment_id,
                    "payment_url": payment_url,
                    "qris_string": res_data.get("qrisCode") or res_data.get("qrContent"),
                    "raw": res_data,
                    "is_mock": False
                }
        except httpx.RequestError as e:
            logger.error(f"Koneksi jaringan ke Mayar.id gagal: {e}")
            raise RuntimeError(f"Gagal menghubungi server pembayaran Mayar: {e}")

    def verify_webhook_token(self, token_from_header: Optional[str]) -> bool:
        """Memverifikasi token otentikasi webhook Mayar."""
        expected_token = settings.MAYAR_WEBHOOK_TOKEN.strip()
        if not expected_token:
            # Jika belum diset di .env, izinkan dengan log warning
            logger.warning("MAYAR_WEBHOOK_TOKEN belum diset di .env!")
            return True
        return token_from_header == expected_token


mayar_service = MayarPaymentService()
