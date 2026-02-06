import threading
import queue
import sys
import yaml
import os
import customtkinter as ctk
from pathlib import Path
from loguru import logger
from tkinter import filedialog, messagebox

from app import __version__
from app.core.config_loader import ConfigLoader
from app.core.engine import ProEngine

# --- CẤU HÌNH GIAO DIỆN ---
ctk.set_appearance_mode("Dark") 
ctk.set_default_color_theme("blue")

class LogSink:
    """Hứng log từ Loguru đưa vào Queue để hiển thị lên GUI"""
    def __init__(self, q): self.q = q
    def write(self, msg): self.q.put(msg)

class StreamToLogger:
    """Bắt cóc thanh tiến trình (tqdm) đưa vào log"""
    def __init__(self, level="INFO"):
        self.level = level
    def write(self, buffer):
        text = buffer.strip()
        if text: logger.opt(depth=1).log(self.level, text)
    def flush(self): pass

class ProGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        # 1. SETUP CỬA SỔ
        self.title(f"Pipeline Reup Pro v{__version__}")
        self.geometry("1280x850")
        self.minsize(1100, 750)
        
        # 2. DETECT HARDWARE
        self.hw_info = "Checking..."
        self.hw_color = "gray"
        self._check_hardware()

        # 3. LOAD CONFIG
        try:
            self.cfg = ConfigLoader.load()
        except Exception as e:
            messagebox.showerror("Config Error", f"Lỗi đọc config: {e}")
            sys.exit(1)

        # 4. SETUP LOGGING
        self.log_queue = queue.Queue()
        logger.remove()
        logger.add(LogSink(self.log_queue), format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")
        Path("logs").mkdir(exist_ok=True)
        logger.add("logs/session.log", rotation="5 MB", level="DEBUG")
        sys.stderr = StreamToLogger("INFO") 

        # 5. TRẠNG THÁI ENGINE
        self.engine = None
        self.is_running = False

        # 6. DỰNG GIAO DIỆN
        self._init_layout()
        self._load_values_to_ui()
        
        # 7. LOOP LOG
        self.after(100, self._poll_log)

    def _check_hardware(self):
        """Kiểm tra GPU để hiện lên GUI"""
        try:
            import torch
            if torch.cuda.is_available():
                gpu_name = torch.cuda.get_device_name(0)
                if len(gpu_name) > 25: gpu_name = gpu_name[:22] + "..."
                self.hw_info = f"GPU: {gpu_name}"
                self.hw_color = "#2ecc71" # Xanh lá
            else:
                self.hw_info = "MODE: CPU ONLY"
                self.hw_color = "#f1c40f" # Vàng
        except:
            self.hw_info = "MODE: UNKNOWN"
            self.hw_color = "gray"

    def _init_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # === SIDEBAR (Bên trái) ===
        self.sidebar = ctk.CTkFrame(self, width=320, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(6, weight=1)

        # Logo
        ctk.CTkLabel(self.sidebar, text="PIPELINE\nREUP PRO", font=ctk.CTkFont(size=26, weight="bold")).grid(row=0, column=0, padx=20, pady=(40, 10))
        
        # Info Box
        info_frame = ctk.CTkFrame(self.sidebar, fg_color="#2b2b2b")
        info_frame.grid(row=1, column=0, padx=15, pady=(0, 20), sticky="ew")
        ctk.CTkLabel(info_frame, text="● LICENSE: ACTIVE", text_color="#2ecc71", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(10, 2))
        ctk.CTkLabel(info_frame, text=f"● VERSION: {__version__}", text_color="#3498db", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=2)
        ctk.CTkLabel(info_frame, text=f"● {self.hw_info}", text_color=self.hw_color, font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(2, 10))

        # Buttons
        self.btn_run = ctk.CTkButton(self.sidebar, text="▶ BẮT ĐẦU XỬ LÝ", height=55, fg_color="#27ae60", hover_color="#2ecc71", font=ctk.CTkFont(size=15, weight="bold"), command=self._on_start)
        self.btn_run.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.btn_save = ctk.CTkButton(self.sidebar, text="💾 LƯU CẤU HÌNH", height=40, fg_color="#2980b9", hover_color="#3498db", command=self._on_save_config)
        self.btn_save.grid(row=3, column=0, padx=20, pady=10, sticky="ew")

        self.btn_open_out = ctk.CTkButton(self.sidebar, text="📂 MỞ THƯ MỤC OUTPUT", height=40, fg_color="#e67e22", hover_color="#d35400", command=self._open_output_folder)
        self.btn_open_out.grid(row=4, column=0, padx=20, pady=10, sticky="ew")

        # Status
        self.lbl_status = ctk.CTkLabel(self.sidebar, text="READY TO RUN", font=ctk.CTkFont(size=14, weight="bold"), text_color="gray")
        self.lbl_status.grid(row=7, column=0, padx=20, pady=30)

        # === MAIN CONTENT ===
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, padx=20, pady=10, sticky="nsew")

        self.tab_dashboard = self.tabview.add("📺 Dashboard")
        self.tab_io = self.tabview.add("📂 Input/Output")
        self.tab_ai = self.tabview.add("🧠 AI Config")
        self.tab_sub = self.tabview.add("🎨 Sub & Mix")
        self.tab_sys = self.tabview.add("⚙️ Hệ Thống")

        self._ui_dashboard()
        self._ui_io()
        self._ui_ai()
        self._ui_sub_mix()
        self._ui_sys()

    # --- TAB 1: DASHBOARD (CÓ NÚT XÓA LOG) ---
    def _ui_dashboard(self):
        self.tab_dashboard.grid_columnconfigure(0, weight=1)
        self.tab_dashboard.grid_rowconfigure(1, weight=1) # Dòng 1 là textbox log (giãn nở)

        # 1. Toolbar (Chứa Label và Nút Clear)
        toolbar = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent", height=40)
        toolbar.grid(row=0, column=0, sticky="ew", padx=5, pady=(0, 5))
        
        # Label tiêu đề
        ctk.CTkLabel(toolbar, text="LOG HOẠT ĐỘNG (REAL-TIME)", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        
        # Nút Xóa Log
        ctk.CTkButton(toolbar, text="🗑 XÓA LOG", width=100, height=30, fg_color="#c0392b", hover_color="#e74c3c", command=self._on_clear_log).pack(side="right", padx=5)

        # 2. Textbox Log
        self.console = ctk.CTkTextbox(self.tab_dashboard, font=("Consolas", 12), state="disabled", fg_color="#1e1e1e", text_color="#dcdcdc")
        self.console.grid(row=1, column=0, sticky="nsew", padx=5, pady=5)

    # --- TAB 2: INPUT / OUTPUT ---
    def _ui_io(self):
        frame = ctk.CTkScrollableFrame(self.tab_io, label_text="Đường dẫn thư mục")
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.ent_input = self._add_path_row(frame, "Input Videos Folder:", self.cfg.pipeline.input_videos, dir=True)
        self.ent_output = self._add_path_row(frame, "Final Output Folder:", self.cfg.pipeline.step6_final, dir=True)
        ctk.CTkLabel(frame, text="--- Các folder tạm (Workspace) ---", text_color="gray").pack(pady=(20,5))
        self.ent_wav = self._add_path_row(frame, "Step 1 (Wav):", self.cfg.pipeline.step1_wav, dir=True)
        self.ent_sep = self._add_path_row(frame, "Step 2 (Separated):", self.cfg.pipeline.step2_separated, dir=True)
        self.ent_srt = self._add_path_row(frame, "Step 3 (SRT Raw):", self.cfg.pipeline.step3_srt_raw, dir=True)

    # --- TAB 3: AI CONFIG ---
    def _ui_ai(self):
        frame = ctk.CTkScrollableFrame(self.tab_ai)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        self._add_header(frame, "Step 2: Tách Nhạc (Demucs)")
        self.combo_demucs_model = self._add_combo(frame, "Model:", ["htdemucs", "htdemucs_ft", "mdx_extra_q"], self.cfg.step2.model)
        self.combo_demucs_dev = self._add_combo(frame, "Device:", ["auto", "cuda", "cpu"], self.cfg.step2.device)
        self.entry_demucs_jobs = self._add_entry(frame, "Threads (Jobs):", self.cfg.step2.jobs)
        self._add_header(frame, "Step 3: Nhận diện Sub (SRT)")
        self.combo_srt_src = self._add_combo(frame, "Nguồn Sub:", ["voice", "image"], self.cfg.step3.srt_source)
        self.combo_whisper = self._add_combo(frame, "Whisper Model (Voice):", ["base", "small", "medium", "large-v2"], self.cfg.step3.model_size)
        self.entry_lang = self._add_entry(frame, "Ngôn ngữ nguồn (VD: zh, en, ja):", self.cfg.step3.language)
        self._add_header(frame, "Cấu hình OCR (Nếu chọn nguồn Sub là Image)")
        self.entry_ocr_lang = self._add_entry(frame, "Mã ngôn ngữ OCR (VD: ch, en):", self.cfg.step3.image_ocr_lang)
        self.slider_ocr_interval, _ = self._add_slider(frame, "Quét mỗi X giây:", 0.1, 2.0, self.cfg.step3.image_frame_interval, is_float=True)
        self._add_header(frame, "Step 4: Dịch thuật")
        self.entry_target_lang = self._add_entry(frame, "Ngôn ngữ đích (VD: vi, en):", self.cfg.step4.target_lang)

    # --- TAB 4: SUB & MIX ---
    def _ui_sub_mix(self):
        frame = ctk.CTkScrollableFrame(self.tab_sub)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        self._add_header(frame, "Step 5: Giao diện Subtitle")
        self.entry_font_size = self._add_entry(frame, "Cỡ chữ:", self.cfg.step5.font_size)
        self.entry_font_path = self._add_path_row(frame, "Font chữ (.ttf):", self.cfg.step5.font_path, dir=False)
        self.entry_color = self._add_entry(frame, "Màu chữ (Hex ASS &HAABBGGRR):", str(self.cfg.step5.text_color))
        ctk.CTkLabel(frame, text="Vùng quét/che sub (ROI Y):").pack(anchor="w", padx=10, pady=5)
        self.slider_roi_start, _ = self._add_slider(frame, "Bắt đầu (Top %):", 0.0, 1.0, self.cfg.step5.roi_y_start, is_float=True)
        self.slider_roi_end, _ = self._add_slider(frame, "Kết thúc (Bottom %):", 0.0, 1.0, self.cfg.step5.roi_y_end, is_float=True)
        self._add_header(frame, "Step 6: TTS & Mix")
        self.entry_tts_lang = self._add_entry(frame, "Mã ngôn ngữ đọc (gTTS):", self.cfg.step6.tts_lang)
        self.slider_vol, _ = self._add_slider(frame, "Âm lượng nhạc nền (dB):", -50, 0, self.cfg.step6.bg_volume, is_float=False)

    # --- TAB 5: SYSTEM ---
    def _ui_sys(self):
        frame = ctk.CTkScrollableFrame(self.tab_sys)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.ent_ffmpeg = self._add_path_row(frame, "Đường dẫn FFmpeg:", self.cfg.ffmpeg_bin or "", dir=False)
        self._add_header(frame, "API Keys (Gemini - Dịch B4)")
        self.txt_keys = ctk.CTkTextbox(frame, height=100)
        self.txt_keys.pack(fill="x", padx=10, pady=5)
        keys_str = ",\n".join(self.cfg.step4.gemini_api_keys)
        self.txt_keys.insert("0.0", keys_str)

    # ================= HELPERS =================
    def _add_header(self, parent, text):
        ctk.CTkLabel(parent, text=text, font=ctk.CTkFont(size=16, weight="bold"), text_color="#3498db").pack(anchor="w", padx=10, pady=(20, 5))

    def _add_path_row(self, parent, label, value, dir=True):
        f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(f, text=label, width=150, anchor="w").pack(side="left")
        ent = ctk.CTkEntry(f); ent.pack(side="left", fill="x", expand=True, padx=5); ent.insert(0, str(value))
        def pick():
            path = filedialog.askdirectory(title="Chọn thư mục") if dir else filedialog.askopenfilename(title="Chọn file")
            if path: ent.delete(0, "end"); ent.insert(0, path)
        ctk.CTkButton(f, text="📂", width=40, fg_color="#34495e", hover_color="#2c3e50", command=pick).pack(side="right")
        return ent

    def _add_entry(self, parent, label, value):
        f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(f, text=label, width=200, anchor="w").pack(side="left")
        ent = ctk.CTkEntry(f); ent.pack(side="left", fill="x", expand=True); ent.insert(0, str(value))
        return ent

    def _add_combo(self, parent, label, values, value):
        f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(f, text=label, width=200, anchor="w").pack(side="left")
        cb = ctk.CTkOptionMenu(f, values=values); cb.pack(side="left", fill="x", expand=True); cb.set(str(value))
        return cb

    def _add_slider(self, parent, label, vmin, vmax, val, is_float=False):
        f = ctk.CTkFrame(parent, fg_color="transparent"); f.pack(fill="x", padx=5, pady=2)
        ctk.CTkLabel(f, text=label, width=200, anchor="w").pack(side="left")
        lbl = ctk.CTkLabel(f, text=str(val), width=50); lbl.pack(side="right")
        def update(v): lbl.configure(text="{:.2f}".format(v) if is_float else "{:.0f}".format(v))
        sl = ctk.CTkSlider(f, from_=vmin, to=vmax, command=update); sl.set(val); sl.pack(side="left", fill="x", expand=True, padx=10)
        return sl, lbl

    def _load_values_to_ui(self): pass

    # --- XỬ LÝ LOG ---
    def _poll_log(self):
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.console.configure(state="normal")
                self.console.insert("end", msg + "\n")
                self.console.see("end")
                self.console.configure(state="disabled")
        except queue.Empty: pass
        self.after(100, self._poll_log)

    def _on_clear_log(self):
        """Xóa sạch nội dung trong textbox log"""
        self.console.configure(state="normal")
        self.console.delete("0.0", "end")
        self.console.configure(state="disabled")
        logger.info("🧹 Log đã được xóa.")

    # --- ACTIONS ---
    def _on_save_config(self):
        try:
            c = self.cfg
            c.pipeline.input_videos = Path(self.ent_input.get())
            c.pipeline.step6_final = Path(self.ent_output.get())
            c.step2.model = self.combo_demucs_model.get()
            c.step2.device = self.combo_demucs_dev.get()
            c.step2.jobs = int(self.entry_demucs_jobs.get())
            c.step3.srt_source = self.combo_srt_src.get()
            c.step3.model_size = self.combo_whisper.get()
            c.step3.language = self.entry_lang.get()
            c.step3.image_ocr_lang = self.entry_ocr_lang.get()
            c.step3.image_frame_interval = float(self.slider_ocr_interval.get())
            c.step4.target_lang = self.entry_target_lang.get()
            c.step5.font_size = int(self.entry_font_size.get())
            c.step5.font_path = self.entry_font_path.get()
            c.step5.text_color = self.entry_color.get()
            c.step5.roi_y_start = float(self.slider_roi_start.get())
            c.step5.roi_y_end = float(self.slider_roi_end.get())
            c.step6.tts_lang = self.entry_tts_lang.get()
            c.step6.bg_volume = float(self.slider_vol.get())
            c.ffmpeg_bin = self.ent_ffmpeg.get().strip() or None
            
            keys_raw = self.txt_keys.get("0.0", "end").strip()
            c.step4.gemini_api_keys = [k.strip() for k in keys_raw.split(",") if k.strip()]

            data = c.model_dump()
            def path_to_str(d):
                for k, v in d.items():
                    if isinstance(v, dict): path_to_str(v)
                    elif isinstance(v, Path): d[k] = str(v)
                return d
            data = path_to_str(data)
            
            with open("config.yaml", "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
            
            env_content = f"FFMPEG_BIN={c.ffmpeg_bin or ''}\nGEMINI_API_KEYS={','.join(c.step4.gemini_api_keys)}"
            with open(".env", "w", encoding="utf-8") as f: f.write(env_content)

            messagebox.showinfo("Thành công", "Đã lưu cấu hình!")
        except Exception as e:
            messagebox.showerror("Lỗi Lưu", str(e))

    def _open_output_folder(self):
        path = self.ent_output.get()
        if os.path.isdir(path): os.startfile(path)
        else: messagebox.showwarning("Lỗi", "Thư mục Output chưa tồn tại!")

    def _on_start(self):
        if self.is_running: return
        self._on_save_config()
        self.is_running = True
        self.btn_run.configure(state="disabled", text="ĐANG CHẠY...", fg_color="#e67e22")
        self.lbl_status.configure(text="PROCESSING...", text_color="#e67e22")
        threading.Thread(target=self._thread_pipeline, daemon=True).start()

    def _thread_pipeline(self):
        try:
            engine = ProEngine()
            engine.cfg = self.cfg
            engine.run()
            self.lbl_status.configure(text="COMPLETED", text_color="#2ecc71")
            messagebox.showinfo("Xong", "Đã xử lý xong!")
        except Exception as e:
            logger.exception("Pipeline Error")
            self.lbl_status.configure(text="ERROR", text_color="#e74c3c")
            messagebox.showerror("Lỗi", str(e))
        finally:
            self.is_running = False
            self.btn_run.configure(state="normal", text="▶ BẮT ĐẦU XỬ LÝ", fg_color="#27ae60")

if __name__ == "__main__":
    app = ProGUI()
    app.mainloop()