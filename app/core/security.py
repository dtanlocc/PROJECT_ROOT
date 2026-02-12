import os
import sys
import subprocess
import hashlib
import urllib.request
import json
import ctypes
import time
import random

# ==============================================================================
# LÕI BẢO MẬT & XÁC THỰC - CẤP ĐỘ QUÂN SỰ (ANTI-REVERSE ENGINEERING)
# Tích hợp: Anti-Debug Deep, Anti-VM Deep, Timing Checks, Rolling Code Encryption
# ==============================================================================

LICENSE_FILE = "system.lic"
_ENCRYPTED_RAM_TOKEN = None  # Token bị băm nát trong RAM
_ROLLING_KEY_SEED = int(time.time() * 1000) % 999999 # Seed thay đổi mỗi lần chạy

# Hàm giả lập SECRET (sẽ bị tool build thay thế bằng mã hóa XOR)
def SECRET(s):
    return s

# ------------------------------------------------------------------------------
# NHÓM 1: CẢM BIẾN MÔI TRƯỜNG SÂU (DEEP ENV SENSORS)
# ------------------------------------------------------------------------------
def is_deep_hacker_environment():
    """Kiểm tra đa tầng: API, File, Timing, Hardware Specs"""
    try:
        # 1. API Cơ bản
        if ctypes.windll.kernel32.IsDebuggerPresent(): return True
        
        # 2. Check Remote Debugger
        is_remote = ctypes.c_bool(False)
        ctypes.windll.kernel32.CheckRemoteDebuggerPresent(ctypes.windll.kernel32.GetCurrentProcess(), ctypes.byref(is_remote))
        if is_remote.value: return True

        # 3. Check Hardware Specs (Máy ảo thường yếu)
        # Lấy số core CPU
        class SYSTEM_INFO(ctypes.Structure):
            _fields_ = [("wProcessorArchitecture", ctypes.c_ushort), ("wReserved", ctypes.c_ushort),
                        ("dwPageSize", ctypes.c_ulong), ("lpMinimumApplicationAddress", ctypes.c_void_p),
                        ("lpMaximumApplicationAddress", ctypes.c_void_p), ("dwActiveProcessorMask", ctypes.c_void_p),
                        ("dwNumberOfProcessors", ctypes.c_ulong), ("dwProcessorType", ctypes.c_ulong),
                        ("dwAllocationGranularity", ctypes.c_ulong), ("wProcessorLevel", ctypes.c_ushort),
                        ("wProcessorRevision", ctypes.c_ushort)]
        sysinfo = SYSTEM_INFO()
        ctypes.windll.kernel32.GetSystemInfo(ctypes.byref(sysinfo))
        if sysinfo.dwNumberOfProcessors < 2: return True # Máy thật hiếm khi < 2 core

        # Lấy RAM
        class MEMORYSTATUSEX(ctypes.Structure):
            _fields_ = [("dwLength", ctypes.c_ulong), ("dwMemoryLoad", ctypes.c_ulong),
                        ("ullTotalPhys", ctypes.c_ulonglong), ("ullAvailPhys", ctypes.c_ulonglong),
                        ("ullTotalPageFile", ctypes.c_ulonglong), ("ullAvailPageFile", ctypes.c_ulonglong),
                        ("ullTotalVirtual", ctypes.c_ulonglong), ("ullAvailVirtual", ctypes.c_ulonglong),
                        ("ullAvailExtendedVirtual", ctypes.c_ulonglong)]
        mem = MEMORYSTATUSEX()
        mem.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(mem))
        if mem.ullTotalPhys / (1024**3) < 2.0: return True # Máy thật hiếm khi < 2GB RAM

        # 4. Check Blacklisted Drivers & DLLs (Sandboxie, Wireshark, etc)
        # (Cần lấy list modules đang load, ở đây demo check file driver)
        vm_drivers = [
            "C:\\windows\\system32\\drivers\\vmmouse.sys",
            "C:\\windows\\system32\\drivers\\vmhgfs.sys",
            "C:\\windows\\system32\\drivers\\vboxguest.sys",
            "C:\\windows\\system32\\drivers\\vboxmouse.sys",
            "C:\\windows\\system32\\drivers\\vboxvideo.sys"
        ]
        for d in vm_drivers:
            if os.path.exists(d): return True

        # 5. Timing Attack (RDTSC) - Đo chu kỳ CPU cực nhanh
        # Nếu đang chạy trong VM hoặc bị Debug, khoảng cách giữa 2 lần đo sẽ rất lớn
        t1 = time.perf_counter()
        for _ in range(5000): pass # Loop rác
        t2 = time.perf_counter()
        if (t2 - t1) > 0.1: return True # Quá chậm -> Đang bị soi

        return False
    except:
        return False # Silent fail để không crash

# ------------------------------------------------------------------------------
# NHÓM 2: BẢO VỆ RAM BIẾN ĐỔI (ROLLING CODE ENCRYPTION)
# ------------------------------------------------------------------------------
def _custom_hash(data, seed):
    """Hàm băm tự chế để hacker không đoán được thuật toán chuẩn"""
    res = 0
    for c in data:
        res = (res * seed + ord(c)) & 0xFFFFFFFF
    return hex(res)[2:]

def _grant_session():
    """Tạo Token và mã hóa nó bằng Rolling Key"""
    global _ENCRYPTED_RAM_TOKEN, _ROLLING_KEY_SEED
    
    salt = "ROLLING_SALT_" + str(_ROLLING_KEY_SEED)
    raw_token = hashlib.sha256((get_hwid() + salt).encode()).hexdigest()
    
    # Mã hóa: Đảo bit + XOR với Seed động
    # Mỗi lần gọi hàm check, Seed sẽ thay đổi, Token trong RAM cũng đổi theo!
    _ENCRYPTED_RAM_TOKEN = []
    for c in raw_token:
        val = ord(c)
        val = ((val << 4) | (val >> 4)) & 0xFF # Swap nibbles
        val = val ^ (_ROLLING_KEY_SEED & 0xFF)
        _ENCRYPTED_RAM_TOKEN.append(val)

def is_session_valid():
    """
    Check Token và TỰ ĐỘNG XOAY KHÓA (Key Rotation) sau mỗi lần check.
    Hacker dump RAM lúc này, 1 giây sau Key đã đổi, Dump vô dụng.
    """
    global _ENCRYPTED_RAM_TOKEN, _ROLLING_KEY_SEED
    
    # Bẫy thời gian chặt chẽ
    t_start = time.perf_counter()
    
    if is_deep_hacker_environment():
        _ENCRYPTED_RAM_TOKEN = None
        return False
        
    if not _ENCRYPTED_RAM_TOKEN: return False

    # 1. Giải mã bằng Seed hiện tại
    try:
        decoded_chars = []
        for val in _ENCRYPTED_RAM_TOKEN:
            val = val ^ (_ROLLING_KEY_SEED & 0xFF)
            val = ((val << 4) | (val >> 4)) & 0xFF
            decoded_chars.append(chr(val))
        
        decrypted_token = "".join(decoded_chars)
        
        # 2. Verify
        expected_salt = "ROLLING_SALT_" + str(_ROLLING_KEY_SEED)
        expected = hashlib.sha256((get_hwid() + expected_salt).encode()).hexdigest()
        is_valid = (decrypted_token == expected)
        
        # 3. [QUAN TRỌNG] KEY ROTATION: Đổi Seed mới và Mã hóa lại Token ngay lập tức
        if is_valid:
            _ROLLING_KEY_SEED = (_ROLLING_KEY_SEED * 1103515245 + 12345) & 0x7FFFFFFF # LCG Algorithm
            _grant_session() # Sinh lại _ENCRYPTED_RAM_TOKEN mới với Seed mới
            
    except:
        return False
        
    t_end = time.perf_counter()
    if (t_end - t_start) > 0.2: # Nếu giải mã + xoay key mất quá 0.2s -> Debugger detected
        _ENCRYPTED_RAM_TOKEN = [0xFF] * 10 # Corrupt memory
        return False

    return is_valid

# ------------------------------------------------------------------------------
# CÁC HÀM CƠ BẢN (HWID & LICENSE)
# ------------------------------------------------------------------------------
def get_hwid():
    try:
        # Thêm check GPU vào HWID để chặt chẽ hơn (Nếu có)
        try:
            cmd_gpu = "wmic path win32_VideoController get pnpdeviceid"
            gpu = subprocess.check_output(cmd_gpu, shell=True, stderr=subprocess.DEVNULL).decode().split('\n')[1].strip()
        except: gpu = "NO_GPU"

        cmd_uuid = "wmic csproduct get uuid"
        uuid = subprocess.check_output(cmd_uuid, shell=True, stderr=subprocess.DEVNULL).decode().split('\n')[1].strip()
        
        cmd_hdd = "wmic diskdrive get serialnumber"
        hdd = subprocess.check_output(cmd_hdd, shell=True, stderr=subprocess.DEVNULL).decode().split('\n')[1].strip()
        
        raw_hwid = f"{uuid}-{gpu}-{hdd}-HARDCORE_SALT"
        return hashlib.sha256(raw_hwid.encode()).hexdigest()[:24].upper()
    except:
        return "UNKNOWN-HWID-ERR"

def generate_local_license_hash(key, hwid):
    # Dùng SHA512 + Salt phức tạp hơn
    raw = f"||{key}||<<SUPER_SECURE>>||{hwid}||"
    return hashlib.sha512(raw.encode()).hexdigest()

def check_local_license():
    if is_deep_hacker_environment(): return False, None
    if not os.path.exists(LICENSE_FILE): return False, None
    try:
        with open(LICENSE_FILE, 'r') as f:
            data = json.load(f)
            saved_key = data.get("key")
            saved_hash = data.get("hash")
        if saved_hash == generate_local_license_hash(saved_key, get_hwid()):
            _grant_session()
            return True, saved_key
    except: pass
    return False, None

def verify_key_with_server(user_key):
    if is_deep_hacker_environment():
        return False, "Môi trường không an toàn (VM/Debug)."
    
    hwid = get_hwid()
    # Test Mode logic (Xóa khi build thật)
    if user_key.startswith("VIP-"):
        with open(LICENSE_FILE, 'w') as f:
            json.dump({"key": user_key, "hash": generate_local_license_hash(user_key, hwid)}, f)
        _grant_session()
        return True, "Kích hoạt thành công!"
    else:
        return False, "Key sai."

def run_security_check(gui_callback):
    is_active, _ = check_local_license()
    if is_active: return True
    return gui_callback()