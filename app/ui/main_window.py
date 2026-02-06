import threading
import queue
import sys
import customtkinter as ctk
from pathlib import Path
from loguru import logger

from app.core.config_loader import ConfigLoader
from app.core.engine import ProEngine

# Cấu hình giao diện
ctk.set_appearance_mode("System")  # Modes: "System" (standard), "Dark", "Light"
ctk.set_default_color_theme("blue")  # Themes: "blue" (standard), "green", "dark-blue"

class LogSink:
    """Class này giúp hứng Log từ Engine đưa lên GUI"""
    def __init__(self, log_queue):
        self.log_queue = log_queue

    def write(self, message):
        self.log_queue.put(message)

class ProGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        # Setup Window
        self.title("Pipeline Reup Pro - Commercial Edition")
        self.geometry("1100x700")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Data & Config
        self.cfg = ConfigLoader.load()
        self.log_queue = queue.Queue()
        self.is_running = False

        # --- SETUP LOGGER ---
        # Hủy logger cũ, thêm sink mới trỏ về GUI
        logger.remove() 
        logger.add(LogSink(self.log_queue), format="{time:HH:mm:ss} | {level} | {message}")
        # Vẫn ghi file log để debug
        logger.add("logs/gui_session.log", rotation="5 MB")

        # --- LAYOUT ---
        self._create_sidebar()
        self._create_main_tabs()
        
        # Start Log Polling
        self.after(100, self._poll_log_queue)

    def _create_sidebar(self):
        self.sidebar = ctk.CTkFrame(self, width=200, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(self.sidebar, text="PIPELINE PRO", font=ctk.CTkFont(size=20, weight="bold")).grid(row=0, column=0, padx=20, pady=(20, 10))
        
        self.btn_run = ctk.CTkButton(self.sidebar, text="▶ START PROCESSING", fg_color="green", command=self._on_start)
        self.btn_run.grid(row=1, column=0, padx=20, pady=10)

        self.btn_stop = ctk.CTkButton(self.sidebar, text="⏹ STOP", fg_color="red", state="disabled", command=self._on_stop)
        self.btn_stop.grid(row=2, column=0, padx=20, pady=10)

        # Status
        self.lbl_status = ctk.CTkLabel(self.sidebar, text="Ready", text_color="gray")
        self.lbl_status.grid(row=5, column=0, padx=20, pady=10)

    def _create_main_tabs(self):
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=20, pady=20, sticky="nsew")

        self.tab_dashboard = self.tabview.add("Dashboard")
        self.tab_settings = self.tabview.add("Settings")
        self.tab_advanced = self.tabview.add("Advanced")

        # --- TAB 1: DASHBOARD (LOGS) ---
        self.tab_dashboard.grid_columnconfigure(0, weight=1)
        self.tab_dashboard.grid_rowconfigure(0, weight=1)
        
        self.log_box = ctk.CTkTextbox(self.tab_dashboard, font=("Consolas", 12))
        self.log_box.grid(row=0, column=0, sticky="nsew")
        self.log_box.configure(state="disabled")

        # --- TAB 2: SETTINGS (PATHS) ---
        self._build_settings_tab()

    def _build_settings_tab(self):
        # Input Path
        ctk.CTkLabel(self.tab_settings, text="Input Folder:").grid(row=0, column=0, sticky="w", padx=10, pady=5)
        self.entry_input = ctk.CTkEntry(self.tab_settings, width=400)
        self.entry_input.grid(row=0, column=1, padx=10, pady=5)
        self.entry_input.insert(0, str(self.cfg.pipeline.input_videos))
        ctk.CTkButton(self.tab_settings, text="Browse", width=50, command=lambda: self._browse(self.entry_input)).grid(row=0, column=2)

        # Output Path
        ctk.CTkLabel(self.tab_settings, text="Output Folder:").grid(row=1, column=0, sticky="w", padx=10, pady=5)
        self.entry_output = ctk.CTkEntry(self.tab_settings, width=400)
        self.entry_output.grid(row=1, column=1, padx=10, pady=5)
        self.entry_output.insert(0, str(self.cfg.pipeline.step6_final))

        # FFmpeg Path
        ctk.CTkLabel(self.tab_settings, text="FFmpeg Bin Path:").grid(row=2, column=0, sticky="w", padx=10, pady=5)
        self.entry_ffmpeg = ctk.CTkEntry(self.tab_settings, width=400, placeholder_text="Auto detect if empty")
        self.entry_ffmpeg.grid(row=2, column=1, padx=10, pady=5)
        if self.cfg.ffmpeg_bin:
            self.entry_ffmpeg.insert(0, str(self.cfg.ffmpeg_bin))

        # Save Button
        ctk.CTkButton(self.tab_settings, text="Save Config", command=self._save_config).grid(row=4, column=1, pady=20)

    def _browse(self, entry_widget):
        path = ctk.filedialog.askdirectory()
        if path:
            entry_widget.delete(0, "end")
            entry_widget.insert(0, path)

    def _save_config(self):
        # Cập nhật giá trị từ GUI vào Object Config
        # (Ở đây demo cập nhật path, bạn có thể map thêm các field khác)
        self.cfg.pipeline.input_videos = Path(self.entry_input.get())
        self.cfg.pipeline.step6_final = Path(self.entry_output.get())
        
        ff = self.entry_ffmpeg.get().strip()
        self.cfg.ffmpeg_bin = ff if ff else None

        # Lưu ngược ra file yaml (bạn cần viết hàm save trong ConfigLoader hoặc dump thủ công)
        # Tạm thời chỉ thông báo
        logger.info("Configuration saved (In Memory) - Ready to run.")
        # Nếu muốn lưu file thật: Bạn cần implement method save() trong ConfigLoader
    
    def _poll_log_queue(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.log_box.configure(state="normal")
                self.log_box.insert("end", msg + "\n")
                self.log_box.see("end")
                self.log_box.configure(state="disabled")
        except queue.Empty:
            pass
        self.after(100, self._poll_log_queue)

    def _run_pipeline_thread(self):
        try:
            logger.info("🚀 Starting Pipeline Engine...")
            self.lbl_status.configure(text="Running...", text_color="orange")
            
            # Khởi tạo Engine (Sẽ load config mới nhất)
            engine = ProEngine()
            # Override config nếu cần thiết từ GUI memory
            engine.cfg = self.cfg 
            
            engine.run()
            
            logger.success("🏁 Pipeline Finished Successfully.")
            self.lbl_status.configure(text="Completed", text_color="green")
        except Exception as e:
            logger.exception(f"🔥 GUI Error: {e}")
            self.lbl_status.configure(text="Error", text_color="red")
        finally:
            self.is_running = False
            self.btn_run.configure(state="normal")
            self.btn_stop.configure(state="disabled")

    def _on_start(self):
        if self.is_running: return
        self.is_running = True
        self.btn_run.configure(state="disabled")
        self.btn_stop.configure(state="normal")
        
        # Chạy trong Thread riêng để không đơ GUI
        t = threading.Thread(target=self._run_pipeline_thread, daemon=True)
        t.start()

    def _on_stop(self):
        # Việc dừng ThreadPoolExecutor đang chạy là rất khó.
        # Cách đơn giản nhất: set cờ exit và để engine tự check (cần sửa engine)
        # Hoặc restart app.
        logger.warning("🛑 Stop signal received (Waiting for current tasks to finish)...")
        self.lbl_status.configure(text="Stopping...", text_color="red")

if __name__ == "__main__":
    app = ProGUI()
    app.mainloop()