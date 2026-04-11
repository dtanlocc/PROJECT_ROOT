import asyncio
import json
import os
import re
import sys
import threading
import time
import cv2
import yaml
import pysrt
import subprocess
import platform
from pathlib import Path
import numpy as np
from loguru import logger
from PyQt6.QtWidgets import QSizePolicy
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                             QHBoxLayout, QGridLayout, QLabel, QPushButton, QSplitter,
                             QCheckBox, QSlider, QProgressBar, QTextEdit, QDialog,
                             QFileDialog, QListWidget, QTableWidget, QFormLayout,
                             QTableWidgetItem, QHeaderView, QAbstractItemView, QGroupBox,
                             QLineEdit, QComboBox, QColorDialog, QDialog, QVBoxLayout, QFormLayout, QLabel, QLineEdit, QComboBox,
    QPushButton, QHBoxLayout, QColorDialog, QTextEdit, QTabWidget )
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QEvent
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter, QPen, QCursor, QFont
import hashlib

from app.core.language.registry import LanguageRegistry, get_edge_voices_for_language

# --- IMPORT CORE ENGINE ---
try:
    from app import __version__
    from app.core.config_loader import ConfigLoader
    from app.core.engine import ProEngine
except ImportError:
    __version__ = "1.0.0"
    ConfigLoader = None
    ProEngine = None
    print("Cảnh báo: Đang chạy độc lập, không tìm thấy Core Engine.")

# ======================================================================
# CÁC HÀM HELPER XỬ LÝ MÀU SẮC
# ======================================================================
def _ass_to_rgb(ass_str):
    if not ass_str or not isinstance(ass_str, str) or not str(ass_str).strip().upper().startswith("&H"):
        return (255, 255, 0)
    try:
        s = str(ass_str).strip().upper().replace("&H", "")
        if len(s) >= 6:
            r = int(s[6:8], 16) if len(s) >= 8 else 0
            g, b = int(s[4:6], 16), int(s[2:4], 16)
            return (r, g, b)
    except: pass
    return (255, 255, 0)

def _rgb_hex(r: int, g: int, b: int) -> str:
    return "#{:02x}{:02x}{:02x}".format(int(r) & 255, int(g) & 255, int(b) & 255)

def _ass_to_rgba_list(ass_str):
    if not ass_str or not isinstance(ass_str, str) or not str(ass_str).strip().upper().startswith("&H"):
        return [255, 255, 0, 255]
    try:
        s = str(ass_str).strip().upper().replace("&H", "")
        if len(s) >= 8:
            r = int(s[6:8], 16); g, b = int(s[4:6], 16), int(s[2:4], 16)
            a = 255 - int(s[0:2], 16)
            return [r, g, b, a]
    except: pass
    return [255, 255, 0, 255]

# ======================================================================
# CLASS TÙY CHỈNH (SLIDER NHẤP NHẢ & WORKER ĐÓNG BĂNG)
# ======================================================================
class ClickableSlider(QSlider):
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            # Nhảy tức thì đến vị trí click chuột
            val = self.minimum() + ((self.maximum() - self.minimum()) * ev.pos().x()) / self.width()
            self.setValue(int(val))
            self.sliderMoved.emit(int(val))
            ev.accept() # Chặn event mặc định của QSlider
        else:
            super().mousePressEvent(ev)
            
class GUILogSink:
    def __init__(self, signal):
        self.signal = signal
    def write(self, message):
        self.signal.emit(message.strip())

class PipelineWorker(QThread):
    progress_sig = pyqtSignal(int, int, str)
    log_sig = pyqtSignal(str)
    pause_for_sub_sig = pyqtSignal()
    request_roi_sig = pyqtSignal(str) # Thêm tín hiệu này
    finished_sig = pyqtSignal()

    def __init__(self, app_state):
        super().__init__()
        self.state = app_state

    def run(self):
        sink = GUILogSink(self.log_sig)
        handler_id = logger.add(sink.write, format="<blue>{time:HH:mm:ss}</blue> | {level} | {message}")

        def on_progress(completed, total, current):
            curr_text = " | ".join(current) if isinstance(current, list) else str(current)
            self.progress_sig.emit(completed, total, curr_text)
            if completed == 4 and self.state['chk_pause']:
                self.log_sig.emit("⏳ Tạm dừng nội bộ tại Bước 4. Chờ nạp Sub...")
                self.state['pause_event'].clear() 
                self.pause_for_sub_sig.emit()     
                self.state['pause_event'].wait()  

        try:
            if not ProEngine:
                self.log_sig.emit("❌ Lỗi: Không tìm thấy ProEngine.")
                return

            engine = ProEngine()
            engine.cfg = ConfigLoader.load() 
            
            # =========================================================
            # LÁCH LUẬT PYDANTIC: Ép gán thẳng vào bộ nhớ __dict__
            # =========================================================
            engine.cfg.pipeline.__dict__['run_s1'] = self.state['steps']['s1']
            engine.cfg.pipeline.__dict__['run_s2'] = self.state['steps']['s2']
            engine.cfg.pipeline.__dict__['run_s3'] = self.state['steps']['s3']
            engine.cfg.pipeline.__dict__['run_s4'] = self.state['steps']['s4']
            engine.cfg.pipeline.__dict__['run_s5'] = self.state['steps']['s5']
            engine.cfg.pipeline.__dict__['run_s6'] = self.state['steps']['s6']
            # =========================================================

            # --- HOOK: Bắt cóc luồng của Engine ---
            original_process_one = engine.process_one
            
            def hooked_process_one(video_path):
                # 1. Báo cho giao diện mở Video lên (và cập nhật tên video)
                self.request_roi_sig.emit(str(video_path))
                
                # 2. KHÓA LUỒNG NGAY TẠI ĐÂY (Nếu checkbox ROI được tích)
                if self.state['chk_pause_roi']:
                    self.state['pause_roi_event'].clear() 
                    self.state['pause_roi_event'].wait()  
                    
                # 3. Khi event được nhả, thả cho AI xử lý tiếp
                original_process_one(video_path)           
                
            engine.process_one = hooked_process_one
            # ----------------------------------------------------------------------------

            self.log_sig.emit("🚀 Bắt đầu chạy Pipeline...")
            engine.run(on_progress=on_progress)
            self.log_sig.emit(f"✅ Tiến trình hoàn tất toàn bộ!")
            
        except Exception as e:
            logger.exception("Pipeline Error")
            self.log_sig.emit(f"❌ Lỗi Pipeline: {str(e)}")
        finally:
            logger.remove(handler_id)
            self.finished_sig.emit()

# ======================================================================
# CỬA SỔ SETTING (CONFIG WINDOW) - BẢN PRO UI/UX
# ======================================================================
class ConfigWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("⚙️ Cài đặt - Studio Master")
        self.resize(720, 560)
        self.setMinimumSize(680, 520)

        self.cfg = parent.cfg
        self.registry = LanguageRegistry()

        # Giữ màu để paint lại
        self.step5_text_rgb = parent.step5_text_rgb
        self.step5_out_rgb = parent.step5_out_rgb
        self.step5_pill_rgb = parent.step5_pill_rgb

        self._setup_ui()
        self._apply_styles()
        
    def _browse_font(self):
        from PyQt6.QtWidgets import QFileDialog
        initial_dir = str(Path(self.le_font_path.text()).parent) if self.le_font_path.text() else "C:/Windows/Fonts"
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file Font", initial_dir, "Font Files (*.ttf *.otf);;All Files (*.*)"
        )
        if file_path: 
            self.le_font_path.setText(file_path)
        
    def _browse_ffmpeg(self):
        from PyQt6.QtWidgets import QFileDialog
        initial_dir = str(Path(self.le_ffmpeg.text()).parent) if self.le_ffmpeg.text() else ""
        file_path, _ = QFileDialog.getOpenFileName(self, "Chọn file ffmpeg.exe", initial_dir, "FFmpeg Executable (ffmpeg.exe);;All Files (*.*)")
        if file_path: self.le_ffmpeg.setText(file_path)
        
    def _browse_bg_music(self):
        from PyQt6.QtWidgets import QFileDialog
        initial_dir = self.le_bg_music.text() or ""
        dir_path = QFileDialog.getExistingDirectory(self, "Chọn thư mục nhạc nền ngẫu nhiên", initial_dir)
        if dir_path: self.le_bg_music.setText(dir_path)
        
    def _update_edge_voices(self, edge_prefix: str):
        """Cập nhật ComboBox voice của Edge"""
        if not hasattr(self, 'cb_edge_voice'):
            return

        # Chạy async trong thread để không freeze GUI
        def load_voices():
            voices = asyncio.run(get_edge_voices_for_language(edge_prefix))
            self.cb_edge_voice.clear()
            for v in voices:
                self.cb_edge_voice.addItem(v["name"], v["id"])
            
            # Chọn voice mặc định nếu có
            if voices:
                self.cb_edge_voice.setCurrentIndex(0)

        # Chạy trong thread
        threading.Thread(target=load_voices, daemon=True).start()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(12, 12, 12, 12)
        main_layout.setSpacing(12)

        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # Tab 1: Ngôn ngữ & Hệ thống
        tab_ai = QWidget()
        lay_ai = QFormLayout(tab_ai)
        lay_ai.setSpacing(12)

        # FFmpeg
        h_ffmpeg = QHBoxLayout()
        self.le_ffmpeg = QLineEdit(self.cfg.ffmpeg_bin or "")
        btn_ffmpeg = QPushButton("📁")
        btn_ffmpeg.setFixedWidth(50)
        btn_ffmpeg.clicked.connect(self._browse_ffmpeg)
        h_ffmpeg.addWidget(self.le_ffmpeg)
        h_ffmpeg.addWidget(btn_ffmpeg)
        lay_ai.addRow("FFmpeg Path:", h_ffmpeg)

        # Source & Target
        self.cb_source = QComboBox()
        self.cb_target = QComboBox()
        for code, name in self.registry.get_all():
            self.cb_source.addItem(name, code)
            self.cb_target.addItem(name, code)

        source_code = getattr(self.cfg, 'source_lang', 'zh')
        target_code = getattr(self.cfg, 'target_lang', 'vi')

        self.cb_source.setCurrentIndex(self.cb_source.findData(source_code))
        self.cb_target.setCurrentIndex(self.cb_target.findData(target_code))

        self.cb_source.currentIndexChanged.connect(self._on_language_changed)
        self.cb_target.currentIndexChanged.connect(self._on_language_changed)

        lay_ai.addRow("Ngôn ngữ nguồn:", self.cb_source)
        lay_ai.addRow("Ngôn ngữ đích:", self.cb_target)

        # Gemini
        self.le_s4_model = QLineEdit(getattr(self.cfg.step4, "model_name", "gemini-2.5-flash"))
        lay_ai.addRow("Model Gemini:", self.le_s4_model)

        self.txt_s4_keys = QTextEdit()
        self.txt_s4_keys.setMaximumHeight(90)
        self.txt_s4_keys.setPlaceholderText("Mỗi API Key một dòng...")
        keys = getattr(self.cfg.step4, "gemini_api_keys", [])
        self.txt_s4_keys.setPlainText("\n".join(keys))
        lay_ai.addRow("Gemini API Keys:", self.txt_s4_keys)

        self.tabs.addTab(tab_ai, "🤖 Hệ thống & Dịch")

        # --- TAB 2: DÒ SUB (OCR & WHISPER) ---
        tab_sub = QWidget()
        lay_sub = QFormLayout(tab_sub)
        lay_sub.setSpacing(15)
        lay_sub.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.cb_s3_src = QComboBox()
        self.cb_s3_src.addItems(["voice", "image"])
        self.cb_s3_src.setCurrentText(getattr(self.cfg.step3, "srt_source", "voice"))
        lay_sub.addRow("Nguồn tách Sub:", self.cb_s3_src)

        self.le_s3_lang = QLineEdit(getattr(self.cfg.step3, "language", "zh"))
        self.le_s3_lang.setReadOnly(True)
        self.le_s3_lang.setStyleSheet("background-color: #1e1e1e; color: #7f8c8d; border: 1px dashed #555;")
        self.le_s3_lang.setToolTip("Giá trị này được đồng bộ tự động từ Ngôn ngữ nguồn")
        lay_sub.addRow("Ngôn ngữ Video gốc:", self.le_s3_lang)

        self.le_s3_frames = QLineEdit(str(getattr(self.cfg.step3, "image_step_frames", 10)))
        lay_sub.addRow("Bỏ qua khung hình (Frames):", self.le_s3_frames)

        # --- TAB 3: TRANG TRÍ PHỤ ĐỀ (MÀU SẮC) ---
        tab_color = QWidget()
        lay_color = QFormLayout(tab_color)
        lay_color.setSpacing(20)
        lay_color.setContentsMargins(20, 20, 20, 20)

        font_box = QHBoxLayout()
        self.le_font_path = QLineEdit(getattr(self.cfg.step5, "font_path", ""))
        self.le_font_path.setPlaceholderText("Để trống sẽ dùng font mặc định...")
        btn_font = QPushButton("🔤 Chọn Font (.ttf/.otf)")
        btn_font.clicked.connect(self._browse_font)
        font_box.addWidget(self.le_font_path)
        font_box.addWidget(btn_font)
        lay_color.addRow("Font chữ Subtitle:", font_box)

        def create_color_picker(target, rgb):
            h = QHBoxLayout()
            lbl_ref = QLabel()
            lbl_ref.setFixedSize(50, 30)
            lbl_ref.setStyleSheet(f"background-color: {_rgb_hex(*rgb)}; border: 1px solid #7f8c8d; border-radius: 6px;")
            btn = QPushButton(f"🎨 Đổi Màu")
            btn.setFixedWidth(100)
            btn.clicked.connect(lambda: self._pick_color(target, lbl_ref))
            h.addWidget(lbl_ref)
            h.addWidget(btn)
            h.addStretch()
            return h

        lay_color.addRow("Chữ chính (Text):", create_color_picker("text", self.step5_text_rgb))
        lay_color.addRow("Viền chữ (Outline):", create_color_picker("outline", self.step5_out_rgb))
        lay_color.addRow("Nền bo góc (Pill Box):", create_color_picker("pill", self.step5_pill_rgb))

        # --- TAB 4: ÂM THANH & TTS ---
        tab_audio = QWidget()
        lay_audio = QFormLayout(tab_audio)
        lay_audio.setSpacing(15)
        lay_audio.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.cb_s6_engine = QComboBox()
        self.cb_s6_engine.addItems(["qwen", "edge", "google"])
        self.cb_s6_engine.setCurrentText(getattr(self.cfg.step6, "tts_engine", "qwen").lower())
        self.cb_s6_engine.currentTextChanged.connect(self._toggle_dynamic_ui)
        lay_audio.addRow("Engine Đọc thoại:", self.cb_s6_engine)

        # Qwen Voice
        self.w_qwen_voice = QWidget()
        lay_qwen = QHBoxLayout(self.w_qwen_voice)
        lay_qwen.setContentsMargins(0,0,0,0)
        self.cb_qwen_voice = QComboBox()

        json_path = Path("gwen-tts/data/ref_info.json")
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    for key, val in data.items():
                        display_name = val.get("name", key)
                        self.cb_qwen_voice.addItem(display_name, userData=key)
            except:
                pass

        if self.cb_qwen_voice.count() == 0:
            self.cb_qwen_voice.addItem("Ái Vy", userData="ai_vy")

        curr_qwen = getattr(self.cfg.step6, "qwen_voice", "ai_vy")
        idx = self.cb_qwen_voice.findData(curr_qwen)
        if idx >= 0:
            self.cb_qwen_voice.setCurrentIndex(idx)

        lay_qwen.addWidget(self.cb_qwen_voice)
        self.lbl_qwen_voice = QLabel("Giọng (Qwen TTS):")
        lay_audio.addRow(self.lbl_qwen_voice, self.w_qwen_voice)

        # Edge Voice
        self.w_edge_voice = QWidget()
        lay_edge = QHBoxLayout(self.w_edge_voice)
        lay_edge.setContentsMargins(0,0,0,0)
        self.cb_edge_voice = QComboBox()
        lay_edge.addWidget(self.cb_edge_voice)
        self.lbl_edge_voice = QLabel("Giọng (Edge TTS):")
        lay_audio.addRow(self.lbl_edge_voice, self.w_edge_voice)

        # Mode Mix
        self.cb_s6_mode = QComboBox()
        self.cb_s6_mode.addItems(["1 - Giữ toàn bộ âm gốc", "2 - Thay âm thanh mới"])
        self.cb_s6_mode.setCurrentIndex(0 if str(getattr(self.cfg.step6, "audio_mode", 1)) == "1" else 1)
        self.cb_s6_mode.currentIndexChanged.connect(self._toggle_dynamic_ui)
        lay_audio.addRow("Chế độ Mix Video:", self.cb_s6_mode)

        # Thư mục nhạc nền
        self.w_bgm = QWidget()
        lay_bgm = QHBoxLayout(self.w_bgm)
        lay_bgm.setContentsMargins(0,0,0,0)
        self.le_bg_music = QLineEdit(getattr(self.cfg.step6, "random_bgm_dir", ""))
        self.le_bg_music.setPlaceholderText("Ví dụ: D:\\NhacNen")
        btn_bgm = QPushButton("📁 Browse")
        btn_bgm.setFixedWidth(80)
        btn_bgm.clicked.connect(self._browse_bg_music)
        lay_bgm.addWidget(self.le_bg_music)
        lay_bgm.addWidget(btn_bgm)
        self.lbl_bgm = QLabel("Thư mục Nhạc ngẫu nhiên:")
        lay_audio.addRow(self.lbl_bgm, self.w_bgm)

        # Các thông số số
        h_params = QHBoxLayout()
        v1 = QVBoxLayout(); v1.addWidget(QLabel("Vol Đọc (TTS)")); self.le_s6_vol = QLineEdit(str(getattr(self.cfg.step6, "tts_volume", 1.4))); v1.addWidget(self.le_s6_vol)
        v2 = QVBoxLayout(); v2.addWidget(QLabel("Vol Nhạc nền (BGM)")); self.le_s6_bg_vol = QLineEdit(str(getattr(self.cfg.step6, "music_volume", 0.2))); v2.addWidget(self.le_s6_bg_vol)
        v_extra = QVBoxLayout(); v_extra.addWidget(QLabel("Vol gốc")); self.le_s6_extra = QLineEdit(str(getattr(self.cfg.step6, "extra_voice_volume", 0.1))); v_extra.addWidget(self.le_s6_extra)
        v3 = QVBoxLayout(); v3.addWidget(QLabel("Dãn thời gian (Stretch)")); self.le_s6_sp = QLineEdit(str(getattr(self.cfg.step6, "stretch_ratio", 1.1))); v3.addWidget(self.le_s6_sp)
        v4 = QVBoxLayout(); v4.addWidget(QLabel("Cao độ giọng (Pitch)")); self.le_s6_pitch = QLineEdit(str(getattr(self.cfg.step6, "pitch_factor", 1.2))); v4.addWidget(self.le_s6_pitch)
        v5 = QVBoxLayout(); v5.addWidget(QLabel("Tốc độ khi đoạn thoại ngắn")); self.le_s6_speed = QLineEdit(str(getattr(self.cfg.step6, "speedup_when_short", 1.5))); v5.addWidget(self.le_s6_speed)

        h_params.addLayout(v1)
        h_params.addLayout(v2)
        h_params.addLayout(v_extra)
        h_params.addLayout(v3)
        h_params.addLayout(v4)
        h_params.addLayout(v5)
        lay_audio.addRow(h_params)

        # ==================== THÊM TẤT CẢ TAB VÀO ====================
        self.tabs.addTab(tab_ai, "🤖 AI & Hệ thống")
        self.tabs.addTab(tab_sub, "🔎 Quét Phụ đề")
        self.tabs.addTab(tab_color, "🎨 Chỉnh Màu ASS")
        self.tabs.addTab(tab_audio, "🎧 Âm thanh & TTS")

        main_layout.addWidget(self.tabs)

        # Bottom buttons
        h_btn = QHBoxLayout()
        btn_cancel = QPushButton("Hủy bỏ")
        btn_cancel.setFixedWidth(100)
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("💾 LƯU CẤU HÌNH")
        btn_save.setObjectName("btnSave")
        btn_save.setFixedWidth(150)
        btn_save.clicked.connect(self._save_and_close)

        h_btn.addStretch()
        h_btn.addWidget(btn_cancel)
        h_btn.addWidget(btn_save)
        main_layout.addLayout(h_btn)

        self._toggle_dynamic_ui()
        
    def _on_language_changed(self):
        source_code = self.cb_source.currentData()
        target_code = self.cb_target.currentData()
        if not source_code or not target_code:
            return

        src = self.registry.get(source_code)
        tgt = self.registry.get(target_code)

        self.le_s3_lang.setText(src.whisper)
        self._update_edge_voices(tgt.edge_prefix)

    def _apply_styles(self):
        self.setStyleSheet("""
            QDialog { background-color: #1a1a1a; color: white; font-family: 'Segoe UI', Arial;}
            QLabel { color: #bdc3c7; font-weight: bold; font-size: 13px;}
            QLineEdit, QTextEdit { 
                background-color: #2b2b2b; color: #ecf0f1; 
                border: 1px solid #3d3d3d; padding: 6px; border-radius: 4px; font-size: 13px;
            }
            QLineEdit:focus, QTextEdit:focus { border: 1px solid #3498db; background-color: #333;}
            QComboBox { 
                background-color: #2b2b2b; color: white; border: 1px solid #3d3d3d; 
                padding: 5px; border-radius: 4px; font-size: 13px; min-height: 25px;
            }
            QComboBox::drop-down { border: 0px; }
            QPushButton { 
                background-color: #34495e; color: white; padding: 8px; 
                border: none; border-radius: 4px; font-weight: bold; font-size: 13px;
            }
            QPushButton:hover { background-color: #3f546a; }
            QPushButton#btnSave { background-color: #27ae60; font-size: 14px;}
            QPushButton#btnSave:hover { background-color: #2ecc71; }
            
            /* Style cho Tab */
            QTabWidget::pane { border: 1px solid #3d3d3d; border-radius: 6px; background-color: #222; top: -1px;}
            QTabBar::tab { 
                background-color: #2b2b2b; color: #7f8c8d; padding: 8px 16px; 
                margin-right: 2px; border-top-left-radius: 4px; border-top-right-radius: 4px;
                font-weight: bold; font-size: 13px;
            }
            QTabBar::tab:selected { background-color: #222; color: #3498db; border: 1px solid #3d3d3d; border-bottom-color: #222;}
            QTabBar::tab:hover:!selected { background-color: #333; color: white;}
        """)
        
    def _on_target_lang_changed(self, text):
        """Hàm này tự động chạy khi người dùng gõ vào ô Ngôn ngữ Đích"""
        target_lang = text.strip().lower()
        
        # Cắt lấy 2 chữ cái đầu để so khớp (Ví dụ: "vietnamese" hoặc "vi" đều lấy "vi")
        lang_code = target_lang[:2] if len(target_lang) >= 2 else "vi"

        self.cb_edge_voice.clear()

        # Tìm danh sách giọng hợp lệ từ json
        voices_to_add = self.edge_voice_data.get(lang_code, [])
        
        # Nếu không tìm thấy ngôn ngữ trùng khớp, lôi toàn bộ giọng ra cho người dùng tự chọn
        if not voices_to_add:
            for lang_list in self.edge_voice_data.values():
                voices_to_add.extend(lang_list)
        
        # Nếu file json bị lỗi hoặc không có, fallback cứng
        if not voices_to_add:
            voices_to_add = [
                {"id": "vi-VN-NamMinhNeural", "name": "Nam Minh (Mặc định)"},
                {"id": "en-US-ChristopherNeural", "name": "Christopher (Tiếng Anh)"}
            ]

        # Nạp vào ComboBox: Hiển thị Name, nhưng ngầm lưu ID
        for v in voices_to_add:
            self.cb_edge_voice.addItem(v["name"], userData=v["id"])

        # Phục hồi lại giọng đã lưu trong file YAML (nếu nó nằm trong list mới lọc)
        saved_edge_voice = getattr(self.cfg.step6, "edge_voice", "vi-VN-NamMinhNeural")
        idx = self.cb_edge_voice.findData(saved_edge_voice)
        if idx >= 0:
            self.cb_edge_voice.setCurrentIndex(idx)

    def _toggle_dynamic_ui(self):
        # Hiện box Qwen nếu chọn Qwen
        is_qwen = self.cb_s6_engine.currentText() == "qwen"
        self.w_qwen_voice.setVisible(is_qwen)
        self.lbl_qwen_voice.setVisible(is_qwen)

        # Hiện box Edge nếu chọn Edge
        is_edge = self.cb_s6_engine.currentText() == "edge"
        self.w_edge_voice.setVisible(is_edge)
        self.lbl_edge_voice.setVisible(is_edge)

        # Hiện mục thư mục nhạc nền nếu chọn Mode 2
        is_mode_2 = self.cb_s6_mode.currentIndex() == 1
        self.w_bgm.setVisible(is_mode_2)
        self.lbl_bgm.setVisible(is_mode_2)

    def _pick_color(self, target, label_ref):
        if target == "text": initial = QColor(*self.step5_text_rgb)
        elif target == "outline": initial = QColor(*self.step5_out_rgb)
        elif target == "pill": initial = QColor(*self.step5_pill_rgb)
        else: return
        
        color = QColorDialog.getColor(initial, self, f"Chọn màu")
        if color.isValid():
            rgb = (color.red(), color.green(), color.blue())
            label_ref.setStyleSheet(f"background-color: {_rgb_hex(*rgb)}; border: 1px solid #7f8c8d; border-radius: 6px;")
            if target == "text": self.step5_text_rgb = rgb
            elif target == "outline": self.step5_out_rgb = rgb
            elif target == "pill": self.step5_pill_rgb = rgb

    def _save_and_close(self):
        """Lưu config - Buộc ghi target_lang top-level"""
        c = self.cfg
        try:
            source_code = self.cb_source.currentData() or "zh"
            target_code = self.cb_target.currentData() or "vi"

            src = self.registry.get(source_code)
            tgt = self.registry.get(target_code)

            # ==================== BUỘC GHI TOP-LEVEL ====================
            c.source_lang = source_code
            c.target_lang = target_code

            # ==================== CÁC STEP ====================
            c.step3.__dict__['language'] = src.whisper
            c.step3.__dict__['image_ocr_lang'] = src.paddleocr

            c.step4.__dict__['source_lang'] = src.gemini
            c.step4.__dict__['target_lang'] = target_code

            c.step5.__dict__['ocr_lang'] = src.paddleocr

            c.step6.__dict__['tts_lang'] = target_code
            c.step6.__dict__['google_lang'] = target_code

            if hasattr(self, 'cb_edge_voice') and self.cb_edge_voice.currentData():
                c.step6.__dict__['edge_voice'] = self.cb_edge_voice.currentData()
            else:
                c.step6.__dict__['edge_voice'] = f"{tgt.edge_prefix}-Neural"

            # ==================== GIÁ TRỊ GUI KHÁC ====================
            c.ffmpeg_bin = self.le_ffmpeg.text().strip()

            c.step3.__dict__['srt_source'] = self.cb_s3_src.currentText()
            c.step3.__dict__['image_step_frames'] = int(self.le_s3_frames.text() or 10)

            c.step4.__dict__['model_name'] = self.le_s4_model.text().strip()
            keys_text = self.txt_s4_keys.toPlainText().strip()
            c.step4.__dict__['gemini_api_keys'] = [k.strip() for k in re.split(r'[,;\n]', keys_text) if k.strip()] if keys_text else []

            c.step5.__dict__['font_path'] = self.le_font_path.text().strip()

            c.step6.__dict__['tts_engine'] = self.cb_s6_engine.currentText().lower() if hasattr(self, 'cb_s6_engine') else "edge"
            c.step6.__dict__['qwen_voice'] = self.cb_qwen_voice.currentData() if hasattr(self, 'cb_qwen_voice') else getattr(c.step6, 'qwen_voice', None)

            c.step6.__dict__['tts_volume'] = float(self.le_s6_vol.text() or 1.4)
            c.step6.__dict__['speedup_when_short'] = float(self.le_s6_speed.text() or 1.5)
            c.step6.__dict__['music_volume'] = float(self.le_s6_bg_vol.text() or 0.35)
            c.step6.__dict__['extra_voice_volume'] = float(self.le_s6_extra.text() or 0.05)
            c.step6.__dict__['stretch_ratio'] = float(self.le_s6_sp.text() or 1.1)
            c.step6.__dict__['pitch_factor'] = float(self.le_s6_pitch.text() or 1.2)
            c.step6.__dict__['audio_mode'] = 1 if self.cb_s6_mode.currentIndex() == 0 else 2
            c.step6.__dict__['random_bgm_dir'] = self.le_bg_music.text().strip()

            self.parent.step5_text_rgb = getattr(self, 'step5_text_rgb', [255, 255, 255, 255])
            self.parent.step5_out_rgb = getattr(self, 'step5_out_rgb', [0, 0, 0, 255])
            self.parent.step5_pill_rgb = getattr(self, 'step5_pill_rgb', [0, 0, 0, 200])

        except Exception as e:
            logger.error(f"Lỗi xử lý Setting: {e}")
            self.parent.log_msg(f"⚠️ Lỗi xử lý Setting: {e}")
            return

        # Gọi lưu
        self.parent.save_yaml_config()
        self.parent.log_msg(f"✅ Đã lưu config!\nSource: {src.name} → Target: {tgt.name}")
        self.accept()
        
    def _sync_source_lang(self, text):
        """Hàm tự động copy chữ từ Ngôn ngữ Nguồn (Tab 1) sang Ngôn ngữ Gốc (Tab 2)"""
        self.le_s3_lang.setText(text.strip())

# ======================================================================
# WIDGET VẼ ROI CINEMATIC MASK
# ======================================================================
class VideoCanvas(QLabel):
    roi_updated = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet("background-color: #0f0f0f; border-radius: 8px;")
        from PyQt6.QtWidgets import QSizePolicy
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(320, 240) # Đảm bảo canvas không bị co dúm lại quá nhỏ
        
        self.current_frame = None
        self.is_drawing = False
        self.temp_y = None
        self.roi_start_y = 0.6
        self.roi_end_y = 1.0
        self.y_off = 0
        self.draw_h = 0

    def update_frame(self, frame):
        self.current_frame = frame
        self.repaint_canvas()

    def repaint_canvas(self):
        if self.current_frame is None: return
        lbl_w, lbl_h = self.width(), self.height()
        if lbl_w < 10 or lbl_h < 10: return
        
        frame_h, frame_w = self.current_frame.shape[:2]
        ratio = min(lbl_w / frame_w, lbl_h / frame_h)
        new_w, new_h = int(frame_w * ratio), int(frame_h * ratio)
        
        self.y_off = (lbl_h - new_h) // 2
        self.draw_h = new_h

        resized = cv2.resize(self.current_frame, (new_w, new_h))
        rgb_image = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        
        q_img = QImage(rgb_image.data, new_w, new_h, new_w * 3, QImage.Format.Format_RGB888)
        pixmap = QPixmap.fromImage(q_img)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        if self.cursor().shape() == Qt.CursorShape.CrossCursor or self.roi_end_y > 0:
            ry1 = int(new_h * self.roi_start_y)
            ry2 = int(new_h * self.roi_end_y)
            
            if self.is_drawing and self.temp_y is not None:
                ry1 = min(self._start_y, self.temp_y)
                ry2 = max(self._start_y, self.temp_y)
                ry1, ry2 = max(0, min(new_h, ry1)), max(0, min(new_h, ry2))

            # Vẽ màn đen bóng mờ cho phần KHÔNG CHỌN
            painter.fillRect(0, 0, new_w, ry1, QColor(0, 0, 0, 180)) 
            painter.fillRect(0, ry2, new_w, new_h - ry2, QColor(0, 0, 0, 180)) 
            
            # Vẽ đường Line đứt đoạn đẹp mắt
            pen = QPen(QColor(46, 204, 113), 2, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(0, ry1, new_w, ry1)
            painter.drawLine(0, ry2, new_w, ry2)

            # Vẽ chữ thông báo tọa độ Y
            painter.setPen(QPen(QColor(255, 255, 255)))
            font = QFont("Arial", 12, QFont.Weight.Bold)
            painter.setFont(font)
            
            pct1, pct2 = (ry1 / new_h) * 100, (ry2 / new_h) * 100
            # Nền cho Text
            painter.fillRect(10, ry1 - 25, 75, 20, QColor(0, 0, 0, 150))
            painter.fillRect(10, ry2 + 5, 75, 20, QColor(0, 0, 0, 150))
            # Text
            painter.drawText(15, ry1 - 10, f"Y: {pct1:.1f}%")
            painter.drawText(15, ry2 + 20, f"Y: {pct2:.1f}%")

        painter.end()
        self.setPixmap(pixmap)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.cursor().shape() == Qt.CursorShape.CrossCursor:
            self.is_drawing = True
            self._start_y = event.pos().y() - self.y_off

    def mouseMoveEvent(self, event):
        if self.is_drawing:
            self.temp_y = event.pos().y() - self.y_off
            self.repaint_canvas()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.is_drawing:
            self.is_drawing = False
            if self.draw_h == 0: return
            
            y1, y2 = self._start_y, event.pos().y() - self.y_off
            pct1, pct2 = max(0.0, min(1.0, y1 / self.draw_h)), max(0.0, min(1.0, y2 / self.draw_h))
            
            self.roi_start_y, self.roi_end_y = min(pct1, pct2), max(pct1, pct2)
            self.temp_y = None
            
            self.roi_updated.emit(self.roi_start_y, self.roi_end_y)
            self.repaint_canvas()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.repaint_canvas()

# ======================================================================
# GIAO DIỆN CHÍNH
# ======================================================================
class ProGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Nini Auto Edit Pro - Studio Master v{__version__}")
        
        self._init_config()
        self.cap = None; self.fps = 30; self.total_frames = 0; self.is_playing = False
        
        self.current_folder = self.cfg.pipeline.input_videos
        self.output_folder = getattr(self.cfg.pipeline, 'output_dir', "")
        self.current_video_path = None 
        self.current_srt_path = None
        self.sub_data_cache = []
        
        self.is_paused_for_sub = False
        self.worker = None
        self.pause_event = threading.Event()
        self.pause_event.set()
        
        # --- THÊM EVENT CHO ROI ---
        self.pause_roi_event = threading.Event()
        self.pause_roi_event.set()
        
        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._video_loop)

        self._setup_ui()
        self._apply_dark_theme()

        if self.current_folder and os.path.exists(str(self.current_folder)):
            self.reload_folder()
            
        # --- LỆNH FULL MÀN HÌNH CHUẨN XÁC NHẤT ---
        QTimer.singleShot(100, self.showMaximized)

    # --- THÊM HÀM NÀY ĐỂ TRÁNH LỖI QThread KHI ĐÓNG APP ---
    def closeEvent(self, event):
        self.log_msg("⚠️ Đang buộc thoát toàn bộ hệ thống. Vui lòng đợi...")
        
        # 1. Giải phóng Video Player để không bị kẹt file WinError 32
        if self.cap:
            self.cap.release()
            self.cap = None

        # 2. Ẩn giao diện ngay lập tức để người dùng không cảm thấy bị lag/treo
        self.hide()
        event.accept()

        # 3. TIÊU DIỆT TẬN GỐC TẤT CẢ CHILD PROCESSES (FFMPEG, AI VENV, V.V...)
        current_pid = os.getpid()
        try:
            if platform.system() == "Windows":
                # Lệnh taskkill của Windows: 
                # /F: Ép buộc (Force)
                # /T: Giết cả tiến trình mẹ lẫn mọi tiến trình con (Tree)
                subprocess.Popen(
                    f"taskkill /F /T /PID {current_pid}", 
                    shell=True, 
                    stdout=subprocess.DEVNULL, 
                    stderr=subprocess.DEVNULL
                )
            else:
                # Dành cho Linux/Mac
                import signal
                os.killpg(os.getpgrp(), signal.SIGKILL)
        except Exception as e:
            print(f"Lỗi khi dọn dẹp tiến trình: {e}")

        # 4. Thoát cứng cấp hệ điều hành (Bỏ qua mọi vòng lặp hoặc try/finally đang chạy)
        os._exit(0)
            
    def _ms_to_srt_time(self, ms):
        s, ms = divmod(int(ms), 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _init_config(self):
        if ConfigLoader: self.cfg = ConfigLoader.load()
        else:
            class DummyCfg: pass
            self.cfg = DummyCfg()
            self.cfg.pipeline = DummyCfg(); self.cfg.pipeline.input_videos = ""; self.cfg.pipeline.output_dir = ""
            self.cfg.step2 = DummyCfg(); self.cfg.step3 = DummyCfg(); self.cfg.step4 = DummyCfg(); self.cfg.step6 = DummyCfg()
            self.cfg.step5 = DummyCfg(); self.cfg.step5.roi_y_start = 0.6; self.cfg.step5.roi_y_end = 1.0
            self.cfg.step5.text_color = "&H0000FFFF"; self.cfg.step5.outline_color = "&H00000000"

        # ==================== SỬA PHẦN MÀU Ở ĐÂY ====================
        def get_color_list(key, default_rgb=(255,255,255)):
            val = getattr(self.cfg.step5, key, None)
            if isinstance(val, (list, tuple)) and len(val) >= 3:
                return list(val[:3])   # lấy 3 giá trị RGB
            elif isinstance(val, str) and val.startswith("&H"):
                return _ass_to_rgb(val)[:3]
            else:
                return list(default_rgb)

        self.step5_text_rgb    = get_color_list('text_color', (255, 255, 255))
        self.step5_out_rgb = get_color_list('outline_color', (0, 0, 0))
        self.step5_pill_rgb    = get_color_list('pill_background_color', (0, 0, 0))
        # ===========================================================

    def save_yaml_config(self):
        try:
            config_path = Path("config.yaml").resolve()

            # Đọc file hiện tại
            if config_path.exists():
                with open(config_path, "r", encoding="utf-8") as f:
                    data = yaml.safe_load(f) or {}
            else:
                data = {}

            # Buộc ghi top-level source_lang và target_lang
            data["source_lang"] = getattr(self.cfg, "source_lang", "zh")
            data["target_lang"] = getattr(self.cfg, "target_lang", "vi")

            # Ghi các step
            if "step3" not in data: data["step3"] = {}
            data["step3"]["language"] = getattr(self.cfg.step3, "language", "zh")
            data["step3"]["image_ocr_lang"] = getattr(self.cfg.step3, "image_ocr_lang", "ch")

            if "step4" not in data: data["step4"] = {}
            data["step4"]["source_lang"] = getattr(self.cfg.step4, "source_lang", "zh-CN")
            data["step4"]["target_lang"] = getattr(self.cfg.step4, "target_lang", "vi")

            if "step5" not in data: data["step5"] = {}
            data["step5"]["ocr_lang"] = getattr(self.cfg.step5, "ocr_lang", "ch")

            if "step6" not in data: data["step6"] = {}
            data["step6"]["tts_lang"] = getattr(self.cfg.step6, "tts_lang", "vi")
            data["step6"]["google_lang"] = getattr(self.cfg.step6, "google_lang", "vi")
            data["step6"]["edge_voice"] = getattr(self.cfg.step6, "edge_voice", "vi-VN-NamMinhNeural")
            data["step6"]["tts_volume"] = getattr(self.cfg.step6, "tts_volume", 1.4)
            data["step6"]["music_volume"] = getattr(self.cfg.step6, "music_volume", 0.35)
            data["step6"]["extra_voice_volume"] = getattr(self.cfg.step6, "extra_voice_volume", 0.1)
            data["step6"]["stretch_ratio"] = getattr(self.cfg.step6, "stretch_ratio", 1.1)
            data["step6"]["pitch_factor"] = getattr(self.cfg.step6, "pitch_factor", 1.2)
            data["step6"]["audio_mode"] = getattr(self.cfg.step6, "audio_mode", 1)
            data["step6"]["speedup_when_short"] = getattr(self.cfg.step6, "speedup_when_short", 2.0)
            data["step6"]["random_bgm_dir"] = getattr(self.cfg.step6, "random_bgm_dir", "")
            

            # 4. Lưu trực tiếp file yaml
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False)
                
            self.log_msg(f"💾 Đã lưu cấu hình trực tiếp vào: {config_path}")
            
        except Exception as e:
            self.log_msg(f"❌ Lỗi lưu cấu hình: {e}")

    def _setup_ui(self):
        
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)
        main_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.setSpacing(10)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        
        # --- PANEL 1: WORKSPACE ---
        pnl_left = QWidget()
        l_layout = QVBoxLayout(pnl_left)
        l_layout.setContentsMargins(0, 0, 0, 0)
        
        group_tools = QGroupBox("📁 Quản lý File")
        lay_tools = QVBoxLayout(group_tools)
        h1 = QHBoxLayout(); h1.addWidget(QPushButton("Mở Input", clicked=self.load_video_folder)); h1.addWidget(QPushButton("Reload", clicked=self.reload_folder))
        h2 = QHBoxLayout(); h2.addWidget(QPushButton("Chọn Output", clicked=self.select_output_folder)); h2.addWidget(QPushButton("Mở Output", clicked=self.open_output_folder))
        lay_tools.addLayout(h1); lay_tools.addLayout(h2)
        l_layout.addWidget(group_tools)
        
        self.list_videos = QListWidget()
        self.list_videos.itemClicked.connect(self._on_video_selected)
        l_layout.addWidget(self.list_videos, stretch=1)
        
        group_steps = QGroupBox("⚙️ Cấu hình Các Bước")
        lay_steps = QVBoxLayout(group_steps)
        self.step_vars = {}
        for key, name in [("s3", "Dò Sub"), 
                          ("s4", "Dịch thuật"), ("s5", "Vẽ Phụ đề"), ("s6", "Mix TTS")]:
            chk = QCheckBox(name); chk.setChecked(True); self.step_vars[key] = chk
            lay_steps.addWidget(chk)
            
        self.chk_pause = QCheckBox("✋ Tạm dừng sửa Sub ở Bước 4")
        self.chk_pause.setChecked(True)
        self.chk_pause.setStyleSheet("color: #f1c40f; font-weight: bold; margin-top: 5px;")
        lay_steps.addWidget(self.chk_pause)
        
        # --- THÊM NÚT DỪNG ROI ---
        self.chk_pause_roi = QCheckBox("📐 Dừng set ROI cho MỖI VIDEO")
        self.chk_pause_roi.setChecked(True)
        self.chk_pause_roi.setStyleSheet("color: #e74c3c; font-weight: bold;")
        lay_steps.addWidget(self.chk_pause_roi)
        
        l_layout.addWidget(group_steps)
        
        h_run = QHBoxLayout()
        self.btn_setup = QPushButton("⚙️ SETTING"); self.btn_setup.clicked.connect(self.open_setup)
        self.btn_run = QPushButton("▶ CHẠY BƯỚC 1 -> 4")
        self.btn_run.setObjectName("btnRun")
        self.btn_run.setMinimumHeight(45)
        self.btn_run.clicked.connect(self._on_btn_run_clicked)
        h_run.addWidget(self.btn_setup); h_run.addWidget(self.btn_run, stretch=1)
        l_layout.addLayout(h_run)

        # --- PANEL 2: VIDEO PLAYER ---
        pnl_center = QWidget()
        c_layout = QVBoxLayout(pnl_center)
        c_layout.setContentsMargins(0, 0, 0, 0)
        
        h_roi = QHBoxLayout()
        self.lbl_roi_val = QLabel(f"📐 Tọa độ ROI: {self.cfg.step5.roi_y_start:.2f} - {self.cfg.step5.roi_y_end:.2f}")
        self.lbl_roi_val.setStyleSheet("color: #bdc3c7;")
        self.btn_roi = QPushButton("✂ Click để Vẽ ROI")
        self.btn_roi.clicked.connect(self.toggle_roi_mode)
        h_roi.addWidget(self.lbl_roi_val); h_roi.addStretch(); h_roi.addWidget(self.btn_roi)
        c_layout.addLayout(h_roi)
        
        self.canvas = VideoCanvas()
        self.canvas.roi_start_y, self.canvas.roi_end_y = self.cfg.step5.roi_y_start, self.cfg.step5.roi_y_end
        self.canvas.roi_updated.connect(self._on_roi_updated)
        c_layout.addWidget(self.canvas, stretch=1)
        
        h_time = QHBoxLayout()
        self.btn_play = QPushButton("▶ Phát"); self.btn_play.clicked.connect(self.toggle_play)
        
        # SỬ DỤNG SLIDER MỚI CÓ THỂ NHẤP CHUỘT
        self.slider = ClickableSlider(Qt.Orientation.Horizontal) 
        self.slider.sliderMoved.connect(self.on_slider_moved)
        
        self.lbl_timecode = QLabel("00:00:00 / 00:00:00"); self.lbl_timecode.setFont(QFont("Consolas", 10))
        h_time.addWidget(self.btn_play); h_time.addWidget(self.slider); h_time.addWidget(self.lbl_timecode)
        c_layout.addLayout(h_time)

        # --- PANEL 3: BẢNG SUBTITLE ---
        pnl_right = QWidget()
        r_layout = QVBoxLayout(pnl_right)
        r_layout.setContentsMargins(0, 0, 0, 0)
        
        h_sub_top = QHBoxLayout()
        h_sub_top.addWidget(QLabel("📝 Dịch thuật (Cột 2 cho phép sửa)"))
        h_sub_top.addStretch()
        btn_load_sub = QPushButton("Nạp Thủ Công"); btn_load_sub.clicked.connect(lambda: self.load_srt_file(None))
        h_sub_top.addWidget(btn_load_sub)
        r_layout.addLayout(h_sub_top)
        
        self.table_sub = QTableWidget(0, 2)
        self.table_sub.setHorizontalHeaderLabels(["Time", "Subtitle Bản dịch"])
        self.table_sub.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_sub.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_sub.verticalHeader().setVisible(False)
        self.table_sub.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        # BẬT XUỐNG DÒNG (WORD-WRAP) CHO SUBTITLE
        self.table_sub.setWordWrap(True)
        self.table_sub.setTextElideMode(Qt.TextElideMode.ElideNone) 
        
        self.table_sub.cellClicked.connect(self._on_sub_row_clicked)
        r_layout.addWidget(self.table_sub, stretch=1)

        self.splitter.addWidget(pnl_left); self.splitter.addWidget(pnl_center); self.splitter.addWidget(pnl_right)
        self.splitter.setSizes([300, 700, 350]) 
        main_layout.addWidget(self.splitter, stretch=1)
        # 1. Khi chiều rộng bảng thay đổi -> Tự tính lại chiều cao các hàng
        self.table_sub.horizontalHeader().sectionResized.connect(lambda: self.table_sub.resizeRowsToContents())
        # 2. Khi người dùng gõ sửa chữ (hoặc copy paste) -> Tự động tính lại chiều cao
        self.table_sub.itemChanged.connect(lambda item: self.table_sub.resizeRowsToContents())

        # --- KHU VỰC DƯỚI: PROGRESS BAR & LOG ---
        pnl_bottom = QWidget()
        pnl_bottom.setFixedHeight(150) # Tăng xíu chiều cao cho rộng
        b_layout = QVBoxLayout(pnl_bottom)
        b_layout.setContentsMargins(0, 0, 0, 0)
        
        # 1. KHỞI TẠO CONSOLE TRƯỚC
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setFont(QFont("Consolas", 10))
        
        # 2. KHỞI TẠO LABEL VÀ NÚT XÓA LOG
        h_prog = QHBoxLayout()
        self.lbl_progress = QLabel("Sẵn sàng (0/0 File)")
        self.lbl_progress.setStyleSheet("color: #ecf0f1; font-weight: bold; font-size: 13px;")
        
        btn_clear_log = QPushButton("🗑 Xóa Log")
        btn_clear_log.setFixedWidth(100)
        btn_clear_log.clicked.connect(self.console.clear) # Bay giờ self.console đã tồn tại nên không lỗi nữa
        
        h_prog.addWidget(self.lbl_progress)
        h_prog.addStretch()
        h_prog.addWidget(btn_clear_log)
        b_layout.addLayout(h_prog)
        
        # 3. KHỞI TẠO PROGRESS BAR
        self.progressbar = QProgressBar()
        self.progressbar.setFixedHeight(8) # Làm dày xíu cho dễ nhìn
        self.progressbar.setTextVisible(False) 
        self.progressbar.setValue(0)
        b_layout.addWidget(self.progressbar)
        
        # 4. THÊM CONSOLE VÀO GIAO DIỆN
        b_layout.addWidget(self.console)
        main_layout.addWidget(pnl_bottom)

        self.chk_pause.stateChanged.connect(self._update_run_btn_label)
        self._update_run_btn_label()

    def _apply_dark_theme(self):
        dark_qss = """
        QMainWindow, QWidget { background-color: #121212; color: #ecf0f1; }
        QGroupBox { border: 1px solid #333; border-radius: 6px; margin-top: 10px; padding-top: 15px; font-weight: bold;}
        QGroupBox::title { subcontrol-origin: margin; left: 10px; color: #95a5a6; }
        QPushButton { background-color: #2c3e50; border: none; padding: 6px 12px; border-radius: 4px; }
        QPushButton:hover { background-color: #34495e; }
        QPushButton#btnRun { background-color: #27ae60; font-weight: bold; font-size: 14px; border-radius: 6px;}
        QPushButton#btnRun:hover { background-color: #2ecc71; }
        QPushButton#btnRun:disabled { background-color: #7f8c8d; color: #bdc3c7;}
        QListWidget, QTableWidget, QTextEdit { background-color: #1e1e1e; border: 1px solid #2c3e50; border-radius: 4px; outline: none;}
        QTableWidget::item:selected { background-color: #2980b9; color: white;}
        QProgressBar { border: none; background-color: #2c3e50; border-radius: 3px; }
        QProgressBar::chunk { background-color: #2ecc71; border-radius: 3px; }
        QSplitter::handle { background-color: #121212; }
        """
        self.setStyleSheet(dark_qss)

    # ==========================================
    # LOGIC ĐIỀU HƯỚNG BẰNG EVENT BLOCKING
    # ==========================================
    def open_setup(self):
        dlg = ConfigWindow(self)
        dlg.exec()

    def _update_run_btn_label(self):
        if not self.is_paused_for_sub and self.worker is None:
            if self.chk_pause.isChecked():
                self.btn_run.setText("▶ CHẠY (Dừng tại Bước 4)")
                self.btn_run.setStyleSheet("background-color: #27ae60; color: white;")
            else:
                self.btn_run.setText("▶ CHẠY TOÀN BỘ")
                self.btn_run.setStyleSheet("background-color: #8e44ad; color: white;")

    def _on_btn_run_clicked(self):
        # 1. NẾU ĐANG BỊ ĐÓNG BĂNG DO ROI (Nhấn nút "Xác nhận ROI")
        if not self.pause_roi_event.is_set():
            self.save_yaml_config()
            if self.cap:
                self.cap.release() # GIẢI PHÓNG VIDEO ĐỂ ENGINE KHÔNG BỊ LỖI
                self.cap = None
            self.log_msg("✅ Đã chốt ROI. Đang xử lý Video...")
            self.btn_run.setEnabled(False)
            self.btn_run.setText("⏳ ĐANG XỬ LÝ PIPELINE...")
            self.btn_run.setStyleSheet("background-color: #e67e22; color: white;")
            self.pause_roi_event.set() # Nhả luồng cho Engine chạy
            return

        # 2. NẾU ĐANG BỊ ĐÓNG BĂNG DO SUB (Nhấn nút "Xác nhận Sub")
        if self.is_paused_for_sub:
            self.save_edited_sub()
            self.is_paused_for_sub = False
            
            # --- THÊM ĐOẠN NÀY: ĐÓNG VIDEO LẠI ĐỂ NHƯỜNG FILE CHO AI (Chống WinError 32) ---
            if self.cap:
                self.cap.release()
                self.cap = None
                self.canvas.clear() # Làm đen màn hình canvas
            # -----------------------------------------------------------------------------
                
            self.btn_run.setEnabled(False)
            self.btn_run.setText("⏳ ĐANG CHẠY TIẾP BƯỚC 5->6...")
            self.btn_run.setStyleSheet("background-color: #e67e22; color: white;")
            self.log_msg("▶ Đã xác nhận Sub. Tiếp tục chạy Pipeline...")
            self.pause_event.set()
            return

        # 3. BẮT ĐẦU CHẠY MỚI TỪ ĐẦU
        self.save_yaml_config()
        self.is_paused_for_sub = False
        self.pause_event.set() 
        self.pause_roi_event.set()
        
        if self.cap:
            self.cap.release()
            self.cap = None
            
        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳ ĐANG XỬ LÝ...")
        self.btn_run.setStyleSheet("background-color: #e67e22; color: white;")
        self.progressbar.setValue(0)
        
        # ====================== SỬA Ở ĐÂY ======================
        steps = {k: v.isChecked() for k, v in self.step_vars.items()}
        
        # Bổ sung s1 và s2 (vì bạn đã bỏ checkbox)
        app_state = {
            'chk_pause': self.chk_pause.isChecked(),
            'chk_pause_roi': self.chk_pause_roi.isChecked(),
            'pause_event': self.pause_event,
            'pause_roi_event': self.pause_roi_event,
            'steps': {
                's1': True,      # Luôn chạy Step 1
                's2': True,      # Luôn chạy Step 2
                **steps          # Merge s3,s4,s5,s6 từ checkbox
            }
        }
        # =======================================================
        
        self.worker = PipelineWorker(app_state)
        self.worker.progress_sig.connect(self._update_progress)
        self.worker.log_sig.connect(self.log_msg)
        self.worker.pause_for_sub_sig.connect(self._on_worker_paused)
        self.worker.request_roi_sig.connect(self._on_request_roi) 
        self.worker.finished_sig.connect(self._on_worker_finished)
        self.worker.start()

    # --- HÀM XỬ LÝ KHI WORKER YÊU CẦU MỞ VIDEO ĐỂ SET ROI ---
    def _on_request_roi(self, video_path):
        # --- THÊM DÒNG NÀY: Giúp app biết đích xác video nào đang chạy để Auto-load SRT ---
        self.current_video_path = video_path 
        
        self.load_video_player(video_path)
        if self.chk_pause_roi.isChecked():
            self.log_msg(f"📐 Đã dừng tại: {Path(video_path).name}. Hãy vẽ ROI và bấm Xác nhận!")
            self.btn_run.setEnabled(True)
            self.btn_run.setText("✅ XÁC NHẬN ROI VÀ CHẠY")
            self.btn_run.setStyleSheet("background-color: #3498db; color: white; font-weight: bold;")
        else:
            if self.cap:
                self.cap.release() 
                self.cap = None
            self.pause_roi_event.set()

    def _on_worker_paused(self):
        self.is_paused_for_sub = True
        self.log_msg("⏳ Luồng xử lý đã bị khóa. Đang tự động quét nạp Sub...")
        self._auto_load_srt()
        
        # --- THÊM ĐOẠN NÀY: MỞ LẠI VIDEO ĐỂ XEM VÀ SỬA SUB ---
        if self.current_video_path and os.path.exists(self.current_video_path):
            self.load_video_player(self.current_video_path)
            self.log_msg("🎬 Đã nạp lại Video Player để đồng bộ Timeline.")
        # -----------------------------------------------------

        self.btn_run.setEnabled(True)
        self.btn_run.setText("✅ XÁC NHẬN SUB & CHẠY TIẾP B5")
        self.btn_run.setStyleSheet("background-color: #f39c12; color: black; font-weight: bold;")

    def _on_worker_finished(self):
        self.is_paused_for_sub = False
        self.worker = None
        self.btn_run.setEnabled(True)
        self._update_run_btn_label()

    def _update_progress(self, completed, total, text):
        try:
            # File hiện tại / Tổng số
            if total > 0:
                pct = int((completed / total) * 100)
                pct = max(0, min(100, pct)) 
                self.progressbar.setValue(pct)
                self.lbl_progress.setText(f"📁 Tiến độ File: {completed}/{total} ({pct}%)  ⚡ Đang chạy: {text}")
            else:
                self.lbl_progress.setText(f"Trạng thái: {text}")
        except: pass

    # ==========================================
    # CƠ CHẾ NẠP SRT THÔNG MINH KẾT HỢP TÊN VIDEO
    # ==========================================
    def _auto_load_srt(self):
        if not self.current_video_path:
            self.log_msg("⚠️ Chưa chọn Video trên danh sách để lấy Tên so khớp.")
            return

        # Tạo safe_stem y hệt như bên enginee.py
        video_name = Path(self.current_video_path).name # Lấy cả đuôi mp4
        safe_hash = hashlib.md5(video_name.encode('utf-8')).hexdigest()[:10]
        safe_stem = f"vid_{safe_hash}"
        
        search_dirs = [
            self.cfg.pipeline.step4_srt_translated, # Thư mục đích của B4
            self.output_folder, 
            self.current_folder,
            Path("workspace/processing") # Folder làm việc tạm của engine
        ]
        
        latest_srt = None
        max_mtime = 0
        
        for d in search_dirs:
            if d and os.path.exists(str(d)):
                for root, _, files in os.walk(d):
                    for file in files:
                        # Đổi logic: Tìm đúng file chứa mã safe_stem
                        if file.endswith(".srt") and safe_stem in file:
                            p = os.path.join(root, file)
                            try:
                                mtime = os.path.getmtime(p)
                                if mtime > max_mtime:
                                    max_mtime = mtime
                                    latest_srt = p
                            except: pass
                            
        if latest_srt:
            self.load_srt_file(latest_srt)
            self.log_msg(f"✅ Auto-load chuẩn xác: {Path(latest_srt).name}")
        else:
            self.log_msg(f"⚠️ Không tìm thấy file SRT nào chứa mã '{safe_stem}'. Vui lòng nạp thủ công.")

    def load_srt_file(self, auto_path=None):
        path = auto_path
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn file SRT", "", "SRT Files (*.srt)")
        if not path or not os.path.exists(path): return
        
        self.current_srt_path = path
        subs = pysrt.open(path, encoding='utf-8')
        
        self.table_sub.setUpdatesEnabled(False)
        self.table_sub.setRowCount(len(subs))
        self.sub_data_cache = []
        
        for i, s in enumerate(subs):
            start_ms, end_ms = s.start.ordinal, s.end.ordinal
            
            # Format Time cực đẹp
            t_str = f"{self._ms_to_srt_time(start_ms)}\n{self._ms_to_srt_time(end_ms)}"
            time_item = QTableWidgetItem(t_str)
            time_item.setFlags(Qt.ItemFlag.ItemIsEnabled) 
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setForeground(QColor("#e67e22")) # Cho màu cam xịn xò
            
            text_item = QTableWidgetItem(s.text.replace("\n", " "))
            
            self.table_sub.setItem(i, 0, time_item)
            self.table_sub.setItem(i, 1, text_item)
            self.sub_data_cache.append({"start": start_ms, "end": end_ms})
            
        self.table_sub.resizeRowsToContents()
        self.table_sub.setUpdatesEnabled(True)

    def _on_sub_row_clicked(self, row, col):
        # Đã bỏ điều kiện `if col == 0:`
        if self.fps > 0:
            frame = int((self.sub_data_cache[row]["start"] / 1000.0) * self.fps)
            if self.is_playing: self.toggle_play()
            self.slider.setValue(frame)
            self.show_frame_at(frame)

    def save_edited_sub(self):
        if not self.current_srt_path or not os.path.exists(self.current_srt_path): return
        try:
            subs = pysrt.open(self.current_srt_path, encoding='utf-8')
            for i in range(self.table_sub.rowCount()):
                if i < len(subs):
                    item = self.table_sub.item(i, 1)
                    if item: subs[i].text = item.text()
            subs.save(self.current_srt_path, encoding='utf-8')
            self.log_msg("💾 Đã lưu những thay đổi của Bản dịch vào ổ cứng.")
        except Exception as e:
            self.log_msg(f"❌ Lỗi khi lưu Sub: {e}")

    # ==========================================
    # QUẢN LÝ THƯ MỤC & VIDEO
    # ==========================================
    def load_video_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục Input")
        if folder: self.current_folder = folder; self.cfg.pipeline.input_videos = Path(folder); self.reload_folder(); self.save_yaml_config()

    def reload_folder(self):
        if not self.current_folder or not os.path.exists(str(self.current_folder)): return
        self.list_videos.clear()
        files = [f for f in os.listdir(self.current_folder) if f.endswith(('.mp4', '.mkv', '.avi', '.mov'))]
        for f in files: self.list_videos.addItem(f)

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục Output")
        if folder: self.output_folder = folder; self.cfg.pipeline.output_dir = Path(folder); self.save_yaml_config()

    def open_output_folder(self):
        # 1. Lấy đường dẫn user đã chọn, nếu không có thì lấy đường dẫn mặc định của Step 6
        out_dir = str(self.output_folder)
        if not out_dir or out_dir == "." or out_dir == "":
            if hasattr(self.cfg.pipeline, 'step6_final'):
                out_dir = str(self.cfg.pipeline.step6_final)
            else:
                self.log_msg("⚠️ Chưa cấu hình thư mục Output!")
                return

        # 2. Tự động tạo thư mục nếu nó chưa tồn tại
        if not os.path.exists(out_dir):
            try:
                os.makedirs(out_dir, exist_ok=True)
            except Exception as e:
                self.log_msg(f"❌ Không thể tạo thư mục Output: {e}")
                return

        # 3. Mở thư mục bằng trình duyệt file của hệ điều hành
        try:
            if platform.system() == "Windows": 
                os.startfile(out_dir)
            elif platform.system() == "Darwin": 
                subprocess.Popen(["open", out_dir])
            else: 
                subprocess.Popen(["xdg-open", out_dir])
            self.log_msg(f"📂 Đã mở thư mục Output: {out_dir}")
        except Exception as e:
            self.log_msg(f"❌ Lỗi mở thư mục: {e}")

    def log_msg(self, text):
        self.console.append(text)
        self.console.verticalScrollBar().setValue(self.console.verticalScrollBar().maximum())

    def _on_video_selected(self, item):
        path = os.path.join(self.current_folder, item.text())
        self.current_video_path = path # Lưu vết để thuật toán quét Tên Auto-load
        self.load_video_player(path)

    def load_video_player(self, path):
        if self.cap: self.cap.release()
        self.play_timer.stop()
        self.is_playing = False; self.btn_play.setText("▶ Phát")
        
        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened(): return
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30
        
        self.slider.setMaximum(self.total_frames - 1); self.slider.setValue(0)
        self.show_frame_at(0)

    def toggle_play(self):
        if not self.cap: return
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.btn_play.setText("⏸ Dừng"); self.play_timer.start(int(1000 / self.fps))
        else:
            self.btn_play.setText("▶ Phát"); self.play_timer.stop()

    def _video_loop(self):
        curr = int(self.cap.get(cv2.CAP_PROP_POS_FRAMES))
        if curr >= self.total_frames - 1:
            self.toggle_play(); self.show_frame_at(0)
        else:
            self.show_frame_at(curr + 1); self.slider.setValue(curr + 1)

    def on_slider_moved(self, value):
        if self.is_playing: self.toggle_play()
        self.show_frame_at(value)

    def show_frame_at(self, frame_idx):
        if not self.cap: return
        self.cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
        ret, frame = self.cap.read()
        if ret:
            self.canvas.update_frame(frame)
            s = int(frame_idx / self.fps); t = int(self.total_frames / self.fps)
            self.lbl_timecode.setText(f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d} / {t//3600:02d}:{(t%3600)//60:02d}:{t%60:02d}")
            if not self.is_playing: self.sync_sub_with_timeline(frame_idx)

    def sync_sub_with_timeline(self, frame_idx):
        if not self.sub_data_cache or self.fps == 0: return
        curr_ms = (frame_idx / self.fps) * 1000
        for i, item in enumerate(self.sub_data_cache):
            if item["start"] <= curr_ms <= item["end"]:
                self.table_sub.selectRow(i)
                break

    def toggle_roi_mode(self):
        is_drawing = not self.canvas.is_drawing if self.canvas.cursor().shape() == Qt.CursorShape.CrossCursor else True
        if is_drawing:
            self.btn_roi.setText("✂ Đang cắt ROI...")
            self.btn_roi.setStyleSheet("color: #e74c3c; font-weight: bold;")
            self.canvas.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        else:
            self.btn_roi.setText("✂ Click để Vẽ ROI")
            self.btn_roi.setStyleSheet("")
            self.canvas.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.canvas.is_drawing = False
        self.canvas.repaint_canvas()

    def _on_roi_updated(self, y1, y2):
        self.cfg.step5.roi_y_start, self.cfg.step5.roi_y_end = y1, y2
        self.lbl_roi_val.setText(f"📐 Tọa độ ROI: {y1:.2f} - {y2:.2f}")
        self.log_msg(f"✂ Đã chốt vùng ROI: {y1:.2f} -> {y2:.2f}")
        self.save_yaml_config()
        self.toggle_roi_mode()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = ProGUI()
    window.showMaximized()
    sys.exit(app.exec())