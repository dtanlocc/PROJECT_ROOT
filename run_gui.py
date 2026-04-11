import customtkinter as ctk
import sys
import os

# Import Main App
from app.ui.main_window import ProGUI
# Import Security
from app.core.security import run_security_check, verify_key_with_server, get_hwid

# --- CẤU HÌNH GIAO DIỆN ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

def resource_path(relative_path):
    if '__compiled__' in globals() or getattr(sys, 'frozen', False):
        base_path = os.path.dirname(os.path.abspath(sys.argv[0]))
    else:
        base_path = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base_path, relative_path)

class LoginPopup(ctk.CTkToplevel):
    """Popup đăng nhập (Modal Dialog)"""
    def __init__(self, master):
        super().__init__(master)
        self.title("Kích hoạt bản quyền")
        self.geometry("460x320")
        self.resizable(False, False)
        
        self.is_authenticated = False
        
        # Setup UI
        self.setup_ui()
        
        # Focus và Modal (Chặn tương tác cửa sổ cha)
        self.after(100, self.lift)
        self.after(200, self.focus_force)
        self.grab_set() # [Quan trọng] Biến cửa sổ này thành Modal
        
        # Căn giữa
        self.center_on_screen()
        
        # Sự kiện đóng
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # Sửa thành:
        icon_path = resource_path(os.path.join("app", "assets", "icon.ico"))
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)
            try:
                from ctypes import windll
                myappid = 'overlord.aireup.pro.v1' 
                windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except: pass
        else:
            print(f"⚠️ Warning: Không tìm thấy icon tại {icon_path}")

    def center_on_screen(self):
        self.update_idletasks()
        width = self.winfo_width()
        height = self.winfo_height()
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f"+{x}+{y}")

    def setup_ui(self):
        # Header
        ctk.CTkLabel(self, text="BẢO MẬT HỆ THỐNG", font=("Arial", 22, "bold"), text_color="#3498db").pack(pady=(25, 5))
        ctk.CTkLabel(self, text="Vui lòng nhập Key kích hoạt để mở khóa phần mềm", font=("Arial", 12), text_color="gray").pack(pady=(0, 15))
        
        # HWID Display
        hwid_frame = ctk.CTkFrame(self, fg_color="#2b2b2b", corner_radius=6)
        hwid_frame.pack(pady=5, padx=20, fill="x")
        
        ctk.CTkLabel(hwid_frame, text="Hardware ID:", font=("Arial", 11, "bold")).pack(side="left", padx=10, pady=8)
        self.lbl_hwid = ctk.CTkEntry(hwid_frame, width=220, font=("Consolas", 11), border_width=0, fg_color="transparent")
        self.lbl_hwid.insert(0, get_hwid())
        self.lbl_hwid.configure(state="readonly")
        self.lbl_hwid.pack(side="right", padx=10)
        
        # Key Entry
        self.entry_key = ctk.CTkEntry(self, width=320, height=40, placeholder_text="Nhập License Key (Ví dụ: VIP-XXXX)...", font=("Arial", 13))
        self.entry_key.pack(pady=20)
        self.entry_key.bind("<Return>", lambda e: self.btn_click()) # Enter để login
        
        # Button
        self.btn_active = ctk.CTkButton(self, text="KÍCH HOẠT", width=200, height=40, 
                                      font=("Arial", 14, "bold"), fg_color="#27ae60", hover_color="#2ecc71",
                                      command=self.btn_click)
        self.btn_active.pack(pady=5)
        
        # Status Label
        self.lbl_status = ctk.CTkLabel(self, text="", text_color="#e74c3c", font=("Arial", 11))
        self.lbl_status.pack(pady=5)

    def btn_click(self):
        key = self.entry_key.get().strip()
        if not key: return
            
        self.btn_active.configure(state="disabled", text="ĐANG KIỂM TRA...")
        self.lbl_status.configure(text="Đang đối chiếu HWID...", text_color="#f39c12")
        self.update() 
        
        # Gọi Security Check (Trả về thành công + Bytecode)
        success, result = verify_key_with_server(key)
        
        if success:
            # result lúc này chứa chuỗi core_blob (Bytecode)
            self.load_core_and_start(result)
        else:
            self.btn_active.configure(state="normal", text="KÍCH HOẠT")
            self.lbl_status.configure(text=f"❌ {result}", text_color="#e74c3c")

    def load_core_and_start(self, core_data):
        import marshal, types, base64
        try:
            # TIÊM RAM FILELESS: Nạp thuật toán AI từ Bytecode vừa lấy được
            b = marshal.loads(base64.b64decode(core_data))
            m = types.ModuleType('_core_sys_x64')
            exec(b, m.__dict__)
            sys.modules['_core_sys_x64'] = m
            
            self.lbl_status.configure(text="✔ Kích hoạt thành công!", text_color="#2ecc71")
            self.is_authenticated = True
            self.update()
            self.after(500, self.destroy)
        except Exception as e:
            self.lbl_status.configure(text=f"❌ Lỗi nạp Lõi: {e}", text_color="#e74c3c")
            self.btn_active.configure(state="normal", text="THỬ LẠI")

    def on_close(self):
        self.is_authenticated = False
        self.destroy()

# --- TIỂU XẢO: ÉP APP ĐỌC THƯ VIỆN TỪ VENV BÊN NGOÀI ---
def inject_venv_path():
    if getattr(sys, 'frozen', False) or '__compiled__' in globals():
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(os.path.dirname(__file__))
    venv_site = os.path.join(base_dir, "venv", "Lib", "site-packages")
    if os.path.exists(venv_site):
        sys.path.insert(0, venv_site)

if __name__ == "__main__":
    inject_venv_path()
    
    # Tạo config nếu chưa có
    if not os.path.exists("config.yaml") and os.path.exists("config.dist.yaml"):
        import shutil
        try: shutil.copy("config.dist.yaml", "config.yaml")
        except: pass
    from PyQt6.QtWidgets import QApplication
    # 1. Khởi tạo App Chính (Ẩn ngay lập tức)
    app = QApplication(sys.argv)
    window = ProGUI()
    window.showMaximized()
    sys.exit(app.exec())
    # app.withdraw() # Ẩn đi để chờ check security

    # # 2. Định nghĩa hàm khởi động quy trình
    # def start_application_flow():
    #     try:
    #         # Callback hiển thị Popup
    #         def show_login_popup():
    #             login_window = LoginPopup(master=app)
    #             app.wait_window(login_window) # Chờ Popup đóng
    #             return login_window.is_authenticated

    #         # Check Security
    #         is_authorized = run_security_check(show_login_popup)

    #         if is_authorized:
    #             print(">> Access Granted.")
    #             app.deiconify() # Hiện App chính
    #         else:
    #             print(">> Access Denied.")
    #             app.quit() # Thoát vòng lặp
    #             sys.exit() # Thoát hẳn
                
    #     except Exception as e:
    #         print(f"Error in flow: {e}")
    #         app.quit()

    # # 3. Lên lịch chạy Security Check SAU KHI Mainloop bắt đầu
    # # app.after(100, func) nghĩa là: Chờ 100ms sau khi mainloop chạy thì gọi func
    # app.after(100, start_application_flow)

    # # 4. Bắt đầu Vòng lặp Sự kiện (Phải gọi dòng này cửa sổ mới hiện và xử lý được logic)
    # try:
    #     app.mainloop()
    # except KeyboardInterrupt:
    #     app.quit()