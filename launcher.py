import os
import sys
import subprocess

# ==============================================================================
# SMART LAUNCHER - TRÌNH KHỞI CHẠY THÔNG MINH
# Nhiệm vụ: Tìm môi trường venv và gọi App chính (ẩn Console)
# ==============================================================================

def main():
    # 1. Tìm thư mục gốc (nơi chứa file Launcher.exe)
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # 2. Đường dẫn tới Python bên trong venv
    # (Thư mục venv sẽ được Inno Setup tải về sau)
    python_exe = os.path.join(base_dir, "venv", "Scripts", "python.exe")
    
    # Đường dẫn tới file chạy chính (đã build hoặc script)
    # Ưu tiên chạy bản đã build (run_gui.exe hoặc pyd) nếu có, không thì chạy .py
    if os.path.exists(os.path.join(base_dir, "run_gui.exe")):
         main_script = os.path.join(base_dir, "run_gui.exe")
         # Nếu là exe thì gọi trực tiếp
         cmd = [main_script]
    else:
         main_script = os.path.join(base_dir, "run_gui.py")
         cmd = [python_exe, main_script]

    # 3. Kiểm tra môi trường
    # Nếu đang chạy dạng script (.py) mà không thấy python của venv -> Báo lỗi
    if not os.path.exists(python_exe) and main_script.endswith(".py"):
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, "Không tìm thấy môi trường (venv).\nVui lòng chạy Setup hoặc kiểm tra thư mục cài đặt!", "Lỗi Khởi Động", 16)
        sys.exit(1)

    # 4. CHẠY APP (Ẩn cửa sổ CMD)
    startupinfo = None
    if os.name == 'nt': # Chỉ áp dụng cho Windows
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE (Ẩn cửa sổ đen)

    try:
        # Gọi subprocess để chạy App độc lập
        subprocess.run(cmd, startupinfo=startupinfo)
    except Exception as e:
        print(f"Error launching app: {e}")
        input()

if __name__ == "__main__":
    main()