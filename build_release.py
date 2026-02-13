import os
import shutil
import subprocess
import random
import ast
import base64
import time
import hashlib
import string
from setuptools import setup
from Cython.Build import cythonize

# ==============================================================================
# BUILD PIPELINE V7.0 - GOD-EYE SINGULARITY (MILITARY GRADE)
# Quy trình bảo mật tối tân: Import Hiding + Bit-Shuffling + Anti-Forensics
# ==============================================================================

SOURCE_DIR = "app"
RELEASE_DIR = "GodEye_Release"
BUILD_TEMP = "singularity_temp"

# File được tiêm bảo vệ mức cao nhất
SENSITIVE_FILES = [
    "app/core/security.py",      # Bảo mật bản quyền
    "app/core/engine.py",        # Luồng xử lý chính
    "app/core/config_loader.py", # Cấu hình hệ thống
    "app/services/ffmpeg_manager.py", # Thuật toán xử lý video
    "app/steps/s1_normalize.py"
    "app/steps/s2_demucs.py",    # Thuật toán tách âm
    "app/steps/s3_transcribe.py", # Thuật toán nhận diện tiếng nói
    "app/steps/s4_translate.py",  # Thuật toán dịch thuật
    "app/steps/s5_overlay.py",    # Thuật toán chèn sub
    "app/steps/s6_mix.py",        # Thuật toán mix final
    "app/ui/main_window.py",   # Giao diện người dùng chính
    "launcher.py",              # Entry point của CLI
    "run_gui.py"                 # Entry point của GUI
]

# ------------------------------------------------------------------------------
# 1. THUẬT TOÁN "SINGULARITY CIPHER" (S-BOX + DYNAMIC BIT SHUFFLE)
# ------------------------------------------------------------------------------
def singularity_encrypt(data: str, key: int) -> str:
    """Mã hóa kết hợp hoán vị bit và thay thế giá trị dựa trên ma trận động."""
    res = []
    state = key
    for char in data.encode('utf-8'):
        # LCG PRNG cập nhật trạng thái liên tục
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        s_box = (state >> 24) & 0xFF
        
        # Bước 1: XOR với trạng thái động
        val = char ^ s_box
        
        # Bước 2: Bit Shuffling (Hoán vị bit ngẫu nhiên dựa trên key)
        # Chuyển đổi vị trí bit để Decompiler không thể nhận diện phép toán
        shift_a = (key % 5) + 1
        shift_b = (key % 3) + 1
        val = ((val << shift_a) | (val >> (8 - shift_a))) & 0xFF
        val = val ^ ((val >> shift_b) | (val << (8 - shift_b))) & 0xFF
        
        res.append(val)
    return base64.b64encode(bytes(res)).decode('utf-8')

# Lõi giải mã Singularity - Được nhúng vào mọi file
DECRYPTOR_CORE = """
import base64 as _b64
def _s_dec(s, k):
    try:
        d = _b64.b64decode(s)
        r = []; st = k
        for v in d:
            st = (st * 1664525 + 1013904223) & 0xFFFFFFFF
            sb = (st >> 24) & 0xFF
            sa = (k % 5) + 1; sb_sh = (k % 3) + 1
            # Đảo ngược quy trình Bit Shuffling
            v = v ^ ((v >> sb_sh) | (v << (8 - sb_sh))) & 0xFF
            v = ((v >> sa) | (v << (8 - sa))) & 0xFF
            r.append(v ^ sb)
        return bytes(r).decode('utf-8')
    except: return ""

def _v_imp(m, k):
    # Hàm ẩn danh Import để che giấu thư viện hệ thống
    return __import__(_s_dec(m, k))
"""

# ------------------------------------------------------------------------------
# 2. ADVANCED SENTINEL (CHỐNG PHÁP Y KỸ THUẬT SỐ)
# ------------------------------------------------------------------------------
def generate_advanced_sentinel(key: int):
    """Sentinel thông minh: Phát hiện máy ảo, debugger và sandbox qua dấu vết hệ thống."""
    # Mã hóa các chuỗi nhạy cảm để hacker không search được string trong binary
    reg_path = singularity_encrypt("HARDWARE\\Description\\System\\CentralProcessor\\0", key)
    vm_files = [
        singularity_encrypt("C:\\windows\\system32\\drivers\\vmmouse.sys", key),
        singularity_encrypt("C:\\windows\\system32\\drivers\\vboxguest.sys", key)
    ]
    
    sentinel_code = f"""
def _guard():
    _ct = _v_imp('{singularity_encrypt("ctypes", key)}', {key})
    _os = _v_imp('{singularity_encrypt("os", key)}', {key})
    # 1. Check Debugger (WinAPI)
    if _ct.windll.kernel32.IsDebuggerPresent(): _os._exit(0)
    # 2. Check Sandbox/VM qua Registry
    try:
        _winreg = _v_imp('{singularity_encrypt("winreg", key)}', {key})
        k = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, _s_dec('{reg_path}', {key}))
        v, _ = _winreg.QueryValueEx(k, "ProcessorNameString")
        if "QEMU" in v or "VirtIO" in v: _os._exit(0)
    except: pass
    # 3. Check VM Drivers
    for f in [{', '.join([f"'{x}'" for x in vm_files])}]:
        if _os.path.exists(_s_dec(f, {key})): _os._exit(0)
_guard()
"""
    return sentinel_code

# ------------------------------------------------------------------------------
# 3. AST SINGULARITY TRANSFORMER
# ------------------------------------------------------------------------------
class SingularityObfuscator(ast.NodeTransformer):
    def __init__(self, seed):
        self.seed = seed
        self.key_mapping = {}

    def visit_Import(self, node):
        """Xóa bỏ các lệnh import tường minh."""
        return ast.Pass()

    def visit_ImportFrom(self, node):
        """Xóa bỏ các lệnh import from tường minh."""
        return ast.Pass()

    def visit_Constant(self, node):
        """Mã hóa mọi chuỗi hằng số."""
        if isinstance(node.value, str) and len(node.value) > 2:
            if node.value.startswith("__"): return node
            encrypted = singularity_encrypt(node.value, self.seed)
            return ast.Call(
                func=ast.Name(id='_s_dec', ctx=ast.Load()),
                args=[ast.Constant(value=encrypted), ast.Constant(value=self.seed)],
                keywords=[]
            )
        return node

# ------------------------------------------------------------------------------
# 4. MAIN BUILD PIPELINE
# ------------------------------------------------------------------------------
def step_info(msg):
    print(f"\n\033[92m[GOD-EYE-V7]\033[0m ➤ {msg}")

def main():
    t_start = time.time()
    
    # Chuẩn bị môi trường
    if os.path.exists(RELEASE_DIR): shutil.rmtree(RELEASE_DIR)
    if os.path.exists(BUILD_TEMP): shutil.rmtree(BUILD_TEMP)
    os.makedirs(os.path.join(RELEASE_DIR, "app"), exist_ok=True)
    
    shutil.copytree(SOURCE_DIR, os.path.join(BUILD_TEMP, "app"))
    for f in ["run_gui.py", "launcher.py"]:
        if os.path.exists(f): shutil.copy(f, os.path.join(BUILD_TEMP, f))

    # Obfuscation Stage
    step_info("Đang thực thi biến đổi Singularity (AST Obfuscation)...")
    all_files = []
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f.endswith(".py"): all_files.append(os.path.join(root, f))

    for path in all_files:
        rel = os.path.relpath(path, BUILD_TEMP).replace("\\", "/")
        is_sensitive = any(s in rel for s in SENSITIVE_FILES)
        
        with open(path, "r", encoding="utf-8") as f:
            source = f.read()

        try:
            tree = ast.parse(source)
            f_seed = random.randint(500000, 2000000)
            transformer = SingularityObfuscator(f_seed)
            new_tree = transformer.visit(tree)
            ast.fix_missing_locations(new_tree)
            processed_code = ast.unparse(new_tree)
        except Exception as e:
            processed_code = source

        # Lắp ráp lớp bảo vệ God-Eye
        final_code = DECRYPTOR_CORE + "\n"
        if is_sensitive:
            final_code += generate_advanced_sentinel(f_seed) + "\n"
        final_code += processed_code
        
        with open(path, "w", encoding="utf-8") as f:
            f.write(final_code)

    # Biên dịch Binary
    step_info("Biên dịch mã máy C-Level (.pyd)...")
    target_pys = []
    for root, _, files in os.walk(os.path.join(BUILD_TEMP, "app")):
        for f in files:
            if f.endswith(".py") and f != "__init__.py":
                target_pys.append(os.path.join(root, f))
    target_pys.append(os.path.join(BUILD_TEMP, "run_gui.py"))

    try:
        setup(
            ext_modules=cythonize(
                target_pys, 
                compiler_directives={'language_level': "3", 'always_allow_keywords': True, 'profile': False},
                quiet=True
            ),
            script_args=["build_ext", "--build-lib", RELEASE_DIR]
        )
    except Exception as e:
        print(f"❌ Lỗi biên dịch: {e}")

    # Đóng gói OneFile
    step_info("Nén 'God-Eye' vào file thực thi duy nhất (Nuitka)...")
    icon = os.path.join(SOURCE_DIR, "assets", "icon.ico")
    nuitka_cmd = [
        "python", "-m", "nuitka", "--standalone", "--disable-console",
        "--onefile", "--remove-output", "--lto=yes", "--jobs=4",
        f"--output-dir={RELEASE_DIR}",
        "--output-filename=AI_Reup_Pro_V7.exe",
        f"--windows-icon-from-ico={icon}" if os.path.exists(icon) else "",
        os.path.join(BUILD_TEMP, "launcher.py")
    ]
    subprocess.run([c for c in nuitka_cmd if c], check=True)

    # Finalize
    step_info("Hoàn tất cấu trúc bản thương mại...")
    final_app_path = os.path.join(RELEASE_DIR, "app")
    shutil.copytree(os.path.join(SOURCE_DIR, "assets"), os.path.join(final_app_path, "assets"), dirs_exist_ok=True)
    if os.path.exists("config.dist.yaml"):
        shutil.copy("config.dist.yaml", os.path.join(RELEASE_DIR, "config.yaml"))

    # Cleanup
    for trash in [BUILD_TEMP, "build"]:
        if os.path.exists(trash): shutil.rmtree(trash)

    duration = time.time() - t_start
    step_info(f"🚀 BUILD V7 THÀNH CÔNG! Tổng thời gian: {duration:.2f}s")
    print(f"📍 Sản phẩm: {os.path.abspath(RELEASE_DIR)}")

if __name__ == "__main__":
    main()