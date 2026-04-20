import datetime
import os
import subprocess
import hashlib
import urllib.request
import json
import ctypes
import time
import threading
import base64
from cryptography.fernet import Fernet, InvalidToken
from dateutil import parser as dateutil_parser

# ==============================================================================
# CONFIG
# ==============================================================================
LICENSE_FILE = "system.lic"
EDGE_FUNC_URL = "https://gfihmymecoykcogqykbl.supabase.co/functions/v1/verify-license"

# ==============================================================================
# GLOBAL STATE (đã tối ưu)
# ==============================================================================
_CACHED_HWID = None
_ENCRYPTED_RAM_TOKEN = None
_ROLLING_KEY_SEED = int(time.time() * 1000) % 999999
_SESSION_EXPIRES_AT = None          # Luôn là UTC aware hoặc None
_LAST_ENV_CHECK = 0.0
_LAST_ENV_RESULT = False

# ==============================================================================
# HELPER: XỬ LÝ THỜI GIAN (FIX LỖI CHÍNH)
# ==============================================================================
def _parse_expires(expires_str: str):
    """Luôn trả về UTC aware hoặc None (PERMANENT)"""
    if not expires_str or expires_str == "PERMANENT_NO_EXPIRY_OVERLORD":
        return None
    dt = dateutil_parser.isoparse(expires_str)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=datetime.timezone.utc)
    return dt.astimezone(datetime.timezone.utc)

def _is_expired(expires_at):
    """So sánh chuẩn UTC"""
    if not expires_at:
        return False
    now_utc = datetime.datetime.now(datetime.timezone.utc)
    return now_utc > expires_at

# ==============================================================================
# 1. HWID (giữ nguyên, ổn định)
# ==============================================================================
def _get_raw_hwid_components() -> str:
    parts = []
    try:
        out = subprocess.check_output("wmic csproduct get uuid", shell=True, stderr=subprocess.DEVNULL).decode()
        parts.append(out.split('\n')[1].strip())
    except:
        parts.append("MB_UNKNOWN")
    try:
        out = subprocess.check_output("wmic cpu get ProcessorId", shell=True, stderr=subprocess.DEVNULL).decode()
        parts.append(out.split('\n')[1].strip())
    except:
        parts.append("CPU_UNKNOWN")
    try:
        out = subprocess.check_output("wmic diskdrive get SerialNumber", shell=True, stderr=subprocess.DEVNULL).decode()
        parts.append(out.split('\n')[1].strip())
    except:
        parts.append("DISK_UNKNOWN")
    return "|".join(parts)

def get_hwid() -> str:
    global _CACHED_HWID
    if _CACHED_HWID:
        return _CACHED_HWID
    raw = _get_raw_hwid_components()
    _CACHED_HWID = hashlib.sha256(f"OVERLORD_{raw}_SALT".encode()).hexdigest()[:32].upper()
    return _CACHED_HWID

# ==============================================================================
# 2. ANTI-DEBUG, ANTI-VM, ANTI-PROCESS
# ==============================================================================
# Danh sách process của các tool reverse engineering phổ biến
_SUSPICIOUS_PROCESSES = {
    "x64dbg.exe", "x32dbg.exe", "ollydbg.exe", "windbg.exe",
    "idaq.exe", "idaq64.exe",       # IDA Pro
    "dnspy.exe",                     # dnSpy
    "de4dot.exe",                    # .NET deobfuscator
    "cheatengine.exe", "cheatengine-x86_64.exe",
    "processhacker.exe", "procmon.exe", "procmon64.exe",
    "wireshark.exe",
    "fiddler.exe", "fiddler4.exe",
    "charles.exe",
    "httpdebugger.exe",                # Có thể remove nếu bạn ship dạng exe
}

def _is_debugger_present() -> bool:
    try:
        if ctypes.windll.kernel32.IsDebuggerPresent():
            return True
        is_remote = ctypes.c_bool(False)
        ctypes.windll.kernel32.CheckRemoteDebuggerPresent(
            ctypes.windll.kernel32.GetCurrentProcess(),
            ctypes.byref(is_remote)
        )
        if is_remote.value:
            return True
        # NtQueryInformationProcess — chống ScyllaHide
        nt      = ctypes.windll.ntdll.NtQueryInformationProcess
        handle  = ctypes.windll.kernel32.GetCurrentProcess()
        dbg_port = ctypes.c_ulong(0)
        nt(handle, 7, ctypes.byref(dbg_port), ctypes.sizeof(dbg_port), None)
        if dbg_port.value != 0:
            return True
        return False
    except:
        return False

def _is_vm_environment() -> bool:
    try:
        for f in [
            "C:\\windows\\system32\\drivers\\vmmouse.sys",
            "C:\\windows\\system32\\drivers\\vmhgfs.sys",
            "C:\\windows\\system32\\drivers\\vboxguest.sys",
            "C:\\windows\\system32\\drivers\\vboxmouse.sys",
            "C:\\windows\\system32\\drivers\\vboxvideo.sys",
        ]:
            if os.path.exists(f):
                return True

        class SYSTEM_INFO(ctypes.Structure):
            _fields_ = [
                ("wProcessorArchitecture",      ctypes.c_ushort),
                ("wReserved",                   ctypes.c_ushort),
                ("dwPageSize",                  ctypes.c_ulong),
                ("lpMinimumApplicationAddress", ctypes.c_void_p),
                ("lpMaximumApplicationAddress", ctypes.c_void_p),
                ("dwActiveProcessorMask",       ctypes.c_void_p),
                ("dwNumberOfProcessors",        ctypes.c_ulong),
                ("dwProcessorType",             ctypes.c_ulong),
                ("dwAllocationGranularity",     ctypes.c_ulong),
                ("wProcessorLevel",             ctypes.c_ushort),
                ("wProcessorRevision",          ctypes.c_ushort),
            ]
        si = SYSTEM_INFO()
        ctypes.windll.kernel32.GetSystemInfo(ctypes.byref(si))
        # Nâng ngưỡng lên 2 thay vì 1 để ít false positive hơn
        if si.dwNumberOfProcessors < 2:
            return True
        return False
    except:
        return False

def _is_suspicious_process_running() -> bool:
    """Kiểm tra có tool reverse engineering nào đang chạy không."""
    try:
        out = subprocess.check_output(
            "tasklist /FO CSV /NH",
            shell=True, stderr=subprocess.DEVNULL
        ).decode(errors='ignore').lower()
        for proc in _SUSPICIOUS_PROCESSES:
            if proc.lower() in out:
                return True
        return False
    except:
        return False

def is_deep_hacker_environment() -> bool:
    global _LAST_ENV_CHECK, _LAST_ENV_RESULT
    now = time.time()
    if now - _LAST_ENV_CHECK < 60:
        return _LAST_ENV_RESULT
    result = (_is_debugger_present() or _is_vm_environment() or _is_suspicious_process_running())
    _LAST_ENV_CHECK = now
    _LAST_ENV_RESULT = result
    return result

# ==============================================================================
# 3. FERNET LICENSE FILE
# ==============================================================================
def _derive_fernet_key(hwid: str) -> bytes:
    """Tạo Fernet key 32 bytes deterministic từ HWID."""
    raw = hashlib.sha256(
        f"FERNET_DERIVE_{hwid}_OVERLORD_V2".encode()
    ).digest()
    return base64.urlsafe_b64encode(raw)

def _generate_license_hash(key: str, hwid: str, expires_at=None) -> str:
    expiry = expires_at if expires_at else "PERMANENT_NO_EXPIRY_OVERLORD"
    return hashlib.sha512(
        f"||{key}||<<SECURE>>||{hwid}||{expiry}||".encode()
    ).hexdigest()

def _save_license(key: str, expires_at_str):
    hwid = get_hwid()
    data = {
        "key":        key,
        "hash":       _generate_license_hash(key, hwid, expires_at_str),
        "expires_at": expires_at_str,
    }
    raw     = json.dumps(data).encode()
    fernet  = Fernet(_derive_fernet_key(hwid))
    # Mỗi lần ghi → IV random → ciphertext khác nhau
    encrypted = fernet.encrypt(raw)
    with open(LICENSE_FILE, 'wb') as f:
        f.write(encrypted)

def _load_license():
    if not os.path.exists(LICENSE_FILE):
        return None
    try:
        with open(LICENSE_FILE, 'rb') as f:
            encrypted = f.read()
        if not encrypted:
            return None
        fernet = Fernet(_derive_fernet_key(get_hwid()))
        # Fernet tự verify HMAC — file bị sửa → InvalidToken
        raw = fernet.decrypt(encrypted)
        return json.loads(raw.decode())
    except (InvalidToken, Exception):
        # Sai HWID, file corrupt, hoặc bị giả mạo
        return None

# ==============================================================================
# 4. MEMORY PROTECTION - PHIÊN BẢN ĐƠN GIẢN & ỔN ĐỊNH
# ==============================================================================
_SESSION_EXPIRES_AT = None   # Khai báo global ở đây một lần

def _grant_session(expires_at_str=None):
    """Chỉ lưu expires_at dưới dạng UTC aware"""
    global _SESSION_EXPIRES_AT
    _SESSION_EXPIRES_AT = _parse_expires(expires_at_str)


def is_session_valid() -> bool:
    """Phiên bản siêu đơn giản - ít lỗi nhất"""
    global _SESSION_EXPIRES_AT

    if is_deep_hacker_environment():
        return False

    if _SESSION_EXPIRES_AT and _is_expired(_SESSION_EXPIRES_AT):
        _SESSION_EXPIRES_AT = None
        return False

    return True

# ==============================================================================
# 5. SESSION WATCHDOG
# ==============================================================================
class SessionWatchdog(threading.Thread):
    CHECK_INTERVAL = 5 * 60          # 5 phút (từ 2 phút → ít lag hơn)
    OFFLINE_TOLERANCE = 4            # chịu được 4 lần offline

    def __init__(self, shutdown_callback):
        super().__init__(daemon=True)
        self.shutdown_cb = shutdown_callback
        self.running = True
        self._offline_streak = 0

    def stop(self):
        self.running = False

    def run(self):
        while self.running:
            time.sleep(self.CHECK_INTERVAL)
            if not self.running:
                break
            self._recheck()

    def _recheck(self):
        global _SESSION_EXPIRES_AT

        # Kiểm tra hết hạn
        if _SESSION_EXPIRES_AT and _is_expired(_SESSION_EXPIRES_AT):
            self._kill("Key đã hết hạn!")
            return

        if _is_suspicious_process_running():
            self._kill("Phát hiện công cụ can thiệp!")
            return

        data = _load_license()
        if not data:
            self._kill("File license bị xóa hoặc hỏng!")
            return

        try:
            ok, result = verify_key_with_server(data.get("key"))
            if not ok:
                self._kill(f"Server từ chối: {result}")
                return
            
            # Cập nhật expires mới từ server
            if isinstance(result, dict) and result.get("expires"):
                _grant_session(result["expires"])
            self._offline_streak = 0
        except Exception:
            self._offline_streak += 1
            if self._offline_streak > self.OFFLINE_TOLERANCE:
                self._kill("Mất kết nối server quá lâu!")

    def _kill(self, reason):
        global _ENCRYPTED_RAM_TOKEN, _SESSION_EXPIRES_AT
        _ENCRYPTED_RAM_TOKEN = None
        _SESSION_EXPIRES_AT = None
        self.running = False
        try:
            self.shutdown_cb(reason)
        except:
            os._exit(1)

_watchdog: SessionWatchdog = None

def start_watchdog(shutdown_callback):
    global _watchdog
    if _watchdog and _watchdog.is_alive():
        _watchdog.stop()
    _watchdog = SessionWatchdog(shutdown_callback)
    _watchdog.start()

# ==============================================================================
# 6. PUBLIC API
# ==============================================================================
def check_local_license():
    if is_deep_hacker_environment():
        return False, "ENV_HACKER: Phát hiện môi trường không an toàn!"

    data = _load_license()
    if not data:
        return False, "LOAD_FAIL: Không tìm thấy hoặc không đọc được file system.lic!"

    try:
        saved_key = data.get("key")
        saved_hash = data.get("hash")
        saved_expires = data.get("expires_at")

        expected_hash = _generate_license_hash(saved_key, get_hwid(), saved_expires)
        if saved_hash != expected_hash:
            os.remove(LICENSE_FILE)
            return False, "HASH_FAIL: File license bị giả mạo!"

        exp_date = _parse_expires(saved_expires)
        if _is_expired(exp_date):
            os.remove(LICENSE_FILE)
            return False, "EXPIRY_FAIL: Key đã hết hạn!"

        _grant_session(saved_expires)   # gọi hàm mới
        return True, saved_key
    except Exception as e:
        return False, f"EXCEPTION: {str(e)}"


def verify_key_with_server(user_key: str):
    hwid = get_hwid()
    try:
        req_data = json.dumps({"p_key": user_key, "p_hwid": hwid}).encode('utf-8')
        req = urllib.request.Request(EDGE_FUNC_URL, data=req_data, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            res_data = json.loads(resp.read().decode('utf-8'))

        expires_str = res_data.get("expires") if isinstance(res_data, dict) else None
        core_data = res_data.get("data", res_data)

        _save_license(user_key, expires_str)
        _grant_session(expires_str)
        return True, {"core": core_data, "expires": expires_str}
    except urllib.error.HTTPError as e:
        err_msg = e.read().decode('utf-8')
        try:
            err_msg = json.loads(err_msg).get("error", err_msg)
        except:
            pass
        if "HWID mismatch" in err_msg: return False, "Key đã bị khóa cho máy khác!"
        if "expired" in err_msg: return False, "Key đã hết hạn!"
        if "Rate limit" in err_msg: return False, "Thử lại sau 1 phút!"
        return False, f"Server từ chối: {err_msg}"
    except Exception as e:
        return False, f"Lỗi kết nối: {str(e)}"


def run_security_check(gui_callback, shutdown_callback):
    is_active, msg = check_local_license()
    if is_active:
        start_watchdog(shutdown_callback)
        return True
    result = gui_callback()
    if result:
        start_watchdog(shutdown_callback)
    return result