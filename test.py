import os
import ctypes

# Kiểm tra xem Windows có load được file không
dll_path = r"C:\Program Files (x86)\Reup_Pro\zlibwapi.dll"
try:
    ctypes.CDLL(dll_path)
    print("✅ Windows nạp zlibwapi thành công!")
except Exception as e:
    print(f"❌ Windows từ chối nạp zlibwapi. Lỗi: {e}")

# Xem các thư mục mà Windows đang tìm DLL
print("\nCác đường dẫn Windows đang tìm DLL:")
for path in os.environ['PATH'].split(';'):
    print(path)