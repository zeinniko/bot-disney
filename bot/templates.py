# Custom Animated Emoji
EMOJI_FIREWORKS = '<tg-emoji emoji-id="5368324170671202286">🎆</tg-emoji>'
EMOJI_DISNEY_LOGO = '<tg-emoji emoji-id="6172726091573108485">🔵</tg-emoji>'
EMOJI_QUESTION = '<tg-emoji emoji-id="5368324170671202287">⁉️</tg-emoji>'
EMOJI_BOOK = '<tg-emoji emoji-id="5368324170671202288">📖</tg-emoji>'

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
    "<code>pindercat@example.com|A3KN7X</code>\n"
    "<code>pindercat@example.com|A3KN7X|MyPass123</code>"
)

TEXT_CHPASS_SIGNOUT = (
    "MODE DIPILIH:\n"
    "🔒 <b>Change Password + 💻 Signout All Devices</b>\n\n"
    "✒️ Kirim data dengan format:\n"
    "<code>email|kode_akses</code> — password otomatis\n"
    "<code>email|kode_akses|passwordbaru</code> — password custom\n\n"
    "✅ Contoh:\n"
    "<code>pindercat@example.com|A3KN7X</code>\n"
    "<code>pindercat@example.com|A3KN7X|MyPass123</code>"
)

TEXT_LOOKUP_KICK = (
    "MODE DIPILIH:\n"
    "🔍 <b>Lookup / 💻 Kick Device</b>\n\n"
    "✒️ Kirim data dengan format:\n"
    "<code>email|password|kode_akses</code>\n\n"
    "✅ Contoh:\n"
    "<code>pindercat@example.com|P4ssw0rd|A3KN7X</code>"
)