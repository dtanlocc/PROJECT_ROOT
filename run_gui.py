import sys
import os
from pathlib import Path

# Thêm thư mục hiện tại vào sys.path để Python tìm thấy package 'app'
ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Chuyển thư mục làm việc về ROOT (để load config.yaml đúng)
os.chdir(ROOT)

if __name__ == "__main__":
    try:
        # Import GUI từ package app
        from app.ui.main_window import ProGUI
        
        app = ProGUI()
        app.mainloop()
        
    except ImportError as e:
        print(f"Lỗi Import: {e}")
        print("Hãy chắc chắn bạn đã cài đủ thư viện: pip install customtkinter loguru pydantic")
        input("Nhấn Enter để thoát...")
    except Exception as e:
        print(f"Lỗi Fatal: {e}")
        input("Nhấn Enter để thoát...")