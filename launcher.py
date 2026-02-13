import os
import sys
import subprocess

# ==============================================================================
# SMART LAUNCHER - TRÌNH KHỞI CHẠY THÔNG MINH
# ==============================================================================

def main():
    # 1. Xác định thư mục gốc của ứng dụng
    if getattr(sys, 'frozen', False):
        # Nếu đang chạy file .exe đã đóng gói (Nuitka)
        base_dir = os.path.dirname(sys.executable)
    else:
        # Nếu đang chạy file script .py
        base_dir = os.path.dirname(os.path.abspath(__file__))

    # 2. Xác định đường dẫn Python trong venv
    # Giả định thư mục venv nằm ngay cạnh launcher
    venv_python = os.path.join(base_dir, "venv", "Scripts", "python.exe")
    
    # 3. Xác định file chạy chính
    if os.path.exists(os.path.join(base_dir, "run_gui.exe")):
        # Ưu tiên chạy file EXE đã build nếu có (Giai đoạn 2)
        target_cmd = [os.path.join(base_dir, "run_gui.exe")]
    else:
        # Chạy file script Python (Giai đoạn 1 - Dev)
        script_path = os.path.join(base_dir, "run_gui.py")
        target_cmd = [venv_python, script_path]

    # 4. Kiểm tra môi trường (Chống lỗi sơ đẳng)
    if not os.path.exists(target_cmd[0]) and target_cmd[0].endswith(".exe"):
         # Trường hợp gọi python.exe nhưng không thấy file
         import ctypes
         ctypes.windll.user32.MessageBoxW(0, "Không tìm thấy môi trường Python (venv)!\nVui lòng chạy file Setup để cài đặt.", "Lỗi Hệ Thống", 16)
         sys.exit(1)

    # 5. Cấu hình chạy ẩn Console (Chỉ trên Windows)
    startupinfo = None
    if os.name == 'nt':
        startupinfo = subprocess.STARTUPINFO()
        startupinfo.dwFlags |= subprocess.STARTF_USESHOWWINDOW
        startupinfo.wShowWindow = 0 # SW_HIDE (Ẩn cửa sổ đen)

    # 6. THỰC THI
    try:
        # cwd=base_dir: Quan trọng! Đảm bảo lệnh import app... hoạt động đúng
        subprocess.run(target_cmd, cwd=base_dir, startupinfo=startupinfo)
    except Exception as e:
        import ctypes
        ctypes.windll.user32.MessageBoxW(0, f"Lỗi khởi động:\n{str(e)}", "Fatal Error", 16)

if __name__ == "__main__":
    main()