# Custom Animated Emoji
EMOJI_FIREWORKS = '🎆'
EMOJI_DISNEY_LOGO = '🔵'
EMOJI_QUESTION = '⁉️'
EMOJI_BOOK = '📖'

TEXT_START = (
    f"{EMOJI_FIREWORKS} <b>SELAMAT DATANG di Disney+ Auto Setup Bot</b>\n\n"
    f"Gunakan bot ini untuk mengelola akun {EMOJI_DISNEY_LOGO} <b>Disney+</b> secara otomatis — "
    "ganti password, kick perangkat, dan sign out semua device dengan cepat & mudah.\n\n"
    f"{EMOJI_QUESTION} <b>Cara pakai?</b>\n"
    "Minta <b>kode akses</b> dari admin, lalu pilih fitur di bawah dan masukkan data sesuai format.\n\n"
    f"{EMOJI_BOOK} <b>MENU UTAMA:</b>\n"
    "Pilih fitur yang ingin digunakan:"
)

TEXT_CHPASS_ONLY = (
    "MODE DIPILIH:\n"
    "🔒 <b>Change Password Only</b>\n\n"
    "✒️ Kirim data dengan format:\n"
    "<code>email|kode_akses</code> — password otomatis\n"
    "<code>email|kode_akses|passwordbaru</code> — password custom\n\n"
    "✅ Contoh:\n"
    "<code>pider@example.com|A3KN7X</code>\n"
    "<code>pider@example.com|A3KN7X|MyPass123</code>"
)

TEXT_CHPASS_SIGNOUT = (
    "MODE DIPILIH:\n"
    "🔒 <b>Change Password + 💻 Signout All Devices</b>\n\n"
    "✒️ Kirim data dengan format:\n"
    "<code>email|kode_akses</code> — password otomatis\n"
    "<code>email|kode_akses|passwordbaru</code> — password custom\n\n"
    "✅ Contoh:\n"
    "<code>pider@example.com|A3KN7X</code>\n"
    "<code>pider@example.com|A3KN7X|MyPass123</code>"
)

TEXT_LOOKUP_KICK = (
    "MODE DIPILIH:\n"
    "🔍 <b>Lookup / 💻 Kick Device</b>\n\n"
    "✒️ Kirim data dengan format:\n"
    "<code>email|password|kode_akses</code>\n\n"
    "✅ Contoh:\n"
    "<code>pider@example.com|P4ssw0rd|A3KN7X</code>"
)