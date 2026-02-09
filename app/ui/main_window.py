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


def _ass_to_rgb(ass_str):
    """Parse ASS &HAABBGGRR -> (r, g, b). Config lưu ASS sau khi load."""
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
    """Parse ASS &HAABBGGRR -> [r, g, b, a] để ghi YAML dạng list."""
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

        # 5. TRẠNG THÁI ENGINE & PROGRESS
        self.engine = None
        self.is_running = False
        self._progress_queue = queue.Queue()
        self._progress_display = {"completed": 0, "total": 0, "current": []}

        # 6. DỰNG GIAO DIỆN
        self._init_layout()
        self._load_values_to_ui()
        
        # 7. LOOP LOG
        self.after(100, self._poll_log)

    def _check_hardware(self):
        """Kiểm tra GPU/PyTorch để hiện lên sidebar."""
        try:
            import torch
            self._set_hw_from_torch(torch)
        except RuntimeError as e:
            if "already registered" in str(e):
                # PyTorch type da duoc dang ky boi process khac (vd plugin) - thu lay torch tu sys.modules
                torch = __import__("sys").modules.get("torch")
                if torch is not None:
                    try:
                        self._set_hw_from_torch(torch)
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
            if len(gpu_name) > 25:
                gpu_name = gpu_name[:22] + "..."
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

        # === SIDEBAR (Bên trái) ===
        self.sidebar = ctk.CTkFrame(self, width=320, corner_radius=0)
        self.sidebar.grid(row=0, column=0, sticky="nsew")
        self.sidebar.grid_rowconfigure(7, weight=1)

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

        self.btn_reset = ctk.CTkButton(self.sidebar, text="↩ PHỤC HỒI MẶC ĐỊNH", height=40, fg_color="#7f8c8d", hover_color="#95a5a6", command=self._on_reset_defaults)
        self.btn_reset.grid(row=4, column=0, padx=20, pady=10, sticky="ew")

        self.btn_open_out = ctk.CTkButton(self.sidebar, text="📂 MỞ THƯ MỤC OUTPUT", height=40, fg_color="#e67e22", hover_color="#d35400", command=self._open_output_folder)
        self.btn_open_out.grid(row=5, column=0, padx=20, pady=10, sticky="ew")

        # Status
        self.lbl_status = ctk.CTkLabel(self.sidebar, text="READY TO RUN", font=ctk.CTkFont(size=14, weight="bold"), text_color="gray")
        self.lbl_status.grid(row=8, column=0, padx=20, pady=30)

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

    # --- TAB 1: DASHBOARD (PROGRESS + LOG) ---
    def _ui_dashboard(self):
        self.tab_dashboard.grid_columnconfigure(0, weight=1)
        self.tab_dashboard.grid_rowconfigure(2, weight=1)

        # 1. Thanh tiến trình tổng (Video X/Y, bước hiện tại)
        self.progress_frame = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent")
        self.progress_frame.grid(row=0, column=0, sticky="ew", padx=5, pady=(5, 5))
        self.progress_frame.grid_columnconfigure(1, weight=1)
        self.lbl_progress = ctk.CTkLabel(self.progress_frame, text="Video 0/0 — Sẵn sàng", font=ctk.CTkFont(weight="bold"), text_color="#3498db")
        self.lbl_progress.grid(row=0, column=0, columnspan=2, sticky="w", padx=5, pady=2)
        self.progress_bar = ctk.CTkProgressBar(self.progress_frame, height=14, corner_radius=7, fg_color="#2b2b2b", progress_color="#3498db")
        self.progress_bar.grid(row=1, column=0, columnspan=2, sticky="ew", padx=5, pady=2)
        self.progress_bar.set(0)

        # 2. Toolbar (Label + Nút Clear)
        toolbar = ctk.CTkFrame(self.tab_dashboard, fg_color="transparent", height=40)
        toolbar.grid(row=1, column=0, sticky="ew", padx=5, pady=(5, 5))
        ctk.CTkLabel(toolbar, text="LOG HOẠT ĐỘNG (REAL-TIME)", font=ctk.CTkFont(weight="bold")).pack(side="left", padx=5)
        ctk.CTkButton(toolbar, text="🗑 XÓA LOG", width=100, height=30, fg_color="#c0392b", hover_color="#e74c3c", command=self._on_clear_log).pack(side="right", padx=5)

        # 3. Textbox Log
        self.console = ctk.CTkTextbox(self.tab_dashboard, font=("Consolas", 12), state="disabled", fg_color="#1e1e1e", text_color="#dcdcdc")
        self.console.grid(row=2, column=0, sticky="nsew", padx=5, pady=5)

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
        self.entry_demucs_shifts = self._add_entry(frame, "Shifts (chất lượng tách, VD: 2):", getattr(self.cfg.step2, "shifts", 2))
        self.combo_demucs_output = self._add_combo(
            frame, "Xuất audio:", ["int24", "float32"],
            "float32" if getattr(self.cfg.step2, "output_float32", False) else "int24"
        )
        self._add_header(frame, "Step 3: Nhận diện Sub (SRT)")
        self.combo_srt_src = self._add_combo(frame, "Nguồn Sub:", ["voice", "image"], self.cfg.step3.srt_source)
        self.combo_whisper = self._add_combo(frame, "Whisper Model (Voice):", ["base", "small", "medium", "large-v2"], self.cfg.step3.model_size)
        self.entry_lang = self._add_entry(frame, "Ngôn ngữ nguồn (VD: zh, en, ja):", self.cfg.step3.language)
        self.entry_cpu_threads = self._add_entry(frame, "Whisper CPU threads (VD: 1):", getattr(self.cfg.step3, "cpu_threads", 1))
        self._add_header(frame, "Cấu hình OCR (Nếu chọn nguồn Sub là Image)")
        self.entry_ocr_lang = self._add_entry(frame, "Mã ngôn ngữ OCR (VD: ch, en):", self.cfg.step3.image_ocr_lang)
        step_frames = getattr(self.cfg.step3, "image_step_frames", 10)
        self.entry_ocr_step_frames = self._add_entry(
            frame,
            "Cứ mỗi N frame lấy 1 lần (VD: 10). Càng nhỏ = nhiều frame, chậm hơn:",
            step_frames,
        )
        self._add_header(frame, "Step 4: Dịch thuật (Gemini)")
        self.entry_step4_model = self._add_entry(frame, "Model Gemini (VD: gemini-2.5-flash):", self.cfg.step4.model_name)
        self.entry_source_lang = self._add_entry(frame, "Ngôn ngữ nguồn (VD: zh-CN, en):", self.cfg.step4.source_lang)
        self.entry_target_lang = self._add_entry(frame, "Ngôn ngữ đích (VD: vi, en):", self.cfg.step4.target_lang)
        self.entry_max_lines_chunk = self._add_entry(frame, "Số dòng tối đa mỗi chunk (VD: 250):", getattr(self.cfg.step4, "max_lines_per_chunk", 250))

    # --- TAB 4: SUB & MIX ---
    def _ui_sub_mix(self):
        frame = ctk.CTkScrollableFrame(self.tab_sub)
        frame.pack(fill="both", expand=True, padx=10, pady=10)
        self._add_header(frame, "Step 5: Giao diện Subtitle")
        self.entry_font_size = self._add_entry(frame, "Cỡ chữ:", self.cfg.step5.font_size)
        self.entry_max_words_per_line = self._add_entry(frame, "Số từ tối đa mỗi dòng (VD: 10):", getattr(self.cfg.step5, "max_words_per_line", 10))
        self.entry_font_path = self._add_path_row(frame, "Font chữ (.ttf):", self.cfg.step5.font_path, dir=False)

        # Màu chữ (Text) — bảng chọn màu
        tr, tg, tb = _ass_to_rgb(self.cfg.step5.text_color)
        self.step5_text_rgb = (tr, tg, tb)
        ctk.CTkLabel(frame, text="Màu chữ (Text):", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 2))
        row_text = ctk.CTkFrame(frame, fg_color="transparent")
        row_text.pack(fill="x", padx=5, pady=2)
        self.preview_text = ctk.CTkFrame(row_text, width=56, height=32, fg_color=_rgb_hex(tr, tg, tb), corner_radius=6)
        self.preview_text.pack(side="left", padx=(0, 10))
        def pick_text_color():
            rgb_hex = _rgb_hex(*self.step5_text_rgb)
            result = colorchooser.askcolor(initialcolor=rgb_hex, title="Chọn màu chữ")
            if result and result[0] is not None:
                r, g, b = [int(x) for x in result[0]]
                self.step5_text_rgb = (r, g, b)
                self.preview_text.configure(fg_color=_rgb_hex(r, g, b))
        ctk.CTkButton(row_text, text="🎨 Chọn màu", width=120, fg_color="#34495e", hover_color="#2c3e50", command=pick_text_color).pack(side="left")

        # Màu viền (Outline) — bảng chọn màu
        or_, og, ob = _ass_to_rgb(self.cfg.step5.outline_color)
        self.step5_outline_rgb = (or_, og, ob)
        ctk.CTkLabel(frame, text="Màu viền (Outline):", font=ctk.CTkFont(weight="bold")).pack(anchor="w", padx=10, pady=(10, 2))
        row_out = ctk.CTkFrame(frame, fg_color="transparent")
        row_out.pack(fill="x", padx=5, pady=2)
        self.preview_outline = ctk.CTkFrame(row_out, width=56, height=32, fg_color=_rgb_hex(or_, og, ob), corner_radius=6)
        self.preview_outline.pack(side="left", padx=(0, 10))
        def pick_outline_color():
            rgb_hex = _rgb_hex(*self.step5_outline_rgb)
            result = colorchooser.askcolor(initialcolor=rgb_hex, title="Chọn màu viền")
            if result and result[0] is not None:
                r, g, b = [int(x) for x in result[0]]
                self.step5_outline_rgb = (r, g, b)
                self.preview_outline.configure(fg_color=_rgb_hex(r, g, b))
        ctk.CTkButton(row_out, text="🎨 Chọn màu", width=120, fg_color="#34495e", hover_color="#2c3e50", command=pick_outline_color).pack(side="left")

        ctk.CTkLabel(frame, text="Vùng quét/che sub (ROI Y):").pack(anchor="w", padx=10, pady=5)
        self.slider_roi_start, _ = self._add_slider(frame, "Bắt đầu (Top %):", 0.0, 1.0, self.cfg.step5.roi_y_start, is_float=True)
        self.slider_roi_end, _ = self._add_slider(frame, "Kết thúc (Bottom %):", 0.0, 1.0, self.cfg.step5.roi_y_end, is_float=True)
        self._add_header(frame, "Step 6: TTS & Mix")
        self.entry_tts_lang = self._add_entry(frame, "Mã ngôn ngữ đọc (gTTS):", self.cfg.step6.tts_lang)
        self.slider_vol, _ = self._add_slider(frame, "Âm lượng nhạc nền (dB):", -50, 0, self.cfg.step6.bg_volume, is_float=False)
        self.slider_pitch, _ = self._add_slider(frame, "Pitch TTS (1.0 = bình thường, 1.2 = cao hơn):", 0.8, 1.5, getattr(self.cfg.step6, "pitch_factor", 1.0), is_float=True)
        self.entry_tts_volume = self._add_entry(frame, "Âm lượng TTS khi mix (VD: 1.4):", getattr(self.cfg.step6, "tts_volume", 1.4))
        self.entry_min_words_tts = self._add_entry(frame, "Min từ cho TTS (0 = tắt lặp câu ngắn):", getattr(self.cfg.step6, "min_words_for_tts", 0))
        self.entry_speedup_short = self._add_entry(frame, "Speedup khi TTS ngắn hơn slot (VD: 1.5):", getattr(self.cfg.step6, "speedup_when_short", 1.5))

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

    def _apply_cfg_to_ui(self):
        """Đổ lại giá trị config vào UI (dùng cho nút reset)."""
        c = self.cfg
        # IO
        _set_entry(self.ent_input, c.pipeline.input_videos)
        _set_entry(self.ent_output, c.pipeline.step6_final)
        # Step2
        self.combo_demucs_model.set(str(c.step2.model))
        self.combo_demucs_dev.set(str(c.step2.device))
        _set_entry(self.entry_demucs_jobs, c.step2.jobs)
        _set_entry(self.entry_demucs_shifts, getattr(c.step2, "shifts", 2))
        self.combo_demucs_output.set("float32" if getattr(c.step2, "output_float32", False) else "int24")
        # Step3
        self.combo_srt_src.set(str(c.step3.srt_source))
        self.combo_whisper.set(str(c.step3.model_size))
        _set_entry(self.entry_lang, c.step3.language)
        _set_entry(self.entry_cpu_threads, getattr(c.step3, "cpu_threads", 1))
        _set_entry(self.entry_ocr_lang, c.step3.image_ocr_lang)
        _set_entry(self.entry_ocr_step_frames, getattr(c.step3, "image_step_frames", 10))
        # Step4
        _set_entry(self.entry_step4_model, c.step4.model_name)
        _set_entry(self.entry_source_lang, c.step4.source_lang)
        _set_entry(self.entry_target_lang, c.step4.target_lang)
        _set_entry(self.entry_max_lines_chunk, getattr(c.step4, "max_lines_per_chunk", 250))
        # Step5
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
        # Step6
        _set_entry(self.entry_tts_lang, c.step6.tts_lang)
        self.slider_vol.set(float(c.step6.bg_volume))
        self.slider_pitch.set(float(getattr(c.step6, "pitch_factor", 1.0)))
        _set_entry(self.entry_tts_volume, getattr(c.step6, "tts_volume", 1.4))
        _set_entry(self.entry_min_words_tts, getattr(c.step6, "min_words_for_tts", 0))
        _set_entry(self.entry_speedup_short, getattr(c.step6, "speedup_when_short", 1.5))
        # System
        _set_entry(self.ent_ffmpeg, c.ffmpeg_bin or "")
        _set_textbox(self.txt_keys, ",\n".join(c.step4.gemini_api_keys))

    def _on_reset_defaults(self):
        if self.is_running:
            messagebox.showwarning("Đang chạy", "Hãy đợi pipeline chạy xong rồi reset.")
            return
        try:
            self.cfg = ConfigLoader.load("config.dist.yaml")
            self._apply_cfg_to_ui()
            messagebox.showinfo("Xong", "Đã phục hồi cài đặt mặc định (config.dist.yaml).")
        except Exception as e:
            messagebox.showerror("Lỗi reset", str(e))

    def _update_progress_ui(self, completed: int, total: int, current: list):
        """Cập nhật thanh tiến trình và nhãn (gọi từ main thread)."""
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
        self.lbl_progress.configure(
            text=f"Video {completed}/{total} ({int(pct * 100)}%) — {cur_text}"
        )

    # --- XỬ LÝ LOG ---
    def _poll_log(self):
        # Cập nhật progress từ queue (engine gửi từ worker threads)
        try:
            while True:
                item = self._progress_queue.get_nowait()
                if item[0] == "progress":
                    _, (completed, total, current) = item
                    self._update_progress_ui(completed, total, current)
        except queue.Empty:
            pass
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self.console.configure(state="normal")
                self.console.insert("end", msg + "\n")
                self.console.see("end")
                self.console.configure(state="disabled")
        except queue.Empty:
            pass
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
            c.step2.jobs = int(self.entry_demucs_jobs.get() or 1)
            try:
                c.step2.shifts = max(1, int(self.entry_demucs_shifts.get().strip() or 2))
            except (ValueError, AttributeError):
                c.step2.shifts = 2
            c.step2.output_float32 = self.combo_demucs_output.get() == "float32"
            c.step3.srt_source = self.combo_srt_src.get()
            c.step3.model_size = self.combo_whisper.get()
            c.step3.language = self.entry_lang.get()
            try:
                c.step3.cpu_threads = max(1, int(self.entry_cpu_threads.get().strip() or 1))
            except (ValueError, AttributeError):
                c.step3.cpu_threads = 1
            c.step3.image_ocr_lang = self.entry_ocr_lang.get()
            try:
                c.step3.image_step_frames = max(1, int(self.entry_ocr_step_frames.get().strip() or 10))
            except (ValueError, AttributeError):
                c.step3.image_step_frames = 10
            c.step4.model_name = self.entry_step4_model.get().strip() or "gemini-2.5-flash"
            c.step4.source_lang = self.entry_source_lang.get().strip() or "zh-CN"
            c.step4.target_lang = self.entry_target_lang.get()
            try:
                c.step4.max_lines_per_chunk = max(1, int(self.entry_max_lines_chunk.get().strip() or 250))
            except (ValueError, AttributeError):
                c.step4.max_lines_per_chunk = 250
            c.step5.font_size = int(self.entry_font_size.get() or 45)
            try:
                c.step5.max_words_per_line = max(1, int(self.entry_max_words_per_line.get().strip() or 10))
            except (ValueError, AttributeError):
                c.step5.max_words_per_line = 10
            c.step5.font_path = self.entry_font_path.get()
            c.step5.text_color = [*self.step5_text_rgb, 255]
            c.step5.outline_color = [*self.step5_outline_rgb, 255]
            c.step5.roi_y_start = float(self.slider_roi_start.get())
            c.step5.roi_y_end = float(self.slider_roi_end.get())
            c.step6.tts_lang = self.entry_tts_lang.get()
            c.step6.bg_volume = float(self.slider_vol.get())
            try:
                c.step6.pitch_factor = float(self.slider_pitch.get())
            except (ValueError, TypeError):
                c.step6.pitch_factor = 1.0
            try:
                c.step6.tts_volume = float(self.entry_tts_volume.get().strip() or 1.4)
            except (ValueError, AttributeError):
                c.step6.tts_volume = 1.4
            try:
                c.step6.min_words_for_tts = max(0, int(self.entry_min_words_tts.get().strip() or 0))
            except (ValueError, AttributeError):
                c.step6.min_words_for_tts = 0
            try:
                c.step6.speedup_when_short = max(0.5, float(self.entry_speedup_short.get().strip() or 1.5))
            except (ValueError, AttributeError):
                c.step6.speedup_when_short = 1.5
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
            # Ghi step5 màu dạng list [R,G,B,A] cho dễ đọc trong YAML
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
        if self.is_running: return
        self._on_save_config()
        self.is_running = True
        self.btn_run.configure(state="disabled", text="ĐANG CHẠY...", fg_color="#e67e22")
        self.lbl_status.configure(text="PROCESSING...", text_color="#e67e22")
        threading.Thread(target=self._thread_pipeline, daemon=True).start()

    def _thread_pipeline(self):
        def on_progress(completed, total, current):
            self._progress_queue.put(("progress", (completed, total, current)))

        try:
            engine = ProEngine()
            engine.cfg = self.cfg
            engine.run(on_progress=on_progress)
            self._progress_queue.put(("progress", (engine._progress_total, engine._progress_total, [])))
            self.lbl_status.configure(text="COMPLETED", text_color="#2ecc71")
            messagebox.showinfo("Xong", "Đã xử lý xong!")
        except Exception as e:
            logger.exception("Pipeline Error")
            self.lbl_status.configure(text="ERROR", text_color="#e74c3c")
            msg = str(e)
            if is_shm_dll_error(e):
                msg = msg + "\n\n" + SHM_FIX_MESSAGE
            elif is_meth_static_error(e):
                msg = msg + "\n\n" + METH_FIX_MESSAGE
            messagebox.showerror("Lỗi", msg)
        finally:
            self.is_running = False
            self.btn_run.configure(state="normal", text="▶ BẮT ĐẦU XỬ LÝ", fg_color="#27ae60")
            self._update_progress_ui(0, 0, [])

if __name__ == "__main__":
    app = ProGUI()
    app.mainloop()