import aiosqlite
import secrets
import string
from typing import Optional, Dict, Tuple

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

# --- MODUL VALIDASI & PROSES SAKTI ---

async def get_account_by_access_code(email: str, access_code: str) -> Optional[Dict]:
    """
    Validasi email dan kode akses.
    Mengambil password lama dari database lokal jika valid.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            """
            SELECT a.id, a.email, a.current_password, k.access_code
            FROM accounts a
            JOIN access_keys k ON a.id = k.account_id
            WHERE LOWER(a.email) = LOWER(?) AND k.access_code = ?
            """,
            (email.strip(), access_code.strip())
        ) as cursor:
            row = await cursor.fetchone()
            return dict(row) if row else None

async def update_account_password(email: str, new_password: str):
    """Memperbarui password di database lokal setelah proses di Playwright berhasil."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE accounts SET current_password = ?, updated_at = CURRENT_TIMESTAMP WHERE LOWER(email) = LOWER(?)",
            (new_password, email.strip())
        )
        await db.commit()

# --- ADMIN CRUD OPERATIONS ---

async def add_account_with_key(email: str, current_password: str, telegram_id: Optional[int] = None) -> str:
    """Menambah akun baru & otomatis membuatkan kode kunci unik."""
    code = generate_access_code()
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO accounts (email, current_password) VALUES (?, ?)",
            (email.strip(), current_password)
        )
        account_id = cursor.lastrowid
        
        await db.execute(
            "INSERT INTO access_keys (access_code, account_id, telegram_id) VALUES (?, ?, ?)",
            (code, account_id, telegram_id)
        )
        await db.commit()
    return code

async def regenerate_token(email: str) -> Optional[str]:
    """Generasi ulang kode kunci baru untuk suatu akun."""
    new_code = generate_access_code()
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id FROM accounts WHERE LOWER(email) = LOWER(?)", (email.strip(),)) as cursor:
            acc = await cursor.fetchone()
            if not acc:
                return None
            account_id = acc[0]

        await db.execute(
            "UPDATE access_keys SET access_code = ? WHERE account_id = ?",
            (new_code, account_id)
        )
        await db.commit()
    return new_code

async def register_customer(telegram_id: int, username: str, full_name: str, role: str = 'customer'):
    """Registrasi pengguna/customer Telegram."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO users (telegram_id, username, full_name, role)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET username=excluded.username, full_name=excluded.full_name
            """,
            (telegram_id, username, full_name, role)
        )
        await db.commit()

async def is_admin(telegram_id: int) -> bool:
    """Cek apakah user Telegram adalah admin."""
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT role FROM users WHERE telegram_id = ?", (telegram_id,)) as cursor:
            row = await cursor.fetchone()
            return row is not None and row[0] == 'admin'

async def log_activity(telegram_id: int, action: str, email: str, status: str, details: str = ""):
    """Mencatat aktivitas pengguna ke database."""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO activity_logs (telegram_id, action, email, status, details) VALUES (?, ?, ?, ?, ?)",
            (telegram_id, action, email, status, details)
        )
        await db.commit()
