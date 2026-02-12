# clean_source.py
import os
import glob

# Các file đã biên dịch sang pyd
targets = [
    # "app/core/engine",
    # "app/core/security",       # File bảo mật vừa tạo
    # "app/steps/s1_normalize",
    # "app/steps/s2_demucs",
    # "app/steps/s3_transcribe",
    # "app/steps/s4_translate",
    # "app/steps/s5_overlay",
    # "app/steps/s6_mix",
    # "app/services/ffmpeg_manager",
    # "app/core/config_loader"
    "app/ui/main_window"
]

for target in targets:
    py_file = target + ".py"
    # Tìm file pyd tương ứng (tên có thể dài loằng ngoằng do Cython)
    pyd_files = glob.glob(target + "*.pyd")
    
    if os.path.exists(py_file) and pyd_files:
        print(f"Đang xóa source gốc: {py_file} (Đã có {pyd_files[0]})")
        os.remove(py_file)
    else:
        print(f"Giữ nguyên: {py_file} (Chưa biên dịch xong)")

print("Dọn dẹp hoàn tất! Source code đã được bảo vệ.")