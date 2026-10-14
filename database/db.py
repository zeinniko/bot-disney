import aiosqlite
import secrets
import string
from typing import Optional, Dict, Tuple
from datetime import datetime, date

DB_PATH = "bot_data.db"

async def init_db():
    """Inisialisasi tabel database saat bot start."""
    async with aiosqlite.connect(DB_PATH) as db:
        with open("database/schema.sql", "r") as f:
            await db.executescript(f.read())
        await db.commit()

def generate_access_code(length: int = 6) -> str:
    """Menghasilkan kode unik acak seperti A3KN7X."""
    chars = string.ascii_uppercase + string.digits
    return "".join(secrets.choice(chars) for _ in range(length))

# --- USER TELEGRAM AUTO-CHECK ---

async def upsert_user(telegram_id: int, username: Optional[str], full_name: Optional[str], role: Optional[str] = None):
    """
    Mencatat atau memperbarui data user Telegram yang mengakses bot.
    Dipanggil otomatis saat pengakses bot terdeteksi.
    """
async def upsert_user(telegram_id: int, username: Optional[str], full_name: Optional[str], role: Optional[str] = None):
    """
    Mencatat atau memperbarui data user Telegram yang mengakses bot.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (telegram_id, username, full_name, role)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET 
                username = excluded.username,
                full_name = excluded.full_name,
                role = COALESCE(?, users.role)
            """,
            (telegram_id, username, full_name, role, role)
        )
        await db.commit()

async def is_admin(telegram_id: int) -> bool:
    """Cek apakah user Telegram memiliki role admin."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None and row[0] == 'admin'

# --- VALIDASI & PEMBARUAN PASSWORD ---

async def get_account_by_access_code(email: str, access_code: str) -> Optional[Dict]:
    """Validasi email, kode akses, dan cek apakah token belum expired."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT a.id, a.email, a.current_password, k.access_code, k.expired_at
            FROM accounts a
            JOIN access_keys k ON a.id = k.account_id
            WHERE LOWER(a.email) = LOWER(?) 
              AND k.access_code = ?
              AND (k.expired_at IS NULL OR k.expired_at >= CURRENT_TIMESTAMP)
            """,
            (email.strip(), access_code.strip())
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_account_password(email: str, new_password: str):
    """Memperbarui password di database lokal setelah alur Playwright berhasil."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET current_password = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(email) = LOWER(?)",
            (new_password, email.strip())
        )
        await db.commit()

# --- ADMIN OPERATIONAL & MEMBER MANAGEMENT ---

async def add_account(email: str, current_password: Optional[str] = None) -> int:
    """Menambah akun produk baru (password opsional/default NULL)."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO accounts (email, current_password) VALUES (?, ?)",
            (email.strip(), current_password)
        )
        await db.commit()
        return cursor.lastrowid

async def register_member(
    customer_name: str, 
    email: str, 
    target_date: str  # Format string: "YYYY-MM-DD" atau "YYYY-MM-DD HH:MM:SS" (misal: "2026-10-12")
) -> Tuple[Optional[str], Optional[str]]:
    """
    Mendaftarkan langganan customer ke tabel members & membuat access_code di access_keys dengan tanggal kedaluwarsa spesifik.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        # 1. Cari account_id berdasarkan email
        async with db.execute("SELECT id FROM accounts WHERE LOWER(email) = LOWER(?)", (email.strip(),)) as cursor:
            acc = await cursor.fetchone()
            if not acc:
                return None, "Akun email produk belum terdaftar di database."
            account_id = acc[0]

        # 2. Format tanggal kedaluwarsa agar konsisten
        # Jika format yang dikirim hanya tanggal ("2026-10-12"), kita set ke akhir hari "2026-10-12 23:59:59"
        expired_at_str = target_date.strip()
        if len(expired_at_str) == 10:
            expired_at_str += " 23:59:59"

        # 3. Tambah record member
        await db.execute(
            """
            INSERT INTO members (customer_name, account_id, expired_at)
            VALUES (?, ?, DATETIME(?))
            """,
            (customer_name.strip(), account_id, expired_at_str)
        )
        
        # 4. Buat access key unik
        code = generate_access_code()
        await db.execute(
            """
            INSERT INTO access_keys (access_code, account_id, expired_at)
            VALUES (?, ?, DATETIME(?))
            """,
            (code, account_id, expired_at_str)
        )
        
        await db.commit()
        return code, None
    
async def regenerate_token(email: str, target_date: Optional[str] = None) -> Optional[str]:
    """
    Generasi ulang kode kunci baru untuk akun/member. 
    Jika target_date diisi, expired_at akan diperbarui sesuai tanggal tersebut.
    Jika target_date None, expired_at tidak diubah (mengikuti masa aktif lama).
    """
    new_code = generate_access_code()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM accounts WHERE LOWER(email) = LOWER(?)", (email.strip(),)) as cursor:
            acc = await cursor.fetchone()
            if not acc:
                return None
            account_id = acc[0]

        expired_at_str = None
        if target_date:
            expired_at_str = target_date.strip()
            if len(expired_at_str) == 10:
                expired_at_str += " 23:59:59"

        # Update access code dan masa berlaku yang terhubung ke account_id
        async with db.execute("SELECT id FROM access_keys WHERE account_id = ?", (account_id,)) as cursor:
            existing_key = await cursor.fetchone()

        if existing_key:
            if expired_at_str:
                await db.execute(
                    "UPDATE access_keys SET access_code = ?, expired_at = DATETIME(?) WHERE account_id = ?",
                    (new_code, expired_at_str, account_id)
                )
                await db.execute(
                    "UPDATE members SET expired_at = DATETIME(?) WHERE account_id = ?",
                    (expired_at_str, account_id)
                )
            else:
                await db.execute(
                    "UPDATE access_keys SET access_code = ? WHERE account_id = ?",
                    (new_code, account_id)
                )
        else:
            await db.execute(
                "INSERT INTO access_keys (access_code, account_id, expired_at) VALUES (?, ?, DATETIME(?))",
                (new_code, account_id, expired_at_str)
            )

        await db.commit()
    return new_code

async def log_activity(telegram_id: Optional[int], action: str, email: Optional[str], status: str, details: Optional[str] = ""):
    """Mencatat aktivitas pengguna ke database dengan binding parameter terproteksi."""
    async with aiosqlite.connect(DB_PATH) as db:
        params = (
            telegram_id,
            str(action) if action else "UNKNOWN_ACTION",
            str(email) if email else "",
            str(status) if status else "UNKNOWN_STATUS",
            str(details) if details else ""
        )
        await db.execute(
            "INSERT INTO activity_logs (telegram_id, action, email, status, details) VALUES (?, ?, ?, ?, ?)",
            params
        )
        await db.commit()

# --- ADMIN MONITORING & LISTING ---

async def get_accounts_list(limit: int = 20, offset: int = 0) -> list[Dict]:
    """Mengambil daftar akun produk terbaru beserta informasi token/member terkait."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT 
                a.id, 
                a.email, 
                a.current_password, 
                a.status, 
                a.created_at,
                k.access_code
            FROM accounts a
            LEFT JOIN access_keys k ON a.id = k.account_id
            ORDER BY a.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]

async def get_members_list(limit: int = 20, offset: int = 0) -> list[Dict]:
    """Mengambil daftar member/langganan terbaru beserta detail email dan token akses."""
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT 
                m.id,
                m.customer_name,
                m.expired_at,
                m.created_at,
                a.email,
                k.access_code
            FROM members m
            JOIN accounts a ON m.account_id = a.id
            LEFT JOIN access_keys k ON a.id = k.account_id
            ORDER BY m.id DESC
            LIMIT ? OFFSET ?
            """,
            (limit, offset)
        ) as cursor:
            rows = await cursor.fetchall()
            return [dict(row) for row in rows]
        
