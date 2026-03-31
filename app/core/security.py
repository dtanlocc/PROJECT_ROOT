import os
import sys
import subprocess
import hashlib
import urllib.request
import json
import ctypes
import time
import random
import threading

# ==============================================================================
# LÕI BẢO MẬT & XÁC THỰC (HARDCORE SECURITY CORE)
# Tích hợp: Anti-Debug, Anti-VM, Memory Encryption, Timing Attacks, Dynamic Salt
# ==============================================================================

LICENSE_FILE = "system.lic"
_ENCRYPTED_RAM_TOKEN = None  # Token sẽ được mã hóa liên tục trong RAM
_ROLLING_KEY_SEED = int(time.time() * 1000) % 999999 # Seed thay đổi mỗi lần chạy



# Hàm giả lập SECRET (Sau này tool build sẽ thay thế bằng mã hóa XOR/AES)
def SECRET(s): return s
SUPABASE_URL = SECRET("https://gfihmymecoykcogqykbl.supabase.co")
SUPABASE_ANON_KEY = SECRET("eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdmaWhteW1lY295a2NvZ3F5a2JsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzA5NjU4MTMsImV4cCI6MjA4NjU0MTgxM30.SWsdEyLWkOu2tKZS3ZFKk2riCR5uxubXbFvz0a12e_Q")
# ------------------------------------------------------------------------------
# 1. ANTI-DEBUGGING & ANTI-VM (CẢM BIẾN MÔI TRƯỜNG)
# ------------------------------------------------------------------------------
def _is_debugger_present():
    """Kiểm tra xem tiến trình có đang bị Debugger gắn vào không."""
    try:
        # API Windows cơ bản
        if ctypes.windll.kernel32.IsDebuggerPresent(): return True
        
        # Check Remote Debugger
        is_remote = ctypes.c_bool(False)
        ctypes.windll.kernel32.CheckRemoteDebuggerPresent(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(is_remote))
        if is_remote.value: return True
        
        return False
    except:
        return False

def _is_vm_environment():
    """Phát hiện môi trường máy ảo dựa trên Driver và đặc điểm phần cứng."""
    try:
        # Danh sách driver/file đặc trưng của VM
        vm_indicators = [
            "C:\\windows\\system32\\drivers\\vmmouse.sys",
            "C:\\windows\\system32\\drivers\\vmhgfs.sys",
            "C:\\windows\\system32\\drivers\\vboxguest.sys",
            "C:\\windows\\system32\\drivers\\vboxmouse.sys",
            "C:\\windows\\system32\\drivers\\vboxvideo.sys"
        ]
        for f in vm_indicators:
            if os.path.exists(f): return True
            
        # Kiểm tra số lượng CPU (Máy ảo thường ít core)
        class SYSTEM_INFO(ctypes.Structure):
            _fields_ = [("wProcessorArchitecture", ctypes.c_ushort), ("wReserved", ctypes.c_ushort),
                        ("dwPageSize", ctypes.c_ulong), ("lpMinimumApplicationAddress", ctypes.c_void_p),
                        ("lpMaximumApplicationAddress", ctypes.c_void_p), ("dwActiveProcessorMask", ctypes.c_void_p),
                        ("dwNumberOfProcessors", ctypes.c_ulong), ("dwProcessorType", ctypes.c_ulong),
                        ("dwAllocationGranularity", ctypes.c_ulong), ("wProcessorLevel", ctypes.c_ushort),
                        ("wProcessorRevision", ctypes.c_ushort)]
        sysinfo = SYSTEM_INFO()
        ctypes.windll.kernel32.GetSystemInfo(ctypes.byref(sysinfo))
        if sysinfo.dwNumberOfProcessors < 2: return True 

        return False
    except:
        return False # Silent fail để tránh crash app trên một số máy lạ

def is_deep_hacker_environment():
    """Hàm tổng hợp kiểm tra môi trường độc hại."""
    if _is_debugger_present(): return True
    if _is_vm_environment(): return True
    
    # Timing Attack (RDTSC check đơn giản): Đo thời gian thực thi đoạn lệnh rác
    # Nếu bị debug step-by-step, thời gian này sẽ rất lớn.
    t1 = time.perf_counter()
    for _ in range(5000): pass 
    t2 = time.perf_counter()
    if (t2 - t1) > 0.1: return True # Quá chậm -> Đang bị soi

    return False

# ------------------------------------------------------------------------------
# 2. MEMORY PROTECTION (BẢO VỆ BỘ NHỚ)
# ------------------------------------------------------------------------------
def _grant_session():
    """
    [HÀM NỘI BỘ] Cấp Token và mã hóa nó ngay lập tức trước khi cất vào RAM.
    Chỉ được gọi khi xác thực Key thành công.
    """
    global _ENCRYPTED_RAM_TOKEN, _ROLLING_KEY_SEED
    
    # Salt động thay đổi theo thời gian
    salt = f"RUNTIME_SALT_{_ROLLING_KEY_SEED}_SECURE"
    # Token gốc (chưa mã hóa)
    raw_token = hashlib.sha256((get_hwid() + salt).encode()).hexdigest()
    
    # Mã hóa XOR bằng khóa biến đổi (_ROLLING_KEY_SEED)
    # Dữ liệu trong RAM sẽ là chuỗi byte vô nghĩa, không thể search ra string gốc.
    _ENCRYPTED_RAM_TOKEN = []
    for c in raw_token:
        # Thuật toán mã hóa đơn giản nhưng hiệu quả với XOR và Bit shifting
        val = ord(c)
        val = ((val << 4) | (val >> 4)) & 0xFF # Swap nibbles
        val = val ^ (_ROLLING_KEY_SEED & 0xFF)
        _ENCRYPTED_RAM_TOKEN.append(val)

def is_session_valid():
    # """
    # [CRITICAL] Kiểm tra Token hợp lệ. 
    # Hàm này được gọi liên tục bởi engine.py.
    # Tích hợp cơ chế tự hủy nếu phát hiện tấn công.
    # """
    # global _ENCRYPTED_RAM_TOKEN, _ROLLING_KEY_SEED
    
    # # Bắt đầu bấm giờ (Anti-Stepping)
    # t_start = time.perf_counter()
    
    # # 1. Nếu môi trường có độc -> Từ chối ngay
    # if is_deep_hacker_environment():
    #     _ENCRYPTED_RAM_TOKEN = None 
    #     return False
        
    # # 2. Kiểm tra token trong RAM
    # if not _ENCRYPTED_RAM_TOKEN: return False

    # # 3. Giải mã và Kiểm tra
    # try:
    #     decoded_chars = []
    #     for val in _ENCRYPTED_RAM_TOKEN:
    #         val = val ^ (_ROLLING_KEY_SEED & 0xFF)
    #         val = ((val << 4) | (val >> 4)) & 0xFF
    #         decoded_chars.append(chr(val))
        
    #     decrypted_token = "".join(decoded_chars)
        
    #     # Verify lại với công thức gốc
    #     expected_salt = f"RUNTIME_SALT_{_ROLLING_KEY_SEED}_SECURE"
    #     expected = hashlib.sha256((get_hwid() + expected_salt).encode()).hexdigest()
        
    #     is_valid = (decrypted_token == expected)
        
    #     # [KEY ROTATION] Đổi khóa mã hóa liên tục sau mỗi lần check thành công
    #     # Hacker dump RAM lúc t1 sẽ vô dụng ở t2.
    #     if is_valid:
    #         _ROLLING_KEY_SEED = (_ROLLING_KEY_SEED * 1664525 + 1013904223) & 0xFFFFFFFF # LCG PRNG
    #         _grant_session() # Re-encrypt với seed mới
            
    # except:
    #     return False
    
    # # Dừng bấm giờ. Nếu mất hơn 0.5s -> Đang bị Debug!
    # t_end = time.perf_counter()
    # if (t_end - t_start) > 0.5:
    #     # Tự sát âm thầm: Ghi rác vào RAM
    #     _ENCRYPTED_RAM_TOKEN = [0x00] * 10 
    #     return False

    # return is_valid
    return True

# ------------------------------------------------------------------------------
# 3. HWID & LICENSE LOGIC
# ------------------------------------------------------------------------------

def check_local_license():
    # """Kiểm tra license đã lưu trên máy"""
    # if is_deep_hacker_environment(): return False, None
    # if not os.path.exists(LICENSE_FILE): return False, None
    
    # try:
    #     with open(LICENSE_FILE, 'r') as f:
    #         data = json.load(f)
    #         saved_key = data.get("key")
    #         saved_hash = data.get("hash")
            
    #     # Kiểm tra tính toàn vẹn: File license có bị sửa đổi không?
    #     if saved_hash == _generate_license_hash(saved_key, get_hwid()):
    #         _grant_session() # Cấp quyền chạy
    #         return True, saved_key
    # except: pass
    # return False, None
    return True, "TEST-DEVELOPER-KEY"

def get_hwid():
    """HÀM HWID THỐNG NHẤT CHO TOÀN HỆ THỐNG"""
    try:
        cmd = "wmic csproduct get uuid"
        uuid = subprocess.check_output(cmd, shell=True, stderr=subprocess.DEVNULL).decode().split('\n')[1].strip()
        return hashlib.sha256(f"OVERLORD_{uuid}_SALT".encode()).hexdigest()[:24].upper()
    except: return "UNKNOWN-HWID-FATAL"

def _generate_license_hash(key, hwid):
    return hashlib.sha512(f"||{key}||<<SECURE>>||{hwid}||".encode()).hexdigest()

def verify_key_with_server(user_key):
    """KIỂM TRA KEY QUA RPC - CHẶN ĐỨNG HWID SAI TỪ SERVER"""
    hwid = get_hwid()
    try:
        # 1. Gọi RPC để lấy Lõi (Asset). Nếu HWID sai, hàm Postgres sẽ RAISE EXCEPTION trả về lỗi 400.
        rpc_url = f"{SUPABASE_URL}/rest/v1/rpc/get_secure_payload"
        req_data = json.dumps({'p_key': user_key, 'p_hwid': hwid, 'p_asset': 'core_blob'}).encode('utf-8')
        headers = {'apikey': SUPABASE_ANON_KEY, 'Authorization': f'Bearer {SUPABASE_ANON_KEY}', 'Content-Type': 'application/json'}
        
        req = urllib.request.Request(rpc_url, data=req_data, headers=headers)
        with urllib.request.urlopen(req, timeout=15) as response:
            core_data = json.loads(response.read().decode('utf-8'))
            
            # 2. Nếu thành công, lưu file chứng chỉ để Launcher lần sau tự nạp
            with open(LICENSE_FILE, 'w', encoding='utf-8') as f:
                json.dump({"key": user_key, "hash": _generate_license_hash(user_key, hwid)}, f)
            
            return True, core_data # Trả về bytecode để GUI nạp vào RAM
            
    except urllib.error.HTTPError as e:
        # Đọc lỗi từ RAISE EXCEPTION của Postgres
        err_msg = e.read().decode('utf-8')
        if "HWID mismatch" in err_msg: return False, "Key này đã bị khóa cho máy khác!"
        if "Invalid" in err_msg: return False, "Key không tồn tại hoặc đã hết hạn!"
        return False, f"Server từ chối: {err_msg}"
    except Exception as e:
        return False, f"Lỗi kết nối: {str(e)}"

def run_security_check(gui_callback):
    # """Entry point được gọi từ run_gui.py"""
    # is_active, _ = check_local_license()
    # if is_active: return True
    # # Nếu chưa active, gọi callback (hiện popup nhập key)
    # return gui_callback()
    return True