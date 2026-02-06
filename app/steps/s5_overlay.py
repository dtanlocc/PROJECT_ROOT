import os
import subprocess
import numpy as np
import pysrt
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

# Import các thư viện xử lý ảnh
try:
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None

class Step5Overlay(BaseStep):
    def __init__(self, cfg, ffmpeg: FFmpegManager):
        super().__init__(cfg)
        self.ffmpeg_bin = ffmpeg.bin
        self.out_dir = self.cfg.pipeline.step5_video_subbed
        self._ocr = None

    # --- CÁC HÀM HELPER TỪ FILE GỐC CỦA BẠN ---

    def _resolve_font(self):
        """Tìm font hệ thống"""
        cfg_font = self.cfg.step5.font_path
        if cfg_font and Path(cfg_font).exists():
            return str(cfg_font)
        
        # Fallback font Windows
        for name in ["arialbd.ttf", "arial.ttf", "seguiemj.ttf", "tahoma.ttf"]:
            p = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if p.exists(): return str(p)
        return "arial.ttf"

    def _get_optimal_font_size(self, text, font_path, max_w, max_h, target_size=55):
        """Thuật toán tự động co nhỏ font để vừa khung"""
        size = int(target_size)
        try:
            font = ImageFont.truetype(font_path, size)
        except:
            font = ImageFont.load_default()
            return font
            
        while size > 15:
            bbox = font.getbbox(text)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w <= (max_w - 40) and h <= (max_h * 0.9):
                break
            size -= 2
            font = ImageFont.truetype(font_path, size)
        return font

    def _get_active_sub_text(self, subs, current_ms):
        """Lấy text sub tại thời điểm hiện tại"""
        for s in subs:
            if s.start.ordinal <= current_ms <= s.end.ordinal:
                # Xử lý xuống dòng đơn giản thành dấu cách để auto-fit
                return s.text.replace("\n", " ").strip()
        return None

    def _detect_geometry(self, video_path, roi_start_pct, roi_end_pct):
        """Dùng PaddleOCR tìm vị trí sub cũ"""
        if not self._ocr:
            import logging
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            try:
                self._ocr = PaddleOCR(use_angle_cls=False, lang="ch", use_gpu=self.cfg.step3.image_use_gpu, show_log=False)
            except:
                self._ocr = PaddleOCR(use_angle_cls=False, lang="ch", use_gpu=False, show_log=False)

        cap = cv2.VideoCapture(str(video_path))
        h_video = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w_video = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        y_start = int(h_video * roi_start_pct)
        y_end = int(h_video * roi_end_pct)
        
        candidates = {}
        interval = max(1, total_frames // 50) # Quét 50 frame rải rác
        
        for fno in range(0, total_frames, interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
            ret, frame = cap.read()
            if not ret: break
            
            roi = frame[y_start:y_end, :]
            try:
                res = self._ocr.ocr(roi, cls=False)
            except: continue
            
            if res and res[0]:
                for line in res[0]:
                    box = line[0]
                    y1 = min(p[1] for p in box) + y_start
                    h_text = (max(p[1] for p in box) + y_start) - y1
                    w_text = max(p[0] for p in box) - min(p[0] for p in box)
                    
                    # Grouping
                    matched = False
                    for k in candidates:
                        if abs(k - y1) < 15:
                            candidates[k]['h'].append(h_text)
                            candidates[k]['w'].append(w_text)
                            candidates[k]['count'] += 1
                            matched = True
                            break
                    if not matched:
                        candidates[y1] = {'h': [h_text], 'w': [w_text], 'count': 1}
        
        cap.release()
        
        # Chọn candidate tốt nhất
        valid = [(y, sum(v['h'])/len(v['h']), max(v['w']), v['count']) 
                 for y, v in candidates.items() if v['count'] > 2]
        
        if not valid: return None, None, None # Fallback

        valid.sort(key=lambda x: x[3], reverse=True)
        best_y, best_h, best_w, _ = valid[0]
        
        final_bw = min(w_video, int(best_w + w_video * 0.05))
        final_bh = int(best_h * 1.5) # Padding cao hơn xíu
        final_by = int(best_y - (best_h * 0.2))
        
        return final_by, final_bh, final_bw

    # --- CORE PROCESS ---
    def process(self, video_path: Path, srt_path: Path):
        self.ensure_dir(self.out_dir)
        out_file = self.out_dir / f"{video_path.stem}.mp4"
        if out_file.exists(): return out_file

        logger.info(f"🎨 [Step 5] Overlay Sub (Hard Burn): {video_path.name}")
        
        # 1. Setup Video
        cap = cv2.VideoCapture(str(video_path))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS)
        
        # 2. Detect Geometry
        try:
            dy, dh, dw = self._detect_geometry(video_path, self.cfg.step5.roi_y_start, self.cfg.step5.roi_y_end)
        except: dy = None

        if dy is None:
            # Fallback mặc định
            dh = int(h * 0.15)
            dy = int(h * 0.8)
            dw = int(w * 0.9)
        
        bx = (w - dw) // 2
        by = dy
        
        # 3. Load Resources
        try:
            subs = pysrt.open(str(srt_path))
        except:
            logger.warning("SRT Error, skip overlay text.")
            subs = []

        font_path = self._resolve_font()
        target_size = 55 # Mặc định to, sau đó auto-shrink
        
        # Màu mặc định (Trắng viền Đen) như file gốc
        text_color = (255, 255, 255, 255)
        outline_color = (0, 0, 0, 255)

        # 4. Setup FFmpeg Pipe
        # File raw tạm thời
        temp_raw = self.out_dir / f"raw_{video_path.stem}.mp4"
        
        encodings = [
            ["-c:v", "h264_nvenc", "-preset", "p1", "-rc", "vbr", "-cq", "18", "-b:v", "12M"],
            ["-c:v", "libx264", "-preset", "ultrafast", "-crf", "18"]
        ]

        proc = None
        for enc in encodings:
            cmd = [
                self.ffmpeg_bin, "-y",
                "-f", "rawvideo", "-vcodec", "rawvideo", "-s", f"{w}x{h}",
                "-pix_fmt", "bgr24", "-r", str(fps), "-i", "-"
            ] + enc + ["-pix_fmt", "yuv420p", str(temp_raw)]
            
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except: continue
        
        if not proc: raise RuntimeError("FFmpeg Start Failed")

        # 5. Rendering Loop
        frame_idx = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret: break
                
                # A. Blur Sub cũ (Gaussian Blur)
                # Đảm bảo ko vượt quá khung hình
                y2 = min(h, by + dh)
                x2 = min(w, bx + dw)
                roi = frame[by:y2, bx:x2]
                
                if roi.size > 0:
                    frame[by:y2, bx:x2] = cv2.GaussianBlur(roi, (51, 51), 0)

                # B. Vẽ Sub mới
                current_ms = (frame_idx / fps) * 1000
                txt = self._get_active_sub_text(subs, current_ms)
                
                if txt:
                    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    draw = ImageDraw.Draw(img_pil)
                    
                    font = self._get_optimal_font_size(txt, font_path, dw, dh, target_size)
                    
                    # Căn giữa
                    bbox = draw.textbbox((0, 0), txt, font=font)
                    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    tx = bx + (dw - tw) // 2
                    ty = by + (dh - th) // 2 - bbox[1]
                    
                    # Vẽ Outline
                    for ox, oy in [(-2,-2), (2,-2), (-2,2), (2,2), (0,-2), (0,2), (-2,0), (2,0)]:
                        draw.text((tx+ox, ty+oy), txt, font=font, fill=outline_color)
                    
                    # Vẽ Text
                    draw.text((tx, ty), txt, font=font, fill=text_color)
                    
                    frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)

                # C. Write Pipe
                proc.stdin.write(frame.tobytes())
                frame_idx += 1
                
        except Exception as e:
            logger.error(f"Render Loop Error: {e}")
        finally:
            cap.release()
            if proc:
                proc.stdin.close()
                proc.wait()

        # 6. Mux Audio gốc
        if temp_raw.exists():
            final_cmd = [
                self.ffmpeg_bin, "-y",
                "-i", str(temp_raw),
                "-i", str(video_path),
                "-map", "0:v", "-map", "1:a?",
                "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                str(out_file)
            ]
            subprocess.run(final_cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            temp_raw.unlink()
        
        return out_file