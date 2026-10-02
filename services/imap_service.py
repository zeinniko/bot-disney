import asyncio
import email as email_parser
from email.header import decode_header
from email.utils import parsedate_to_datetime
import os
from pathlib import Path
import re
import time
import aioimaplib
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(dotenv_path=BASE_DIR / ".env", override=True)


def clean_html(raw_html: str) -> str:
    clean_text = re.sub(
        r"<style[^>]*>[\s\S]*?</style>", " ", raw_html, flags=re.IGNORECASE
    )
    clean_text = re.sub(
        r"<script[^>]*>[\s\S]*?</script>", " ", clean_text, flags=re.IGNORECASE
    )
    clean_text = re.sub(r"<[^>]+>", " ", clean_text)
    clean_text = re.sub(r"&[a-zA-Z0-9#]+;", " ", clean_text)
    return clean_text


def extract_otp_from_body(body_text: str) -> str:
    cleaned = clean_html(body_text)
    matches = re.findall(r"\b(\d{6})\b", cleaned)
    valid_matches = [m for m in matches if m != "000000"]
    return valid_matches[0] if valid_matches else None


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


async def fetch_disney_otp(
    email: str, 
    max_wait_seconds: int = 45, 
    interval: int = 5,
    since_time: float = None  # Added: Parameter Unix timestamp batas awal email
) -> str:
    user = os.getenv("IMAP_USER", "").strip()
    password = os.getenv("IMAP_PASS", "").replace(" ", "").strip()
    server = "imap.gmail.com"
    port = 993

    start_time = time.time()

    while time.time() - start_time < max_wait_seconds:
        try:
            imap_client = aioimaplib.IMAP4_SSL(host=server, port=port)
            await imap_client.wait_hello_from_server()

            res, msg = await imap_client.login(user, password)
            if res != "OK":
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
                        
                        # --- FILTER EMAIL BERDASARKAN WAKTU TERIMA (since_time) ---
                        if since_time is not None:
                            date_header = parsed.get("Date")
                            if date_header:
                                try:
                                    msg_date = parsedate_to_datetime(date_header)
                                    msg_timestamp = msg_date.timestamp()
                                    # Abaikan jika email dikirim sebelum timestamp request OTP
                                    if msg_timestamp < since_time:
                                        continue
                                except Exception:
                                    pass

                        to_header = decode_str(parsed.get("To")).lower()

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
                            email.lower() in to_header
                            or email.lower() in body_to_use.lower()
                        ):
                            otp = extract_otp_from_body(body_to_use)
                            if otp:
                                await imap_client.logout()
                                return otp

            await imap_client.logout()

        except Exception:
            pass

        await asyncio.sleep(interval)

    return None