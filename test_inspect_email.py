import asyncio
import email as email_parser
import aioimaplib
from config.settings import IMAP_PASS, IMAP_PORT, IMAP_SERVER, IMAP_USER


async def inspect_recent_emails(limit: int = 3):
    print("=" * 60)
    print("🔍 MEMERIKSA DETAIL EMAIL DI INBOX")
    print("=" * 60)
    print(f"📌 Server Target : '{IMAP_SERVER}'")
    print(f"📌 Port Target   : {IMAP_PORT}")
    print(f"📌 User Target   : '{IMAP_USER}'")
    print("-" * 60)

    if not IMAP_SERVER:
        print("❌ ERROR: IMAP_SERVER kosong! File .env belum terbaca.")
        return

    try:
        imap_client = aioimaplib.IMAP4_SSL(host=IMAP_SERVER, port=IMAP_PORT)
        await imap_client.wait_hello_from_server()

        res, msg = await imap_client.login(IMAP_USER, IMAP_PASS)
        if res != "OK":
            print(f"❌ Login Gagal: {msg}")
            return

        await imap_client.select("INBOX")

        # Cari semua pesan di inbox
        status, response = await imap_client.search("ALL")
        if status != "OK" or not response[0]:
            print("ℹ️ Tidak ada email di INBOX.")
            return

        msg_nums = response[0].split()
        target_nums = list(reversed(msg_nums))[:limit]

        print(
            f"📥 Menampilkan {len(target_nums)} email terbaru dari total {len(msg_nums)} email:\n"
        )

        for idx, num in enumerate(target_nums, 1):
            num_str = num.decode("utf-8")
            status, msg_data = await imap_client.fetch(num_str, "(RFC822)")

            if status == "OK":
                raw_email = msg_data[1]
                parsed_email = email_parser.message_from_bytes(raw_email)

                sender = parsed_email.get("From", "-")
                subject = parsed_email.get("Subject", "-")
                date = parsed_email.get("Date", "-")

                # Ambil isi teks
                body = ""
                if parsed_email.is_multipart():
                    for part in parsed_email.walk():
                        if part.get_content_type() in [
                            "text/plain",
                            "text/html",
                        ]:
                            payload = part.get_payload(decode=True)
                            if payload:
                                body += payload.decode(
                                    "utf-8", errors="ignore"
                                )
                else:
                    payload = parsed_email.get_payload(decode=True)
                    if payload:
                        body = payload.decode("utf-8", errors="ignore")

                print(f"--- [EMAIL #{idx}] ---")
                print(f"📌 FROM    : {sender}")
                print(f"📌 SUBJECT : {subject}")
                print(f"📌 DATE    : {date}")
                print(f"📝 BODY SNIPPET (150 Karakter Pertama):")
                print(f'"{body.strip()[:150]}..."')
                print("-" * 60)

        await imap_client.logout()

    except Exception as err:
        print(f"❌ Exception: {err}")


if __name__ == "__main__":
    asyncio.run(inspect_recent_emails())