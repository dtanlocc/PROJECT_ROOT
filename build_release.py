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

class ApexTransformer(ast.NodeTransformer):
    def __init__(self, seed, file_map, dir_map):
        self.seed = seed
        self.file_map = file_map
        self.dir_map = dir_map
        self.in_fstring = False

    def _patch_module_path(self, module_path):
        if not module_path:
            return module_path
        parts = [p.strip() for p in module_path.split('.')]
        new_parts = []
        for p in parts:
            if p in self.dir_map:
                new_parts.append(self.dir_map[p])
            elif p in self.file_map:
                new_parts.append(self.file_map[p])
            else:
                new_parts.append(p)
        return '.'.join(new_parts)

    def visit_Import(self, node):
        for alias in node.names:
            alias.name = self._patch_module_path(alias.name)
        return node

    def visit_ImportFrom(self, node):
        if node.module:
            node.module = self._patch_module_path(node.module)
        for alias in node.names:
            if alias.name in self.file_map:
                alias.name = self.file_map[alias.name]
        return node

    def visit_JoinedStr(self, node):
        old = self.in_fstring
        self.in_fstring = True
        self.generic_visit(node)
        self.in_fstring = old
        return node

    def visit_Constant(self, node):
        if self.in_fstring: 
            return node
        if isinstance(node.value, str):
            val = node.value
            if val.isidentifier() or val.startswith("__") or len(val) < 2:
                return node
            enc = chaos_encrypt(val, self.seed)
            return ast.Call(
                func=ast.Attribute(value=ast.Name(id=CORE_LIB_NAME, ctx=ast.Load()), attr='_s', ctx=ast.Load()),
                args=[ast.Constant(value=enc)], 
                keywords=[]
            )
        return node
# ------------------------------------------------------------------------------
# 3. GHOSTING & MAIN PIPELINE
# ------------------------------------------------------------------------------
def rand_name(length=14): return "_X_" + "".join(random.choices(string.ascii_letters + string.digits, k=length))

def get_ghost_maps(build_path):
    """Tạo tên ghost cho thư mục và file - Đảm bảo đồng bộ"""
    dir_map = {
        "core": rand_name(10),
        "steps": rand_name(10),
        "services": rand_name(10),
        "ui": rand_name(10),
        "language": rand_name(10),        # Quan trọng: language phải có
    }
    
    file_map = {}
    
    # Quét tất cả file .py để tạo tên mới
    for root, _, files in os.walk(build_path):
        for f in files:
            if f.endswith(".py") and f not in ["__init__.py", "launcher.py", ENTRY_GUI]:
                old_name = f[:-3]
                file_map[old_name] = rand_name(16)
    
    file_map[ENTRY_GUI[:-3]] = rand_name(16)
    
    return dir_map, file_map

def main():
    t0 = time.time()
    build_seed = random.randint(2000000, 9000000)
    # for d in [RELEASE_DIR, INSPECT_DIR, BUILD_TEMP]:
    #     if os.path.exists(d): shutil.rmtree(d)
    os.makedirs(os.path.join(RELEASE_DIR, "app"), exist_ok=True)
    os.makedirs(INSPECT_DIR, exist_ok=True)
    
    print("🚀 [BƯỚC 1] Khởi tạo không gian Overlord Apex...")
    shutil.copytree(SOURCE_DIR, os.path.join(BUILD_TEMP, SOURCE_DIR))
    shutil.copy(ENTRY_GUI, os.path.join(BUILD_TEMP, ENTRY_GUI))
    # === SAU KHI copy vào BUILD_TEMP, TRƯỚC KHI obfuscate ===
    print("🚀 [BƯỚC 1.5] Patch hardcoded paths trước khi Obfuscate...")

    # Tính tên ghost trước
    dir_map, file_map = get_ghost_maps(BUILD_TEMP)  # gọi sớm hơn
    new_gui_name = file_map[ENTRY_GUI[:-3]]

    steps_ghost   = dir_map.get("steps", "steps")
    worker_new    = file_map.get("s6_tts_worker", "s6_tts_worker")
    s6_mix_orig   = os.path.join(BUILD_TEMP, "app", "steps", "s6_mix.py")

    if os.path.exists(s6_mix_orig):
        with open(s6_mix_orig, "r", encoding="utf-8") as f:
            content = f.read()

        old_p = "app/steps/s6_tts_worker.py"
        new_p = f"app/{steps_ghost}/{worker_new}.py"
        content = content.replace(old_p, new_p)

        with open(s6_mix_orig, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"   ✅ Patch: {old_p} → {new_p}")

    # Tiếp tục BƯỚC 2 (Obfuscate) như cũ...
    
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

    print("🚀 [BƯỚC 3] Thực thi Ghosting vật lý - ĐỒNG BỘ tên thư mục & code...")

    # 1. Rename thư mục cấp 1 trước
    for old_d, new_d in dir_map.items():
        old_path = os.path.join(BUILD_TEMP, "app", old_d)
        if os.path.exists(old_path):
            new_path = os.path.join(BUILD_TEMP, "app", new_d)
            os.rename(old_path, new_path)
            print(f"   Rename thư mục: {old_d} → {new_d}")

    # 2. Rename thư mục 'language' nằm bên trong core (sau khi core đã rename)
    core_new_name = dir_map.get("core")
    language_new_name = dir_map.get("language")
    if core_new_name and language_new_name:
        language_old_path = os.path.join(BUILD_TEMP, "app", core_new_name, "language")
        if os.path.exists(language_old_path):
            language_new_path = os.path.join(BUILD_TEMP, "app", core_new_name, language_new_name)
            os.rename(language_old_path, language_new_path)
            print(f"   Rename thư mục language: language → {language_new_name} (bên trong {core_new_name})")

    # 3. Rename tất cả file .py (đồng bộ với file_map)
    renamed = 0
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f.endswith(".py") and f[:-3] in file_map:
                old_file = os.path.join(root, f)
                new_file = os.path.join(root, f"{file_map[f[:-3]]}.py")
                os.rename(old_file, new_file)
                renamed += 1
    print(f"   Đã rename {renamed} file .py")
                
    print("🚀 [BƯỚC 4] Biên dịch Cython (.pyd) và Tách UI...")
    curr = os.getcwd(); abs_rel = os.path.abspath(RELEASE_DIR)
    os.chdir(BUILD_TEMP)

    # 1. Xác định thư mục/file GUI đã bị đổi tên (Ghosting) để loại trừ khỏi Cython
    ui_ghost_dir = os.path.normpath(os.path.join("app", dir_map.get("ui", "ui")))
    gui_ghost_run = file_map.get(ENTRY_GUI[:-3], ENTRY_GUI[:-3]) + ".py"

    targets = []
    for r, _, fs in os.walk("."):
        for f in fs:
            if f.endswith(".py") and f not in ["launcher.py", "__init__.py"]:
                # Nếu file thuộc giao diện UI hoặc là run_gui -> Bỏ qua Cython
                if ui_ghost_dir in os.path.normpath(r) or f == gui_ghost_run:
                    continue
                targets.append(os.path.relpath(os.path.join(r, f), "."))

    # Compile các file Core, Engine... bằng Cython
    setup(ext_modules=cythonize(targets, compiler_directives={'language_level': "3", 'always_allow_keywords': True, 'binding': True}, quiet=True), script_args=["build_ext", "--build-lib", abs_rel])
    os.chdir(curr)
    
    # 2. Copy __init__.py VÀ các file UI (đã làm rối nhưng không build Cython) sang RELEASE_DIR
    for root, _, files in os.walk(BUILD_TEMP):
        for f in files:
            if f.endswith(".py"):
                # Kiểm tra xem file này có phải là file UI vừa bị loại trừ ở trên không
                is_ui_file = ui_ghost_dir in os.path.normpath(root) or f == gui_ghost_run
                
                if f == "__init__.py" or is_ui_file:
                    dst = os.path.join(RELEASE_DIR, os.path.relpath(os.path.join(root, f), BUILD_TEMP))
                    os.makedirs(os.path.dirname(dst), exist_ok=True)
                    shutil.copy2(os.path.join(root, f), dst)

# ------------------------------------------------------------------------------
    # 5. LAUNCHER APEX (GIAO DIỆN CUSTOM-TKINTER NGUYÊN BẢN CỦA BẠN)
    # ------------------------------------------------------------------------------
    print("🚀 [BƯỚC 5] Tạo Launcher (Tích hợp giao diện CustomTkinter)...")
    
    payload_template = f"""import sys, os, base64, marshal, types, traceback, urllib.request, json, subprocess, hashlib, ctypes

log_path = r'{{base_dir}}/crash_log.txt'
try:
    venv_site = os.path.join(r'{{base_dir}}', 'venv', 'Lib', 'site-packages')
    if os.path.exists(venv_site): sys.path.insert(0, venv_site)
    sys.path.insert(0, r'{{base_dir}}')

    bin_dir = os.path.join(r'{{base_dir}}', 'bin')
    if os.path.exists(bin_dir):
        os.environ['PATH'] = bin_dir + os.pathsep + os.environ.get('PATH', '')
        if hasattr(os, 'add_dll_directory'):
            try: os.add_dll_directory(bin_dir)
            except Exception: pass

    def get_hwid():
        parts = []
        try:
            out = subprocess.check_output('wmic csproduct get uuid', shell=True, stderr=subprocess.DEVNULL).decode()
            # ĐÃ SỬA: Dùng split('\\n') để giống hệt security.py, tránh lỗi wmic newline của Windows
            parts.append(out.split('\\n')[1].strip())
        except: parts.append('MB_UNKNOWN')
        try:
            out = subprocess.check_output('wmic cpu get ProcessorId', shell=True, stderr=subprocess.DEVNULL).decode()
            parts.append(out.split('\\n')[1].strip())
        except: parts.append('CPU_UNKNOWN')
        try:
            out = subprocess.check_output('wmic diskdrive get SerialNumber', shell=True, stderr=subprocess.DEVNULL).decode()
            parts.append(out.split('\\n')[1].strip())
        except: parts.append('DISK_UNKNOWN')
        raw = '|'.join(parts)
        return hashlib.sha256(f'OVERLORD_{{raw}}_SALT'.encode()).hexdigest()[:32].upper()

    hwid = get_hwid()
    lic_path = os.path.join(r'{{base_dir}}', 'system.lic')
    user_key = None
    has_valid_license = False

    def _derive_fernet_key(h):
        raw = hashlib.sha256(f'FERNET_DERIVE_{{h}}_OVERLORD_V2'.encode()).digest()
        return base64.urlsafe_b64encode(raw)

    if os.path.exists(lic_path):
        try:
            from cryptography.fernet import Fernet
            with open(lic_path, 'rb') as f: encrypted = f.read()
            fnet = Fernet(_derive_fernet_key(hwid))
            raw_data = fnet.decrypt(encrypted)
            data = json.loads(raw_data.decode())
            user_key = data.get('key')
            if user_key: has_valid_license = True
        except Exception: pass

    # ================= HIỂN THỊ GIAO DIỆN NẾU CHƯA CÓ KEY =================
    if not has_valid_license:
        import customtkinter as ctk
        
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
        
        class LoginPopup(ctk.CTk):
            def __init__(self):
                super().__init__()
                self.title("Kích hoạt bản quyền")
                self.geometry("460x320")
                self.resizable(False, False)
                
                # Căn giữa màn hình
                self.update_idletasks()
                w, h = 460, 320
                x = (self.winfo_screenwidth() // 2) - (w // 2)
                y = (self.winfo_screenheight() // 2) - (h // 2)
                self.geometry(f"{{w}}x{{h}}+{{x}}+{{y}}")
                
                icon_path = os.path.join(r'{{base_dir}}', "app", "assets", "icon.ico")
                if os.path.exists(icon_path):
                    try: self.iconbitmap(icon_path)
                    except: pass

                ctk.CTkLabel(self, text="BẢO MẬT HỆ THỐNG", font=("Arial", 22, "bold"), text_color="#3498db").pack(pady=(25, 5))
                ctk.CTkLabel(self, text="Vui lòng nhập Key kích hoạt để mở khóa phần mềm", font=("Arial", 12), text_color="gray").pack(pady=(0, 15))
                
                hwid_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=6)
                hwid_frame.pack(pady=5, padx=20, fill="x")
                
                ctk.CTkLabel(hwid_frame, text="Hardware ID:", font=("Arial", 11, "bold")).pack(side="left", padx=10, pady=8)
                self.lbl_hwid = ctk.CTkEntry(hwid_frame, width=220, font=("Consolas", 11), border_width=0, fg_color="transparent")
                self.lbl_hwid.insert(0, hwid)
                self.lbl_hwid.configure(state="readonly")
                self.lbl_hwid.pack(side="right", padx=10)
                
                self.entry_key = ctk.CTkEntry(self, width=320, height=40, placeholder_text="Nhập License Key (Ví dụ: VIP-XXXX)...", font=("Arial", 13))
                self.entry_key.pack(pady=20)
                self.entry_key.bind("<Return>", lambda e: self.btn_click())
                
                self.btn_active = ctk.CTkButton(self, text="KÍCH HOẠT", width=200, height=40, font=("Arial", 14, "bold"), fg_color="#27ae60", hover_color="#2ecc71", command=self.btn_click)
                self.btn_active.pack(pady=5)
                
                self.lbl_status = ctk.CTkLabel(self, text="", text_color="#e74c3c", font=("Arial", 11))
                self.lbl_status.pack(pady=5)

            def btn_click(self):
                global has_valid_license, user_key
                k = self.entry_key.get().strip()
                if not k: return
                    
                self.btn_active.configure(state="disabled", text="ĐANG KIỂM TRA...")
                self.lbl_status.configure(text="Đang đối chiếu HWID...", text_color="#f39c12")
                self.update() 
                
                edge_url = "https://gfihmymecoykcogqykbl.supabase.co/functions/v1/verify-license"
                req_data = json.dumps({{"p_key": k, "p_hwid": hwid}}).encode('utf-8')
                req = urllib.request.Request(edge_url, data=req_data, headers={{"Content-Type": "application/json"}})
                
                try:
                    with urllib.request.urlopen(req, timeout=15) as resp:
                        res_data = json.loads(resp.read().decode('utf-8'))
                        expires_str = res_data.get("expires") if isinstance(res_data, dict) else None
                        
                        from cryptography.fernet import Fernet
                        expiry = expires_str if expires_str else "PERMANENT_NO_EXPIRY_OVERLORD"
                        lic_hash = hashlib.sha512(f'||{{k}}||<<SECURE>>||{{hwid}}||{{expiry}}||'.encode()).hexdigest()
                        save_data = {{"key": k, "hash": lic_hash, "expires_at": expires_str}}
                        
                        fnet = Fernet(_derive_fernet_key(hwid))
                        with open(lic_path, 'wb') as f:
                            f.write(fnet.encrypt(json.dumps(save_data).encode()))
                        
                        user_key = k
                        has_valid_license = True
                        self.lbl_status.configure(text="✔ Kích hoạt thành công!", text_color="#2ecc71")
                        self.update()
                        self.after(500, self.destroy)
                except urllib.error.HTTPError as e:
                    err_msg = e.read().decode('utf-8')
                    try: err_msg = json.loads(err_msg).get("error", err_msg)
                    except: pass
                    self.btn_active.configure(state="normal", text="KÍCH HOẠT")
                    self.lbl_status.configure(text=f"❌ {{err_msg}}", text_color="#e74c3c")
                except Exception as e:
                    self.btn_active.configure(state="normal", text="KÍCH HOẠT")
                    self.lbl_status.configure(text=f"❌ Lỗi mạng: {{str(e)}}", text_color="#e74c3c")

        app = LoginPopup()
        app.mainloop()

    # ================= KÉO CORE VÀ KHỞI ĐỘNG RUN_GUI.PY =================
    if has_valid_license:
        rpc_url = '{SUPABASE_URL}/rest/v1/rpc/get_secure_payload'
        req_data = json.dumps({{"p_key": user_key, "p_hwid": hwid, "p_asset": "core_blob"}}).encode('utf-8')
        req_rpc = urllib.request.Request(rpc_url, data=req_data, headers={{"apikey": "{SUPABASE_ANON_KEY}", "Authorization": "Bearer {SUPABASE_ANON_KEY}", "Content-Type": "application/json"}})
        
        try:
            with urllib.request.urlopen(req_rpc, timeout=20) as resp:
                raw = resp.read().decode('utf-8').strip()
                core_data = json.loads(raw)
                core_blob = core_data.get('data') if isinstance(core_data, dict) else core_data
                b = marshal.loads(base64.b64decode(core_blob))
                m = types.ModuleType('{CORE_LIB_NAME}')
                exec(b, m.__dict__)
                sys.modules['{CORE_LIB_NAME}'] = m
        except Exception as e:
            ctypes.windll.user32.MessageBoxW(0, f"Lỗi tải lõi bảo mật:\\n{{str(e)}}", "Fatal Error", 16)
            sys.exit(1)

        # Đánh thức phần mềm chính
        g = __import__('{new_gui_name}')
        getattr(g, '{VOID_ENTRY}')()
    else:
        sys.exit(0)
except Exception as specific_error:
    sys.stderr.write(str(specific_error))
    with open(log_path, 'a', encoding='utf-8') as f: f.write('\\n--- FATAL ERROR (LAUNCHER) ---\\n' + traceback.format_exc())
    sys.exit(1)
"""

    launcher_code = f"""
import os, sys, subprocess, ctypes, traceback, base64

def write_log_and_show_error(base_dir, msg, title="Critical Error"):
    try:
        log_path = os.path.join(base_dir, "crash_log.txt")
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"\\n--- {{title}} ---\\n{{msg}}\\n")
    except: pass
    try: ctypes.windll.user32.MessageBoxW(0, str(msg), str(title), 16)
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
            write_log_and_show_error(base_dir, f"Không tìm thấy venv tại:\\n{{base_dir}}", "Lỗi Môi Trường")
            sys.exit(1)
            
        raw_payload = base64.b64decode("{base64.b64encode(payload_template.encode('utf-8')).decode('utf-8')}").decode('utf-8')
        ready_payload = raw_payload.replace("{{base_dir}}", posix_base)
        encoded_payload = base64.b64encode(ready_payload.encode('utf-8')).decode('utf-8')
        
        final_cmd = f"import base64; exec(base64.b64decode('{{encoded_payload}}').decode('utf-8'))"

        CREATE_NO_WINDOW = 0x08000000
        # ĐÃ SỬA: Ép Python chạy chế độ UTF-8 (-X utf8) và cấu hình encoding='utf-8' để đọc Output
        result = subprocess.run([python_exe, "-X", "utf8", "-c", final_cmd], cwd=base_dir, creationflags=CREATE_NO_WINDOW, capture_output=True, text=True, encoding='utf-8')
        
        if result.returncode != 0:
            err_msg = result.stderr if result.stderr else result.stdout
            write_log_and_show_error(base_dir, f"Tiến trình venv bị ngắt (Code {{result.returncode}}).\\n\\nStderr:\\n{{err_msg}}", "Subprocess Crash")

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