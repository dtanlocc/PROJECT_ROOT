import threading
import queue
import sys
import yaml
import os
import customtkinter as ctk
from pathlib import Path
from loguru import logger
from tkinter import filedialog, messagebox, colorchooser

from app import __version__
from app.core.config_loader import ConfigLoader
from app.core.engine import ProEngine, is_shm_dll_error, SHM_FIX_MESSAGE, is_meth_static_error, METH_FIX_MESSAGE

# 1. Hàm tìm đường dẫn tài nguyên
def resource_path(relative_path):
    try:
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")
    return os.path.join(base_path, relative_path)

def _ass_to_rgb(ass_str):
    if not ass_str or not isinstance(ass_str, str) or not str(ass_str).strip().upper().startswith("&H"):
        return (255, 255, 0)
    try:
        s = str(ass_str).strip().upper().replace("&H", "")
        if len(s) >= 6:
            r = int(s[6:8], 16) if len(s) >= 8 else 0
            g, b = int(s[4:6], 16), int(s[2:4], 16)
            return (r, g, b)
    except Exception:
        pass
    return (255, 255, 0)

def _ass_to_rgba_list(ass_str):
    if not ass_str or not isinstance(ass_str, str) or not str(ass_str).strip().upper().startswith("&H"):
        return [255, 255, 0, 255]
    try:
        s = str(ass_str).strip().upper().replace("&H", "")
        if len(s) >= 8:
            r = int(s[6:8], 16)
            g, b = int(s[4:6], 16), int(s[2:4], 16)
            a = 255 - int(s[0:2], 16)
            return [r, g, b, a]
    except Exception:
        pass
    return [255, 255, 0, 255]

def _set_entry(ent: ctk.CTkEntry, value):
    ent.delete(0, "end")
    ent.insert(0, str(value))

def _set_textbox(tb: ctk.CTkTextbox, value: str):
    tb.delete("0.0", "end")
    tb.insert("0.0", value)

def _rgb_hex(r: int, g: int, b: int) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(r) & 255, int(g) & 255, int(b) & 255)

# --- CẤU HÌNH GIAO DIỆN ---
ctk.set_appearance_mode("Dark") 
ctk.set_default_color_theme("blue")

class LogSink:
    def __init__(self, q): self.q = q
    def write(self, msg): self.q.put(msg)
    def flush(self): pass

class StreamToLogger:
    def __init__(self, level="INFO"):
        self.level = level
    def write(self, buffer):
        text = buffer.strip()
        if text: logger.opt(depth=1).log(self.level, text)
    def flush(self): pass

class ProGUI(ctk.CTk):
    def __init__(self):
        super().__init__()
        
        self.is_running = True
        self.poll_log_id = None 

        self.title(f"Pipeline Reup Pro v{__version__}")
        self.geometry("1280x850")
        self.minsize(1100, 750)
        
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        icon_path = resource_path(os.path.join("app", "assets", "icon.ico"))
        if os.path.exists(icon_path):
            self.iconbitmap(icon_path)
            try:
                from ctypes import windll
                myappid = 'mycompany.myproduct.subproduct.version' 
                windll.shell32.SetCurrentProcessExplicitAppUserModelID(myappid)
            except: pass
        
        self.hw_info = "Checking..."
        self.hw_color = "gray"
        self._check_hardware()
        self.last_stream_index = None
        
        try:
            self.cfg = ConfigLoader.load()
            self.install_mode = ConfigLoader.get_install_mode()
        except Exception as e:
            messagebox.showerror("Config Error", f"Lỗi đọc config: {e}")
            sys.exit(1)

        self.log_queue = queue.Queue()
        logger.remove()
        logger.add(LogSink(self.log_queue), format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>", level="INFO")
        Path("logs").mkdir(exist_ok=True)
        logger.add("logs/session.log", rotation="5 MB", level="DEBUG")
        sys.stderr = StreamToLogger("INFO") 

        self.engine = None
        self._progress_queue = queue.Queue()
        self._progress_display = {"completed": 0, "total": 0, "current": []}

        self._init_layout()
        self._load_values_to_ui()

        self.console.tag_config("info", foreground="#dcdcdc")      
        self.console.tag_config("success", foreground="#2ecc71")   
        self.console.tag_config("error", foreground="#e74c3c")     
        self.console.tag_config("warning", foreground="#f1c40f")   
        self.console.tag_config("debug", foreground="#7f8c8d")     
        self.console.tag_config("step", foreground="#3498db")      

        self.active_streams = {} 
        self.poll_log_id = self.after(100, self._safe_poll_log) 

    def on_closing(self):
        self.is_running = False 
        if self.poll_log_id:
            try: self.after_cancel(self.poll_log_id)
            except: pass
        self.destroy() 
        sys.exit(0) 

    def _safe_poll_log(self):
        if not self.is_running: return
        try:
            self._poll_log()
        except Exception:
            pass 
        finally:
            if self.is_running:
                try: self.poll_log_id = self.after(30, self._safe_poll_log)
                except: pass

    def _poll_log(self):
        if not self.winfo_exists(): return 
        try:
            while not self._progress_queue.empty():
                item = self._progress_queue.get_nowait()
                if item[0] == "progress":
                    _, (completed, total, current) = item
                    self._update_progress_ui(completed, total, current)
        except: pass

        try:
            if not self.console.winfo_exists(): return 
            self.console.configure(state="normal")
            has_new_log = False
            
            while not self.log_queue.empty():
                msg = self.log_queue.get_nowait()
                has_new_log = True
                
                if msg.startswith("[STREAM]"):
                    parts = [p.strip() for p in msg.split("|")]
                    if len(parts) >= 3:
                        video_id = parts[1]
                        content = " | ".join(parts[2:])
                        if video_id in self.active_streams:
                            idx = self.active_streams[video_id]
                            self.console.delete(idx, f"{idx} lineend + 1c")
                        self.active_streams[video_id] = self.console.index("end-1c")
                        self.console.insert("end", content + "\n", "debug")
                else:
                    tag = "info"
                    if "✅" in msg or "SUCCESS" in msg: tag = "success"
                    elif "❌" in msg or "ERROR" in msg: tag = "error"
                    elif "🚀" in msg or "STEP" in msg: tag = "step"
                    elif "⚠️" in msg or "WARNING" in msg: tag = "warning"
                    
                    for vid in list(self.active_streams.keys()):
                        if vid in msg: del self.active_streams[vid]
                    
                    self.console.insert("end", msg + "\n", tag)

            if has_new_log:
                self.console.see("end")
                if self.is_running: self.update_idletasks() 
                
        except Exception: pass
        finally:
            if self.is_running and self.console.winfo_exists():
                try: self.console.configure(state="disabled")
                except: pass

    def _check_hardware(self):
        try:
            import torch
            self._set_hw_from_torch(torch)
        except RuntimeError as e:
            if "already registered" in str(e):
                torch = __import__("sys").modules.get("torch")
                if torch is not None:
                    try: self._set_hw_from_torch(torch)
                    except Exception:
                        self.hw_info = "GPU: (PyTorch OK, type conflict)"
                        self.hw_color = "#2ecc71"
                else:
                    self.hw_info = "GPU: (PyTorch OK)"
                    self.hw_color = "#2ecc71"
            else:
                self._hw_error(e)
        except Exception as e:
            self._hw_error(e)

    def _set_hw_from_torch(self, torch):
        if torch.cuda.is_available():
            gpu_name = torch.cuda.get_device_name(0)
            if len(gpu_name) > 25: gpu_name = gpu_name[:22] + "..."
            self.hw_info = f"GPU: {gpu_name}"
            self.hw_color = "#2ecc71"
        else:
            self.hw_info = "MODE: CPU ONLY"
            self.hw_color = "#f1c40f"

    def _hw_error(self, e):
        logger.debug(f"PyTorch check failed: {type(e).__name__}: {e}")
        if is_shm_dll_error(e):
            self.hw_info = "PyTorch GPU lỗi (shm.dll)\n→ Chạy setup_venv_cpu.bat"
            self.hw_color = "#e67e22"
        else:
            short = str(e).split("\n")[0].strip()[:50]
            self.hw_info = f"PyTorch lỗi: {short}..." if len(str(e)) > 50 else f"PyTorch lỗi: {short}"
            self.hw_color = "#e74c3c"

    def _init_layout(self):
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self.sidebar = ctk.CTkFrame(self, width=320, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(7, weight=1)

        ctk.CTkLabel(self.sidebar, text="PIPELINE\nREUP PRO", font=ctk.CTkFont(size=26, weight="bold")).grid(row=0, column=0, padx=20, pady=(40, 10))
        
        info_frame = ctk.CTkFrame(self.sidebar, fg_color="#2b2b2b")
        info_frame.grid(row=1, column=0, padx=15, pady=(0, 20), sticky="ew")
        ctk.CTkLabel(info_frame, text="● LICENSE: ACTIVE", text_color="#2ecc71", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(10, 2))
        ctk.CTkLabel(info_frame, text=f"● VERSION: {__version__}", text_color="#3498db", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=2)
        install_label = "Chỉ CPU" if self.install_mode == "cpu" else ("GPU (có thể chọn CPU)" if self.install_mode == "both" else "GPU")
        ctk.CTkLabel(info_frame, text=f"● CÀI ĐẶT: {install_label}", text_color="#9b59b6", font=ctk.CTkFont(size=12, weight="bold")).pack(pady=2)
        ctk.CTkLabel(info_frame, text=f"● {self.hw_info}", text_color=self.hw_color, font=ctk.CTkFont(size=12, weight="bold")).pack(pady=(2, 10))

        self.btn_run = ctk.CTkButton(self.sidebar, text="▶ BẮT ĐẦU XỬ LÝ", height=55, fg_color="#27ae60", hover_color="#2ecc71", font=ctk.CTkFont(size=15, weight="bold"), command=self._on_start)
        self.btn_run.grid(row=2, column=0, padx=20, pady=10, sticky="ew")

        self.btn_save = ctk.CTkButton(self.sidebar, text="💾 LƯU CẤU HÌNH", height=40, fg_color="#2980b9", hover_color="#3498db", command=self._on_save_config)
        self.btn_save.grid(row=3, column=0, padx=20, pady=10, sticky="ew")

        self.btn_reset = ctk.CTkButton(self.sidebar, text="↩ PHỤC HỒI MẶC ĐỊNH", height=40, fg_color="#7f8c8d", hover_color="#95a5a6", command=self._on_reset_defaults)
        self.btn_reset.grid(row=4, column=0, padx=20, pady=10, sticky="ew")

        self.btn_open_out = ctk.CTkButton(self.sidebar, text="📂 MỞ THƯ MỤC OUTPUT", height=40, fg_color="#e67e22", hover_color="#d35400", command=self._open_output_folder)
        self.btn_open_out.grid(row=5, column=0, padx=20, pady=10, sticky="ew")

        self.lbl_status = ctk.CTkLabel(self.sidebar, text="READY TO RUN", font=ctk.CTkFont(size=14, weight="bold"), text_color="gray")
        self.lbl_status.grid(row=8, column=0, padx=20, pady=30)

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

    def _ui_dashboard(self):
        self.tab_dashboard.grid_columnconfigure(0, weight=1)
        self.tab_dashboard.grid_rowconfigure(2, weight=1)

        self.progress_frame = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent")
        self.progress_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 5))
        self.progress_frame.grid_columnconfigure(1, weight=1)
        self.lbl_progress = ctk.CTkLabel(self.progress_frame, text="Video 0/0 — Sẵn sàng", font=ctk.CTkFont(weight="bold"), text_color="#3498db")
        self.lbl_progress.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=2)
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=14, corner_radius=7, fg_color="#2b2b2b", progress_color="#3498db")
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=2)
        self.progress_bar.set(0)

        toolbar = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent", height=40)
        toolbar.grid(row=1, column=0, sticky="ew", padx=5, pady=(5, 5))
        ctk.CTkLabel(toolbar, text="LOG HOẠT ĐỘNG (REAL-TIME)", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="🗑 XÓA LOG", width=100, height=30, fg_color="#c0392b", hover_color="#e74c3c", command=self._on_clear_log).pack(side="right", padx=5)

        self.console = ctk.CTkTextbox(self.tab_dashboard, font=("Consolas", 12, "bold"), state="disabled", fg_color="#1e1e1e", text_color="#dcdcdc")
        self.console.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)
        
    def _ui_io(self):
        frame = ctk.CTkScrollableFrame(self.tab_io, label_text="Đường dẫn thư mục")
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        self.ent_input = self._add_path_row(frame, "Input Videos Folder:", self.cfg.pipeline.input_videos, dir=True)
        self.ent_output = self._add_path_row(frame, "Final Output Folder:", self.cfg.pipeline.step6_final, dir=True)
        ctk.CTkLabel(frame, text="--- Các folder tạm (Workspace) ---", text_color="gray").pack(pady=(20,5))
        self.ent_wav = self._add_path_row(frame, "Step 1 (Wav):", self.cfg.pipeline.step1_wav, dir=True)
        self.ent_sep = self._add_path_row(frame, "Step 2 (Separated):", self.cfg.pipeline.step2_separated, dir=True)
        self.ent_srt = self._add_path_row(frame, "Step 3 (SRT Raw):", self.cfg.pipeline.step3_srt_raw, dir=True)

    def _ui_ai(self):
        frame = ctk.CTkScrollableFrame(self.tab_ai)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        self._add_header(frame, "Step 2: Tách Nhạc (Demucs)")
        self.combo_demucs_model = self._add_combo(frame, "Model:", ["htdemucs", "htdemucs_ft", "mdx_extra_q"], self.cfg.step2.model)
        demucs_dev_values = ["cpu"] if self.install_mode == "cpu" else ["auto", "cuda", "cpu"]
        self.combo_demucs_dev = self._add_combo(frame, "Device:", demucs_dev_values, self.cfg.step2.device)
        self.entry_demucs_jobs = self._add_entry(frame, "Threads (Jobs):", self.cfg.step2.jobs)
        self.entry_demucs_shifts = self._add_entry(frame, "Shifts (chất lượng tách, VD: 2):", getattr(self.cfg.step2, "shifts", 2))
        self.combo_demucs_output = self._add_combo(frame, "Xuất audio:", ["int24", "float32"], "float32" if getattr(self.cfg.step2, "output_float32", False) else "int24")
        
        self._add_header(frame, "Step 3: Nhận diện Sub (SRT)")
        self.combo_srt_src = self._add_combo(frame, "Nguồn Sub:", ["voice", "image"], self.cfg.step3.srt_source)
        self.combo_whisper = self._add_combo(frame, "Whisper Model (Voice):", ["base", "small", "medium", "large-v2"], self.cfg.step3.model_size)
        self.entry_lang = self._add_entry(frame, "Ngôn ngữ nguồn (VD: zh, en, ja):", self.cfg.step3.language)
        self.entry_cpu_threads = self._add_entry(frame, "Whisper CPU threads (VD: 1):", getattr(self.cfg.step3, "cpu_threads", 1))
        
        self._add_header(frame, "Cấu hình OCR (Nếu chọn nguồn Sub là Image)")
        self.entry_ocr_lang = self._add_entry(frame, "Mã ngôn ngữ OCR (VD: ch, en):", self.cfg.step3.image_ocr_lang)
        self.entry_ocr_step_frames = self._add_entry(frame, "Cứ mỗi N frame lấy 1 lần (VD: 10):", getattr(self.cfg.step3, "image_step_frames", 10))
        
        self._add_header(frame, "Step 4: Dịch thuật (Gemini)")
        self.entry_step4_model = self._add_entry(frame, "Model Gemini (VD: gemini-2.5-flash):", self.cfg.step4.model_name)
        self.entry_source_lang = self._add_entry(frame, "Ngôn ngữ nguồn (VD: zh-CN, en):", self.cfg.step4.source_lang)
        self.entry_target_lang = self._add_entry(frame, "Ngôn ngữ đích (VD: vi, en):", self.cfg.step4.target_lang)
        self.entry_max_lines_chunk = self._add_entry(frame, "Số dòng tối đa mỗi chunk (VD: 250):", getattr(self.cfg.step4, "max_lines_per_chunk", 250))

    def _ui_sub_mix(self):
        frame = ctk.CTkScrollableFrame(self.tab_sub)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        
        # --- PHẦN 1: VIDEO & SUBTITLE ---
        self._add_header(frame, "Phần 1: Cấu hình Phụ đề (Subtitle)")
        self.entry_font_size = self._add_entry(frame, "Cỡ chữ:", self.cfg.step5.font_size)
        self.entry_max_words_per_line = self._add_entry(frame, "Số từ tối đa mỗi dòng (VD: 10):", getattr(self.cfg.step5, "max_words_per_line", 10))
        self.entry_font_path = self._add_path_row(frame, "Font chữ (.ttf):", self.cfg.step5.font_path, dir=False)

        # Hàng: Màu chữ
        tr, tg, tb = _ass_to_rgb(self.cfg.step5.text_color)
        self.step5_text_rgb = (tr, tg, tb)
        row_text = ctk.CTkFrame(frame, fg_color="transparent")
        row_text.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(row_text, text="Màu chữ (Text):", width=300, anchor="w").pack(side="left")
        
        self.preview_text = ctk.CTkFrame(row_text, width=80, height=28, fg_color=_rgb_hex(tr, tg, tb), corner_radius=6)
        self.preview_text.pack(side="left", padx=(0, 10))
        self.preview_text.pack_propagate(False) # Chống co lại
        
        def pick_text_color():
            rgb_hex = _rgb_hex(*self.step5_text_rgb)
            result = colorchooser.askcolor(initialcolor=rgb_hex, title="Chọn màu chữ")
            if result and result[0] is not None:
                r, g, b = [int(x) for x in result[0]]
                self.step5_text_rgb = (r, g, b)
                self.preview_text.configure(fg_color=_rgb_hex(r, g, b))
        ctk.CTkButton(row_text, text="🎨 Chọn màu", width=120, fg_color="#34495e", hover_color="#2c3e50", command=pick_text_color).pack(side="left")

        # Hàng: Màu viền
        or_, og, ob = _ass_to_rgb(self.cfg.step5.outline_color)
        self.step5_outline_rgb = (or_, og, ob)
        row_out = ctk.CTkFrame(frame, fg_color="transparent")
        row_out.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(row_out, text="Màu viền (Outline):", width=300, anchor="w").pack(side="left")
        
        self.preview_outline = ctk.CTkFrame(row_out, width=80, height=28, fg_color=_rgb_hex(or_, og, ob), corner_radius=6)
        self.preview_outline.pack(side="left", padx=(0, 10))
        self.preview_outline.pack_propagate(False)
        
        def pick_outline_color():
            rgb_hex = _rgb_hex(*self.step5_outline_rgb)
            result = colorchooser.askcolor(initialcolor=rgb_hex, title="Chọn màu viền")
            if result and result[0] is not None:
                r, g, b = [int(x) for x in result[0]]
                self.step5_outline_rgb = (r, g, b)
                self.preview_outline.configure(fg_color=_rgb_hex(r, g, b))
        ctk.CTkButton(row_out, text="🎨 Chọn màu", width=120, fg_color="#34495e", hover_color="#2c3e50", command=pick_outline_color).pack(side="left")

        ctk.CTkLabel(frame, text="Vùng quét/che sub (ROI Y):", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(15, 0))
        self.slider_roi_start, _ = self._add_slider(frame, "↳ Bắt đầu (Top %):", 0.0, 1.0, self.cfg.step5.roi_y_start, is_float=True)
        self.slider_roi_end, _ = self._add_slider(frame, "↳ Kết thúc (Bottom %):", 0.0, 1.0, self.cfg.step5.roi_y_end, is_float=True)
        
        # --- PHẦN 2: ÂM THANH & MIX ---
        self._add_header(frame, "Phần 2: Cấu hình Âm thanh (Audio & Mix)")
        self.entry_tts_lang = self._add_entry(frame, "Mã ngôn ngữ đọc (TTS):", self.cfg.step6.tts_lang)
        
        ctk.CTkLabel(frame, text="Bảng điều chỉnh Mixer:", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(15, 0))
        self.entry_tts_volume = self._add_entry(frame, "↳ Âm lượng giọng AI đọc (VD: 1.4):", getattr(self.cfg.step6, "tts_volume", 1.4))
        self.slider_vol, _ = self._add_slider(frame, "↳ Âm lượng Nhạc nền (dB):", -50, 0, self.cfg.step6.bg_volume, is_float=False)
        self.slider_orig_voice_vol, _ = self._add_slider(frame, "↳ Âm lượng Giọng gốc (1=100%, 0=Tắt):", 0.0, 2.0, getattr(self.cfg.step6, "original_voice_volume", 0.2), is_float=True)
        
        ctk.CTkLabel(frame, text="Hiệu chỉnh giọng AI (TTS):", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(15, 0))
        self.slider_pitch, _ = self._add_slider(frame, "↳ Pitch (1.0 = chuẩn, 1.2 = cao):", 0.8, 1.5, getattr(self.cfg.step6, "pitch_factor", 1.0), is_float=True)
        self.entry_min_words_tts = self._add_entry(frame, "↳ Min từ (0 = tắt lặp câu ngắn):", getattr(self.cfg.step6, "min_words_for_tts", 0))
        self.entry_speedup_short = self._add_entry(frame, "↳ Tốc độ x khi TTS ngắn (VD: 1.5):", getattr(self.cfg.step6, "speedup_when_short", 1.5))

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
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=10, pady=4)
        # Chốt cứng Label 300px
        ctk.CTkLabel(f, text=label, width=300, anchor="w").pack(side="left")
        
        ent = ctk.CTkEntry(f)
        # Dành chỗ 50px cho nút bên phải, entry tự giãn
        ent.pack(side="left", fill="x", expand=True, padx=(0, 10))
        ent.insert(0, str(value))
        
        def pick():
            path = filedialog.askdirectory(title="Chọn thư mục") if dir else filedialog.askopenfilename(title="Chọn file")
            if path: ent.delete(0, "end"); ent.insert(0, path)
            
        ctk.CTkButton(f, text="📂", width=50, fg_color="#34495e", hover_color="#2c3e50", command=pick).pack(side="right")
        return ent

    def _add_entry(self, parent, label, value):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(f, text=label, width=300, anchor="w").pack(side="left")
        
        ent = ctk.CTkEntry(f)
        # padding phải 60px để bằng với các hàng có nút/slider
        ent.pack(side="left", fill="x", expand=True, padx=(0, 60))
        ent.insert(0, str(value))
        return ent

    def _add_combo(self, parent, label, values, value):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(f, text=label, width=300, anchor="w").pack(side="left")
        
        cb = ctk.CTkOptionMenu(f, values=values)
        # padding phải 60px
        cb.pack(side="left", fill="x", expand=True, padx=(0, 60))
        cb.set(str(value))
        return cb

    def _add_slider(self, parent, label, vmin, vmax, val, is_float=False):
        f = ctk.CTkFrame(parent, fg_color="transparent")
        f.pack(fill="x", padx=10, pady=4)
        ctk.CTkLabel(f, text=label, width=300, anchor="w").pack(side="left")
        
        def update(v): lbl.configure(text="{:.2f}".format(v) if is_float else "{:.0f}".format(v))
        
        sl = ctk.CTkSlider(f, from_=vmin, to=vmax, command=update)
        sl.set(val)
        sl.pack(side="left", fill="x", expand=True, padx=(0, 10))
        
        # Chốt cứng Label hiện số 50px sát lề phải
        lbl = ctk.CTkLabel(f, text=str(val), width=50, anchor="e")
        lbl.pack(side="right")
        return sl, lbl

    def _load_values_to_ui(self): pass

    def _apply_cfg_to_ui(self):
        c = self.cfg
        _set_entry(self.ent_input, c.pipeline.input_videos)
        _set_entry(self.ent_output, c.pipeline.step6_final)
        self.combo_demucs_model.set(str(c.step2.model))
        self.combo_demucs_dev.set(str(c.step2.device))
        _set_entry(self.entry_demucs_jobs, c.step2.jobs)
        _set_entry(self.entry_demucs_shifts, getattr(c.step2, "shifts", 2))
        self.combo_demucs_output.set("float32" if getattr(c.step2, "output_float32", False) else "int24")
        self.combo_srt_src.set(str(c.step3.srt_source))
        self.combo_whisper.set(str(c.step3.model_size))
        _set_entry(self.entry_lang, c.step3.language)
        _set_entry(self.entry_cpu_threads, getattr(c.step3, "cpu_threads", 1))
        _set_entry(self.entry_ocr_lang, c.step3.image_ocr_lang)
        _set_entry(self.entry_ocr_step_frames, getattr(c.step3, "image_step_frames", 10))
        _set_entry(self.entry_step4_model, c.step4.model_name)
        _set_entry(self.entry_source_lang, c.step4.source_lang)
        _set_entry(self.entry_target_lang, c.step4.target_lang)
        _set_entry(self.entry_max_lines_chunk, getattr(c.step4, "max_lines_per_chunk", 250))
        _set_entry(self.entry_font_size, c.step5.font_size)
        _set_entry(self.entry_max_words_per_line, getattr(c.step5, "max_words_per_line", 10))
        _set_entry(self.entry_font_path, c.step5.font_path)
        tr, tg, tb = _ass_to_rgb(c.step5.text_color)
        or_, og, ob = _ass_to_rgb(c.step5.outline_color)
        self.step5_text_rgb = (tr, tg, tb)
        self.step5_outline_rgb = (or_, og, ob)
        self.preview_text.configure(fg_color=_rgb_hex(tr, tg, tb))
        self.preview_outline.configure(fg_color=_rgb_hex(or_, og, ob))
        self.slider_roi_start.set(float(c.step5.roi_y_start))
        self.slider_roi_end.set(float(c.step5.roi_y_end))
        
        # Load Data Step 6
        _set_entry(self.entry_tts_lang, c.step6.tts_lang)
        self.slider_vol.set(float(c.step6.bg_volume))
        self.slider_pitch.set(float(getattr(c.step6, "pitch_factor", 1.0)))
        
        self.slider_orig_voice_vol.set(float(getattr(c.step6, "original_voice_volume", 0.2)))
        
        _set_entry(self.entry_tts_volume, getattr(c.step6, "tts_volume", 1.4))
        _set_entry(self.entry_min_words_tts, getattr(c.step6, "min_words_for_tts", 0))
        _set_entry(self.entry_speedup_short, getattr(c.step6, "speedup_when_short", 1.5))
        _set_entry(self.ent_ffmpeg, c.ffmpeg_bin or "")
        _set_textbox(self.txt_keys, ",\n".join(c.step4.gemini_api_keys))

    def _on_reset_defaults(self):
        if self.is_running_pipeline:
            messagebox.showwarning("Đang chạy", "Hãy đợi pipeline chạy xong rồi reset.")
            return
        try:
            self.cfg = ConfigLoader.load("config.dist.yaml")
            self._apply_cfg_to_ui()
            messagebox.showinfo("Xong", "Đã phục hồi cài đặt mặc định (config.dist.yaml).")
        except Exception as e:
            messagebox.showerror("Lỗi reset", str(e))

    def _update_progress_ui(self, completed: int, total: int, current: list):
        self._progress_display["completed"] = completed
        self._progress_display["total"] = total
        self._progress_display["current"] = current
        if total <= 0:
            self.progress_bar.set(0)
            self.lbl_progress.configure(text="Video 0/0 — Sẵn sàng")
            return
        pct = completed / total
        self.progress_bar.set(pct)
        cur_text = " | ".join(current) if current else "Đang chờ..."
        self.lbl_progress.configure(text=f"Video {completed}/{total} ({int(pct * 100)}%) — {cur_text}")

    def _on_clear_log(self):
        self.console.configure(state="normal")
        self.console.delete("0.0", "end")
        self.console.configure(state="disabled")
        logger.info("🧹 Log đã được xóa.")

    def _on_save_config(self):
        try:
            c = self.cfg
            c.pipeline.input_videos = Path(self.ent_input.get())
            c.pipeline.step6_final = Path(self.ent_output.get())
            c.step2.model = self.combo_demucs_model.get()
            c.step2.device = self.combo_demucs_dev.get()
            c.step2.jobs = int(self.entry_demucs_jobs.get() or 1)
            try: c.step2.shifts = max(1, int(self.entry_demucs_shifts.get().strip() or 2))
            except: c.step2.shifts = 2
            c.step2.output_float32 = self.combo_demucs_output.get() == "float32"
            c.step3.srt_source = self.combo_srt_src.get()
            c.step3.model_size = self.combo_whisper.get()
            c.step3.language = self.entry_lang.get()
            try: c.step3.cpu_threads = max(1, int(self.entry_cpu_threads.get().strip() or 1))
            except: c.step3.cpu_threads = 1
            c.step3.image_ocr_lang = self.entry_ocr_lang.get()
            try: c.step3.image_step_frames = max(1, int(self.entry_ocr_step_frames.get().strip() or 10))
            except: c.step3.image_step_frames = 10
            c.step4.model_name = self.entry_step4_model.get().strip() or "gemini-2.5-flash"
            c.step4.source_lang = self.entry_source_lang.get().strip() or "zh-CN"
            c.step4.target_lang = self.entry_target_lang.get()
            try: c.step4.max_lines_per_chunk = max(1, int(self.entry_max_lines_chunk.get().strip() or 250))
            except: c.step4.max_lines_per_chunk = 250
            c.step5.font_size = int(self.entry_font_size.get() or 45)
            try: c.step5.max_words_per_line = max(1, int(self.entry_max_words_per_line.get().strip() or 10))
            except: c.step5.max_words_per_line = 10
            c.step5.font_path = self.entry_font_path.get()
            c.step5.text_color = [*self.step5_text_rgb, 255]
            c.step5.outline_color = [*self.step5_outline_rgb, 255]
            c.step5.roi_y_start = float(self.slider_roi_start.get())
            c.step5.roi_y_end = float(self.slider_roi_end.get())
            
            # Lưu Data Step 6
            c.step6.tts_lang = self.entry_tts_lang.get()
            c.step6.bg_volume = float(self.slider_vol.get())
            try: c.step6.pitch_factor = float(self.slider_pitch.get())
            except: c.step6.pitch_factor = 1.0
                
            try: c.step6.original_voice_volume = float(self.slider_orig_voice_vol.get())
            except: c.step6.original_voice_volume = 0.2
                
            try: c.step6.tts_volume = float(self.entry_tts_volume.get().strip() or 1.4)
            except: c.step6.tts_volume = 1.4
            try: c.step6.min_words_for_tts = max(0, int(self.entry_min_words_tts.get().strip() or 0))
            except: c.step6.min_words_for_tts = 0
            try: c.step6.speedup_when_short = max(0.5, float(self.entry_speedup_short.get().strip() or 1.5))
            except: c.step6.speedup_when_short = 1.5
            
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
            if "step5" in data:
                for key in ("text_color", "outline_color"):
                    if key in data["step5"] and isinstance(data["step5"][key], str) and str(data["step5"][key]).strip().upper().startswith("&H"):
                        data["step5"][key] = _ass_to_rgba_list(data["step5"][key])

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
        if self.is_running_pipeline: return
        self._on_save_config()
        self.is_running_pipeline = True
        self.btn_run.configure(state="disabled", text="ĐANG CHẠY...", fg_color="#e67e22")
        self.lbl_status.configure(text="PROCESSING...", text_color="#e67e22")
        threading.Thread(target=self._thread_pipeline, daemon=True).start()

    def _thread_pipeline(self):
        def on_progress(completed, total, current):
            self._progress_queue.put(("progress", (completed, total, current)))

        try:
            from app.core.config_loader import ConfigLoader
            self.cfg = ConfigLoader.load() 
            
            engine = ProEngine()
            engine.cfg = self.cfg 
            
            engine._s2 = None
            engine._s3 = None
            
            engine.run(on_progress=on_progress)
            self._progress_queue.put(("progress", (engine._progress_total if hasattr(engine, '_progress_total') else 0, engine._progress_total if hasattr(engine, '_progress_total') else 0, [])))
            self.lbl_status.configure(text="COMPLETED", text_color="#2ecc71")
            messagebox.showinfo("Xong", "Đã xử lý xong!")
        except Exception as e:
            logger.exception("Pipeline Error")
            self.lbl_status.configure(text="ERROR", text_color="#e74c3c")
            msg = str(e)
            if is_shm_dll_error(e): msg = msg + "\n\n" + SHM_FIX_MESSAGE
            elif is_meth_static_error(e): msg = msg + "\n\n" + METH_FIX_MESSAGE
            messagebox.showerror("Lỗi", msg)
        finally:
            self.is_running_pipeline = False
            self.btn_run.configure(state="normal", text="▶ BẮT ĐẦU XỬ LÝ", fg_color="#27ae60")
            self._update_progress_ui(0, 0, [])

    is_running_pipeline = False 

if __name__ == "__main__":
    app = ProGUI()
    app.mainloop()