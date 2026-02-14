import os
import shutil
import subprocess
import random
import ast
import base64
import time
import string
import sys
import marshal
from setuptools import setup
from Cython.Build import cythonize

# ==============================================================================
# BUILD PIPELINE V48.0 - OVERLORD APEX (CLOUD-GHOST)
# Trạng thái: Ổn định (Dựa trên V46.1).
# Chức năng: Xuất file core_blob.enc để giấu lên Supabase. 
# Logic: EXE rỗng -> Tải linh hồn từ URL -> Nạp RAM -> Chạy App.
# ==============================================================================

SOURCE_DIR = "app"
ENTRY_GUI = "run_gui.py"
RELEASE_DIR = "Overlord_Apex_Release"
INSPECT_DIR = "Overlord_Source_Inspect"
BUILD_TEMP = "overlord_apex_temp"
VOID_ENTRY = "void_main_entry"
CORE_LIB_NAME = "_core_sys_x64" 

# URL TRỰC TIẾP ĐẾN FILE core_blob.enc TRÊN SUPABASE STORAGE CỦA BẠN
# Sau khi upload file core_blob.enc lên Supabase, hãy dán link Public URL vào đây.
CORE_API_URL = "https://supabase.com/dashboard/project/gfihmymecoykcogqykbl/storage/files/buckets/security/core_blob.enc"

# ------------------------------------------------------------------------------
# 1. ENCRYPTION ENGINE & CORE BYTECODE GENERATOR
# ------------------------------------------------------------------------------
def chaos_encrypt(data: str, key: int) -> str:
    res = []
    state = key
    b_data = data.encode('utf-8')
    for i, char in enumerate(b_data):
        state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        xor_key = (state >> 24) & 0xFF
        shift = (key + i) % 7 + 1
        val = char ^ xor_key
        val = ((val << shift) | (val >> (8 - shift))) & 0xFF
        val ^= (i & 0xFF)
        res.append(val)
    return base64.b64encode(bytes(res)).decode('utf-8')

def get_encrypted_core_bytecode(seed):
    junk_val1 = random.randint(0xFFFFF, 0xFFFFFF)
    junk_val2 = random.randint(0xFFFFF, 0xFFFFFF)
    target_xor = seed ^ junk_val1
    final_op_val = target_xor + junk_val2

    core_src = f"""
import base64 as _b
import marshal as _m
import types as _t
import sys, os, ctypes

_CACHE = {{}}

def _get_k():
    base = {final_op_val}
    return (base - {junk_val2}) ^ {junk_val1}

def _s(s):
    if not s: return ""
    if s in _CACHE: return _CACHE[s]
    try:
        k = _get_k()
        d = _b.b64decode(s); r = bytearray(); st = k
        for i, v in enumerate(d):
            st = (st * 1664525 + 1013904223) & 0xFFFFFFFF
            v ^= (i & 0xFF)
            sh = (k + i) % 7 + 1
            v = ((v >> sh) | (v << (8 - sh))) & 0xFF
            r.append(v ^ ((st >> 24) & 0xFF))
        res = r.decode('utf-8')
        _CACHE[s] = res
        return res
    except: return ""
"""
    bytecode = compile(core_src, '<ram_turbo_core>', 'exec')
    return base64.b64encode(marshal.dumps(bytecode)).decode('utf-8')

# ------------------------------------------------------------------------------
# 2. APEX TRANSFORMER (Giữ nguyên logic V46.1)
# ------------------------------------------------------------------------------
class ApexTransformer(ast.NodeTransformer):
    def __init__(self, seed, file_map, dir_map):
        self.seed = seed
        self.file_map = file_map
        self.dir_map = dir_map
        self.in_fstring = False

    def _patch_module_path(self, module_path):
        if not module_path: return module_path
        parts = module_path.split('.')
        new_parts = []
        for p in parts:
            if p in self.dir_map: new_parts.append(self.dir_map[p])
            elif p in self.file_map: new_parts.append(self.file_map[p])
            else: new_parts.append(p)
        return '.'.join(new_parts)

    def visit_Import(self, node):
        for alias in node.names:
            alias.name = self._patch_module_path(alias.name)
        return node

    def visit_ImportFrom(self, node):
        node.module = self._patch_module_path(node.module)
        return node

    def visit_JoinedStr(self, node):
        old = self.in_fstring
        self.in_fstring = True
        self.generic_visit(node)
        self.in_fstring = old
        return node

    def visit_Constant(self, node):
        if self.in_fstring: return node
        if isinstance(node.value, str):
            if len(node.value) < 1 or node.value.startswith("__"): return node
            enc = chaos_encrypt(node.value, self.seed)
            return ast.Call(
                func=ast.Attribute(value=ast.Name(id=CORE_LIB_NAME, ctx=ast.Load()), attr='_s', ctx=ast.Load()),
                args=[ast.Constant(value=enc)], keywords=[]
            )
        return node

# ------------------------------------------------------------------------------
# 3. MAIN PIPELINE
# ------------------------------------------------------------------------------
def rand_name(length=14):
    return "_X_" + "".join(random.choices(string.ascii_letters + string.digits, k=length))

def main():
    t0 = time.time()
    build_seed = random.randint(2000000, 9000000)
    
    for d in [RELEASE_DIR, INSPECT_DIR, BUILD_TEMP]:
        if os.path.exists(d): shutil.rmtree(d)
    
    os.makedirs(os.path.join(RELEASE_DIR, "app"), exist_ok=True)
    os.makedirs(INSPECT_DIR, exist_ok=True)
    
    print("🚀 [BƯỚC 1] Khởi tạo không gian Overlord Apex...")
    shutil.copytree(SOURCE_DIR, os.path.join(BUILD_TEMP, SOURCE_DIR))
    shutil.copy(ENTRY_GUI, os.path.join(BUILD_TEMP, ENTRY_GUI))

    dir_map = {"core": rand_name(10), "steps": rand_name(10), "services": rand_name(10), "ui": rand_name(10)}
    file_map = {}
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f.endswith(".py") and f not in ["__init__.py", "launcher.py", ENTRY_GUI]:
                file_map[f[:-3]] = rand_name(16)
    file_map[ENTRY_GUI[:-3]] = rand_name(16)
    new_gui_name = file_map[ENTRY_GUI[:-3]]

    # SINH BYTECODE VÀ XUẤT FILE ĐỂ GIẤU LÊN SERVER
    core_bytecode_b64 = get_encrypted_core_bytecode(build_seed)
    cloud_blob_path = os.path.join(RELEASE_DIR, "core_blob.enc")
    with open(cloud_blob_path, "w", encoding="utf-8") as f:
        f.write(core_bytecode_b64)
    print(f"✅ ĐÃ TẠO FILE BẢO MẬT: {cloud_blob_path} (Hãy upload file này lên Supabase)")

    print("🚀 [BƯỚC 2] Thực thi Obfuscation...")
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f.endswith(".py") and f != "launcher.py":
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8") as file: src = file.read()
                try:
                    tree = ast.parse(src)
                    tree.body.insert(0, ast.Import(names=[ast.alias(name=CORE_LIB_NAME, asname=None)]))
                    if f == ENTRY_GUI or 'class AppWrapper' in src:
                        new_body = []
                        found_entry = False
                        for node in tree.body:
                            is_main = (isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and "__name__" in ast.unparse(node.test))
                            if is_main and not found_entry:
                                new_func = ast.FunctionDef(
                                    name=VOID_ENTRY, args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]),
                                    body=node.body, decorator_list=[], returns=None
                                )
                                new_body.append(new_func); found_entry = True
                            else: new_body.append(node)
                        tree.body = new_body
                    transformer = ApexTransformer(build_seed, file_map, dir_map)
                    ast.fix_missing_locations(transformer.visit(tree))
                    with open(p, "w", encoding="utf-8") as file: file.write(ast.unparse(tree))
                except Exception as e: print(f"   [!] Error {f}: {e}")

    print("🚀 [BƯỚC 3] Thực thi Ghosting vật lý...")
    for old_d, new_d in dir_map.items():
        op, np = os.path.join(BUILD_TEMP, "app", old_d), os.path.join(BUILD_TEMP, "app", new_d)
        if os.path.exists(op): os.rename(op, np)
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f.endswith(".py") and f[:-3] in file_map:
                os.rename(os.path.join(root, f), os.path.join(root, f"{file_map[f[:-3]]}.py"))

    print("🚀 [BƯỚC 4] Biên dịch Cython (.pyd)...")
    curr = os.getcwd(); abs_rel = os.path.abspath(RELEASE_DIR)
    os.chdir(BUILD_TEMP)
    targets = []
    for root, _, files in os.walk("."):
        for f in files:
            if f.endswith(".py") and f not in ["launcher.py", "__init__.py"]:
                targets.append(os.path.relpath(os.path.join(root, f), "."))
    setup(ext_modules=cythonize(targets, quiet=True), script_args=["build_ext", "--build-lib", abs_rel])
    os.chdir(curr)
    
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f == "__init__.py":
                src = os.path.join(root, f); dst = os.path.join(RELEASE_DIR, os.path.relpath(src, BUILD_TEMP))
                os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(src, dst)

    print("🚀 [BƯỚC 5] Tạo Launcher Cloud-Sync (Triệt tiêu Hardcode)...")
    launcher_code = f"""
import os, sys, subprocess, ctypes, base64, marshal, types, traceback, urllib.request

def write_log_and_show_error(base_dir, msg, title="Security Error"):
    try:
        log_path = os.path.join(base_dir, "crash_log.txt")
        with open(log_path, "w", encoding="utf-8") as f: f.write(f"--- {{title}} ---\\n{{msg}}")
    except: pass
    try: ctypes.windll.user32.MessageBoxW(0, str(msg), str(title), 16)
    except: pass

def find_python_exe(base_dir):
    candidates = [os.path.join(base_dir, "venv", "Scripts", "python.exe"), os.path.join(base_dir, "Scripts", "python.exe")]
    for c in candidates:
        if os.path.exists(c): return os.path.normpath(c)
    return None

def main():
    try:
        if ctypes.windll.kernel32.IsDebuggerPresent(): sys.exit(0)
        exe_path = os.path.abspath(sys.argv[0]) if getattr(sys, 'frozen', False) else os.path.abspath(__file__)
        base_dir = os.path.dirname(exe_path)
        posix_base = base_dir.replace('\\\\', '/')
        python_exe = find_python_exe(base_dir)

        if not python_exe:
            write_log_and_show_error(base_dir, "Môi trường không hợp lệ! Vui lòng cài đặt lại.", "System Error")
            sys.exit(1)

        # LOGIC TẢI LINH HỒN TỪ CLOUD (Giấu hoàn toàn khỏi EXE)
        payload_template = (
            "import sys, os, base64, marshal, types, ctypes, traceback, urllib.request\\n"
            "try:\\n"
            "    # Buoc 1: Tai logic giai ma tu Supabase\\n"
            "    url = '{CORE_API_URL}'\\n"
            "    req = urllib.request.Request(url, headers={{'User-Agent': 'Mozilla/5.0'}})\\n"
            "    with urllib.request.urlopen(req, timeout=15) as response:\\n"
            "        core_data = response.read().decode('utf-8')\\n"
            "    # Buoc 2: Tiem vao RAM\\n"
            "    b = marshal.loads(base64.b64decode(core_data))\\n"
            "    m = types.ModuleType('{CORE_LIB_NAME}')\\n"
            "    exec(b, m.__dict__)\\n"
            "    sys.modules['{CORE_LIB_NAME}'] = m\\n"
            "    # Buoc 3: Run GUI\\n"
            "    sys.path.insert(0, r'{{base_dir}}')\\n"
            "    g = __import__('{new_gui_name}')\\n"
            "    getattr(g, '{VOID_ENTRY}')()\\n"
            "except Exception as e:\\n"
            "    ctypes.windll.user32.MessageBoxW(0, 'Khong the ket noi Server bao mat! Kiem tra Internet.\\\\n\\\\n' + str(e), 'Cloud Fail', 16)\\n"
        )
        
        payload = payload_template.replace("{{base_dir}}", posix_base)
        b64_payload = base64.b64encode(payload.encode('utf-8')).decode('utf-8')
        final_cmd = f"import base64; exec(base64.b64decode('{{b64_payload}}').decode('utf-8'))"

        CREATE_NO_WINDOW = 0x08000000
        subprocess.run([python_exe, "-c", final_cmd], cwd=base_dir, creationflags=CREATE_NO_WINDOW)

    except Exception:
        write_log_and_show_error(os.getcwd(), traceback.format_exc(), "Launcher Crash")

if __name__ == "__main__": main()
"""
    with open(os.path.join(BUILD_TEMP, "launcher.py"), "w", encoding="utf-8") as f: f.write(launcher_code)

    print("🚀 [BƯỚC 6] Đóng gói Nuitka (V48.0 Cloud-Ghost)...")
    icon_p = os.path.join(SOURCE_DIR, "assets", "icon.ico")
    n_cmd = ["python", "-m", "nuitka", "--standalone", "--onefile", "--windows-console-mode=disable", "--remove-output", f"--output-dir={RELEASE_DIR}", "--output-filename=AI_Reup_Pro_V48.exe", os.path.join(BUILD_TEMP, "launcher.py")]
    if os.path.exists(icon_p): n_cmd.insert(-1, f"--windows-icon-from-ico={icon_p}")
    subprocess.run(n_cmd, check=True)

    shutil.copytree(os.path.join(SOURCE_DIR, "assets"), os.path.join(RELEASE_DIR, "app", "assets"), dirs_exist_ok=True)
    if os.path.exists("config.dist.yaml"): shutil.copy("config.dist.yaml", os.path.join(RELEASE_DIR, "config.yaml"))
    shutil.rmtree("build", ignore_errors=True)
    
    print(f"\n✅ BUILD V48.0 HOÀN TẤT!")
    print(f"👉 FILE CẦN GIẤU LÊN SERVER: {os.path.abspath(cloud_blob_path)}")
    print(f"👉 Link Cloud hiện tại đang cấu hình: {CORE_API_URL}")

if __name__ == "__main__":
    main()