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
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

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

    def _wrap_text(self, text, font, max_width):
        lines = []
        raw_lines = text.replace('<br />', '\n').replace('<br>', '\n').split('\n')
        for raw_line in raw_lines:
            words = raw_line.split()
            if not words: continue
            current_line = []
            for word in words:
                test_line = ' '.join(current_line + [word]) if current_line else word
                bbox = font.getbbox(test_line)
                if (bbox[2] - bbox[0]) <= max_width:
                    current_line.append(word)
                else:
                    if current_line: lines.append(' '.join(current_line))
                    current_line = [word]
            if current_line: lines.append(' '.join(current_line))
        return '\n'.join(lines)

    def _get_active_sub_info(self, subs, current_time_ms):
        for index, s in enumerate(subs):
            if s.start.ordinal <= current_time_ms <= s.end.ordinal:
                clean_text = s.text.replace('<br />', '\n').replace('<br>', '\n').strip()
                return index, clean_text
        return None, None

    def _detect_smart_geometry(self, video_path, srt_path):
        from paddleocr import PaddleOCR
        if not self._ocr:
            self._ocr = PaddleOCR(use_angle_cls=False, lang='ch', use_gpu=self.cfg.step3.image_use_gpu, show_log=False)
        
        cap = cv2.VideoCapture(str(video_path))
        h_vid = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        
        try:
            subs_list = pysrt.open(str(srt_path))
            target_frames = [int(((s.start.ordinal + s.end.ordinal) / 2.0 / 1000.0) * fps) for s in subs_list]
        except: return None, None, None, {}

        y_roi_start, y_roi_end = int(h_vid * self.cfg.step5.roi_y_start), int(h_vid * self.cfg.step5.roi_y_end)
        candidates = {}
        raw_ocr_results = {}

        for index, fno in enumerate(target_frames):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
            ret, frame = cap.read()
            if not ret: continue
            res = self._ocr.ocr(frame[y_roi_start:y_roi_end, :], cls=False)
            raw_ocr_results[index] = res
            if res and res[0]:
                for line in res[0]:
                    box = np.array(line[0]) # FIX: Ép kiểu NumPy ngay từ đầu
                    txt = line[1][0]
                    y1, y2 = box[:, 1].min() + y_roi_start, box[:, 1].max() + y_roi_start
                    h_txt = y2 - y1
                    if h_txt > (h_vid * 0.12): continue
                    matched = False
                    for y_key in list(candidates.keys()):
                        if abs(y_key - y1) <= 15:
                            candidates[y_key]["boxes"].append(h_txt)
                            candidates[y_key]["texts"].append(txt)
                            candidates[y_key]["count"] += 1; matched = True; break
                    if not matched: candidates[y1] = {"boxes": [h_txt], "texts": [txt], "count": 1}
        cap.release()

        valid = [ (y, max(d["boxes"]), d["count"]) for y, d in candidates.items() if d["count"] > 5 ]
        if not valid: return None, None, None, {}
        valid.sort(key=lambda x: x[2], reverse=True)
        best_y, best_h = int(valid[0][0]), int(valid[0][1] * 1.05)

        # FIX: Sửa logic tính toán blur_boxes để tránh lỗi tuple index
        blur_boxes = {}
        for idx, res in raw_ocr_results.items():
            if res and res[0]:
                xs = []
                for line in res[0]:
                    box = np.array(line[0])
                    p_y_min = box[:, 1].min() + y_roi_start
                    if abs(p_y_min - best_y) <= 30:
                        xs.extend(box[:, 0])
                if xs: blur_boxes[idx] = {'x': int(min(xs)), 'w': int(max(xs)-min(xs))}
        
        return best_y, best_h, int(best_h * 5), blur_boxes

    def process(self, video_path: Path, srt_path: Path):
        self.ensure_dir(self.out_dir)
        txt_color_tuple = _color_to_rgb(self.cfg.step5.text_color)
        out_color_tuple = _color_to_rgb(self.cfg.step5.outline_color)
        abs_v = os.path.normpath(str(video_path.absolute()))
        out_f = self.out_dir / f"{video_path.stem}.mp4"
        
        # 1. Đo đạc tọa độ
        sub_y, sub_h, sub_w, blur_map = self._detect_smart_geometry(abs_v, srt_path)
        
        if self._ocr: del self._ocr; self._ocr = None; gc.collect()
        if torch.cuda.is_available(): torch.cuda.empty_cache()

        cap = cv2.VideoCapture(abs_v)
        w, h, fps = int(cap.get(3)), int(cap.get(4)), cap.get(5)
        
        font_scale = getattr(self.cfg.step5, "font_scale_h_percent", 0.025)
        font_size = int(h * font_scale)
        font_path = self.cfg.step5.font_path or "C:/Windows/Fonts/arialbd.ttf"
        main_font = ImageFont.truetype(font_path, font_size)
        
        bg_fill = (0, 0, 0, 160)
        line_spacing = int(h * self.cfg.step5.line_spacing_h_percent) if getattr(self.cfg.step5, "line_spacing_h_percent", None) else int(font_size * 0.3)
        blur_pad = int(h * 0.015)

        if sub_y is None: sub_y = int(h * 0.88); sub_h = int(font_size * 1.5); sub_w = int(w * 0.8); blur_map = {}

        temp_v = self.out_dir / f"temp_{video_path.stem}.mp4"
        cmd = [self.ffmpeg_bin, "-y", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{w}x{h}",
               "-r", str(fps), "-i", "-",
               "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22", "-pix_fmt", "yuv420p", str(temp_v)]
        
        proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.DEVNULL)
        subs = pysrt.open(str(srt_path), encoding='utf-8')

        f_idx = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret: break
                t_ms = (f_idx / fps) * 1000
                active_idx, text = self._get_active_sub_info(subs, t_ms)
                if text:
                    box = blur_map.get(active_idx, {'x': (w - sub_w)//2, 'w': sub_w})
                    bx, bw = max(0, box['x'] - blur_pad), min(w, box['w'] + blur_pad * 2)
                    roi = frame[sub_y:sub_y+sub_h, bx:bx+bw].copy()
                    frame[sub_y:sub_y+sub_h, bx:bx+bw] = cv2.GaussianBlur(roi, (51, 51), 0)
                    
                    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)).convert('RGBA')
                    bg_layer = Image.new('RGBA', img_pil.size, (0,0,0,0))
                    draw_bg = ImageDraw.Draw(bg_layer)
                    
                    wrapped_txt = self._wrap_text(text, main_font, int(w * 0.9))
                    bbox = draw_bg.multiline_textbbox((0, 0), wrapped_txt, font=main_font, align='center', spacing=line_spacing)
                    tw, th = bbox[2]-bbox[0], bbox[3]-bbox[1]
                    lx, ly = (w - tw) // 2, sub_y + (sub_h - th) // 2 - bbox[1]
                    
                    pad_x, pad_y = int(font_size * 0.5), int(font_size * 0.15)
                    bg_rect = [lx - pad_x, ly - pad_y, lx + tw + pad_x, ly + th + pad_y]
                    draw_bg.rounded_rectangle(bg_rect, radius=int((bg_rect[3]-bg_rect[1])*0.3), fill=(0, 0, 0, 160))
                    
                    img_pil = Image.alpha_composite(img_pil, bg_layer)
                    ImageDraw.Draw(img_pil).multiline_text((lx, ly), wrapped_txt, font=main_font, fill=txt_color_tuple, 
                                                            align='center', spacing=line_spacing, stroke_width=2, stroke_fill=out_color_tuple)
                    frame = cv2.cvtColor(np.array(img_pil.convert('RGB')), cv2.COLOR_RGB2BGR)
                proc.stdin.write(frame.tobytes())
                f_idx += 1
        finally:
            cap.release(); proc.stdin.close(); proc.wait()

        subprocess.run([self.ffmpeg_bin, "-y", "-i", str(temp_v), "-i", abs_v, "-map", "0:v", "-map", "1:a?", 
                        "-c:v", "copy", "-c:a", "aac", str(out_f)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if temp_v.exists(): temp_v.unlink()
        return out_f