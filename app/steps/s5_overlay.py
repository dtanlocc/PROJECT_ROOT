# file: app/steps/s5_overlay.py
import os
import re
import cv2
import gc
import numpy as np
import subprocess
import pysrt
import torch
from pathlib import Path
from loguru import logger
from PIL import Image, ImageDraw, ImageFont
from collections import Counter
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

try:
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

def _color_to_rgb(val) -> tuple:
    """
    Chuyển đổi màu từ Config sang Tuple (R, G, B) cho PIL.
    Xử lý được cả dạng List [R, G, B, A] và dạng chuỗi ASS &H00BBGGRR.
    """
    # Nếu là List [255, 255, 0, 255]
    if isinstance(val, list) and len(val) >= 3:
        return (int(val[0]), int(val[1]), int(val[2]))
    
    # Nếu là chuỗi ASS Hex "&H0000FFFF" (do validator trong config_loader tạo ra)
    if isinstance(val, str) and val.strip().upper().startswith("&H"):
        try:
            s = val.strip().upper().replace("&H", "")
            # ASS Format: AABBGGRR hoặc BBGGRR
            if len(s) == 8: # AABBGGRR
                r = int(s[6:8], 16)
                g = int(s[4:6], 16)
                b = int(s[2:4], 16)
                return (r, g, b)
            elif len(s) == 6: # BBGGRR
                r = int(s[4:6], 16)
                g = int(s[2:4], 16)
                b = int(s[0:2], 16)
                return (r, g, b)
        except Exception:
            pass
            
    # Mặc định trả về màu vàng nếu lỗi
    return (255, 255, 0)

class Step5Overlay(BaseStep):
    def __init__(self, cfg, ffmpeg: FFmpegManager):
        super().__init__(cfg)
        self.ffmpeg_bin = ffmpeg.bin
        self.out_dir = Path(self.cfg.pipeline.step5_video_subbed)
        self._ocr = None

    # ============================================================
    # 1. CÁC HÀM LOGIC GỐC TỪ B5 (GIỮ NGUYÊN)
    # ============================================================
    def wrap_text(self, text, font, max_width):
        """Tự động ngắt dòng thông minh"""
        lines = []
        # Giữ lại các ngắt dòng có chủ ý
        raw_lines = text.replace('<br />', '\n').replace('<br>', '\n').split('\n')
        
        for raw_line in raw_lines:
            words = raw_line.split()
            if not words:
                continue
                
            current_line = []
            for word in words:
                test_line = ' '.join(current_line + [word]) if current_line else word
                bbox = font.getbbox(test_line)
                w = bbox[2] - bbox[0]
                
                if w <= max_width:
                    current_line.append(word)
                else:
                    if current_line:
                        lines.append(' '.join(current_line))
                        current_line = [word]
                    else:
                        lines.append(word)
                        current_line = []
                        
            if current_line:
                lines.append(' '.join(current_line))
                
        return '\n'.join(lines)

    def get_active_sub_info(self, subs, current_time_ms):
        for index, s in enumerate(subs):
            if s.start.ordinal <= current_time_ms <= s.end.ordinal:
                clean_text = s.text.replace('<br />', '\n').replace('<br>', '\n').strip()
                return index, clean_text
        return None, None

    def get_middle_frames_from_srt(self, video_path, srt_path, fps):
        if not os.path.exists(srt_path): return []
        try:
            subs = pysrt.open(str(srt_path))
            return [int(((s.start.ordinal + s.end.ordinal) / 2.0 / 1000.0) * fps) for s in subs]
        except: return []

    def detect_smart_sub_geometry(self, video_path, srt_path, ocr_engine):
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): 
            print("⚠️ Không thể mở video.")
            return None, None, None, None

        h_video = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w_video = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        fps = cap.get(cv2.CAP_PROP_FPS)

        target_frames = self.get_middle_frames_from_srt(video_path, srt_path, fps)
        
        if not target_frames:
            print("⚠️ Không có mốc thời gian phụ đề cứng.")
            cap.release()
            return None, None, None, None

        y_roi_start = int(h_video * self.cfg.step5.roi_y_start)
        y_roi_end = int(h_video * self.cfg.step5.roi_y_end)

        candidates = {}
        y_tol = 15 
        raw_ocr_results = {}

        for index, fno in enumerate(target_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
            ret, frame = cap.read()
            if not ret: continue

            roi_frame = frame[y_roi_start:y_roi_end, :]
            result = ocr_engine.ocr(roi_frame, cls=False)
            raw_ocr_results[index] = result
            
            if result and result[0]:
                for line in result[0]:
                    pts = np.array(line[0], np.int32)
                    text_content = line[1][0]
                    
                    y1 = pts[:, 1].min() + y_roi_start
                    y2 = pts[:, 1].max() + y_roi_start
                    x1, x2 = pts[:, 0].min(), pts[:, 0].max()
                    
                    h_text = y2 - y1
                    w_text = x2 - x1

                    if h_text > (h_video * 0.12): continue

                    matched = False
                    for y_key in candidates.keys():
                        if abs(y_key - y1) <= y_tol:
                            candidates[y_key]["boxes"].append((h_text, w_text))
                            candidates[y_key]["texts"].append(text_content)
                            candidates[y_key]["count"] += 1
                            matched = True
                            break
                    
                    if not matched:
                        candidates[y1] = {"boxes": [(h_text, w_text)], "texts": [text_content], "count": 1}

        cap.release()

        valid_candidates = []
        def normalize_text(t):
            t = re.sub(r'[^\w\s]', '', t)
            return t.replace(" ", "").lower()

        for y_key, data in candidates.items():
            normalized_texts = [normalize_text(t) for t in data["texts"] if len(t.strip()) > 1]
            if not normalized_texts: continue
                
            unique_texts_count = len(set(normalized_texts))
            total_valid_counts = len(normalized_texts)
            most_common_text_count = Counter(normalized_texts).most_common(1)[0][1]
            
            static_ratio = most_common_text_count / total_valid_counts
            dynamic_ratio = unique_texts_count / total_valid_counts

            if data["count"] > 5 and static_ratio <= 0.40 and (dynamic_ratio > 0.10 or unique_texts_count > 5):
                valid_candidates.append({"y_key": y_key, "boxes": data["boxes"], "count": data["count"]})

        if not valid_candidates:
            return None, None, None, None

        valid_candidates.sort(key=lambda x: x["count"], reverse=True)
        best_candidate = valid_candidates[0]
        
        global_y = int(best_candidate["y_key"])
        global_h = int(max([box[0] for box in best_candidate["boxes"]]) * 1.05) 
        global_w = max([box[1] for box in best_candidate["boxes"]])

        dynamic_blur_boxes = {}
        
        for index, result in raw_ocr_results.items():
            if not result or not result[0]: continue
            
            valid_x = []
            for line in result[0]:
                pts = np.array(line[0], np.int32)
                y_min = pts[:, 1].min() + y_roi_start 
                y_max = pts[:, 1].max() + y_roi_start 
                
                center_y = (y_min + y_max) / 2
                
                if abs(center_y - global_y) <= 30 or (y_min - 10 <= global_y <= y_max + 10):
                    valid_x.extend(pts[:, 0])
                    
            if valid_x:
                min_x = min(valid_x)
                max_x = max(valid_x)
                dynamic_blur_boxes[index] = {'x': int(min_x), 'w': int(max_x - min_x)}

        print(f"✅ Chốt Sub tại Y={global_y}, H={global_h}. Đo đạc động {len(dynamic_blur_boxes)} câu.")
        return global_y, global_h, global_w, dynamic_blur_boxes

    # ============================================================
    # 2. XỬ LÝ PIPELINE CHÍNH - TỐI ƯU GPU MAX SPEED
    # ============================================================
    def process(self, video_path: Path, srt_path: Path) -> Path:
        self.ensure_dir(self.out_dir)
        abs_v_path = os.path.normpath(str(video_path.absolute()))
        out_file = self.out_dir / f"{video_path.stem}.mp4"

        # A. Dò tìm vùng Sub bằng GPU
        logger.info(f"🤖 [Step 5] Phân tích vùng Sub cho: {video_path.name}")
        ocr = PaddleOCR(use_angle_cls=False, lang='ch', use_gpu=True, show_log=False)
        g_y, g_h, g_w, blur_map = self.detect_smart_sub_geometry(abs_v_path, srt_path, ocr)
        
        # Giải phóng GPU nhường tài nguyên cho Render
        del ocr
        gc.collect()
        if torch.cuda.is_available(): torch.cuda.empty_cache()

        cap = cv2.VideoCapture(abs_v_path)
        w, h, fps = int(cap.get(3)), int(cap.get(4)), cap.get(5) or 30
        
        # B. Cấu hình Font & Scale (%) từ B5
        f_scale = getattr(self.cfg.step5, "font_scale_h_percent", 0.03)
        f_size = int(h * f_scale)
        f_path = self.cfg.step5.font_path or "C:/Windows/Fonts/arialbd.ttf"
        main_font = ImageFont.truetype(f_path, f_size)
        
        # Cấu hình thẩm mỹ B5
        text_color = _color_to_rgb(self.cfg.step5.text_color)
        bg_fill = _color_to_rgb(self.cfg.step5.outline_color)
        line_spacing = int(h * 0.002)  # Khoảng cách giữa các dòng phụ đề
        blur_pad = int(h * 0.015)

        # Chế độ dự phòng nếu không dò được ROI
        fallback_mode = False
        if g_y is None:
            fallback_mode = True; g_y = int(h * 0.88); g_h = int(f_size * 1.5); g_w = int(w * 0.8); blur_map = {}

        # C. KHỞI TẠO FFMPEG PIPE - TỐI ƯU GPU NVENC TỐC ĐỘ CAO
        temp_render = self.out_dir / f"temp_render_{video_path.stem}.mp4"
        command = [
            self.ffmpeg_bin, '-y', '-hwaccel', 'cuda',
            '-f', 'rawvideo', '-vcodec', 'rawvideo', '-s', f'{w}x{h}',
            '-pix_fmt', 'bgr24', '-r', str(fps), '-i', '-',
            '-i', abs_v_path,
            '-map', '0:v', '-map', '1:a?',
            '-c:v', 'h264_nvenc', '-preset', 'p1', '-tune', 'ull', # P1 + ULL = Max Speed
            '-rc', 'vbr', '-cq', '24', '-pix_fmt', 'yuv420p',
            '-c:a', 'aac', '-b:a', '192k', str(out_file)
        ]
        
        proc = subprocess.Popen(command, stdin=subprocess.PIPE, bufsize=10**8)
        subs = pysrt.open(str(srt_path), encoding='utf-8')
        
        frame_count = 0
        logger.info(f"🎨 [Step 5] Đang Render Subtitle (GPU Max Speed)...")
        
        try:
            while True:
                ret, frame = cap.read()
                if not ret: break

                current_time_ms = (frame_count / fps) * 1000
                active_idx, text_to_draw = self.get_active_sub_info(subs, current_time_ms)
                
                if text_to_draw:
                    # 1. Logic Gaussian Blur B5
                    if not fallback_mode:
                        box = blur_map.get(active_idx, {'x': (w - g_w)//2, 'w': g_w})
                        bx, bw = max(0, box['x'] - blur_pad), min(w, box['w'] + blur_pad * 2)
                        roi = frame[g_y:g_y+g_h, bx:bx+bw].copy()
                        frame[g_y:g_y+g_h, bx:bx+bw] = cv2.GaussianBlur(roi, (51, 51), 0)

                    # 2. Logic Vẽ Rounded Background & Sub B5
                    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert('RGBA')
                    bg_layer = Image.new('RGBA', img_pil.size, (0, 0, 0, 0))
                    draw_bg = ImageDraw.Draw(bg_layer)
                    
                    wrapped_txt = self.wrap_text(text_to_draw, main_font, int(w * 0.9))
                    bbox = draw_bg.multiline_textbbox((0, 0), wrapped_txt, font=main_font, align='center', spacing=line_spacing)
                    lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    lx, ly = (w - lw) // 2, g_y + (g_h - lh) // 2 - bbox[1]

                    # Nền bo góc (Radius 30% chiều cao nền)
                    bg_pad_x, bg_pad_y = int(f_size * 0.5), int(f_size * 0.15)
                    bg_rect = [lx - bg_pad_x, ly - bg_pad_y, lx + lw + bg_pad_x, ly + lh + bg_pad_y + int(h*0.001)]
                    draw_bg.rounded_rectangle(bg_rect, radius=int((bg_rect[3]-bg_rect[1])*0.3), fill=bg_fill)

                    img_pil = Image.alpha_composite(img_pil, bg_layer)
                    # Vẽ text lên trên
                    ImageDraw.Draw(img_pil).multiline_text(
                        (lx, ly), wrapped_txt, font=main_font, fill=text_color, 
                        align='center', spacing=line_spacing, stroke_width=2, stroke_fill=(0, 0, 0, 255)
                    )
                    frame = cv2.cvtColor(np.array(img_pil.convert('RGB')), cv2.COLOR_RGB2BGR)

                proc.stdin.write(frame.tobytes())
                frame_count += 1
                if frame_count % 500 == 0: logger.debug(f"Rendered {frame_count} frames...")

        finally:
            cap.release()
            proc.stdin.close()
            proc.wait()

        logger.success(f"✅ [Step 5] DONE: {out_file.name}")
        return out_file