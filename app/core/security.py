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
    """
    [CRITICAL] Kiểm tra Token hợp lệ. 
    Hàm này được gọi liên tục bởi engine.py.
    Tích hợp cơ chế tự hủy nếu phát hiện tấn công.
    """
    global _ENCRYPTED_RAM_TOKEN, _ROLLING_KEY_SEED
    
    # Bắt đầu bấm giờ (Anti-Stepping)
    t_start = time.perf_counter()
    
    # 1. Nếu môi trường có độc -> Từ chối ngay
    if is_deep_hacker_environment():
        _ENCRYPTED_RAM_TOKEN = None 
        return False
        
    # 2. Kiểm tra token trong RAM
    if not _ENCRYPTED_RAM_TOKEN: return False

    # 3. Giải mã và Kiểm tra
    try:
        decoded_chars = []
        for val in _ENCRYPTED_RAM_TOKEN:
            val = val ^ (_ROLLING_KEY_SEED & 0xFF)
            val = ((val << 4) | (val >> 4)) & 0xFF
            decoded_chars.append(chr(val))
        
        decrypted_token = "".join(decoded_chars)
        
        # Verify lại với công thức gốc
        expected_salt = f"RUNTIME_SALT_{_ROLLING_KEY_SEED}_SECURE"
        expected = hashlib.sha256((get_hwid() + expected_salt).encode()).hexdigest()
        
        is_valid = (decrypted_token == expected)
        
        # [KEY ROTATION] Đổi khóa mã hóa liên tục sau mỗi lần check thành công
        # Hacker dump RAM lúc t1 sẽ vô dụng ở t2.
        if is_valid:
            _ROLLING_KEY_SEED = (_ROLLING_KEY_SEED * 1664525 + 1013904223) & 0xFFFFFFFF # LCG PRNG
            _grant_session() # Re-encrypt với seed mới
            
    except:
        return False
    
    # Dừng bấm giờ. Nếu mất hơn 0.5s -> Đang bị Debug!
    t_end = time.perf_counter()
    if (t_end - t_start) > 0.5:
        # Tự sát âm thầm: Ghi rác vào RAM
        _ENCRYPTED_RAM_TOKEN = [0x00] * 10 
        return False

    return is_valid

# ------------------------------------------------------------------------------
# 3. HWID & LICENSE LOGIC
# ------------------------------------------------------------------------------
def get_hwid():
    """Lấy HWID duy nhất, kết hợp Mainboard + HDD + GPU (nếu có)"""
    try:
        # UUID Mainboard
        cmd_uuid = "wmic csproduct get uuid"
        uuid = subprocess.check_output(cmd_uuid, shell=True, stderr=subprocess.DEVNULL).decode().split('\n')[1].strip()
        
        # Serial HDD
        cmd_hdd = "wmic diskdrive get serialnumber"
        hdd = subprocess.check_output(cmd_hdd, shell=True, stderr=subprocess.DEVNULL).decode().split('\n')[1].strip()
        
        # Thử lấy GPU ID (Optional)
        try:
            cmd_gpu = "wmic path win32_VideoController get pnpdeviceid"
            gpu = subprocess.check_output(cmd_gpu, shell=True, stderr=subprocess.DEVNULL).decode().split('\n')[1].strip()
        except: gpu = "NO_GPU"

        # Salt tĩnh để hacker không thể tự tính ra HWID dù biết thông số máy
        raw = f"{uuid}::{gpu}::{hdd}::HARDCORE_SALT_V1"
        return hashlib.sha256(raw.encode()).hexdigest()[:24].upper()
    except:
        return "UNKNOWN-HWID-ERR-001"

def _generate_license_hash(key, hwid):
    """Tạo chữ ký toàn vẹn cho file license"""
    raw = f"||{key}||<<SECURE>>||{hwid}||"
    return hashlib.sha512(raw.encode()).hexdigest()

def check_local_license():
    """Kiểm tra license đã lưu trên máy"""
    if is_deep_hacker_environment(): return False, None
    if not os.path.exists(LICENSE_FILE): return False, None
    
    try:
        with open(LICENSE_FILE, 'r') as f:
            data = json.load(f)
            saved_key = data.get("key")
            saved_hash = data.get("hash")
            
        # Kiểm tra tính toàn vẹn: File license có bị sửa đổi không?
        if saved_hash == _generate_license_hash(saved_key, get_hwid()):
            _grant_session() # Cấp quyền chạy
            return True, saved_key
    except: pass
    return False, None

def verify_key_with_server(user_key):
    """
    Xác thực Key (Online hoặc Offline giả lập).
    URL API được bọc trong SECRET() để tool build tự động mã hóa.
    """
    if is_deep_hacker_environment():
        return False, "Hệ thống phát hiện môi trường không an toàn (VM/Debug)."
    
    hwid = get_hwid()
    
    # --- LOGIC TEST (Khi chưa có Server thật) ---
    # Key test: Bắt đầu bằng VIP-
    if user_key.startswith("VIP-"):
        # Giả lập server trả về OK
        with open(LICENSE_FILE, 'w') as f:
            json.dump({"key": user_key, "hash": _generate_license_hash(user_key, hwid)}, f)
        _grant_session()
        return True, "Kích hoạt thành công (Local Test)!"
    # --------------------------------------------

    # --- LOGIC CALL API THẬT (Production) ---
    # api_url = SECRET("https://api.cuaban.com/verify-license")
    # payload = json.dumps({"license_key": user_key, "hwid": hwid}).encode('utf-8')
    # ... (Code gọi API như cũ) ...
    
    return False, "Key không hợp lệ."

def run_security_check(gui_callback):
    """Entry point được gọi từ run_gui.py"""
    is_active, _ = check_local_license()
    if is_active: return True
    # Nếu chưa active, gọi callback (hiện popup nhập key)
    return gui_callback()