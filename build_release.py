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
# BUILD PIPELINE V53.3 - OVERLORD APEX (RPC INTEGRATION BASED ON V46.1)
# ==============================================================================

SOURCE_DIR = "app"
ENTRY_GUI = "run_gui.py"
RELEASE_DIR = "Overlord_Apex_Release"
INSPECT_DIR = "Overlord_Source_Inspect"
BUILD_TEMP = "overlord_apex_temp"
VOID_ENTRY = "void_main_entry"
CORE_LIB_NAME = "_core_sys_x64" 

# --- THÔNG TIN SUPABASE ---
SUPABASE_URL = "https://gfihmymecoykcogqykbl.supabase.co"
SUPABASE_ANON_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImdmaWhteW1lY295a2NvZ3F5a2JsIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzA5NjU4MTMsImV4cCI6MjA4NjU0MTgxM30.SWsdEyLWkOu2tKZS3ZFKk2riCR5uxubXbFvz0a12e_Q"

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
import base64 as _b, marshal as _m, types as _t, sys, os, ctypes
_CACHE = {{}}
def _get_k(): return ({final_op_val} - {junk_val2}) ^ {junk_val1}
def _s(s):
    if not s or s in _CACHE: return _CACHE.get(s, "")
    try:
        k = _get_k(); d = _b.b64decode(s); r = bytearray(); st = k
        for i, v in enumerate(d):
            st = (st * 1664525 + 1013904223) & 0xFFFFFFFF
            v ^= (i & 0xFF); sh = (k + i) % 7 + 1
            v = ((v >> sh) | (v << (8 - sh))) & 0xFF
            r.append(v ^ ((st >> 24) & 0xFF))
        res = r.decode('utf-8'); _CACHE[s] = res; return res
    except: return ""
"""
    return base64.b64encode(marshal.dumps(compile(core_src, '<ram_turbo_core>', 'exec'))).decode('utf-8')

# ------------------------------------------------------------------------------
# 2. APEX TRANSFORMER (ĐÃ FIX LỖI PYDANTIC)
# ------------------------------------------------------------------------------
class ApexTransformer(ast.NodeTransformer):
    def __init__(self, seed, file_map, dir_map):
        self.seed, self.file_map, self.dir_map, self.in_fstring = seed, file_map, dir_map, False
        
    def _patch_module_path(self, module_path):
        if not module_path: return module_path
        parts = module_path.split('.')
        return '.'.join([self.dir_map.get(p, self.file_map.get(p, p)) for p in parts])
        
    def visit_Import(self, node):
        for alias in node.names: alias.name = self._patch_module_path(alias.name)
        return node
        
    def visit_ImportFrom(self, node):
        node.module = self._patch_module_path(node.module); return node
        
    def visit_JoinedStr(self, node):
        old = self.in_fstring; self.in_fstring = True
        self.generic_visit(node); self.in_fstring = old; return node
        
    def visit_Constant(self, node):
        if self.in_fstring: return node
        if isinstance(node.value, str):
            val = node.value
            # BỌC THÉP: Tha cho các tên biến, tên hàm, tên field để không làm hỏng Pydantic
            if val.isidentifier() or val.startswith("__") or len(val) < 2:
                return node
            enc = chaos_encrypt(val, self.seed)
            return ast.Call(func=ast.Attribute(value=ast.Name(id=CORE_LIB_NAME, ctx=ast.Load()), attr='_s', ctx=ast.Load()), args=[ast.Constant(value=enc)], keywords=[])
        return node

# ------------------------------------------------------------------------------
# 3. GHOSTING & MAIN PIPELINE
# ------------------------------------------------------------------------------
def rand_name(length=14): return "_X_" + "".join(random.choices(string.ascii_letters + string.digits, k=length))

def get_ghost_maps(build_path):
    dir_map = {"core": rand_name(10), "steps": rand_name(10), "services": rand_name(10), "ui": rand_name(10)}
    file_map = {f[:-3]: rand_name(16) for root, _, files in os.walk(build_path) for f in files if f.endswith(".py") and f not in ["__init__.py", "launcher.py", ENTRY_GUI]}
    file_map[ENTRY_GUI[:-3]] = rand_name(16)
    return dir_map, file_map

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
    dir_map, file_map = get_ghost_maps(BUILD_TEMP)
    new_gui_name = file_map[ENTRY_GUI[:-3]]

    # XUẤT BYTECODE ĐỂ CẤT VÀO SECURE_ASSETS (Thủ công lên Supabase)
    core_bytecode_b64 = get_encrypted_core_bytecode(build_seed)
    with open(os.path.join(RELEASE_DIR, "core_blob.enc"), "w", encoding="utf-8") as f: f.write(core_bytecode_b64)
    print(f"✅ ĐÃ TẠO FILE BẢO MẬT: core_blob.enc (Hãy upload file này lên Supabase)")

    print("🚀 [BƯỚC 2] Thực thi Obfuscation (AST Transformation)...")
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f.endswith(".py") and f != "launcher.py":
                p = os.path.join(root, f)
                with open(p, "r", encoding="utf-8") as file: src = file.read()
                try:
                    tree = ast.parse(src)
                    tree.body.insert(0, ast.Import(names=[ast.alias(name=CORE_LIB_NAME, asname=None)]))
                    if f == ENTRY_GUI or 'class AppWrapper' in src:
                        new_body, found_entry = [], False
                        for node in tree.body:
                            if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and "__name__" in ast.unparse(node.test) and not found_entry:
                                new_body.append(ast.FunctionDef(name=VOID_ENTRY, args=ast.arguments(posonlyargs=[], args=[], kwonlyargs=[], kw_defaults=[], defaults=[]), body=node.body, decorator_list=[], returns=None))
                                found_entry = True
                            else: new_body.append(node)
                        tree.body = new_body
                    ast.fix_missing_locations(ApexTransformer(build_seed, file_map, dir_map).visit(tree))
                    with open(p, "w", encoding="utf-8") as file: file.write(ast.unparse(tree))
                except Exception as e: print(f"   [!] Error {f}: {e}")

    print("🚀 [BƯỚC 3] Thực thi Ghosting vật lý...")
    for old_d, new_d in dir_map.items():
        op, np = os.path.join(BUILD_TEMP, "app", old_d), os.path.join(BUILD_TEMP, "app", new_d)
        if os.path.exists(op): os.rename(op, np)
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f.endswith(".py") and f[:-3] in file_map: os.rename(os.path.join(root, f), os.path.join(root, f"{file_map[f[:-3]]}.py"))

    print("🚀 [BƯỚC 4] Biên dịch Cython (.pyd)...")
    curr = os.getcwd(); abs_rel = os.path.abspath(RELEASE_DIR)
    os.chdir(BUILD_TEMP)
    targets = [os.path.relpath(os.path.join(r, f), ".") for r, _, fs in os.walk(".") for f in fs if f.endswith(".py") and f not in ["launcher.py", "__init__.py"]]
    setup(ext_modules=cythonize(targets, compiler_directives={'language_level': "3", 'always_allow_keywords': True}, quiet=True), script_args=["build_ext", "--build-lib", abs_rel])
    os.chdir(curr)
    
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f == "__init__.py":
                dst = os.path.join(RELEASE_DIR, os.path.relpath(os.path.join(root, f), BUILD_TEMP))
                os.makedirs(os.path.dirname(dst), exist_ok=True); shutil.copy2(os.path.join(root, f), dst)

    # ------------------------------------------------------------------------------
    # 5. LAUNCHER APEX (BẢN BỌC THÉP - BÁO LỖI TIẾNG VIỆT)
    # ------------------------------------------------------------------------------
    print("🚀 [BƯỚC 5] Tạo Launcher (Logic V46.1 + RPC Flow)...")
    launcher_code = f"""
import os, sys, subprocess, ctypes, base64, marshal, types, traceback, urllib.request, json, hashlib

def get_hwid():
    try:
        uuid = subprocess.check_output("wmic csproduct get uuid", shell=True, stderr=subprocess.DEVNULL).decode().split('\\n')[1].strip()
        return hashlib.sha256(f"OVERLORD_{{uuid}}_SALT".encode()).hexdigest()[:24].upper()
    except: return "UNKNOWN-HWID-FATAL"

def write_log_and_show_error(base_dir, msg, title="Critical Error"):
    try:
        log_path = os.path.join(base_dir, "crash_log.txt")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\\n--- {{title}} ---\\n{{msg}}\\n")
    except: pass
    try:
        ctypes.windll.user32.MessageBoxW(0, str(msg), str(title), 16)
    except: pass

def find_python_exe(base_dir):
    candidates = [
        os.path.join(base_dir, "venv", "Scripts", "python.exe"),
        os.path.join(base_dir, "Scripts", "python.exe")
    ]
    for c in candidates:
        if os.path.exists(c): return os.path.normpath(c)
    return None

def main():
    try:
        if '__compiled__' in globals() or getattr(sys, 'frozen', False):
            exe_path = os.path.abspath(sys.argv[0])
        else:
            exe_path = os.path.abspath(__file__)
            
        base_dir = os.path.dirname(exe_path)
        posix_base = base_dir.replace('\\\\', '/')
        python_exe = find_python_exe(base_dir)

        if not python_exe:
            write_log_and_show_error(base_dir, f"Khong tim thay venv tai:\\n{{base_dir}}", "Missing Environment")
            sys.exit(1)
        
        payload_template = (
            "import sys, os, base64, marshal, types, traceback, urllib.request, json, subprocess, hashlib, ctypes\\n"
            "log_path = r'{{base_dir}}/crash_log.txt'\\n"
            "try:\\n"
            "    venv_site = os.path.join(r'{{base_dir}}', 'venv', 'Lib', 'site-packages')\\n"
            "    if os.path.exists(venv_site): sys.path.insert(0, venv_site)\\n"
            "    sys.path.insert(0, r'{{base_dir}}')\\n"
            "\\n"
            "    # TÍCH HỢP DLL (cuDNN, zlibwapi) TỪ THƯ MỤC BIN\\n"
            "    bin_dir = os.path.join(r'{{base_dir}}', 'bin')\\n"
            "    if os.path.exists(bin_dir):\\n"
            "        os.environ['PATH'] = bin_dir + os.pathsep + os.environ.get('PATH', '')\\n"
            "        if hasattr(os, 'add_dll_directory'):\\n"
            "            try: os.add_dll_directory(bin_dir)\\n"
            "            except Exception: pass\\n"
            "\\n"
            "    def get_hwid():\\n"
            "        try:\\n"
            "            u = subprocess.check_output('wmic csproduct get uuid', shell=True).decode().split('\\\\n')[1].strip()\\n"
            "            return hashlib.sha256(f'OVERLORD_{{u}}_SALT'.encode()).hexdigest()[:24].upper()\\n"
            "        except: return 'ERR'\\n"
            "\\n"
            "    hwid = get_hwid()\\n"
            "    lic_path = os.path.join(r'{{base_dir}}', 'system.lic')\\n"
            "\\n"
            "    if not os.path.exists(lic_path):\\n"
            "        ctypes.windll.user32.MessageBoxW(0, 'Phần mềm chưa kích hoạt! Vui lòng cài đặt bằng file Setup.exe', 'Lỗi Bản Quyền', 16)\\n"
            "        sys.exit(1)\\n"
            "\\n"
            "    with open(lic_path, 'r', encoding='utf-8') as f: lic_raw = f.read().strip()\\n"
            "    if not lic_raw: raise Exception('LỖI: File system.lic đang bị trống rỗng. Vui lòng chạy lại file Setup.exe để kích hoạt!')\\n"
            "    try:\\n"
            "        data = json.loads(lic_raw)\\n"
            "    except Exception:\\n"
            "        raise Exception('LỖI: File system.lic bị sai định dạng dữ liệu. Vui lòng chạy lại file Setup.exe!')\\n"
            "\\n"
            "    lic, saved_hash = data.get('key'), data.get('hash')\\n"
            "    if saved_hash != hashlib.sha512(f'||{{lic}}||<<SECURE>>||{{hwid}}||'.encode()).hexdigest():\\n"
            "        raise Exception('LỖI: Bản quyền không hợp lệ hoặc đã bị chỉnh sửa cho thiết bị này!')\\n"
            "\\n"
            "    rpc_url = '{SUPABASE_URL}/rest/v1/rpc/get_secure_payload'\\n"
            "    req_data = json.dumps({{'p_key': lic, 'p_hwid': hwid, 'p_asset': 'core_blob'}}).encode('utf-8')\\n"
            "    req_rpc = urllib.request.Request(rpc_url, data=req_data, headers={{'apikey': '{SUPABASE_ANON_KEY}', 'Authorization': 'Bearer {SUPABASE_ANON_KEY}', 'Content-Type': 'application/json'}})\\n"
            "    try:\\n"
            "        with urllib.request.urlopen(req_rpc, timeout=20) as resp:\\n"
            "            raw = resp.read().decode('utf-8').strip()\\n"
            "    except Exception as e:\\n"
            "        raise Exception(f'LỖI MẠNG: Không thể kết nối tới máy chủ Supabase. Chi tiết: {{e}}')\\n"
            "\\n"
            "    if not raw or raw == 'null': raise Exception('LỖI DỮ LIỆU: Máy chủ trả về rỗng! Bạn CHƯA UPLOAD nội dung file core_blob.enc lên Database Supabase.')\\n"
            "    try:\\n"
            "        core_data = json.loads(raw)\\n"
            "    except Exception:\\n"
            "        raise Exception(f'LỖI DỮ LIỆU: Dữ liệu từ Supabase không phải là JSON. Vui lòng kiểm tra lại hàm RPC. Thực tế nhận được: {{raw[:50]}}...')\\n"
            "\\n"
            "    b = marshal.loads(base64.b64decode(core_data))\\n"
            "    m = types.ModuleType('{CORE_LIB_NAME}')\\n"
            "    exec(b, m.__dict__)\\n"
            "    sys.modules['{CORE_LIB_NAME}'] = m\\n"
            "\\n"
            "    g = __import__('{new_gui_name}')\\n"
            "    getattr(g, '{VOID_ENTRY}')()\\n"
            "except Exception as specific_error:\\n"
            "    sys.stderr.write(str(specific_error))\\n"
            "    with open(log_path, 'a', encoding='utf-8') as f: f.write('\\\\n--- FATAL ERROR (CORE) ---\\\\n' + str(specific_error))\\n"
            "    try: ctypes.windll.user32.MessageBoxW(0, str(specific_error), 'Fatal Error', 16)\\n"
            "    except: pass\\n"
            "    sys.exit(1)\\n"
        )
        
        final_cmd = f"import base64; exec(base64.b64decode('{{base64.b64encode(payload_template.replace('{{base_dir}}', posix_base).encode()).decode()}}').decode('utf-8'))"

        CREATE_NO_WINDOW = 0x08000000
        result = subprocess.run([python_exe, "-c", final_cmd], cwd=base_dir, creationflags=CREATE_NO_WINDOW, capture_output=True, text=True)
        
        if result.returncode != 0:
            err_msg = result.stderr if result.stderr else result.stdout
            write_log_and_show_error(base_dir, f"Tiến trình bị ngắt (Code {{result.returncode}}).\\n\\nStderr:\\n{{err_msg}}", "Subprocess Crash")

    except Exception:
        err_dir = base_dir if 'base_dir' in locals() else os.getcwd()
        write_log_and_show_error(err_dir, traceback.format_exc(), "Launcher Crash")

if __name__ == "__main__":
    main()
"""
    l_path = os.path.join(BUILD_TEMP, "launcher.py")
    with open(l_path, "w", encoding="utf-8") as f: f.write(launcher_code)

    print("🚀 [BƯỚC 6] Đóng gói Nuitka (Logic V46.1 + RPC Flow)...")
    icon_p = os.path.join(SOURCE_DIR, "assets", "icon.ico")
    n_cmd = [
        "python", "-m", "nuitka", 
        "--standalone", 
        "--onefile", 
        "--windows-console-mode=disable", 
        "--windows-uac-admin",  # Cấp quyền ghi ổ C tuyệt đối
        "--remove-output", 
        f"--output-dir={RELEASE_DIR}", 
        "--output-filename=Reup_Video_Pro.exe", 
        l_path
    ]
    if os.path.exists(icon_p): n_cmd.insert(-1, f"--windows-icon-from-ico={icon_p}")
    subprocess.run(n_cmd, check=True)

    shutil.copytree(os.path.join(SOURCE_DIR, "assets"), os.path.join(RELEASE_DIR, "app", "assets"), dirs_exist_ok=True)
    if os.path.exists("config.dist.yaml"): shutil.copy("config.dist.yaml", os.path.join(RELEASE_DIR, "config.yaml"))
    shutil.rmtree("build", ignore_errors=True)
    print(f"\n✅ BUILD V53.3 HOÀN TẤT DỰA TRÊN CẤU TRÚC V46.1!")

if __name__ == "__main__": main()