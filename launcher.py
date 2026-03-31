#file: launcher.py
import os
import sys
import subprocess
import ctypes
import hashlib
import time
import threading
import traceback

# ==============================================================================
# SMART LAUNCHER V2 - OVERLORD APEX (Anti-Debug + Anti-Tamper + Robust)
# ==============================================================================

def is_debugger_present():
    """Kiểm tra debugger cơ bản (Windows)"""
    try:
        if ctypes.windll.kernel32.IsDebuggerPresent():
            return True
        # Kiểm tra PEB BeingDebugged flag (cách nâng cao hơn)
        kernel32 = ctypes.windll.kernel32
        GetCurrentProcess = kernel32.GetCurrentProcess
        IsWow64Process = kernel32.IsWow64Process
        # Có thể mở rộng thêm NtQueryInformationProcess nếu cần
        return False
    except:
        return False

def detect_suspicious_processes():
    """Kiểm tra các process debug/RE tool phổ biến"""
    try:
        suspicious = [
            "x64dbg", "x32dbg", "ida", "ida64", "ollydbg", "windbg", "ghidra",
            "dnspy", "fiddler", "wireshark", "procmon", "processhacker", "cheatengine"
        ]
        output = subprocess.check_output("tasklist /fo csv", shell=True, stderr=subprocess.DEVNULL).decode('utf-8', errors='ignore').lower()
        for tool in suspicious:
            if tool in output:
                return True
        return False
    except:
        return False

def anti_debug_thread():
    """Chạy liên tục trong background để phát hiện debug/tamper"""
    while True:
        try:
            if is_debugger_present() or detect_suspicious_processes():
                ctypes.windll.user32.MessageBoxW(0, "Phát hiện công cụ debug/reverse engineering!\nỨng dụng sẽ tự đóng.", "Bảo Vệ", 16)
                os._exit(1)
            
            # Time check chống debugger chậm (simple timing attack)
            start = time.perf_counter()
            for _ in range(500000):
                pass
            if time.perf_counter() - start > 0.08:  # Ngưỡng có thể điều chỉnh
                os._exit(1)
                
        except:
            pass
        time.sleep(1.5)  # Kiểm tra mỗi 1.5 giây

def show_error(msg, title="Lỗi Khởi Động"):
    try:
        ctypes.windll.user32.MessageBoxW(0, str(msg), title, 16)
    except:
        pass
    try:
        with open("crash_log.txt", "a", encoding="utf-8") as f:
            f.write(f"\n[{time.strftime('%Y-%m-%d %H:%M:%S')}] {title}\n{msg}\n")
    except:
        pass

def main():
    try:
        # 1. Xác định base directory
        if getattr(sys, 'frozen', False) or '__compiled__' in globals():
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        os.chdir(base_dir)  # Quan trọng: Đảm bảo đường dẫn tương đối đúng

        # 2. Khởi chạy Anti-Debug ngay từ đầu (multi-thread)
        threading.Thread(target=anti_debug_thread, daemon=True).start()

        # 3. Tìm Python trong venv
        venv_python = os.path.join(base_dir, "venv", "Scripts", "python.exe")

        # 4. Ưu tiên chạy file đã build (run_gui.exe hoặc .pyd launcher)
        if os.path.exists(os.path.join(base_dir, "run_gui.exe")):
            target_cmd = [os.path.join(base_dir, "run_gui.exe")]
        elif os.path.exists(os.path.join(base_dir, "Reup_Video_Pro.exe")):  # Tên exe Nuitka của bạn
            target_cmd = [os.path.join(base_dir, "Reup_Video_Pro.exe")]
        else:
            # Fallback: chạy script Python
            script_path = os.path.join(base_dir, "run_gui.py")
            if not os.path.exists(venv_python):
                show_error("Không tìm thấy venv!\nVui lòng chạy file Setup.exe để cài đặt môi trường.", "Thiếu Môi Trường")
                sys.exit(1)
            target_cmd = [venv_python, script_path]

        # 5. Kiểm tra file tồn tại
        if not os.path.exists(target_cmd[0]):
            show_error(f"Không tìm thấy file khởi chạy chính:\n{target_cmd[0]}", "Lỗi File")
            sys.exit(1)

        # 6. Chạy ẩn console hoàn toàn
        startupinfo = None
        if os.name == 'nt':
            startupinfo = subprocess.STARTUPINFO()
            startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            startupinfo.wShowWindow = 0  # SW_HIDE

        # 7. Thực thi
        result = subprocess.run(
            target_cmd,
            cwd=base_dir,
            startupinfo=startupinfo,
            capture_output=True,
            text=True,
            timeout=300  # Timeout 5 phút phòng treo
        )

        if result.returncode != 0:
            err = result.stderr or result.stdout or "Unknown error"
            show_error(f"Ứng dụng bị dừng bất thường (code {result.returncode}):\n{err[:800]}", "Ứng dụng Crash")

    except Exception as e:
        show_error(f"Lỗi launcher nghiêm trọng:\n{traceback.format_exc()}", "Launcher Fatal Error")
        sys.exit(1)

if __name__ == "__main__":
    main()