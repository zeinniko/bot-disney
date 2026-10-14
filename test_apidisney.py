import asyncio
from typing import Optional
import requests
import json
from playwright.async_api import async_playwright
from services.disney_service import login_disney

BASE_URL = "https://global.edge.bamgrid.com"
GRAPHQL_URL = "https://disney.api.edge.bamgrid.com/v1/public/graphql"
API_KEY = "ZGlzbmV5JmJyb3dzZXImMS4wLjA.Cu56AgSfBTDag5NiRA81oLHkDZfu5L3CKadnefEAY84"


def get_graphql_headers(token: str) -> dict:
    return {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/117.0.0.0 Safari/537.36"
    }


async def extract_tokens_from_browser(page, context):
    """Mengekstrak Bearer Access Token dan Action Grant/Identity Token dari Session Storage / Local Storage / Cookies."""
    tokens = {
        "access_token": None,
        "action_grant": None,
        "id_token": None
    }

    # 1. Cek via LocalStorage & SessionStorage browser
    storage_data = await page.evaluate("""
        () => {
            const data = {};
            for (let i = 0; i < localStorage.length; i++) {
                const k = localStorage.key(i);
                data['local:' + k] = localStorage.getItem(k);
            }
            for (let i = 0; i < sessionStorage.length; i++) {
                const k = sessionStorage.key(i);
                data['session:' + k] = sessionStorage.getItem(k);
            }
            return data;
        }
    """)

    for key, val in storage_data.items():
        if not val:
            continue
        try:
            parsed = json.loads(val)
            if isinstance(parsed, dict):
                if "token" in parsed and "accessToken" in parsed["token"]:
                    tokens["access_token"] = parsed["token"]["accessToken"]
                if "accessToken" in parsed and not tokens["access_token"]:
                    tokens["access_token"] = parsed["accessToken"]
                if "idToken" in parsed:
                    tokens["id_token"] = parsed["idToken"]
                if "actionGrant" in parsed:
                    tokens["action_grant"] = parsed["actionGrant"]
        except Exception:
            pass

    # 2. Fallback: Tangkap dari Cookies jika ada
    cookies = await context.cookies()
    for cookie in cookies:
        if cookie["name"] == "disney_access_token" and not tokens["access_token"]:
            tokens["access_token"] = cookie["value"]
        if cookie["name"] == "disney_id_token" and not tokens["id_token"]:
            tokens["id_token"] = cookie["value"]

    return tokens


def get_all_devices(access_token: str) -> list:
    url = f"{GRAPHQL_URL}?op=listAccountDevices"
    payload = {
        "operationName": "listAccountDevices",
        "variables": {},
        "query": """
query listAccountDevices {
  listAccountDevices {
    devices {
      accountDevice {
        deviceId
        deviceFamily
        applicationRuntime
        deviceProfile
        friendlyDeviceName
        formFactor
      }
      locationV2 {
        physical {
          cityName
          countryCode
          stateName
        }
      }
      sessionDetails {
        generatedOn
        expiresOn
      }
    }
  }
}
"""
    }

    response = requests.post(url, headers=get_graphql_headers(access_token), json=payload)
    if response.status_code == 200:
        data = response.json()
        if "data" in data and "listAccountDevices" in data["data"]:
            return data["data"]["listAccountDevices"].get("devices", [])
    print(f"[-] Gagal mengambil daftar perangkat. Status: {response.status_code}")
    return []


def kick_device_by_id(token: str, device_id: str, action_grant: Optional[str] = None) -> bool:
    url = f"{GRAPHQL_URL}?op=logoutAccountDeviceWithActionGrant"
    
    payload = {
        "operationName": "logoutAccountDeviceWithActionGrant",
        "variables": {
            "input": {
                "actionGrant": action_grant or "",
                "deviceId": device_id
            }
        },
        "query": """
mutation logoutAccountDeviceWithActionGrant($input: LogoutAccountDeviceWithActionGrantInput!) {
  logoutAccountDeviceWithActionGrant(logoutAccountDevice: $input) {
    accepted
  }
}
"""
    }

    response = requests.post(url, headers=get_graphql_headers(token), json=payload)
    if response.status_code == 200:
        res_data = response.json()
        if "errors" in res_data:
            print(f"[-] Gagal melepaskan perangkat {device_id}: {res_data['errors'][0].get('message')}")
            return False
        print(f"[+] Berhasil melepaskan perangkat ID: {device_id}")
        return True
    else:
        print(f"[-] HTTP Error {response.status_code} saat melepaskan {device_id}")
        return False


async def main():
  email = input("Masukkan Email Disney+: ").strip()
  password = input("Masukkan Password Disney+: ").strip()
  pw = await async_playwright().start()
  browser = await pw.chromium.launch(
      headless=False,
      channel="chrome",
      args=[
          "--disable-blink-features=AutomationControlled", 
          "--no-sandbox",
          "--disable-setuid-sandbox",
          "--disable-dev-shm-usage",
          "--disable-accelerated-2d-canvas",
          "--no-first-run",
          "--no-zygote",
          "--disable-infobars",
          "--window-size=1280,720",
          "--lang=en-US,en",
          # Tambahan baru untuk VPS Headless:
          "--disable-gpu",
          "--disable-software-rasterizer",
          "--disable-extensions",
          "--disable-features=IsolateOrigins,site-per-process"
      ]
  )
  context = await browser.new_context(
      storage_state=None,
      user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/122.0.0.0 Safari/537.36", 
      locale="en-US",
      ignore_https_errors=True,
      viewport={'width': 1280, 'height': 720},
      java_script_enabled=True
  )
  await context.clear_cookies()
  page = await context.new_page()
  # Custom logging callback
  async def progress(msg):
      print(f"[INFO] {msg}")
  # Intercept network requests untuk menangkap token Authorization secara otomatis
  captured_tokens = {"access_token": None}
  def handle_request(request):
      auth = request.headers.get("authorization", "")
      if auth.startswith("Bearer ") and "bamgrid.com" in request.url:
          token = auth.replace("Bearer ", "")
          if token != API_KEY:
              captured_tokens["access_token"] = token
  page.on("request", handle_request)
  # 1. Jalankan proses login dari disney_service.py
  result = await login_disney(
      page=page,
      context=context,
      email=email,
      password=password,
      progress_cb=progress,
      is_chpass=False
  )
  if result.get("status") != "success":
      print(f"[-] Login gagal: {result.get('message')}")
      await browser.close()
      return
  print("\n[+] Login berhasil! Ekstraksi token session...")
  await page.wait_for_timeout(3000)
  # 2. Ambil token dari storage/network
  storage_tokens = await extract_tokens_from_browser(page, context)
  access_token = captured_tokens["access_token"] or storage_tokens.get("access_token")
  id_token = storage_tokens.get("id_token") or access_token
  action_grant = storage_tokens.get("action_grant")
  await browser.close()
  if not access_token:
      print("[-] Gagal mendapatkan Access Token dari browser session.")
      return
  # 3. Ambil daftar perangkat via GraphQL API
  print("\n[*] Mengambil daftar perangkat terhubung...")
  devices = get_all_devices(access_token)
  if not devices:
      print("[-] Tidak ada perangkat terdeteksi atau request gagal.")
      return
  # 4. Tampilkan menu interaktif terminal
  print("\n" + "=" * 60)
  print(" DAFTAR PERANGKAT TERHUBUNG ")
  print("=" * 60)
  # Mengasumsikan perangkat pertama dalam array/tertentu adalah Current Device
  # Disney biasanya menandai Current Device atau kita proteksi index 0/perangkat aktif
  valid_devices = []
  for idx, item in enumerate(devices, 1):
      info = item.get("accountDevice", {})
      loc = item.get("locationV2", {}).get("physical", {})
      
      name = info.get("friendlyDeviceName") or info.get("deviceFamily") or "Unknown Device"
      device_id = info.get("deviceId")
      city = loc.get("cityName", "Unknown")
      country = loc.get("countryCode", "")
      
      # Tandai current device (biasanya session aktif saat ini)
      is_current = (idx == 1)
      status_label = " [CURRENT DEVICE - TDK BISA DI-KICK]" if is_current else ""
      
      print(f"[{idx}] {name} ({city}, {country}) | ID: {device_id}{status_label}")
      
      valid_devices.append({
          "index": idx,
          "name": name,
          "device_id": device_id,
          "is_current": is_current
      })
  print("=" * 60)
  print("Pilihan Aksi:")
  print(" [0] Kick ALL (Kecuali Current Device)")
  print(" [1..N] Pilih nomor perangkat yang ingin di-kick")
  print(" [Q] Keluar")
  choice = input("\nMasukkan pilihan Anda: ").strip().lower()
  if choice == "q":
      print("[*] Selesai.")
      return
  elif choice == "0":
      confirm = input("Apakah Anda yakin ingin MENGELUARKAN SEMUA perangkat? (y/n): ").strip().lower()
      if confirm == "y":
          for dev in valid_devices:
              if dev["is_current"]:
                  print(f"[*] Melewati {dev['name']} (Current Device)")
                  continue
              print(f"[*] Mengeluarkan {dev['name']} (ID: {dev['device_id']})...")
              kick_device_by_id(id_token, dev["device_id"], action_grant)
  else:
      try:
          selected_idx = int(choice)
          target = next((d for d in valid_devices if d["index"] == selected_idx), None)
          if not target:
              print("[-] Nomor pilihan tidak valid.")
          elif target["is_current"]:
              print("[-] Perangkat saat ini (Current Device) tidak dapat dikeluarkan!")
          else:
              print(f"[*] Mengeluarkan {target['name']} (ID: {target['device_id']})...")
              kick_device_by_id(id_token, target["device_id"], action_grant)
      except ValueError:
          print("[-] Input tidak valid.")


if __name__ == "__main__":
    asyncio.run(main())