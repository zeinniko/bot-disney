import asyncio
import email as email_parser
from email.header import decode_header
import os
from pathlib import Path
import re
import time
import aioimaplib
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)

USER = os.getenv("IMAP_USER", "").strip()
PASS = os.getenv("IMAP_PASS", "").replace(" ", "").strip()
SERVER = "imap.gmail.com"
PORT = 993


def decode_str(header_value):
    if not header_value:
        return ""
    decoded_list = decode_header(header_value)
    result = ""
    for decoded_string, charset in decoded_list:
        if isinstance(decoded_string, bytes):
            result += decoded_string.decode(
                charset or "utf-8", errors="ignore"
            )
        else:
            result += str(decoded_string)
    return result


def clean_html(raw_html: str) -> str:
    """Membersihkan tag HTML, CSS style (seperti #000000), dan script dari isi email."""
    # 1. Hapus tag <style>...</style> beserta isinya (agar kode warna #000000 hilang)
    clean_text = re.sub(
        r"<style[^>]*>[\s\S]*?</style>", " ", raw_html, flags=re.IGNORECASE
    )
    # 2. Hapus tag <script>...</script>
    clean_text = re.sub(
        r"<script[^>]*>[\s\S]*?</script>", " ", clean_text, flags=re.IGNORECASE
    )
    # 3. Hapus seluruh tag HTML <...>
    clean_text = re.sub(r"<[^>]+>", " ", clean_text)
    # 4. Hapus HTML entities (&nbsp;, dll)
    clean_text = re.sub(r"&[a-zA-Z0-9#]+;", " ", clean_text)
    return clean_text


def extract_otp_from_body(body_text: str) -> str:
    """Mencari 6 digit angka OTP asli setelah HTML dan CSS dibersihkan."""
    cleaned = clean_html(body_text)

    # Cari semua deretan 6 digit angka
    matches = re.findall(r"\b(\d{6})\b", cleaned)

    # Filter out angka dummy seperti 000000
    valid_matches = [m for m in matches if m != "000000"]

    if valid_matches:
        # OTP Disney+ biasanya adalah 6 digit pertama yang valid di teks bersih
        return valid_matches[0]

    return None


async def fetch_disney_otp(
    target_email: str, max_wait_seconds: int = 45, interval: int = 5
):
    print("=" * 60)
    print(f"⏳ MENUNGGU OTP DISNEY+ UNTUK: {target_email}")
    print("=" * 60)

    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        elapsed = int(time.time() - start_time)
        print(f"🔄 Polling IMAP... ({elapsed}s / {max_wait_seconds}s)")

        try:
            imap_client = aioimaplib.IMAP4_SSL(host=SERVER, port=PORT)
            await imap_client.wait_hello_from_server()

            res, msg = await imap_client.login(USER, PASS)
            if res != "OK":
                print(f"❌ LOGIN GAGAL: {msg}")
                await asyncio.sleep(interval)
                continue

            folders_to_check = ["INBOX", '"[Gmail]/Spam"', '"[Gmail]/All Mail"']

            for folder in folders_to_check:
                select_res, _ = await imap_client.select(folder)
                if select_res != "OK":
                    continue

                status, response = await imap_client.search("ALL")
                if status != "OK" or not response[0]:
                    continue

                msg_nums = response[0].split()
                target_nums = list(reversed(msg_nums))[:5]

                for num in target_nums:
                    num_str = num.decode("utf-8")
                    st, msg_data = await imap_client.fetch(num_str, "(RFC822)")
                    if st == "OK":
                        parsed = email_parser.message_from_bytes(msg_data[1])
                        to_header = decode_str(parsed.get("To")).lower()

                        # Utamakan text/plain jika ada, jika tidak gunakan text/html
                        plain_body = ""
                        html_body = ""

                        if parsed.is_multipart():
                            for part in parsed.walk():
                                ctype = part.get_content_type()
                                payload = part.get_payload(decode=True)
                                if payload:
                                    if ctype == "text/plain":
                                        plain_body += payload.decode(
                                            "utf-8", errors="ignore"
                                        )
                                    elif ctype == "text/html":
                                        html_body += payload.decode(
                                            "utf-8", errors="ignore"
                                        )
                        else:
                            payload = parsed.get_payload(decode=True)
                            if payload:
                                plain_body = payload.decode(
                                    "utf-8", errors="ignore"
                                )

                        body_to_use = (
                            plain_body if plain_body.strip() else html_body
                        )

                        if (
                            target_email.lower() in to_header
                            or target_email.lower() in body_to_use.lower()
                        ):
                            otp = extract_otp_from_body(body_to_use)
                            if otp:
                                print(
                                    f"\n🎉 OTP ASLI DITEMUKAN PADA FOLDER [{folder}]!"
                                )
                                print(f"📌 FROM    : {parsed.get('From')}")
                                print(f"📌 TO      : {parsed.get('To')}")
                                print(f"📌 SUBJECT : {parsed.get('Subject')}")
                                print(f"🔑 KODE OTP: {otp}\n")
                                await imap_client.logout()
                                return otp

            await imap_client.logout()

        except Exception as err:
            print(f"⚠️ Warning saat fetch: {err}")

        await asyncio.sleep(interval)

    print("❌ TIMEOUT: OTP tidak ditemukan dalam batas waktu.")
    return None


if __name__ == "__main__":
    asyncio.run(
        fetch_disney_otp(
            target_email="dizney196@pidercat.site", max_wait_seconds=30
        )
    )