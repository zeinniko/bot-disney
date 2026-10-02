-- 1. Tabel User Telegram
CREATE TABLE IF NOT EXISTS users (
    telegram_id BIGINT PRIMARY KEY,
    username VARCHAR(255),
    full_name VARCHAR(255),
    role VARCHAR(20) DEFAULT 'customer', -- 'admin' atau 'customer'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. Tabel Akun Disney/Layanan
CREATE TABLE IF NOT EXISTS accounts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email VARCHAR(255) UNIQUE NOT NULL,
    current_password VARCHAR(255) NOT NULL,
    status VARCHAR(50) DEFAULT 'active', -- 'active', 'expired', 'suspended'
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 3. Tabel Access Keys (Materi Relasi Banyak Akun/User ke Kode Akses)
CREATE TABLE IF NOT EXISTS access_keys (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    access_code VARCHAR(64) UNIQUE NOT NULL, -- Kode kunci acak unik (cth: A3KN7X)
    account_id INTEGER NOT NULL,
    telegram_id BIGINT,                      -- Opsional: Menautkan kunci ke Telegram ID pengguna tertentu
    expired_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (account_id) REFERENCES accounts(id) ON DELETE CASCADE,
    FOREIGN KEY (telegram_id) REFERENCES users(telegram_id) ON DELETE SET NULL
);

-- 4. Tabel Log Aktivitas
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id BIGINT,
    action VARCHAR(100) NOT NULL,            -- 'CHANGE_PASSWORD', 'LOOKUP_DEVICES', 'KICK_DEVICE'
    email VARCHAR(255),
    status VARCHAR(50),                      -- 'SUCCESS', 'FAILED'
    details TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);