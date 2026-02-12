import os
import shutil
import glob
import subprocess
import random
import string
import re
import base64
from setuptools import setup
from Cython.Build import cythonize

# ==============================================================================
# QUY TRÌNH CHỐNG HACK TỐI THƯỢNG - PIPELINE ĐÓNG GÓI TỰ ĐỘNG (V3.0)
# Nâng cấp: Mê Cung Gương + Mã hóa XOR Động + Đa Hình (Mã rác) + Hũ Mật (Honeypot)
# ==============================================================================

SOURCE_DIR = "app"
RELEASE_DIR = "app_release"

# Khóa mã hóa thay đổi ngẫu nhiên mỗi lần bấm Build
BUILD_XOR_KEY = random.randint(1, 255)

# Danh sách file lõi thật
SENSITIVE_FILES = [
    "core/engine.py",
    "core/security.py",       # File bảo mật vừa tạo
    "steps/s1_normalize.py",
    "steps/s2_demucs.py",
    "steps/s3_transcribe.py",
    "steps/s4_translate.py",
    "steps/s5_overlay.py",
    "steps/s6_mix.py",
    "services/ffmpeg_manager.py",
    "core/config_loader.py"
]
]

def generate_random_name(length=10):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))

def generate_junk_code():
    """Tạo ra các hàm Python rác, hợp lệ nhưng không làm gì cả để đổi mã Hash của file"""
    junk_funcs = ""
    for _ in range(random.randint(2, 5)):
        func_name = f"_O{generate_random_name(6)}"
        junk_funcs += f"\ndef {func_name}():\n    x = {random.randint(100, 999)}\n    y = '{generate_random_name()}'\n    return str(x) + y\n"
    return junk_funcs

def step_1_copy_source():
    print("🚀 BƯỚC 1: Tạo bản sao Source Code...")
    if os.path.exists(RELEASE_DIR):
        shutil.rmtree(RELEASE_DIR)
    shutil.copytree(SOURCE_DIR, RELEASE_DIR)

def step_1b_create_honeypots():
    """Tạo ra các file giả mạo chứa tên gọi kích thích để đánh lừa Hacker"""
    print("🚀 BƯỚC 1B: Rải 'Hũ mật' (Honeypots) đánh lạc hướng...")
    honeypot_names = ["license_generator.py", "premium_unlock.py", "bypass_auth.py"]
    core_dir = os.path.join(RELEASE_DIR, "core")
    os.makedirs(core_dir, exist_ok=True)
    
    for hp in honeypot_names:
        hp_path = os.path.join(core_dir, hp)
        with open(hp_path, "w", encoding="utf-8") as f:
            f.write("def unlock_premium():\n    return False\n\ndef get_admin_key():\n    pass\n")
            f.write(generate_junk_code())
        # Thêm file giả này vào danh sách cần mã hóa Cython luôn!
        SENSITIVE_FILES.append(f"core/{hp}")
        print(f"   [-] Đã rải hũ mật: {hp}")

def step_2_encrypt_strings_and_inject_junk():
    """Mã hóa XOR động và chèn mã rác Đa hình (Polymorphism)"""
    print("🚀 BƯỚC 2: Mã hóa XOR Động & Chèn mã rác Đa hình...")
    pattern = re.compile(r'SECRET\s*\(\s*(["\'])(.*?)\1\s*\)')
    count = 0
    
    for root, _, files in os.walk(RELEASE_DIR):
        for f in files:
            if f.endswith(".py"):
                file_path = os.path.join(root, f)
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()

                # 1. Mã hóa chuỗi bằng XOR
                def replacer(match):
                    nonlocal count
                    count += 1
                    raw_str = match.group(2)
                    
                    # XOR từng ký tự với BUILD_XOR_KEY sau đó Encode Base64
                    xor_bytes = bytes([ord(c) ^ BUILD_XOR_KEY for c in raw_str])
                    b64_encoded = base64.b64encode(xor_bytes).decode('utf-8')
                    
                    # Code giải mã (sẽ chạy lúc App thực thi)
                    return f"(''.join(chr(b ^ {BUILD_XOR_KEY}) for b in __import__('base64').b64decode(b'{b64_encoded}')))"

                content = pattern.sub(replacer, content)
                
                # 2. Chèn mã rác (Junk code) vào đầu file để thay đổi cấu trúc
                if file_path.replace("\\", "/").endswith(tuple(SENSITIVE_FILES)):
                    content = generate_junk_code() + "\n" + content

                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(content)
                        
    print(f"   [-] Đã mã hóa {count} chuỗi bằng XOR Key [{BUILD_XOR_KEY}]")
    print(f"   [-] Đã chèn mã rác (Polymorphism) vào các file nhạy cảm.")

def step_3_dynamic_rename():
    print("🚀 BƯỚC 3: Khởi tạo 'Mê cung gương' (Dynamic Rename)...")
    mapping = {}
    new_target_files = []

    for rel_path in SENSITIVE_FILES:
        old_path = os.path.join(RELEASE_DIR, rel_path)
        if os.path.exists(old_path):
            old_dir = os.path.dirname(old_path)
            old_filename = os.path.basename(old_path)
            old_module = old_filename.replace(".py", "")

            new_module = f"sys_{generate_random_name(12)}"
            new_filename = new_module + ".py"
            new_path = os.path.join(old_dir, new_filename)

            os.rename(old_path, new_path)
            mapping[old_module] = new_module
            new_target_files.append(new_path)
            print(f"   [-] Đã ngụy trang: {old_filename} ---> {new_filename}")

    # Fix Imports
    for root, _, files in os.walk(RELEASE_DIR):
        for f in files:
            if f.endswith(".py"):
                file_path = os.path.join(root, f)
                with open(file_path, 'r', encoding='utf-8') as file:
                    content = file.read()
                
                for old_mod, new_mod in mapping.items():
                    content = re.sub(rf'(\bfrom\s+([\w\.]+\.)?){old_mod}\b', rf'\g<1>{new_mod}', content)
                    content = re.sub(rf'(\bimport\s+([\w\.]+\.)?){old_mod}\b', rf'\g<1>{new_mod}', content)
                
                with open(file_path, 'w', encoding='utf-8') as file:
                    file.write(content)

    return new_target_files

def step_4_cythonize(target_files):
    print("🚀 BƯỚC 4: Biên dịch Cython ép thành Binary (.pyd)...")
    if not target_files:
        return

    setup(
        ext_modules=cythonize(
            target_files,
            compiler_directives={'language_level': "3"},
            quiet=True
        ),
        script_args=["build_ext", "--inplace"]
    )

def step_5_cleanup(target_files):
    print("🚀 BƯỚC 5: Dọn dẹp & Xóa dấu vết source code...")
    if os.path.exists("build"): shutil.rmtree("build")
        
    for py_file in target_files:
        if os.path.exists(py_file): os.remove(py_file)
            
    for c_file in glob.glob(f"{RELEASE_DIR}/**/*.c", recursive=True):
        os.remove(c_file)

def step_6_build_launcher():
    print("🚀 BƯỚC 6: Tự động Build Smart Launcher (Nuitka)...")
    if not os.path.exists("launcher.py"): return

    nuitka_cmd = (
        f"python -m nuitka --standalone --disable-console "
        f"--windows-icon-from-ico=app/assets/icon.ico "
        f"--output-dir=dist launcher.py"
    )
    subprocess.run(nuitka_cmd, shell=True)

if __name__ == "__main__":
    print("\n" + "="*60)
    print("🔥 BẮT ĐẦU PIPELINE ĐÓNG GÓI CHỐNG HACK TỐI THƯỢNG (V3.0) 🔥")
    print("="*60)
    
    step_1_copy_source()
    step_1b_create_honeypots()
    step_2_encrypt_strings_and_inject_junk()
    new_files = step_3_dynamic_rename()
    step_4_cythonize(new_files)
    step_5_cleanup(new_files)
    step_6_build_launcher()
    
    print("\n" + "="*60)
    print("✅ HOÀN TẤT TẠO BẢN PHÂN PHỐI SIÊU BẢO MẬT!")
    print("="*60)