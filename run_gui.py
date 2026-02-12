import customtkinter as ctk
import sys
import os
from app.ui.main_window import ProGUI
from app.core.config_loader import ConfigLoader
# Import security module (File này sau sẽ bị cythonize)
from app.core.security import run_security_check, verify_key_with_server, get_hwid

# --- CẤU HÌNH GIAO DIỆN ---
ctk.set_appearance_mode("Dark")
ctk.set_default_color_theme("blue")

class LoginWindow(ctk.CTkToplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Kích hoạt bản quyền")
        self.geometry("450x300")
        self.resizable(False, False)
        
        # Căn giữa màn hình
        screen_width = self.winfo_screenwidth()
        screen_height = self.winfo_screenheight()
        x = (screen_width - 450) // 2
        y = (screen_height - 300) // 2
        self.geometry(f"+{x}+{y}")
        
        self.attributes("-topmost", True)
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.is_authenticated = False
        
        # UI Components
        ctk.CTkLabel(self, text="AI REUP TOOL PRO", font=("Arial", 24, "bold"), text_color="#3498db").pack(pady=(30, 10))
        
        hwid_frame = ctk.CTkFrame(self, fg_color="transparent")
        hwid_frame.pack(pady=5)
        ctk.CTkLabel(hwid_frame, text="Hardware ID:", font=("Arial", 12)).pack(side="left", padx=5)
        self.lbl_hwid = ctk.CTkEntry(hwid_frame, width=200, font=("Consolas", 11))
        self.lbl_hwid.insert(0, get_hwid())
        self.lbl_hwid.configure(state="readonly")
        self.lbl_hwid.pack(side="left")
        
        self.entry_key = ctk.CTkEntry(self, width=300, placeholder_text="Nhập License Key (Ví dụ: VIP-12345)...", height=40)
        self.entry_key.pack(pady=20)
        
        self.btn_active = ctk.CTkButton(self, text="KÍCH HOẠT NGAY", width=200, height=40, font=("Arial", 14, "bold"), command=self.btn_click)
        self.btn_active.pack(pady=10)
        
        self.lbl_status = ctk.CTkLabel(self, text="", text_color="red")
        self.lbl_status.pack()

    def btn_click(self):
        key = self.entry_key.get().strip()
        if not key:
            self.lbl_status.configure(text="Vui lòng nhập Key!", text_color="red")
            return
            
        self.btn_active.configure(state="disabled", text="Đang kiểm tra...")
        self.lbl_status.configure(text="Đang kết nối máy chủ...", text_color="yellow")
        self.update()
        
        # Gọi hàm check key từ security.py
        # Hàm này sẽ cấp Session Token vào RAM nếu thành công
        success, message = verify_key_with_server(key)
        
        if success:
            self.is_authenticated = True
            self.lbl_status.configure(text="Thành công!", text_color="green")
            self.update()
            self.after(500, self.destroy) # Đóng sau 0.5s để vào App
        else:
            self.btn_active.configure(state="normal", text="KÍCH HOẠT NGAY")
            self.lbl_status.configure(text=message, text_color="red")

    def on_close(self):
        sys.exit(0) # Đóng login thì tắt luôn app

class AppWrapper(ctk.CTk):
    """Lớp vỏ để quản lý luồng Login -> Main App"""
    def __init__(self):
        super().__init__()
        self.withdraw() # Ẩn cửa sổ chính tạm thời
        
        # Bước 1: Chạy Security Check
        # Hàm callback sẽ được gọi nếu chưa có Local License hoặc License không khớp
        is_ok = run_security_check(self.show_login_popup)
        
        if is_ok:
            # Bước 2: Nếu OK -> Mở giao diện chính ProGUI
            self.destroy() # Hủy lớp vỏ này đi
            app = ProGUI() # Khởi tạo App chính (Trong app/ui/main_window.py)
            app.mainloop() # Chạy App chính
        else:
            sys.exit()

    def show_login_popup(self):
        login_win = LoginWindow(self)
        self.wait_window(login_win) # Chờ người dùng thao tác xong
        return login_win.is_authenticated

# --- TIỂU XẢO: ÉP APP ĐỌC THƯ VIỆN TỪ VENV BÊN NGOÀI (Cho GĐ4) ---
# Hàm này giúp file .exe tìm được thư mục venv do Inno Setup cài sau này
def inject_venv_path():
    if getattr(sys, 'frozen', False) or '__compiled__' in globals():
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(os.path.dirname(__file__))
    venv_site_packages = os.path.join(base_dir, "venv", "Lib", "site-packages")
    if os.path.exists(venv_site_packages):
        sys.path.insert(0, venv_site_packages)

if __name__ == "__main__":
    inject_venv_path()
    
    # Kiểm tra config trước khi chạy
    if not os.path.exists("config.yaml"):
        if os.path.exists("config.dist.yaml"):
            import shutil
            shutil.copy("config.dist.yaml", "config.yaml")
    
    try:
        app_wrapper = AppWrapper()
        app_wrapper.mainloop()
    except Exception as e:
        print(f"Critical Error: {e}")
        input("Press Enter to exit...")