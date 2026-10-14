import asyncio
from database.db import add_account, init_db

async def bulk_insert_accounts():
    # Pastikan koneksi & tabel terinisialisasi
    await init_db()

    domain = "pidercat.site"
    start_index = 0
    end_index = 210

    success_count = 0
    fail_count = 0

    print(f"🚀 Memulai proses input akun dari dizney@{domain} sampai dizney{end_index}@{domain}...\n")

    for i in range(start_index, end_index + 1):
        # Format nama email: dizney@pidercat.site (saat i=0), dizney1@pidercat.site, dst.
        email_prefix = "dizney" if i == 0 else f"dizney{i}"
        email = f"{email_prefix}@{domain}"

        try:
            acc_id = await add_account(email=email, current_password=None)
            print(f"✅ [{i + 1}/{end_index + 1}] Berhasil menambahkan: {email} (ID: {acc_id})")
            success_count += 1
        except Exception as e:
            print(f"⚠️ [{i + 1}/{end_index + 1}] Gagal menambahkan {email}: {e}")
            fail_count += 1

    print("\n" + "=" * 50)
    print(f"🎉 Selesai! Ringkasan:")
    print(f"   - Total Berhasil : {success_count}")
    print(f"   - Total Gagal    : {fail_count}")
    print("=" * 50)

if __name__ == "__main__":
    asyncio.run(bulk_insert_accounts())