import json, hashlib, subprocess, urllib.request, os

# ĐIỀN THÔNG TIN SUPABASE VÀ KEY VỪA TẠO Ở BƯỚC 1
SUPABASE_URL = "https://gfihmymecoykcogqykbl.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdmaWhteW1lY295a2NvZ3F5a2JsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzA5NjU4MTMsImV4cCI6MjA4NjU0MTgxM30.SWsdEyLWkOu2tKZS3ZFKk2riCR5uxubXbFvz0a12e_Q" # Của bạn
LICENSE_KEY = "VIP-TEST-001"
RELEASE_DIR = "Overlord_Apex_Release"

print("Đang quét HWID...")
hwid = subprocess.check_output('wmic csproduct get uuid', shell=True).decode().split('\n')[1].strip()

print("Tạo mã Hash Anti-Tamper...")
expected_hash = hashlib.sha512(f'||{LICENSE_KEY}||<<SECURE>>||{hwid}||'.encode()).hexdigest()

print("Lưu system.lic vào thư mục Release...")
lic_path = os.path.join(RELEASE_DIR, "system.lic")
with open(lic_path, "w", encoding="utf-8") as f:
    json.dump({"key": LICENSE_KEY, "hash": expected_hash}, f)

print("Đang khóa HWID lên Supabase...")
patch_url = f"{SUPABASE_URL}/rest/v1/licenses?key=eq.{LICENSE_KEY}"
patch_data = json.dumps({"hwid": hwid}).encode('utf-8')
req = urllib.request.Request(patch_url, data=patch_data, method='PATCH', 
                             headers={'apikey': SUPABASE_ANON_KEY, 'Authorization': f'Bearer {SUPABASE_ANON_KEY}', 'Content-Type': 'application/json'})
try:
    urllib.request.urlopen(req)
    print("\n✅ THÀNH CÔNG! Đã giả lập xong Inno Setup.")
    print(f"👉 Bây giờ bạn hãy vào thư mục '{RELEASE_DIR}' và click đúp vào 'AI_Reup_Pro.exe' để xem thành quả!")
except Exception as e:
    print("\n❌ Lỗi khi gửi lên Supabase:", e)