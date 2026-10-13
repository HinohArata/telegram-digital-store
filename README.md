# 🏪 Telegram Digital Store Bot (QRIS Mayar.id & Supabase)

Bot Telegram toko otomatis untuk penjualan kredensial digital (akun, lisensi, voucher) berskala bisnis perorangan dengan standar keamanan tinggi dan siap deploy jangka panjang.

---

## 🛡️ Fitur & Standar Keamanan Bisnis

1. **Enkripsi Kredensial (Data-at-Rest)**:
   - Semua akun/password yang tersimpan di Supabase dienkripsi menggunakan algoritma **AES (Fernet)**.
   - Bahkan jika database bocor/diakses orang lain, data kredensial tetap tidak bisa dibaca tanpa `ENCRYPTION_KEY`.
2. **Anti Double-Selling (Row-Level Locking)**:
   - Menggunakan `SELECT ... FOR UPDATE SKIP LOCKED` di PostgreSQL.
   - Mencegah race condition ketika 2 pembeli membayar di detik yang sama.
3. **Stok Locking & Auto-Release**:
   - Stok dikunci sementara (15 menit) saat invoice dibuat.
   - Jika pembayaran kedaluwarsa/batal, stok otomatis kembali ke katalog.
4. **Idempotensi Webhook**:
   - Menghindari pengiriman akun dobel jika server gateway mengirim notifikasi ulang.
5. **Panel Admin Terintegrasi di Telegram**:
   - Tambah produk baru dengan wizard interaktif (FSM).
   - Tambah stok massal (cukup copy-paste list `user:pass`).
   - Pantau statistik penjualan dan omset.

---

## 📁 Struktur Proyek

```text
tele/
├── Dockerfile                  # Container build siap deploy ke Railway
├── requirements.txt            # Dependensi Python
├── .env.example                # Template konfigurasi environment
├── main.py                     # Entrypoint (Bot Polling + FastAPI Webhook Server)
├── app/
│   ├── config.py               # Pydantic Settings
│   ├── core/
│   │   ├── crypto.py           # Enkripsi AES-Fernet untuk kredensial
│   │   └── logger.py           # Logging sistem
│   ├── db/
│   │   ├── session.py          # SQLAlchemy 2.0 AsyncEngine (Supabase PgBouncer ready)
│   │   └── models.py           # Schema: Users, Products, Stocks, Orders
│   ├── services/
│   │   ├── mayar.py            # Klien API & Verifikasi Webhook Mayar.id
│   │   └── store.py            # Logika bisnis transaksi & stok
│   ├── bot/
│   │   ├── setup.py            # Inisialisasi aiogram 3
│   │   ├── keyboards.py        # Inline keyboards
│   │   └── handlers/
│   │       ├── user.py         # Katalog, Checkout, Cek Status
│   │       └── admin.py        # Panel Admin, Tambah Produk & Stok
│   └── web/
│       └── server.py           # FastAPI Webhook receiver & Health check
```

---

## 🚀 Panduan Setup & Konfigurasi

### 1. Dapatkan Telegram Bot Token & Admin ID
1. Buka [@BotFather](https://t.me/BotFather) di Telegram $\rightarrow$ ketik `/newbot` $\rightarrow$ simpan `BOT_TOKEN`.
2. Cek Telegram User ID Anda via [@userinfobot](https://t.me/userinfobot) untuk diisi ke `ADMIN_IDS`.

### 2. Generate Kunci Enkripsi (Master Key)
Jalankan perintah ini di terminal:
```bash
python3 -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```
Simpan hasilnya ke variabel `ENCRYPTION_KEY`.

### 3. Setup Database (Railway PostgreSQL atau Supabase)
- **Railway PostgreSQL (Paling Praktis)**: Di project Railway, klik **+ New** $\rightarrow$ **Database** $\rightarrow$ **PostgreSQL**.
- **Supabase**: Ambil Connection URI dari menu Database Settings Supabase.

### 4. Setup Akun Mayar.id
1. Daftar akun di [Mayar.id](https://mayar.id).
2. Masuk ke **Pengaturan Pengembang (API & Webhook)**:
   - Dapatkan **API Key** $\rightarrow$ masukkan ke `MAYAR_API_KEY`.
   - Buat **Webhook URL**: Arahkan ke `https://[DOMAIN-RAILWAY-ANDA]/webhook/mayar`.
   - Buat **Webhook Token** $\rightarrow$ masukkan ke `MAYAR_WEBHOOK_TOKEN`.

---

## 🚂 Panduan Deployment ke Railway (Menggunakan Docker Image Jadi)

Karena image Docker di-build otomatis oleh GitHub Actions ke GitHub Container Registry (GHCR), deploy di Railway menjadi sangat cepat tanpa proses build:

1. Buka dashboard [Railway.app](https://railway.app) $\rightarrow$ klik **New Project**.
2. Tambahkan Database: Klik **+ New** $\rightarrow$ **Database** $\rightarrow$ **Add PostgreSQL**.
3. Tambahkan Service Bot dari Docker Image:
   - Klik **+ New** $\rightarrow$ pilih **Docker Image**.
   - Masukkan image: `ghcr.io/hinoharata/telegram-digital-store:latest`.
4. Masuk ke tab **Variables** service bot dan tambahkan variabel:
   - `DATABASE_URL`: `${{Postgres.DATABASE_URL}}`
   - `BOT_TOKEN`: Token bot Telegram Anda.
   - `ADMIN_IDS`: ID Telegram Anda (misal: `123456789`).
   - `ENCRYPTION_KEY`: Kunci Fernet yang telah Anda generate.
   - `MAYAR_API_KEY`: API Key dari Mayar.id.
   - `MAYAR_WEBHOOK_TOKEN`: Token rahasia webhook Mayar.
5. Masuk ke tab **Settings** di Railway $\rightarrow$ di bagian **Networking**, klik **Generate Domain** (misal: `store-bot-production.up.railway.app`).
6. Daftarkan Webhook Callback URL di dashboard Mayar.id:
   ```text
   https://store-bot-production.up.railway.app/webhook/mayar
   ```
7. Selesai! Bot langsung aktif 24/7 di Telegram.

---

## 🧪 Testing Lokal di Termux / Komputer

Jika ingin menguji coba bot secara lokal terlebih dahulu:
1. Salin template konfigurasi:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` dan masukkan `BOT_TOKEN` serta `ADMIN_IDS` Anda.
   *(Jika DATABASE_URL belum diisi, bot akan otomatis menggunakan SQLite lokal `local_store.db`)*.
3. Jalankan:
   ```bash
   python3 main.py
   ```
4. Buka bot di Telegram $\rightarrow$ ketik `/start`.
5. Buka panel admin $\rightarrow$ ketik `/admin` $\rightarrow$ tambah produk dan masukkan stok.
