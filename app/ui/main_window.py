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
    QPushButton, QHBoxLayout, QColorDialog, QTextEdit, QTabWidget, QFrame, QScrollArea, QStackedWidget)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer, QEvent, QPropertyAnimation, QEasingCurve, QRect
from PyQt6.QtGui import QImage, QPixmap, QColor, QPainter, QPen, QCursor, QFont, QPalette, QLinearGradient, QBrush, QPainterPath, QIcon
import hashlib

from app.core.language.registry import LanguageRegistry, get_edge_voices_for_language

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
# DESIGN TOKENS — CINEMATIC DARK STUDIO PALETTE
# ======================================================================
# ======================================================================
# DESIGN TOKENS — ULTRA PREMIUM STUDIO PALETTE
# ======================================================================
# ======================================================================
# DESIGN TOKENS — ULTRA PREMIUM STUDIO PALETTE
# ======================================================================
COLORS = {
    # Nền (Backgrounds) - Xám than sâu thẳm, không dùng đen tuyền
    "bg_base": "#0B0C10",       
    "bg_surface": "#12141A",    
    "bg_elevated": "#1A1D24",   
    "bg_hover": "#222731",      
    "bg_active": "#2A313E",     

    # Điểm nhấn (Accents) 
    "accent_primary": "#00C8FF",   
    "accent_secondary": "#00FF9D", 
    "accent_amber": "#FFB800",     
    "accent_red": "#FF4757",       

    # Tương thích ngược với các hàm ở dưới (Đừng xóa)
    "accent_cyan": "#00C8FF",   
    "accent_green": "#00FF9D",
    "accent_purple": "#7C3AED",

    # Chữ (Text) - Trắng kem nhẹ nhàng để không chói mắt
    "text_primary": "#E2E8F0",     
    "text_secondary": "#94A3B8",   
    "text_muted": "#475569",       

    # Viền (Borders) - Viền siêu mỏng, sắc nét
    "border_subtle": "#1E293B",    
    "border_normal": "#334155",    
    "border_focus": "#00C8FF",

    # Trạng thái
    "status_ok": "#00FF9D", 
    "status_warn": "#FFB800", 
    "status_err": "#FF4757",
}

FONTS = {
    "mono":    "'JetBrains Mono', 'Consolas', monospace",
    "ui":      "'Inter', 'Segoe UI', system-ui, sans-serif",
    "display": "'Inter', 'Segoe UI', system-ui, sans-serif",
}

# ======================================================================
# GLOBAL STYLESHEET (QSS) — ĐÃ TỐI ƯU HÓA HOÀN TOÀN
# ======================================================================
GLOBAL_QSS = f"""
/* === BASE TỔNG THỂ === */
QMainWindow, QWidget {{
    background-color: {COLORS['bg_base']};
    color: {COLORS['text_primary']};
    font-family: {FONTS['ui']};
    font-size: 13px;
}}
QDialog {{
    background-color: {COLORS['bg_surface']};
}}

/* === SPLITTER (Thanh kéo thu phóng) === */
QSplitter::handle {{
    background-color: {COLORS['border_subtle']};
    width: 2px;
    margin: 6px 0px;
}}
QSplitter::handle:hover {{
    background-color: {COLORS['accent_primary']};
}}

/* === GROUPBOX (Khung viền) === */
QGroupBox {{
    background-color: {COLORS['bg_surface']};
    border: 1px solid {COLORS['border_subtle']};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 16px;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 12px;
    top: -8px;
    color: {COLORS['text_secondary']};
    font-weight: bold;
    font-size: 12px;
    background-color: {COLORS['bg_base']};
    padding: 0px 8px;
    letter-spacing: 0.5px;
}}

/* === THANH CUỘN (SCROLLBARS) XỊN === */
QScrollBar:vertical {{
    background: {COLORS['bg_surface']};
    width: 8px;
    border-radius: 4px;
    margin: 2px;
}}
QScrollBar::handle:vertical {{
    background: {COLORS['border_normal']};
    border-radius: 4px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {COLORS['text_muted']};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0px; }}

QScrollBar:horizontal {{
    background: {COLORS['bg_surface']};
    height: 8px;
    border-radius: 4px;
    margin: 2px;
}}
QScrollBar::handle:horizontal {{
    background: {COLORS['border_normal']};
    border-radius: 4px;
}}
QScrollBar::handle:horizontal:hover {{
    background: {COLORS['text_muted']};
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{ width: 0px; }}

/* === INPUTS & TEXT EDITS === */
QLineEdit, QTextEdit {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border_normal']};
    border-radius: 6px;
    padding: 7px 12px;
    selection-background-color: {COLORS['accent_primary']}40;
}}
QLineEdit:hover, QTextEdit:hover {{
    border-color: {COLORS['text_muted']};
}}
QLineEdit:focus, QTextEdit:focus {{
    border: 1px solid {COLORS['border_focus']};
    background-color: {COLORS['bg_hover']};
}}
QLineEdit::placeholder, QTextEdit::placeholder {{
    color: {COLORS['text_muted']};
}}

/* === COMBOBOX (Menu thả xuống) === */
QComboBox {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border_normal']};
    border-radius: 6px;
    padding: 6px 12px;
    min-height: 28px;
}}
QComboBox:hover {{
    border-color: {COLORS['text_muted']};
}}
QComboBox:focus {{
    border-color: {COLORS['border_focus']};
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox::down-arrow {{
    image: none;
    border-left: 4px solid transparent;
    border-right: 4px solid transparent;
    border-top: 5px solid {COLORS['text_secondary']};
}}
QComboBox QAbstractItemView {{
    background-color: {COLORS['bg_elevated']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border_normal']};
    border-radius: 6px;
    selection-background-color: {COLORS['bg_active']};
    selection-color: {COLORS['accent_primary']};
    outline: none;
    padding: 4px;
}}

/* === LIST WIDGET === */
QListWidget {{
    background-color: {COLORS['bg_elevated']};
    border: 1px solid {COLORS['border_subtle']};
    border-radius: 8px;
    outline: none;
    padding: 4px;
}}
QListWidget::item {{
    padding: 8px 12px;
    border-radius: 4px;
    color: {COLORS['text_secondary']};
    border: 1px solid transparent;
}}
QListWidget::item:hover {{
    background-color: {COLORS['bg_hover']};
    color: {COLORS['text_primary']};
}}
QListWidget::item:selected {{
    background-color: {COLORS['bg_active']};
    color: {COLORS['text_primary']};
    border: 1px solid {COLORS['border_normal']};
    border-left: 3px solid {COLORS['accent_primary']};
}}

/* === TABLE WIDGET === */
QTableWidget {{
    background-color: {COLORS['bg_elevated']};
    border: 1px solid {COLORS['border_subtle']};
    border-radius: 8px;
    gridline-color: {COLORS['border_subtle']};
    outline: none;
}}
QTableWidget::item {{
    padding: 6px 8px;
    color: {COLORS['text_primary']};
    border: none;
    border-bottom: 1px solid {COLORS['bg_base']};
}}
QTableWidget::item:selected {{
    background-color: {COLORS['bg_active']};
    color: {COLORS['text_primary']};
}}
QTableWidget::item:hover {{
    background-color: {COLORS['bg_hover']};
}}
QHeaderView::section {{
    background-color: {COLORS['bg_surface']};
    color: {COLORS['text_secondary']};
    border: none;
    border-bottom: 1px solid {COLORS['border_subtle']};
    border-right: 1px solid {COLORS['bg_base']};
    padding: 8px 10px;
    font-size: 11px;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.5px;
}}

/* === PROGRESS BAR === */
QProgressBar {{
    background-color: {COLORS['bg_elevated']};
    border: 1px solid {COLORS['border_subtle']};
    border-radius: 4px;
    height: 8px;
}}
QProgressBar::chunk {{
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 {COLORS['accent_primary']}, stop:1 {COLORS['accent_secondary']});
    border-radius: 3px;
}}

/* === TABS === */
QTabWidget::pane {{
    border: 1px solid {COLORS['border_subtle']};
    border-radius: 8px;
    background-color: {COLORS['bg_surface']};
    top: -1px;
}}
QTabBar::tab {{
    background-color: transparent;
    color: {COLORS['text_secondary']};
    padding: 10px 20px;
    margin-right: 2px;
    border-bottom: 2px solid transparent;
    font-weight: 600;
    font-size: 13px;
}}
QTabBar::tab:selected {{
    color: {COLORS['accent_primary']};
    border-bottom: 2px solid {COLORS['accent_primary']};
}}
QTabBar::tab:hover:!selected {{
    color: {COLORS['text_primary']};
    background-color: {COLORS['bg_hover']};
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}}

/* === CHECKBOXES === */
QCheckBox {{
    color: {COLORS['text_secondary']};
    spacing: 10px;
}}
QCheckBox:hover {{
    color: {COLORS['text_primary']};
}}
QCheckBox::indicator {{
    width: 18px;
    height: 18px;
    border-radius: 4px;
    border: 1px solid {COLORS['border_normal']};
    background-color: {COLORS['bg_elevated']};
}}
QCheckBox::indicator:hover {{
    border-color: {COLORS['text_muted']};
}}
QCheckBox::indicator:checked {{
    background-color: {COLORS['accent_primary']};
    border-color: {COLORS['accent_primary']};
    /* Có thể dùng image checkmark ở đây nếu có file svg */
}}
"""

# ======================================================================
# HELPER FUNCTIONS
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
# CUSTOM WIDGETS
# ======================================================================

class ClickableSlider(QSlider):
    def mousePressEvent(self, ev):
        if ev.button() == Qt.MouseButton.LeftButton:
            val = self.minimum() + ((self.maximum() - self.minimum()) * ev.pos().x()) / self.width()
            self.setValue(int(val))
            self.sliderMoved.emit(int(val))
            ev.accept()
        else:
            super().mousePressEvent(ev)


class StatusBadge(QLabel):
    """Inline pill-shaped status indicator"""
    def __init__(self, text="", color=COLORS['accent_cyan'], parent=None):
        super().__init__(text, parent)
        self._color = color
        self.setFixedHeight(22)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._update_style()

    def _update_style(self):
        self.setStyleSheet(f"""
            QLabel {{
                background-color: {self._color}20;
                color: {self._color};
                border: 1px solid {self._color}60;
                border-radius: 11px;
                padding: 0px 10px;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 0.5px;
            }}
        """)

    def set_state(self, text, color):
        self._color = color
        self.setText(text)
        self._update_style()


class IconButton(QPushButton):
    """Compact icon-style button with hover glow"""
    def __init__(self, text="", accent=COLORS['accent_primary'], parent=None):
        super().__init__(text, parent)
        self._accent = accent
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self._base_style()

    def _base_style(self):
        self.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['bg_elevated']};
                color: {COLORS['text_primary']};
                border: 1px solid {COLORS['border_normal']};
                border-radius: 6px;
                padding: 6px 14px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                background-color: {self._accent}15;  /* Sáng màu accent nhẹ nhàng */
                color: {self._accent};
                border-color: {self._accent}80;
            }}
            QPushButton:pressed {{
                background-color: {self._accent}30;
            }}
        """)


class PrimaryButton(QPushButton):
    """Main CTA button with solid gradients"""
    def __init__(self, text="", parent=None):
        super().__init__(text, parent)
        self.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.setMinimumHeight(48) # Cao to rõ ràng
        self._set_state("idle")

    def _set_state(self, state):
        if state == "idle":
            self.setStyleSheet(f"""
                QPushButton {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 {COLORS['accent_primary']}, stop:1 {COLORS['accent_secondary']});
                    color: {COLORS['bg_base']};
                    border: none;
                    border-radius: 8px;
                    font-size: 15px;
                    font-weight: 800;
                    letter-spacing: 1px;
                }}
                QPushButton:hover {{
                    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #1EE3FF, stop:1 #33FFAB);
                }}
                QPushButton:disabled {{
                    background: {COLORS['bg_elevated']};
                    color: {COLORS['text_muted']};
                    border: 1px solid {COLORS['border_normal']};
                }}
            """)
        elif state == "running":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['bg_active']};
                    color: {COLORS['accent_amber']};
                    border: 1px solid {COLORS['accent_amber']};
                    border-radius: 8px;
                    font-size: 14px;
                    font-weight: 700;
                }}
                QPushButton:disabled {{ 
                    background-color: {COLORS['bg_elevated']}; 
                    color: {COLORS['accent_amber']}; 
                    border: 1px solid {COLORS['accent_amber']}50;
                }}
            """)
        elif state == "confirm_roi":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['accent_primary']};
                    color: {COLORS['bg_base']};
                    border: none;
                    border-radius: 8px;
                    font-size: 14px;
                    font-weight: 800;
                }}
                QPushButton:hover {{ background-color: #1EE3FF; }}
            """)
        elif state == "confirm_sub":
            self.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['accent_amber']};
                    color: {COLORS['bg_base']};
                    border: none;
                    border-radius: 8px;
                    font-size: 14px;
                    font-weight: 800;
                }}
                QPushButton:hover {{ background-color: #FFC933; }}
            """)


class SectionLabel(QLabel):
    """Subtle uppercase section header"""
    def __init__(self, text="", parent=None):
        super().__init__(text.upper(), parent)
        self.setStyleSheet(f"""
            QLabel {{
                color: {COLORS['text_muted']};
                font-size: 10px;
                font-weight: 700;
                letter-spacing: 1.5px;
                padding: 0px 0px 6px 0px;
            }}
        """)


class Divider(QFrame):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFrameShape(QFrame.Shape.HLine)
        self.setFixedHeight(1)
        self.setStyleSheet(f"background-color: {COLORS['border_subtle']}; border: none;")


class StepCheckBox(QCheckBox):
    """Step toggle with accent styling"""
    def __init__(self, icon, label, parent=None):
        super().__init__(f"  {icon}  {label}", parent)
        self.setChecked(True)
        self.setStyleSheet(f"""
            QCheckBox {{
                color: {COLORS['text_secondary']};
                spacing: 6px;
                font-size: 13px;
                padding: 5px 8px;
                border-radius: 6px;
            }}
            QCheckBox:hover {{
                background-color: {COLORS['bg_hover']};
                color: {COLORS['text_primary']};
            }}
            QCheckBox::indicator {{
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1.5px solid {COLORS['border_normal']};
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS['accent_cyan']};
                border-color: {COLORS['accent_cyan']};
            }}
        """)


class GlowCard(QWidget):
    """Borderless card with subtle inner glow"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setStyleSheet(f"""
            GlowCard {{
                background-color: {COLORS['bg_surface']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 10px;
            }}
        """)


class ConsoleOutput(QTextEdit):
    """Styled terminal-like log output"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("JetBrains Mono, Consolas", 11))
        self.setStyleSheet(f"""
            QTextEdit {{
                background-color: {COLORS['bg_base']};
                color: #A8B8CC;
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 8px;
                padding: 8px 10px;
                selection-background-color: {COLORS['accent_cyan']}40;
            }}
        """)

    def log(self, text):
        # Color-code by prefix
        if "✅" in text or "hoàn tất" in text.lower():
            colored = f'<span style="color:{COLORS["status_ok"]}">{text}</span>'
        elif "❌" in text or "lỗi" in text.lower():
            colored = f'<span style="color:{COLORS["status_err"]}">{text}</span>'
        elif "⚠️" in text:
            colored = f'<span style="color:{COLORS["status_warn"]}">{text}</span>'
        elif "🚀" in text or "▶" in text:
            colored = f'<span style="color:{COLORS["accent_cyan"]}">{text}</span>'
        elif text.startswith("💾"):
            colored = f'<span style="color:{COLORS["accent_purple"]}">{text}</span>'
        else:
            colored = f'<span style="color:#8B9DB5">{text}</span>'
        self.append(colored)
        self.verticalScrollBar().setValue(self.verticalScrollBar().maximum())


class GUILogSink:
    def __init__(self, signal):
        self.signal = signal
    def write(self, message):
        self.signal.emit(message.strip())


# ======================================================================
# PIPELINE WORKER (unchanged logic)
# ======================================================================
class PipelineWorker(QThread):
    progress_sig = pyqtSignal(int, int, str)
    log_sig = pyqtSignal(str)
    pause_for_sub_sig = pyqtSignal()
    request_roi_sig = pyqtSignal(str)
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
            engine.cfg.pipeline.__dict__['run_s1'] = self.state['steps']['s1']
            engine.cfg.pipeline.__dict__['run_s2'] = self.state['steps']['s2']
            engine.cfg.pipeline.__dict__['run_s3'] = self.state['steps']['s3']
            engine.cfg.pipeline.__dict__['run_s4'] = self.state['steps']['s4']
            engine.cfg.pipeline.__dict__['run_s5'] = self.state['steps']['s5']
            engine.cfg.pipeline.__dict__['run_s6'] = self.state['steps']['s6']

            original_process_one = engine.process_one

            def hooked_process_one(video_path):
                self.request_roi_sig.emit(str(video_path))
                if self.state['chk_pause_roi']:
                    self.state['pause_roi_event'].clear()
                    self.state['pause_roi_event'].wait()
                original_process_one(video_path)

            engine.process_one = hooked_process_one

            self.log_sig.emit("🚀 Bắt đầu chạy Pipeline...")
            engine.run(on_progress=on_progress)
            self.log_sig.emit(f"✅ Tiến trình hoàn tất toàn bộ!")

        except Exception as e:
            logger.exception("Pipeline Error")
            self.log_sig.emit(f"❌ Lỗi Pipeline: {str(e)}")
        finally:
            logger.remove(handler_id)
            self.finished_sig.emit()

class CapCutStyleColorDialog(QDialog):
    """Color Picker kiểu CapCut - Tab Gợi ý mặc định, Tab Tùy chỉnh tự mở bảng màu"""

    PRESETS = [
        ("Đen huyền bí", [0, 0, 0], 190),
        ("Đen nhẹ", [15, 15, 25], 170),
        ("Xám sang trọng", [35, 35, 45], 200),
        ("Trắng tinh khiết", [255, 255, 255], 255),
        ("Vàng gold", [255, 215, 0], 255),
        ("Cam nổi bật", [255, 140, 0], 255),
        ("Xanh dương tech", [0, 200, 255], 255),
        ("Xanh lá tươi", [50, 255, 140], 255),
        ("Hồng thanh lịch", [255, 80, 120], 255),
        ("Tím huyền bí", [180, 90, 255], 255),
        ("Đỏ năng lượng", [255, 60, 80], 255),
    ]

    def __init__(self, parent=None, target="pill"):
        super().__init__(parent)
        self.setWindowTitle("🎨 Chọn màu phụ đề")
        self.resize(720, 580)
        self.target = target

        # Load giá trị hiện tại
        if target == "text" and hasattr(parent, 'step5_text_rgb'):
            rgb_list = parent.step5_text_rgb
        elif target == "outline" and hasattr(parent, 'step5_out_rgb'):
            rgb_list = parent.step5_out_rgb
        else:
            rgb_list = getattr(parent, 'step5_pill_rgb', [0, 0, 0, 190])

        self.current_rgb = list(rgb_list[:3])
        self.current_alpha = rgb_list[3] if len(rgb_list) > 3 else (190 if target == "pill" else 255)

        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(24, 24, 24, 24)

        # Preview
        self.preview = QLabel()
        self.preview.setFixedHeight(110)
        self.preview.setStyleSheet("border-radius: 12px; border: 3px solid #333;")
        layout.addWidget(self.preview)
        self._update_preview()

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # Tab 1: Gợi ý màu (mặc định)
        tab_preset = QWidget()
        p_layout = QVBoxLayout(tab_preset)
        p_layout.setSpacing(16)

        lbl = QLabel("🌟 Màu gợi ý phổ biến cho phụ đề")
        lbl.setStyleSheet("font-size: 15px; font-weight: 600; color: #00D4FF;")
        p_layout.addWidget(lbl)

        grid = QGridLayout()
        grid.setSpacing(12)
        for i, (name, rgb, alpha) in enumerate(self.PRESETS):
            btn = QPushButton(name)
            btn.setFixedHeight(52)
            btn.setStyleSheet(f"""
                background-color: rgba({rgb[0]},{rgb[1]},{rgb[2]},{alpha});
                color: white;
                font-weight: 600;
                border-radius: 8px;
                border: 2px solid transparent;
            """)
            btn.clicked.connect(lambda _, r=rgb, a=alpha: self._select_preset(r, a))
            grid.addWidget(btn, i // 3, i % 3)
        p_layout.addLayout(grid)
        self.tabs.addTab(tab_preset, "🌟 Gợi ý màu")

        # Tab 2: Tùy chỉnh nâng cao - Tự động mở bảng màu khi chuyển tab
        tab_custom = QWidget()
        c_layout = QVBoxLayout(tab_custom)
        c_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        c_layout.setSpacing(40)

        lbl_custom = QLabel("⚙ Tùy chỉnh nâng cao")
        lbl_custom.setStyleSheet("font-size: 17px; font-weight: 600; color: #FFFFFF;")
        c_layout.addWidget(lbl_custom)

        lbl_sub = QLabel("Bảng màu chi tiết sẽ tự động mở...")
        lbl_sub.setStyleSheet("color: #888; font-size: 13px;")
        c_layout.addWidget(lbl_sub)

        self.tabs.addTab(tab_custom, "⚙ Tùy chỉnh nâng cao")

        layout.addWidget(self.tabs, stretch=1)

        # Nút hành động
        btn_layout = QHBoxLayout()
        cancel_btn = QPushButton("Hủy")
        ok_btn = QPushButton("✓ Áp dụng màu")
        ok_btn.setStyleSheet("background: #00C853; color: black; font-weight: bold; padding: 12px;")

        cancel_btn.clicked.connect(self.reject)
        ok_btn.clicked.connect(self.accept)

        btn_layout.addWidget(cancel_btn)
        btn_layout.addWidget(ok_btn)
        layout.addLayout(btn_layout)

        # Mặc định mở tab Gợi ý
        self.tabs.setCurrentIndex(0)

    def _update_preview(self):
        color = f"rgba({self.current_rgb[0]}, {self.current_rgb[1]}, {self.current_rgb[2]}, {self.current_alpha})"
        self.preview.setStyleSheet(f"background-color: {color}; border-radius: 12px;")

    def _select_preset(self, rgb, alpha):
        self.current_rgb = list(rgb)
        self.current_alpha = alpha
        self._update_preview()

    def _open_qt_color_dialog(self):
        """Mở bảng màu Qt đầy đủ"""
        initial = QColor(*self.current_rgb)
        color = QColorDialog.getColor(initial, self, "Chọn màu chi tiết", 
                                      QColorDialog.ColorDialogOption.ShowAlphaChannel)
        
        if color.isValid():
            self.current_rgb = [color.red(), color.green(), color.blue()]
            self.current_alpha = color.alpha()
            self._update_preview()

    def _on_tab_changed(self, index):
        """Khi chuyển sang tab Tùy chỉnh nâng cao → tự động mở bảng màu Qt"""
        if index == 1:   # Tab thứ 2 là "Tùy chỉnh nâng cao"
            QTimer.singleShot(80, self._open_qt_color_dialog)   # delay nhỏ để tab render xong

    def get_rgb(self):
        return tuple(self.current_rgb)

    def get_alpha(self):
        return self.current_alpha
# ======================================================================
# CONFIG WINDOW — REDESIGNED
# ======================================================================
class ConfigWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.parent = parent
        self.setWindowTitle("Studio Settings")
        self.resize(760, 600)
        self.setMinimumSize(720, 560)

        self.cfg = parent.cfg
        self.registry = LanguageRegistry()
        self.step5_text_rgb = parent.step5_text_rgb
        self.step5_out_rgb = parent.step5_out_rgb
        self.step5_pill_rgb = parent.step5_pill_rgb

        self.setStyleSheet(GLOBAL_QSS + f"""
            QDialog {{
                background-color: {COLORS['bg_surface']};
            }}
        """)

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(20, 20, 20, 16)
        main_layout.setSpacing(16)

        # Header
        hdr = QHBoxLayout()
        title = QLabel("⚙  Studio Settings")
        title.setStyleSheet(f"""
            font-size: 18px;
            font-weight: 700;
            color: {COLORS['text_primary']};
            letter-spacing: -0.3px;
        """)
        hdr.addWidget(title)
        hdr.addStretch()
        sub = QLabel(f"v{__version__}")
        sub.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        hdr.addWidget(sub)
        main_layout.addLayout(hdr)
        main_layout.addWidget(Divider())

        # Tabs
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)

        # ── TAB 1: AI & System ──
        tab_ai = QWidget()
        lay_ai = QFormLayout(tab_ai)
        lay_ai.setSpacing(14)
        lay_ai.setContentsMargins(16, 16, 16, 16)
        lay_ai.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        # FFmpeg
        h_ff = QHBoxLayout(); h_ff.setSpacing(8)
        self.le_ffmpeg = QLineEdit(self.cfg.ffmpeg_bin or "")
        self.le_ffmpeg.setPlaceholderText("Đường dẫn đến ffmpeg.exe...")
        btn_ff = IconButton("📁 Browse")
        btn_ff.setFixedWidth(90)
        btn_ff.clicked.connect(self._browse_ffmpeg)
        h_ff.addWidget(self.le_ffmpeg); h_ff.addWidget(btn_ff)
        lay_ai.addRow(self._lbl("FFmpeg Binary"), h_ff)

        # Languages
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
        lay_ai.addRow(self._lbl("Ngôn ngữ nguồn"), self.cb_source)
        lay_ai.addRow(self._lbl("Ngôn ngữ đích"), self.cb_target)

        # Gemini
        self.le_s4_model = QLineEdit(getattr(self.cfg.step4, "model_name", "gemini-2.5-flash"))
        lay_ai.addRow(self._lbl("Model Gemini"), self.le_s4_model)

        self.txt_s4_keys = QTextEdit()
        self.txt_s4_keys.setMaximumHeight(88)
        self.txt_s4_keys.setPlaceholderText("Mỗi API Key một dòng...")
        keys = getattr(self.cfg.step4, "gemini_api_keys", [])
        self.txt_s4_keys.setPlainText("\n".join(keys))
        lay_ai.addRow(self._lbl("Gemini API Keys"), self.txt_s4_keys)

        # ── TAB 2: OCR & Whisper ──
        tab_sub = QWidget()
        lay_sub = QFormLayout(tab_sub)
        lay_sub.setSpacing(14)
        lay_sub.setContentsMargins(16, 16, 16, 16)
        lay_sub.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.cb_s3_src = QComboBox()
        self.cb_s3_src.addItems(["voice", "image"])
        self.cb_s3_src.setCurrentText(getattr(self.cfg.step3, "srt_source", "voice"))
        lay_sub.addRow(self._lbl("Nguồn tách Sub"), self.cb_s3_src)

        self.le_s3_lang = QLineEdit(getattr(self.cfg.step3, "language", "zh"))
        self.le_s3_lang.setReadOnly(True)
        self.le_s3_lang.setStyleSheet(f"""
            QLineEdit {{
                background-color: {COLORS['bg_base']};
                color: {COLORS['text_muted']};
                border: 1px dashed {COLORS['border_normal']};
                border-radius: 6px;
                padding: 7px 10px;
            }}
        """)
        self.le_s3_lang.setToolTip("Tự động đồng bộ từ Ngôn ngữ nguồn")
        lay_sub.addRow(self._lbl("Ngôn ngữ Video gốc"), self.le_s3_lang)

        self.le_s3_frames = QLineEdit(str(getattr(self.cfg.step3, "image_step_frames", 10)))
        lay_sub.addRow(self._lbl("Bỏ qua (Frames)"), self.le_s3_frames)

        # ── TAB 3: Color / ASS ──
        tab_color = QWidget()
        lay_color = QFormLayout(tab_color)
        lay_color.setSpacing(16)
        lay_color.setContentsMargins(16, 16, 16, 16)

        # Font
        font_box = QHBoxLayout(); font_box.setSpacing(8)
        self.le_font_path = QLineEdit(getattr(self.cfg.step5, "font_path", ""))
        self.le_font_path.setPlaceholderText("Để trống dùng font mặc định...")
        btn_font = IconButton("🔤 Chọn Font")
        btn_font.clicked.connect(self._browse_font)
        font_box.addWidget(self.le_font_path); font_box.addWidget(btn_font)
        lay_color.addRow(self._lbl("Font Subtitle"), font_box)

        def color_row(target, rgb_list):
            """rgb_list có thể là list 3 hoặc 4 phần tử (R,G,B[,A])"""
            # Chỉ lấy 3 giá trị RGB để hiển thị swatch
            rgb = rgb_list[:3] if isinstance(rgb_list, (list, tuple)) else [255, 255, 255]
            
            h = QHBoxLayout()
            h.setSpacing(10)
            
            swatch = QLabel()
            swatch.setFixedSize(36, 28)
            swatch.setStyleSheet(f"""
                background-color: {_rgb_hex(*rgb)};
                border: 1px solid {COLORS['border_normal']};
                border-radius: 6px;
            """)
            
            btn = IconButton("✏ Đổi màu")
            btn.setFixedWidth(100)
            btn.clicked.connect(lambda: self._pick_color(target, swatch))
            
            h.addWidget(swatch)
            h.addWidget(btn)
            h.addStretch()
            return h

        lay_color.addRow(self._lbl("Màu chữ chính"), color_row("text", self.step5_text_rgb[:3]))
        lay_color.addRow(self._lbl("Viền chữ"), color_row("outline", self.step5_out_rgb[:3]))
        lay_color.addRow(self._lbl("Nền Pill Box"), color_row("pill", self.step5_pill_rgb[:3]))

        # ── TAB 4: Audio / TTS ──
        tab_audio = QWidget()
        lay_audio = QFormLayout(tab_audio)
        lay_audio.setSpacing(14)
        lay_audio.setContentsMargins(16, 16, 16, 16)
        lay_audio.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        self.cb_s6_engine = QComboBox()
        self.cb_s6_engine.addItems(["qwen", "edge", "google"])
        self.cb_s6_engine.setCurrentText(getattr(self.cfg.step6, "tts_engine", "qwen").lower())
        self.cb_s6_engine.currentTextChanged.connect(self._toggle_dynamic_ui)
        lay_audio.addRow(self._lbl("TTS Engine"), self.cb_s6_engine)

        self.w_qwen_voice = QWidget()
        lq = QHBoxLayout(self.w_qwen_voice); lq.setContentsMargins(0,0,0,0)
        self.cb_qwen_voice = QComboBox()
        json_path = Path("gwen-tts/data/ref_info.json")
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    for key, val in json.load(f).items():
                        self.cb_qwen_voice.addItem(val.get("name", key), userData=key)
            except: pass
        if self.cb_qwen_voice.count() == 0:
            self.cb_qwen_voice.addItem("Ái Vy", userData="ai_vy")
        idx = self.cb_qwen_voice.findData(getattr(self.cfg.step6, "qwen_voice", "ai_vy"))
        if idx >= 0: self.cb_qwen_voice.setCurrentIndex(idx)
        lq.addWidget(self.cb_qwen_voice)
        self.lbl_qwen_voice = self._lbl("Giọng Qwen TTS")
        lay_audio.addRow(self.lbl_qwen_voice, self.w_qwen_voice)

        self.w_edge_voice = QWidget()
        le = QHBoxLayout(self.w_edge_voice); le.setContentsMargins(0,0,0,0)
        self.cb_edge_voice = QComboBox()
        le.addWidget(self.cb_edge_voice)
        self.lbl_edge_voice = self._lbl("Giọng Edge TTS")
        lay_audio.addRow(self.lbl_edge_voice, self.w_edge_voice)

        self.cb_s6_mode = QComboBox()
        self.cb_s6_mode.addItems(["Mode 1 — Giữ toàn bộ âm gốc", "Mode 2 — Thay âm thanh mới"])
        self.cb_s6_mode.setCurrentIndex(0 if str(getattr(self.cfg.step6, "audio_mode", 1)) == "1" else 1)
        self.cb_s6_mode.currentIndexChanged.connect(self._toggle_dynamic_ui)
        lay_audio.addRow(self._lbl("Chế độ Mix"), self.cb_s6_mode)

        self.w_bgm = QWidget()
        lb = QHBoxLayout(self.w_bgm); lb.setContentsMargins(0,0,0,0); lb.setSpacing(8)
        self.le_bg_music = QLineEdit(getattr(self.cfg.step6, "random_bgm_dir", ""))
        self.le_bg_music.setPlaceholderText("Thư mục nhạc nền ngẫu nhiên...")
        btn_bgm = IconButton("📁 Browse")
        btn_bgm.setFixedWidth(90)
        btn_bgm.clicked.connect(self._browse_bg_music)
        lb.addWidget(self.le_bg_music); lb.addWidget(btn_bgm)
        self.lbl_bgm = self._lbl("Thư mục Nhạc nền")
        lay_audio.addRow(self.lbl_bgm, self.w_bgm)

        # Audio params grid
        params_widget = QWidget()
        params_grid = QGridLayout(params_widget)
        params_grid.setSpacing(10)
        params_grid.setContentsMargins(0, 8, 0, 0)

        param_defs = [
            ("Vol TTS", "le_s6_vol", "tts_volume", 1.4),
            ("Vol BGM", "le_s6_bg_vol", "music_volume", 0.2),
            ("Vol gốc", "le_s6_extra", "extra_voice_volume", 0.1),
            ("Stretch", "le_s6_sp", "stretch_ratio", 1.1),
            ("Pitch", "le_s6_pitch", "pitch_factor", 1.2),
            ("Speed", "le_s6_speed", "speedup_when_short", 1.5),
        ]
        for i, (label, attr, cfg_key, default) in enumerate(param_defs):
            col = i % 3
            row = (i // 3) * 2
            lbl = QLabel(label)
            lbl.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px; font-weight: 600; letter-spacing: 0.5px;")
            le = QLineEdit(str(getattr(self.cfg.step6, cfg_key, default)))
            le.setFixedHeight(32)
            params_grid.addWidget(lbl, row, col)
            params_grid.addWidget(le, row + 1, col)
            setattr(self, attr, le)

        lay_audio.addRow(params_widget)

        # Add tabs
        self.tabs.addTab(tab_ai,    "🤖  AI & Hệ thống")
        self.tabs.addTab(tab_sub,   "🔎  Quét Phụ đề")
        self.tabs.addTab(tab_color, "🎨  Màu ASS")
        self.tabs.addTab(tab_audio, "🎧  Âm thanh & TTS")
        main_layout.addWidget(self.tabs, stretch=1)

        # Footer buttons
        main_layout.addWidget(Divider())
        h_btn = QHBoxLayout()
        h_btn.setSpacing(10)
        btn_cancel = QPushButton("Hủy")
        btn_cancel.setFixedWidth(80)
        btn_cancel.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['text_secondary']};
                border: 1px solid {COLORS['border_normal']};
                border-radius: 6px;
                padding: 8px;
                font-weight: 600;
            }}
            QPushButton:hover {{
                color: {COLORS['text_primary']};
                border-color: {COLORS['border_normal']};
                background-color: {COLORS['bg_hover']};
            }}
        """)
        btn_cancel.clicked.connect(self.reject)

        btn_save = QPushButton("  💾  Lưu cấu hình")
        btn_save.setFixedWidth(160)
        btn_save.setFixedHeight(38)
        btn_save.setStyleSheet(f"""
            QPushButton {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1565C0, stop:1 #0097A7);
                color: white;
                border: none;
                border-radius: 6px;
                font-weight: 700;
                font-size: 13px;
            }}
            QPushButton:hover {{
                background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
                    stop:0 #1976D2, stop:1 #00BCD4);
            }}
        """)
        btn_save.clicked.connect(self._save_and_close)

        h_btn.addStretch()
        h_btn.addWidget(btn_cancel)
        h_btn.addWidget(btn_save)
        main_layout.addLayout(h_btn)

        self._toggle_dynamic_ui()

    def _lbl(self, text):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 13px; font-weight: 600;")
        return lbl

    def _browse_font(self):
        initial_dir = str(Path(self.le_font_path.text()).parent) if self.le_font_path.text() else "C:/Windows/Fonts"
        fp, _ = QFileDialog.getOpenFileName(self, "Chọn Font", initial_dir, "Font Files (*.ttf *.otf)")
        if fp: self.le_font_path.setText(fp)

    def _browse_ffmpeg(self):
        initial_dir = str(Path(self.le_ffmpeg.text()).parent) if self.le_ffmpeg.text() else ""
        fp, _ = QFileDialog.getOpenFileName(self, "Chọn ffmpeg.exe", initial_dir, "FFmpeg (ffmpeg.exe);;All (*.*)")
        if fp: self.le_ffmpeg.setText(fp)

    def _browse_bg_music(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục Nhạc nền", self.le_bg_music.text() or "")
        if d: self.le_bg_music.setText(d)

    def _update_edge_voices(self, edge_prefix: str):
        if not hasattr(self, 'cb_edge_voice'): return
        def load():
            voices = asyncio.run(get_edge_voices_for_language(edge_prefix))
            self.cb_edge_voice.clear()
            for v in voices:
                self.cb_edge_voice.addItem(v["name"], v["id"])
            if voices: self.cb_edge_voice.setCurrentIndex(0)
        threading.Thread(target=load, daemon=True).start()

    def _on_language_changed(self):
        source_code = self.cb_source.currentData()
        target_code = self.cb_target.currentData()
        if not source_code or not target_code: return
        src = self.registry.get(source_code)
        tgt = self.registry.get(target_code)
        self.le_s3_lang.setText(src.whisper)
        self._update_edge_voices(tgt.edge_prefix)

    def _toggle_dynamic_ui(self):
        is_qwen = self.cb_s6_engine.currentText() == "qwen"
        self.w_qwen_voice.setVisible(is_qwen)
        self.lbl_qwen_voice.setVisible(is_qwen)
        is_edge = self.cb_s6_engine.currentText() == "edge"
        self.w_edge_voice.setVisible(is_edge)
        self.lbl_edge_voice.setVisible(is_edge)
        is_mode_2 = self.cb_s6_mode.currentIndex() == 1
        self.w_bgm.setVisible(is_mode_2)
        self.lbl_bgm.setVisible(is_mode_2)

    def _pick_color(self, target, swatch):
        """Color Picker đẹp và dễ dùng giống CapCut"""
        dialog = CapCutStyleColorDialog(self, target)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            rgb = dialog.get_rgb()
            alpha = dialog.get_alpha()

            swatch.setStyleSheet(f"""
                background-color: {_rgb_hex(*rgb)};
                border: 2px solid #555;
                border-radius: 6px;
            """)

            if target == "text":
                self.step5_text_rgb = rgb + (alpha,)
            elif target == "outline":
                self.step5_out_rgb = rgb + (alpha,)
            elif target == "pill":
                self.step5_pill_rgb = rgb + (alpha,)

    def _save_and_close(self):
        c = self.cfg
        try:
            # ==================== NGÔN NGỮ ====================
            source_code = self.cb_source.currentData() or "zh"
            target_code = self.cb_target.currentData() or "vi"
            src = self.registry.get(source_code)
            tgt = self.registry.get(target_code)

            c.source_lang = source_code
            c.target_lang = target_code

            c.step3.__dict__['language'] = src.whisper
            c.step3.__dict__['image_ocr_lang'] = src.paddleocr
            c.step4.__dict__['source_lang'] = src.gemini
            c.step4.__dict__['target_lang'] = target_code
            c.step5.__dict__['ocr_lang'] = src.paddleocr
            c.step6.__dict__['tts_lang'] = target_code
            c.step6.__dict__['google_lang'] = target_code

            # ==================== TTS ENGINE (QUAN TRỌNG NHẤT) ====================
            engine = self.cb_s6_engine.currentText().lower().strip()
            c.step6.__dict__['tts_engine'] = engine

            # Chỉ lưu voice tương ứng với engine được chọn
            if engine == "edge":
                if hasattr(self, 'cb_edge_voice') and self.cb_edge_voice.currentData():
                    c.step6.__dict__['edge_voice'] = self.cb_edge_voice.currentData()
                else:
                    c.step6.__dict__['edge_voice'] = f"{tgt.edge_prefix}-NamMinhNeural"

            elif engine == "qwen":
                if hasattr(self, 'cb_qwen_voice') and self.cb_qwen_voice.currentData():
                    c.step6.__dict__['qwen_voice'] = self.cb_qwen_voice.currentData()
                else:
                    c.step6.__dict__['qwen_voice'] = getattr(c.step6, 'qwen_voice', "nsnd_kim_cuc")

            elif engine == "google":
                # Google TTS không cần voice cụ thể
                pass

            # ==================== CÁC THAM SỐ KHÁC ====================
            c.ffmpeg_bin = self.le_ffmpeg.text().strip()
            c.step3.__dict__['srt_source'] = self.cb_s3_src.currentText()
            c.step3.__dict__['image_step_frames'] = int(self.le_s3_frames.text() or 10)
            c.step4.__dict__['model_name'] = self.le_s4_model.text().strip()

            keys_text = self.txt_s4_keys.toPlainText().strip()
            c.step4.__dict__['gemini_api_keys'] = [k.strip() for k in re.split(r'[,;\n]', keys_text) if k.strip()] if keys_text else []

            c.step5.__dict__['font_path'] = self.le_font_path.text().strip()

            # Audio parameters - An toàn hơn
            if hasattr(self, 'le_s6_vol'):
                c.step6.__dict__['tts_volume'] = float(self.le_s6_vol.text() or 1.4)
            if hasattr(self, 'le_s6_bg_vol'):
                c.step6.__dict__['music_volume'] = float(self.le_s6_bg_vol.text() or 0.35)
            if hasattr(self, 'le_s6_extra'):
                c.step6.__dict__['extra_voice_volume'] = float(self.le_s6_extra.text() or 0.05)
            if hasattr(self, 'le_s6_sp'):
                c.step6.__dict__['stretch_ratio'] = float(self.le_s6_sp.text() or 1.1)
            if hasattr(self, 'le_s6_pitch'):
                c.step6.__dict__['pitch_factor'] = float(self.le_s6_pitch.text() or 1.2)
            if hasattr(self, 'le_s6_speed'):
                c.step6.__dict__['speedup_when_short'] = float(self.le_s6_speed.text() or 1.5)

            c.step6.__dict__['audio_mode'] = 1 if self.cb_s6_mode.currentIndex() == 0 else 2
            c.step6.__dict__['random_bgm_dir'] = getattr(self, 'le_bg_music', QLineEdit("")).text().strip()

            # Lưu màu RGBA
            self.parent.step5_text_rgb = getattr(self, 'step5_text_rgb', [255, 255, 255, 255])
            self.parent.step5_out_rgb  = getattr(self, 'step5_out_rgb',  [0, 0, 0, 255])
            self.parent.step5_pill_rgb = getattr(self, 'step5_pill_rgb', [0, 0, 0, 190])

            c.step5.text_color = list(self.parent.step5_text_rgb)
            c.step5.outline_color = list(self.parent.step5_out_rgb)
            c.step5.pill_background_color = list(self.parent.step5_pill_rgb)

            self.parent.log_msg(f"✅ Đã lưu config — {src.name} → {tgt.name} | Engine: {engine.upper()}")
            
        except Exception as e:
            logger.error(f"Lỗi lưu Setting: {e}")
            self.parent.log_msg(f"⚠️ Lỗi lưu Setting: {e}")
            return

        self.parent.save_yaml_config()
        self.accept()
# ======================================================================
# VIDEO CANVAS — ROI DRAWING (unchanged logic, minor visual polish)
# ======================================================================
class VideoCanvas(QLabel):
    roi_updated = pyqtSignal(float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(f"background-color: #050709; border-radius: 10px;")
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(320, 200)

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
        if self.current_frame is None:
            self._draw_placeholder()
            return
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

            # Dark overlay outside ROI
            painter.fillRect(0, 0, new_w, ry1, QColor(0, 0, 0, 160))
            painter.fillRect(0, ry2, new_w, new_h - ry2, QColor(0, 0, 0, 160))

            # ROI border — cyan dashed
            pen = QPen(QColor(0, 212, 255), 1.5, Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawLine(0, ry1, new_w, ry1)
            painter.drawLine(0, ry2, new_w, ry2)

            # Corner handles
            handle_color = QColor(0, 212, 255)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(handle_color))
            for hx in [0, new_w - 6]:
                painter.drawRect(hx, ry1 - 3, 6, 6)
                painter.drawRect(hx, ry2 - 3, 6, 6)

            # Coordinate labels
            painter.setFont(QFont("JetBrains Mono, Consolas", 10, QFont.Weight.Bold))
            pct1, pct2 = (ry1 / new_h) * 100, (ry2 / new_h) * 100

            for y_pos, pct in [(ry1, pct1), (ry2, pct2)]:
                bg_y = y_pos + 4 if y_pos == ry2 else y_pos - 20
                painter.fillRect(8, bg_y, 72, 16, QColor(0, 0, 0, 180))
                painter.setPen(QPen(QColor(0, 212, 255)))
                painter.drawText(12, bg_y + 12, f"Y: {pct:.1f}%")

        painter.end()
        self.setPixmap(pixmap)

    def _draw_placeholder(self):
        lbl_w, lbl_h = self.width(), self.height()
        pixmap = QPixmap(lbl_w, lbl_h)
        pixmap.fill(QColor("#050709"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.setPen(QPen(QColor(COLORS['text_muted'])))
        painter.setFont(QFont("Segoe UI", 13))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "Chọn video để xem trước →")
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
            pct1 = max(0.0, min(1.0, y1 / self.draw_h))
            pct2 = max(0.0, min(1.0, y2 / self.draw_h))
            self.roi_start_y, self.roi_end_y = min(pct1, pct2), max(pct1, pct2)
            self.temp_y = None
            self.roi_updated.emit(self.roi_start_y, self.roi_end_y)
            self.repaint_canvas()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.repaint_canvas()


# ======================================================================
# MAIN WINDOW — REDESIGNED LAYOUT
# ======================================================================
class ProGUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"  Reup Video Pro — Studio Master  v{__version__}")
        
        # ==============================================================
        # 1. Đặt kích thước tối thiểu (Không cho phép co nhỏ hơn số này)
        self.setMinimumSize(1200, 700)
        # 2. Đặt kích thước mặc định khi ở trạng thái Thu Nhỏ (Restore Down)
        self.resize(1366, 768)
        # ==============================================================
        
        icon_path = Path("app/assets/icon.ico")
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        else:
            logger.warning("Không tìm thấy icon.ico")

        self._init_config()
        self.cap = None
        self.fps = 30
        self.total_frames = 0
        self.is_playing = False

        self.current_folder = self.cfg.pipeline.input_videos
        self.output_folder = getattr(self.cfg.pipeline, 'output_dir', "")
        self.current_video_path = None
        self.current_srt_path = None
        self.sub_data_cache = []

        self.is_paused_for_sub = False
        self.worker = None
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.pause_roi_event = threading.Event()
        self.pause_roi_event.set()

        self.play_timer = QTimer()
        self.play_timer.timeout.connect(self._video_loop)

        self._setup_ui()
        self.setStyleSheet(GLOBAL_QSS)

        if self.current_folder and os.path.exists(str(self.current_folder)):
            self.reload_folder()
        
        # QTimer.singleShot(100, self.showMaximized)

    def closeEvent(self, event):
        if self.cap:
            self.cap.release()
            self.cap = None
        self.hide()
        event.accept()
        current_pid = os.getpid()
        try:
            if platform.system() == "Windows":
                subprocess.Popen(f"taskkill /F /T /PID {current_pid}", shell=True,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            else:
                import signal
                os.killpg(os.getpgrp(), signal.SIGKILL)
        except: pass
        os._exit(0)

    def _ms_to_srt_time(self, ms):
        s, ms = divmod(int(ms), 1000)
        m, s = divmod(s, 60)
        h, m = divmod(m, 60)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _init_config(self):
        if ConfigLoader:
            self.cfg = ConfigLoader.load()
        else:
            class DummyCfg: pass
            self.cfg = DummyCfg()
            self.cfg.pipeline = DummyCfg()
            self.cfg.pipeline.input_videos = ""
            self.cfg.pipeline.output_dir = ""
            for s in ['step2','step3','step4','step6']:
                setattr(self.cfg, s, DummyCfg())
            self.cfg.step5 = DummyCfg()
            self.cfg.step5.roi_y_start = 0.6
            self.cfg.step5.roi_y_end = 1.0
            self.cfg.step5.text_color = "&H0000FFFF"
            self.cfg.step5.outline_color = "&H00000000"

        # ==================== ĐỌC MÀU RGBA - ĐẢM BẢO LUÔN CÓ 4 PHẦN TỬ ====================
        def get_color_list(key, default=[255, 255, 255, 255]):
            val = getattr(self.cfg.step5, key, None)
            if isinstance(val, (list, tuple)):
                # Đảm bảo luôn có đủ 4 giá trị (R,G,B,A)
                color = [int(x) for x in val]
                while len(color) < 4:
                    color.append(default[len(color)])
                return color[:4]
            elif isinstance(val, str) and val.startswith("&H"):
                return _ass_to_rgba_list(val)
            return default

        self.step5_text_rgb    = get_color_list('text_color',    [255, 255, 255, 255])
        self.step5_out_rgb     = get_color_list('outline_color', [0,   0,   0,   255])
        self.step5_pill_rgb    = get_color_list('pill_background_color', [0, 0, 0, 190])
        # =================================================================

    def save_yaml_config(self):
        try:
            cp = Path("config.yaml").resolve()
            data = yaml.safe_load(open(cp, encoding="utf-8")) if cp.exists() else {}
            data = data or {}

            # Các thông tin cơ bản
            data["source_lang"] = getattr(self.cfg, "source_lang", "zh")
            data["target_lang"] = getattr(self.cfg, "target_lang", "vi")
            data["ffmpeg_bin"] = getattr(self.cfg, "ffmpeg_bin", "")

            # Step 3, 4, 6 giữ nguyên
            for sec, pairs in [
                ("step3", [("language","zh"), ("image_ocr_lang","ch"), ("srt_source","image"), ("image_step_frames",10)]),
                ("step4", [("model_name","gemini-2.5-flash"), ("source_lang","zh-CN"), ("target_lang","vi"), ("gemini_api_keys",[])]),
                ("step6", [("tts_lang","vi"), ("google_lang","vi"), ("tts_volume",1.4), ("music_volume",0.35),
                          ("extra_voice_volume",0.05), ("stretch_ratio",1.1), ("pitch_factor",1.2),
                          ("speedup_when_short",1.5), ("audio_mode",1), ("random_bgm_dir",""), ("tts_engine","qwen")]),
            ]:
                if sec not in data: data[sec] = {}
                for k, d in pairs:
                    data[sec][k] = getattr(getattr(self.cfg, sec, {}), k, d)

            # ==================== LƯU MÀU RGBA ĐÚNG CÁCH ====================
            if "step5" not in data:
                data["step5"] = {}

            data["step5"]["ocr_lang"] = getattr(self.cfg.step5, "ocr_lang", "ch")
            data["step5"]["roi_y_start"] = getattr(self.cfg.step5, "roi_y_start", 0.6)
            data["step5"]["roi_y_end"] = getattr(self.cfg.step5, "roi_y_end", 1.0)
            data["step5"]["font_path"] = getattr(self.cfg.step5, "font_path", "")

            # Lưu màu theo đúng format list 4 số RGBA
            data["step5"]["text_color"] = list(self.step5_text_rgb)
            data["step5"]["outline_color"] = list(self.step5_out_rgb)
            data["step5"]["pill_background_color"] = list(self.step5_pill_rgb)

            # Các trường khác của step5
            data["step5"]["font_size"] = getattr(self.cfg.step5, "font_size", 45)
            data["step5"]["max_words_per_line"] = getattr(self.cfg.step5, "max_words_per_line", 10)

            # Lưu file
            yaml.dump(data, open(cp, "w", encoding="utf-8"), allow_unicode=True, sort_keys=False)
            self.log_msg(f"💾 Config đã lưu đúng RGBA → {cp}")

        except Exception as e:
            self.log_msg(f"❌ Lỗi lưu config: {e}")
            logger.exception("Save config error")

    # ==========================================
    # LAYOUT SETUP
    # ==========================================
    def _setup_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── TITLE BAR ──
        titlebar = self._build_titlebar()
        root.addWidget(titlebar)

        # ── MAIN SPLITTER ──
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(2)
        self.splitter.setChildrenCollapsible(False)

        self.splitter.addWidget(self._build_left_panel())
        self.splitter.addWidget(self._build_center_panel())
        self.splitter.addWidget(self._build_right_panel())
        self.splitter.setSizes([280, 720, 360])

        root.addWidget(self.splitter, stretch=1)

        # ── STATUS BAR ──
        statusbar = self._build_statusbar()
        root.addWidget(statusbar)

        self.chk_pause.stateChanged.connect(self._update_run_btn_label)
        self._update_run_btn_label()

    def _build_titlebar(self):
        bar = QWidget()
        bar.setFixedHeight(56)
        bar.setStyleSheet(f"""
            background-color: {COLORS['bg_surface']};
            border-bottom: 1px solid {COLORS['border_subtle']};
        """)
        h = QHBoxLayout(bar)
        h.setContentsMargins(16, 0, 16, 0)
        h.setSpacing(12)

        # Logo PNG
        logo_path = Path("app/assets/logo.png")
        if logo_path.exists():
            logo_label = QLabel()
            pixmap = QPixmap(str(logo_path))
            pixmap = pixmap.scaled(32, 32, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            logo_label.setPixmap(pixmap)
            h.addWidget(logo_label)
        else:
            h.addWidget(QLabel("⬡"))  # fallback

        # Brand name
        brand = QLabel("REUP VIDEO PRO")
        brand.setStyleSheet(f"""
            font-size: 16px;
            font-weight: 800;
            color: {COLORS['accent_cyan']};
            letter-spacing: 1.2px;
        """)
        h.addWidget(brand)

        ver = QLabel(f"Studio Master {__version__}")
        ver.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 12px;")
        h.addWidget(ver)

        h.addStretch()

        # Status badge
        self.badge_status = StatusBadge("● READY", COLORS['accent_green'])
        h.addWidget(self.badge_status)

        return bar

    def _build_left_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(240)
        panel.setMaximumWidth(340)
        panel.setStyleSheet(f"background-color: {COLORS['bg_surface']}; border-right: 1px solid {COLORS['border_subtle']};")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(12)

        # ── File Management ──
        layout.addWidget(SectionLabel("Workspace"))

        # 4 nút cân đối 2x2
        g=QGridLayout(); g.setSpacing(5); g.setColumnStretch(0,1); g.setColumnStretch(1,1)
        self.btn_input  =IconButton("📂 Input");       self.btn_input.clicked.connect(self.load_video_folder)
        self.btn_reload =IconButton("↻ Reload");       self.btn_reload.clicked.connect(self.reload_folder)
        self.btn_output =IconButton("🗂 Output");       self.btn_output.clicked.connect(self.select_output_folder)
        self.btn_open   =IconButton("↗ Mở Output");    self.btn_open.clicked.connect(self.open_output_folder)
        g.addWidget(self.btn_input,0,0); g.addWidget(self.btn_reload,0,1)
        g.addWidget(self.btn_output,1,0); g.addWidget(self.btn_open,1,1)
        layout.addLayout(g)

        # File count indicator
        self.lbl_file_count = QLabel("0 video(s)")
        self.lbl_file_count.setStyleSheet(f"color: {COLORS['text_muted']}; font-size: 11px; padding-left: 2px;")
        layout.addWidget(self.lbl_file_count)

        # File list
        self.list_videos = QListWidget()
        self.list_videos.setAcceptDrops(True)
        self.list_videos.itemClicked.connect(self._on_video_selected)
        layout.addWidget(self.list_videos, stretch=1)

        layout.addWidget(Divider())

        # ── Pipeline Steps ──
        layout.addWidget(SectionLabel("Pipeline Steps"))

        self.step_vars = {}
        step_defs = [
            ("s3", "🔎", "Dò Sub (OCR / Whisper)"),
            ("s4", "🌐", "Dịch thuật (Gemini)"),
            ("s5", "✍", "Vẽ Phụ đề (ASS)"),
            ("s6", "🎧", "Mix TTS"),
        ]
        for key, icon, name in step_defs:
            chk = StepCheckBox(icon, name)
            self.step_vars[key] = chk
            layout.addWidget(chk)

        layout.addWidget(Divider())

        # ── Special Controls ──
        layout.addWidget(SectionLabel("Chế độ đặc biệt"))

        self.chk_pause = QCheckBox("  ✋  Dừng để sửa Sub (Bước 4)")
        self.chk_pause.setChecked(True)
        self.chk_pause.setStyleSheet(f"""
            QCheckBox {{
                color: {COLORS['accent_amber']};
                font-size: 12px;
                font-weight: 600;
                padding: 5px 8px;
                border-radius: 6px;
            }}
            QCheckBox:hover {{ background-color: {COLORS['bg_hover']}; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border-radius: 4px;
                border: 1.5px solid {COLORS['accent_amber']}80;
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS['accent_amber']};
                border-color: {COLORS['accent_amber']};
            }}
        """)
        layout.addWidget(self.chk_pause)

        self.chk_pause_roi = QCheckBox("  📐  Dừng set ROI mỗi video")
        self.chk_pause_roi.setChecked(True)
        self.chk_pause_roi.setStyleSheet(f"""
            QCheckBox {{
                color: {COLORS['accent_red']};
                font-size: 12px;
                font-weight: 600;
                padding: 5px 8px;
                border-radius: 6px;
            }}
            QCheckBox:hover {{ background-color: {COLORS['bg_hover']}; }}
            QCheckBox::indicator {{
                width: 16px; height: 16px;
                border-radius: 4px;
                border: 1.5px solid {COLORS['accent_red']}80;
                background-color: transparent;
            }}
            QCheckBox::indicator:checked {{
                background-color: {COLORS['accent_red']};
                border-color: {COLORS['accent_red']};
            }}
        """)
        layout.addWidget(self.chk_pause_roi)

        layout.addSpacing(6)

        # ── Action Buttons ──
        btn_settings = IconButton("⚙  Settings", COLORS['text_secondary'])
        btn_settings.clicked.connect(self.open_setup)
        layout.addWidget(btn_settings)

        self.btn_run = PrimaryButton("▶  CHẠY PIPELINE")
        self.btn_run.clicked.connect(self._on_btn_run_clicked)
        layout.addWidget(self.btn_run)

        return panel

    def _build_center_panel(self):
        panel = QWidget()
        panel.setStyleSheet(f"background-color: {COLORS['bg_base']};")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # ── ROI Toolbar ──
        roi_bar = QWidget()
        roi_bar.setFixedHeight(38)
        roi_bar.setStyleSheet(f"""
            background-color: {COLORS['bg_surface']};
            border: 1px solid {COLORS['border_subtle']};
            border-radius: 8px;
        """)
        roi_h = QHBoxLayout(roi_bar)
        roi_h.setContentsMargins(10, 0, 10, 0)
        roi_h.setSpacing(12)

        roi_icon = QLabel("✂")
        roi_icon.setStyleSheet(f"color: {COLORS['accent_cyan']}; font-size: 14px;")
        self.lbl_roi_val = QLabel(f"ROI  {self.cfg.step5.roi_y_start:.2f} — {self.cfg.step5.roi_y_end:.2f}")
        self.lbl_roi_val.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; font-family: JetBrains Mono, Consolas;")
        roi_h.addWidget(roi_icon)
        roi_h.addWidget(self.lbl_roi_val)
        roi_h.addStretch()

        self.btn_roi = IconButton("✂  Vẽ ROI", COLORS['accent_cyan'])
        self.btn_roi.setFixedWidth(110)
        self.btn_roi.clicked.connect(self.toggle_roi_mode)
        roi_h.addWidget(self.btn_roi)
        layout.addWidget(roi_bar)

        # ── Video Canvas ──
        self.canvas = VideoCanvas()
        self.canvas.roi_start_y = self.cfg.step5.roi_y_start
        self.canvas.roi_end_y = self.cfg.step5.roi_y_end
        self.canvas.roi_updated.connect(self._on_roi_updated)
        layout.addWidget(self.canvas, stretch=1)

        # ── Playback Controls ──
        ctrl = QWidget()
        ctrl.setFixedHeight(48)
        ctrl.setStyleSheet(f"""
            background-color: {COLORS['bg_surface']};
            border: 1px solid {COLORS['border_subtle']};
            border-radius: 8px;
        """)
        ctrl_h = QHBoxLayout(ctrl)
        ctrl_h.setContentsMargins(12, 6, 12, 6)
        ctrl_h.setSpacing(12)

        self.btn_play = QPushButton("▶")
        self.btn_play.setFixedSize(32, 32)
        self.btn_play.setCursor(QCursor(Qt.CursorShape.PointingHandCursor))
        self.btn_play.setStyleSheet(f"""
            QPushButton {{
                background-color: {COLORS['accent_cyan']}20;
                color: {COLORS['accent_cyan']};
                border: 1px solid {COLORS['accent_cyan']}50;
                border-radius: 16px;
                font-size: 13px;
                font-weight: 700;
            }}
            QPushButton:hover {{
                background-color: {COLORS['accent_cyan']}40;
            }}
        """)
        self.btn_play.clicked.connect(self.toggle_play)
        ctrl_h.addWidget(self.btn_play)

        self.lbl_timecode = QLabel("00:00:00")
        self.lbl_timecode.setFixedWidth(64)
        self.lbl_timecode.setStyleSheet(f"color: {COLORS['text_secondary']}; font-family: JetBrains Mono, Consolas; font-size: 12px;")
        ctrl_h.addWidget(self.lbl_timecode)

        self.slider = ClickableSlider(Qt.Orientation.Horizontal)
        self.slider.sliderMoved.connect(self.on_slider_moved)
        ctrl_h.addWidget(self.slider, stretch=1)

        self.lbl_duration = QLabel("00:00:00")
        self.lbl_duration.setFixedWidth(64)
        self.lbl_duration.setStyleSheet(f"color: {COLORS['text_muted']}; font-family: JetBrains Mono, Consolas; font-size: 12px;")
        ctrl_h.addWidget(self.lbl_duration)

        layout.addWidget(ctrl)
        return panel

    def _build_right_panel(self):
        panel = QWidget()
        panel.setMinimumWidth(300)
        panel.setMaximumWidth(500)
        panel.setStyleSheet(f"background-color: {COLORS['bg_surface']}; border-left: 1px solid {COLORS['border_subtle']};")

        layout = QVBoxLayout(panel)
        layout.setContentsMargins(12, 14, 12, 12)
        layout.setSpacing(10)

        # Sub header
        sub_hdr = QHBoxLayout()
        sub_hdr.setSpacing(8)
        sub_title = QLabel("📝  Subtitle Editor")
        sub_title.setStyleSheet(f"color: {COLORS['text_primary']}; font-size: 13px; font-weight: 700;")
        sub_hdr.addWidget(sub_title)
        sub_hdr.addStretch()

        btn_load_sub = IconButton("↑ Nạp SRT", COLORS['accent_amber'])
        btn_load_sub.setFixedHeight(28)
        btn_load_sub.clicked.connect(lambda: self.load_srt_file(None))
        sub_hdr.addWidget(btn_load_sub)
        layout.addLayout(sub_hdr)

        # Sub path indicator
        self.lbl_srt_path = QLabel("Chưa có file SRT")
        self.lbl_srt_path.setStyleSheet(f"""
            color: {COLORS['text_muted']};
            font-size: 11px;
            font-family: JetBrains Mono, Consolas;
            background-color: {COLORS['bg_elevated']};
            border-radius: 4px;
            padding: 4px 8px;
        """)
        self.lbl_srt_path.setWordWrap(True)
        layout.addWidget(self.lbl_srt_path)

        # Subtitle table
        self.table_sub = QTableWidget(0, 2)
        self.table_sub.setHorizontalHeaderLabels(["  Time  ", "Bản dịch (có thể sửa)"])
        self.table_sub.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.table_sub.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        self.table_sub.verticalHeader().setVisible(False)
        self.table_sub.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_sub.setWordWrap(True)
        self.table_sub.setTextElideMode(Qt.TextElideMode.ElideNone)
        self.table_sub.setShowGrid(False)
        self.table_sub.setAlternatingRowColors(True)
        self.table_sub.setStyleSheet(self.table_sub.styleSheet() + f"""
            QTableWidget {{ alternate-background-color: {COLORS['bg_elevated']}; }}
        """)
        self.table_sub.cellClicked.connect(self._on_sub_row_clicked)
        self.table_sub.horizontalHeader().sectionResized.connect(lambda: self.table_sub.resizeRowsToContents())
        self.table_sub.itemChanged.connect(lambda item: self.table_sub.resizeRowsToContents())
        layout.addWidget(self.table_sub, stretch=1)

        return panel

    def _build_statusbar(self):
        bar = QWidget()
        bar.setFixedHeight(110)
        bar.setStyleSheet(f"""
            background-color: {COLORS['bg_surface']};
            border-top: 1px solid {COLORS['border_subtle']};
        """)
        layout = QVBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)
        layout.setSpacing(6)

        # Progress row
        prog_row = QHBoxLayout()
        prog_row.setSpacing(12)

        self.lbl_progress = QLabel("Sẵn sàng")
        self.lbl_progress.setStyleSheet(f"color: {COLORS['text_secondary']}; font-size: 12px; min-width: 200px;")

        self.progressbar = QProgressBar()
        self.progressbar.setFixedHeight(5)
        self.progressbar.setTextVisible(False)
        self.progressbar.setValue(0)

        self.lbl_pct = QLabel("0%")
        self.lbl_pct.setFixedWidth(36)
        self.lbl_pct.setStyleSheet(f"color: {COLORS['accent_cyan']}; font-size: 11px; font-weight: 700; font-family: JetBrains Mono, Consolas;")

        btn_clear = QPushButton("✕ Xóa log")
        btn_clear.setFixedWidth(80)
        btn_clear.setFixedHeight(22)
        btn_clear.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {COLORS['text_muted']};
                border: 1px solid {COLORS['border_subtle']};
                border-radius: 4px;
                font-size: 11px;
            }}
            QPushButton:hover {{
                color: {COLORS['text_secondary']};
                border-color: {COLORS['border_normal']};
            }}
        """)
        btn_clear.clicked.connect(lambda: self.console.clear())

        prog_row.addWidget(self.lbl_progress)
        prog_row.addWidget(self.progressbar, stretch=1)
        prog_row.addWidget(self.lbl_pct)
        prog_row.addWidget(btn_clear)
        layout.addLayout(prog_row)

        # Console
        self.console = ConsoleOutput()
        self.console.setFixedHeight(62)
        layout.addWidget(self.console)

        return bar

    # ==========================================
    # LOGIC (same as original, minimal changes)
    # ==========================================
    def open_setup(self):
        dlg = ConfigWindow(self)
        dlg.exec()

    def _update_run_btn_label(self):
        if not self.is_paused_for_sub and self.worker is None:
            if self.chk_pause.isChecked():
                self.btn_run.setText("▶  CHẠY  (Dừng tại B4)")
            else:
                self.btn_run.setText("▶  CHẠY TOÀN BỘ")
            self.btn_run._set_state("idle")
            self.badge_status.set_state("● READY", COLORS['accent_green'])

    def _on_btn_run_clicked(self):
        if not self.pause_roi_event.is_set():
            self.save_yaml_config()
            if self.cap: self.cap.release(); self.cap = None
            self.log_msg("✅ Đã chốt ROI. Đang xử lý...")
            self.btn_run.setEnabled(False)
            self.btn_run.setText("⏳  ĐANG XỬ LÝ PIPELINE...")
            self.btn_run._set_state("running")
            self.badge_status.set_state("● RUNNING", COLORS['accent_amber'])
            self.pause_roi_event.set()
            return

        if self.is_paused_for_sub:
            self.save_edited_sub()
            self.is_paused_for_sub = False
            if self.cap: self.cap.release(); self.cap = None; self.canvas.repaint_canvas()
            self.btn_run.setEnabled(False)
            self.btn_run.setText("⏳  ĐANG CHẠY B5→6...")
            self.btn_run._set_state("running")
            self.log_msg("▶ Đã xác nhận Sub. Tiếp tục Pipeline...")
            self.pause_event.set()
            return

        self.save_yaml_config()
        self.is_paused_for_sub = False
        self.pause_event.set()
        self.pause_roi_event.set()
        if self.cap: self.cap.release(); self.cap = None

        self.btn_run.setEnabled(False)
        self.btn_run.setText("⏳  ĐANG XỬ LÝ...")
        self.btn_run._set_state("running")
        self.progressbar.setValue(0)
        self.lbl_pct.setText("0%")
        self.badge_status.set_state("● RUNNING", COLORS['accent_amber'])

        steps = {k: v.isChecked() for k, v in self.step_vars.items()}
        app_state = {
            'chk_pause': self.chk_pause.isChecked(),
            'chk_pause_roi': self.chk_pause_roi.isChecked(),
            'pause_event': self.pause_event,
            'pause_roi_event': self.pause_roi_event,
            'steps': {'s1': True, 's2': True, **steps}
        }

        self.worker = PipelineWorker(app_state)
        self.worker.progress_sig.connect(self._update_progress)
        self.worker.log_sig.connect(self.log_msg)
        self.worker.pause_for_sub_sig.connect(self._on_worker_paused)
        self.worker.request_roi_sig.connect(self._on_request_roi)
        self.worker.finished_sig.connect(self._on_worker_finished)
        self.worker.start()

    def _on_request_roi(self, video_path):
        self.current_video_path = video_path
        self.load_video_player(video_path)
        if self.chk_pause_roi.isChecked():
            self.log_msg(f"📐 Dừng ROI: {Path(video_path).name}")
            self.btn_run.setEnabled(True)
            self.btn_run.setText("✅  XÁC NHẬN ROI & TIẾP TỤC")
            self.btn_run._set_state("confirm_roi")
            self.badge_status.set_state("● PAUSED — ROI", COLORS['accent_cyan'])
        else:
            if self.cap: self.cap.release(); self.cap = None
            self.pause_roi_event.set()

    def _on_worker_paused(self):
        self.is_paused_for_sub = True
        self.log_msg("⏳ Đã dừng tại Bước 4 — đang nạp Sub...")
        self._auto_load_srt()
        if self.current_video_path and os.path.exists(self.current_video_path):
            self.load_video_player(self.current_video_path)
        self.btn_run.setEnabled(True)
        self.btn_run.setText("✅  XÁC NHẬN SUB & CHẠY TIẾP B5")
        self.btn_run._set_state("confirm_sub")
        self.badge_status.set_state("● PAUSED — SUB REVIEW", COLORS['accent_amber'])

    def _on_worker_finished(self):
        self.is_paused_for_sub = False
        self.worker = None
        self.btn_run.setEnabled(True)
        self._update_run_btn_label()
        self.badge_status.set_state("● DONE", COLORS['accent_green'])

    def _update_progress(self, completed, total, text):
        try:
            if total > 0:
                pct = max(0, min(100, int((completed / total) * 100)))
                self.progressbar.setValue(pct)
                self.lbl_pct.setText(f"{pct}%")
                self.lbl_progress.setText(f"File {completed}/{total} — {text[:50]}")
            else:
                self.lbl_progress.setText(text[:60])
        except: pass

    def _auto_load_srt(self):
        if not self.current_video_path: return
        video_name = Path(self.current_video_path).name
        safe_hash = hashlib.md5(video_name.encode('utf-8')).hexdigest()[:10]
        safe_stem = f"vid_{safe_hash}"

        search_dirs = [
            self.cfg.pipeline.step4_srt_translated,
            self.output_folder,
            self.current_folder,
            Path("workspace/processing")
        ]

        latest_srt, max_mtime = None, 0
        for d in search_dirs:
            if d and os.path.exists(str(d)):
                for root, _, files in os.walk(d):
                    for file in files:
                        if file.endswith(".srt") and safe_stem in file:
                            p = os.path.join(root, file)
                            try:
                                mtime = os.path.getmtime(p)
                                if mtime > max_mtime:
                                    max_mtime = mtime; latest_srt = p
                            except: pass

        if latest_srt:
            self.load_srt_file(latest_srt)
            self.log_msg(f"✅ Auto-load: {Path(latest_srt).name}")
        else:
            self.log_msg(f"⚠️ Không tìm thấy SRT ({safe_stem}). Nạp thủ công.")

    def load_srt_file(self, auto_path=None):
        path = auto_path
        if not path:
            path, _ = QFileDialog.getOpenFileName(self, "Chọn file SRT", "", "SRT Files (*.srt)")
        if not path or not os.path.exists(path): return

        self.current_srt_path = path
        self.lbl_srt_path.setText(Path(path).name)
        subs = pysrt.open(path, encoding='utf-8')

        self.table_sub.setUpdatesEnabled(False)
        self.table_sub.setRowCount(len(subs))
        self.sub_data_cache = []

        for i, s in enumerate(subs):
            start_ms, end_ms = s.start.ordinal, s.end.ordinal
            t_str = f"{self._ms_to_srt_time(start_ms)}\n→ {self._ms_to_srt_time(end_ms)}"
            time_item = QTableWidgetItem(t_str)
            time_item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            time_item.setForeground(QColor(COLORS['accent_amber']))

            text_item = QTableWidgetItem(s.text.replace("\n", " "))

            self.table_sub.setItem(i, 0, time_item)
            self.table_sub.setItem(i, 1, text_item)
            self.sub_data_cache.append({"start": start_ms, "end": end_ms})

        self.table_sub.resizeRowsToContents()
        self.table_sub.setUpdatesEnabled(True)

    def _on_sub_row_clicked(self, row, col):
        if self.fps > 0 and row < len(self.sub_data_cache):
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
            self.log_msg("💾 Đã lưu bản dịch.")
        except Exception as e:
            self.log_msg(f"❌ Lỗi lưu Sub: {e}")

    def load_video_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục Input")
        if folder:
            self.current_folder = folder
            self.cfg.pipeline.input_videos = Path(folder)
            self.reload_folder()
            self.save_yaml_config()

    def reload_folder(self):
        if not self.current_folder or not os.path.exists(str(self.current_folder)): return
        self.list_videos.clear()
        files = sorted([f for f in os.listdir(self.current_folder) if f.lower().endswith(('.mp4', '.mkv', '.avi', '.mov'))])
        for f in files:
            self.list_videos.addItem(f)
        count = len(files)
        self.lbl_file_count.setText(f"{count} video{'s' if count != 1 else ''}")

    def select_output_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "Chọn thư mục Output")
        if folder:
            self.output_folder = folder
            self.cfg.pipeline.output_dir = Path(folder)
            self.save_yaml_config()

    def open_output_folder(self):
        out_dir = str(self.output_folder)
        if not out_dir or out_dir in (".", ""):
            if hasattr(self.cfg.pipeline, 'step6_final'):
                out_dir = str(self.cfg.pipeline.step6_final)
            else:
                self.log_msg("⚠️ Chưa cấu hình Output."); return
        if not os.path.exists(out_dir):
            try: os.makedirs(out_dir, exist_ok=True)
            except Exception as e: self.log_msg(f"❌ Không tạo được thư mục: {e}"); return
        try:
            if platform.system() == "Windows": os.startfile(out_dir)
            elif platform.system() == "Darwin": subprocess.Popen(["open", out_dir])
            else: subprocess.Popen(["xdg-open", out_dir])
        except Exception as e:
            self.log_msg(f"❌ Lỗi mở thư mục: {e}")

    def log_msg(self, text):
        self.console.log(text)

    def _on_video_selected(self, item):
        path = os.path.join(self.current_folder, item.text())
        self.current_video_path = path
        self.load_video_player(path)

    def load_video_player(self, path):
        if self.cap: self.cap.release()
        self.play_timer.stop()
        self.is_playing = False
        self.btn_play.setText("▶")

        self.cap = cv2.VideoCapture(path)
        if not self.cap.isOpened(): return
        self.total_frames = int(self.cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or 30

        self.slider.setMaximum(self.total_frames - 1)
        self.slider.setValue(0)
        self.show_frame_at(0)

        total_s = int(self.total_frames / self.fps)
        self.lbl_duration.setText(f"{total_s//3600:02d}:{(total_s%3600)//60:02d}:{total_s%60:02d}")

    def toggle_play(self):
        if not self.cap: return
        self.is_playing = not self.is_playing
        if self.is_playing:
            self.btn_play.setText("⏸")
            self.play_timer.start(int(1000 / self.fps))
        else:
            self.btn_play.setText("▶")
            self.play_timer.stop()

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
            s = int(frame_idx / self.fps)
            self.lbl_timecode.setText(f"{s//3600:02d}:{(s%3600)//60:02d}:{s%60:02d}")
            if not self.is_playing:
                self.sync_sub_with_timeline(frame_idx)

    def sync_sub_with_timeline(self, frame_idx):
        if not self.sub_data_cache or self.fps == 0: return
        curr_ms = (frame_idx / self.fps) * 1000
        for i, item in enumerate(self.sub_data_cache):
            if item["start"] <= curr_ms <= item["end"]:
                self.table_sub.selectRow(i)
                self.table_sub.scrollToItem(self.table_sub.item(i, 0))
                break

    def toggle_roi_mode(self):
        is_drawing = self.canvas.cursor().shape() != Qt.CursorShape.CrossCursor
        if is_drawing:
            self.btn_roi.setText("✓  Đang vẽ ROI...")
            self.btn_roi.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['accent_red']}20;
                    color: {COLORS['accent_red']};
                    border: 1px solid {COLORS['accent_red']}60;
                    border-radius: 6px;
                    padding: 6px 14px;
                    font-weight: 700;
                    font-size: 12px;
                }}
            """)
            self.canvas.setCursor(QCursor(Qt.CursorShape.CrossCursor))
        else:
            self.btn_roi.setText("✂  Vẽ ROI")
            self.btn_roi.setStyleSheet("")
            # Restore IconButton style
            self.btn_roi.setStyleSheet(f"""
                QPushButton {{
                    background-color: {COLORS['accent_cyan']}15;
                    color: {COLORS['accent_cyan']};
                    border: 1px solid {COLORS['accent_cyan']}40;
                    border-radius: 6px;
                    padding: 6px 14px;
                    font-size: 12px;
                    font-weight: 600;
                }}
                QPushButton:hover {{
                    background-color: {COLORS['accent_cyan']}25;
                    border-color: {COLORS['accent_cyan']}90;
                }}
            """)
            self.canvas.setCursor(QCursor(Qt.CursorShape.ArrowCursor))
            self.canvas.is_drawing = False
        self.canvas.repaint_canvas()

    def _on_roi_updated(self, y1, y2):
        self.cfg.step5.roi_y_start = y1
        self.cfg.step5.roi_y_end = y2
        self.lbl_roi_val.setText(f"ROI  {y1:.2f} — {y2:.2f}")
        self.log_msg(f"✂ ROI chốt: {y1:.2f} → {y2:.2f}")
        self.save_yaml_config()
        self.toggle_roi_mode()


# if __name__ == "__main__":
#     app = QApplication(sys.argv)
#     app.setStyle("Fusion")
#     window = ProGUI()
#     window.showMaximized()
#     sys.exit(app.exec())