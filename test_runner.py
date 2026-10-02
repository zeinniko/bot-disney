import asyncio
import sys
import logging
from datetime import datetime

# Import fungsi-fungsi service yang sudah ada
from services.disney_service import (
    get_disney_devices,
    kick_all_devices,
    kick_specific_devices,
    change_disney_password
)

# Konfigurasi Logging Terminal
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)

def print_separator(title: str):
    print("\n" + "=" * 60)
    print(f"  {title.upper()}")
    print("=" * 60)

async def console_progress_callback(message: str):
    """Callback untuk mencetak progress update langsung ke terminal"""
    timestamp = datetime.now().strftime("%H:%M:%S")
    print(f"[{timestamp}] 📌 PROGRESS: {message}")

async def main():
    print_separator("DISNEY SERVICE TERMINAL TESTER")
    
    # 1. Input Kredensial Akun
    email = input("Masukkan Email Disney: ").strip()
    password = input("Masukkan Password Saat Ini: ").strip()

    if not email or not password:
        print("❌ Email dan Password tidak boleh kosong!")
        return

    while True:
        print_separator("PILIH AKSI METODE TESTING")
        print("1. Cek Daftar Perangkat (get_disney_devices)")
        print("2. Kick Perangkat Pilihan (kick_specific_devices)")
        print("3. Kick Semua Perangkat (kick_all_devices)")
        print("4. Ganti Password (change_disney_password)")
        print("0. Keluar")
        
        choice = input("\nPilihan Anda (0-4): ").strip()

        if choice == "1":
            print_separator("Menjalankan: Get Disney Devices")
            res = await get_disney_devices(email, password)
            print("\n📋 RESULT:")
            print(f"Status: {res.get('status')}")
            if res.get("status") == "success":
                print("\nFormatted Text Output:\n")
                print(res.get("formatted_text"))
            else:
                print(f"Error Message: {res.get('message')}")

        elif choice == "2":
            print_separator("Menjalankan: Kick Specific Devices")
            targets_input = input("Masukkan nomor index perangkat (pisahkan koma, ex: 2,3): ").strip()
            try:
                target_indexes = [int(x.strip()) for x in targets_input.split(",") if x.strip().isdigit()]
                if not target_indexes:
                    print("❌ Index perangkat tidak valid!")
                    continue
                
                print(f"Target index yang di-kick: {target_indexes}")
                res = await kick_specific_devices(email, password, target_indexes)
                print("\n📋 RESULT:")
                print(f"Status: {res.get('status')}")
                print(f"Message: {res.get('message')}")
            except Exception as err:
                print(f"❌ Error parse input: {err}")

        elif choice == "3":
            print_separator("Menjalankan: Kick All Devices")
            confirm = input(f"Yakin ingin LOGOUT / KICK SEMUA perangkat di {email}? (y/n): ").strip().lower()
            if confirm == "y":
                res = await kick_all_devices(email, password)
                print("\n📋 RESULT:")
                print(f"Status: {res.get('status')}")
                print(f"Message: {res.get('message')}")

        elif choice == "4":
            print_separator("Menjalankan: Change Password")
            new_pass = input("Masukkan Password Baru: ").strip()
            if not new_pass:
                print("❌ Password baru tidak boleh kosong!")
                continue

            res = await change_disney_password(
                email=email, 
                current_password=password, 
                new_password=new_pass, 
                progress_cb=console_progress_callback
            )
            print("\n📋 RESULT:")
            print(f"Status: {res.get('status')}")
            print(f"Message: {res.get('message')}")

        elif choice == "0":
            print("\nTerima kasih, keluar dari runner.")
            break
        else:
            print("❌ Pilihan tidak valid.")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n⚠️ Eksekusi dibatalkan oleh pengguna (Ctrl+C).")