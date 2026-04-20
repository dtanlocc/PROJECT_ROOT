import os
import subprocess
import gc
from pathlib import Path
from loguru import logger
import pysrt
import cv2
import numpy as np
import torch
from paddleocr import PaddleOCR
from PIL import Image, ImageFont

from app.core.language.registry import LanguageRegistry
from app.steps.base import BaseStep


class Step5Overlay(BaseStep):
    def __init__(self, cfg, ffmpeg):
        super().__init__(cfg)
        self.ffmpeg_bin = ffmpeg.bin
        self.out_dir = Path(self.cfg.pipeline.step5_video_subbed)

        # ==================== MÀU SẮC ====================
        def parse_color(val, default=(0, 0, 0, 200)):
            if isinstance(val, (list, tuple)):
                rgb = [int(x) for x in val[:3]]
                alpha = int(val[3]) if len(val) > 3 else default[3]
                return rgb + [alpha]
            elif isinstance(val, str) and val.startswith('&H'):
                try:
                    s = val.replace('&H', '').zfill(8)
                    a = 255 - int(s[0:2], 16)
                    b = int(s[2:4], 16)
                    g = int(s[4:6], 16)
                    r = int(s[6:8], 16)
                    return [r, g, b, a]
                except:
                    pass
            return list(default)

        self.pill_bg_color = parse_color(
            getattr(self.cfg.step5, 'pill_background_color', None),
            default=[0, 0, 0, 200]
        )
       
        self.text_color = parse_color(
            getattr(self.cfg.step5, 'text_color', None),
            default=[255, 255, 255, 255]
        )
       
        self.outline_color = parse_color(
            getattr(self.cfg.step5, 'outline_color', None),
            default=[0, 0, 0, 255]
        )
        # =================================================================

        self.roi_y_start = getattr(self.cfg.step5, 'roi_y_start', 0.60)
        self.roi_y_end = getattr(self.cfg.step5, 'roi_y_end', 1.0)
        self.font_path = getattr(self.cfg.step5, 'font_path', "C:/Windows/Fonts/arialbd.ttf")
        self.horizontal_padding_ratio = getattr(self.cfg.step5, 'horizontal_padding_ratio', 0.6)

        # ==================== LANGUAGE REGISTRY ====================
        self.registry = LanguageRegistry()
        # OCR language lấy từ source_lang (vì đây là overlay phụ đề đã dịch)
        source_code = getattr(self.cfg, 'source_lang', 'zh')
        src = self.registry.get(source_code)
        self.ocr_lang = src.paddleocr          # "ch", "japan", "korean", ...
        # ============================================================

        self.ensure_dir(self.out_dir)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _make_even(self, n):
        val = int(round(n))
        return val if val % 2 == 0 else val - 1

    def _color_to_rgb(self, val, default=(255, 255, 0)):
        """Chuyển list [r,g,b,a] thành tuple RGB"""
        if isinstance(val, (list, tuple)) and len(val) >= 3:
            return (int(val[0]), int(val[1]), int(val[2]))
        return default

    def _ms_to_ass_time(self, ms: float) -> str:
        try:
            # Dùng float(ms) trước để tránh lỗi nếu ms là string, sau đó round để chính xác nhất
            ms_int = int(round(float(ms)))
            
            h  = ms_int // 3600000
            m  = (ms_int % 3600000) // 60000
            s  = (ms_int % 60000) // 1000
            cs = (ms_int % 1000) // 10
            
            # Ép int() một lần nữa cho chắc chắn từng biến trước khi vào :02d
            return f"{int(h)}:{int(m):02d}:{int(s):02d}.{int(cs):02d}"
        except Exception as e:
            # Nếu có lỗi (ví dụ ms là None), trả về thời gian 0 thay vì crash cả tool
            return "0:00:00.00"

    ASS_WIDTH_SCALE = 1.18

    def _text_render_width(self, text: str, font, target_font_size: int) -> float:
        """
        Đo chiều rộng text an toàn. Nếu font lỗi (fallback về font mặc định size nhỏ),
        sẽ dùng thuật toán ước tính toán học để không bao giờ ra viên thuốc bé tí.
        """
        try:
            pil_w = font.getlength(text)
            # Phát hiện font mặc định (size thường là 10 hoặc không có size)
            if hasattr(font, 'size') and font.size != target_font_size:
                pil_w = len(text) * target_font_size * 0.55
        except Exception:
            pil_w = len(text) * target_font_size * 0.55
        
        return pil_w * self.ASS_WIDTH_SCALE
    
    def _get_font_name_and_dir(self):
        font_p = Path(self.font_path)
        if font_p.exists() and font_p.is_file():
            # Lấy tên file không có đuôi (VD: "NotoSansJP-Bold.ttf" -> "NotoSansJP-Bold")
            return font_p.stem, str(font_p.parent).replace("\\", "/")
        return "Arial", None

    # ------------------------------------------------------------------
    # ASS generation
    # ------------------------------------------------------------------

    def _generate_pill_ass(self, srt_path, ass_path, video_w, video_h, meta_list):
        subs = pysrt.open(str(srt_path), encoding='utf-8')

        def rgb_to_ass(rgb, alpha=0):
            r, g, b = rgb
            return f"&H{alpha:02X}{b:02X}{g:02X}{r:02X}"

        ass_bg  = rgb_to_ass(self._color_to_rgb(self.pill_bg_color))
        ass_txt = rgb_to_ass(self._color_to_rgb(self.text_color))
        ass_out = rgb_to_ass(self._color_to_rgb(self.outline_color))

        # --- LẤY TÊN FONT ĐỘNG ---
        ass_font_name, _ = self._get_font_name_and_dir()

        # Đưa tên font động vào ASS Header thay vì fix cứng "Arial"
        ass_header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {video_w}
PlayResY: {video_h}
ScaledBorderAndShadow: yes
[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: PillBase,{ass_font_name},30,{ass_bg},{ass_bg},{ass_bg},{ass_bg},0,0,0,0,100,100,0,0,1,0,0,7,0,0,0,1
Style: TextMain,{ass_font_name},30,{ass_txt},{ass_out},{ass_out},{ass_bg},-1,0,0,0,100,100,0,0,1,3,2,5,0,0,0,1
"""

        with open(ass_path, "w", encoding="utf-8") as f:
            f.write(ass_header + "\n[Events]\nFormat: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n")

            for i, s in enumerate(subs):
                meta = meta_list[i] if i < len(meta_list) else {
                    "cx": video_w // 2, "cy": int(video_h * 0.85),
                    "x1": video_w // 2, "x2": video_w // 2,
                    "y1": int(video_h * 0.83), "y2": int(video_h * 0.87),
                    "ch": int(video_h * 0.04)
                }

                start_ms, end_ms = s.start.ordinal, s.end.ordinal
                
                ocr_y1, ocr_y2 = meta["y1"], meta["y2"]
                ocr_box_h = max(1, ocr_y2 - ocr_y1)
                font_size = max(int(video_h * 0.02), min(int(ocr_box_h * 0.85), int(video_h * 0.07)))
                
                # --- LOAD FONT CHO PILLOW (ĐỂ ĐO KÍCH THƯỚC CHỮ) ---
                try:
                    if Path(self.font_path).exists():
                        pil_font = ImageFont.truetype(self.font_path, font_size)
                    else:
                        pil_font = ImageFont.truetype("C:/Windows/Fonts/arialbd.ttf", font_size)
                except Exception:
                    pil_font = ImageFont.load_default()

                # 2. XỬ LÝ TEXT & CHẶT THỜI GIAN
                raw_text = str(s.text).strip()
                
                # Phân tách dựa trên dấu xuống dòng có sẵn trong SRT
                if '\n' in raw_text:
                    lines_text = [l.strip() for l in raw_text.split('\n') if l.strip()]
                else:
                    lines_text = [raw_text]
                
                # Nếu chỉ có 1 dòng, kiểm tra xem nó có tràn màn hình không
                max_pill_w = video_w * 0.92
                pad_x = int(font_size * max(self.horizontal_padding_ratio, 0.6))
                
                if len(lines_text) == 1:
                    test_w = self._text_render_width(lines_text[0], pil_font, font_size)
                    test_pill_w = test_w + 2 * pad_x
                    if test_pill_w > max_pill_w:
                        # Buộc phải chặt làm 2 bằng word count
                        words = lines_text[0].split()
                        split_idx = max(1, len(words) // 2)
                        lines_text = [" ".join(words[:split_idx]), " ".join(words[split_idx:])]

                # Tính toán thời lượng cho từng dòng dựa trên tỷ lệ ký tự
                segments = []
                total_chars = max(1, sum(len(l.replace(" ", "")) for l in lines_text))
                current_start = start_ms
                
                max_render_w = 0
                
                for idx_l, l in enumerate(lines_text):
                    char_count = len(l.replace(" ", ""))
                    seg_duration = int((end_ms - start_ms) * (char_count / total_chars))
                    seg_end = current_start + seg_duration
                    
                    # Tránh hụt mili-giây do làm tròn ở đoạn cuối
                    if idx_l == len(lines_text) - 1:
                        seg_end = end_ms
                        
                    rw = self._text_render_width(l, pil_font, font_size)
                    if rw > max_render_w: 
                        max_render_w = rw
                        
                    segments.append({
                        "text": l,
                        "start": current_start,
                        "end": seg_end
                    })
                    current_start = seg_end

                # 3. TÍNH TOÁN KHỐI HỢP NHẤT (UNION BOX) - Khóa cố định cho tất cả các đoạn
                ocr_x1 = meta["x1"]
                ocr_x2 = meta["x2"]
                
                # Tọa độ X lý tưởng của Text (căn giữa)
                text_x1 = (video_w - max_render_w) / 2
                text_x2 = text_x1 + max_render_w
                
                # Nền đen phải bọc cả OCR và Text (Đây là chìa khóa giải quyết yêu cầu của anh)
                final_core_x1 = min(text_x1, ocr_x1)
                final_core_x2 = max(text_x2, ocr_x2)
                
                pill_x1 = max(0, final_core_x1 - pad_x)
                pill_x2 = min(video_w, final_core_x2 + pad_x)
                
                pw = pill_x2 - pill_x1
                px = pill_x1

                # Tính chiều cao Pill (bọc OCR với padding đáy dày để hút bóng đổ)
                pad_y_top = int(font_size * 0.20)
                pad_y_bot = int(font_size * 0.45)
                
                pill_y1 = ocr_y1 - pad_y_top
                pill_y2 = ocr_y2 + pad_y_bot
                
                ph = self._make_even(pill_y2 - pill_y1)
                py = pill_y1
                
                text_center_y = py + (ph / 2)

                # 4. DRAW COMMAND & LƯU ASS
                r  = ph / 2.0
                wi = max(0.0, pw - ph)
                draw_cmd = (
                    f"m {r} 0 "
                    f"l {wi + r} 0 "
                    f"b {wi + r + r*0.55} 0 {wi + ph} {r*0.45} {wi + ph} {r} "
                    f"b {wi + ph} {ph - r*0.45} {wi + r + r*0.55} {ph} {wi + r} {ph} "
                    f"l {r} {ph} "
                    f"b {r - r*0.55} {ph} 0 {ph - r*0.45} 0 {r} "
                    f"b 0 {r*0.45} {r - r*0.55} 0 {r} 0"
                )

                for seg in segments:
                    t0 = self._ms_to_ass_time(seg["start"])
                    t1 = self._ms_to_ass_time(seg["end"])

                    f.write(f"Dialogue: 0,{t0},{t1},PillBase,,0,0,0,,{{\\be25\\pos({px},{py})}}{{\\p1}}{draw_cmd}{{\\p0}}\n")
                    f.write(f"Dialogue: 1,{t0},{t1},PillBase,,0,0,0,,{{\\be4\\pos({px},{py})}}{{\\p1}}{draw_cmd}{{\\p0}}\n")
                    f.write(f"Dialogue: 2,{t0},{t1},TextMain,,0,0,0,,{{\\q2\\fs{font_size}\\pos({video_w // 2},{text_center_y})\\bord{3}\\shad{1}}}{seg['text']}\n")
        logger.success("[Step 5] Tạo ASS hoàn tất — Union X Box, \q2 Anti-wrap, và Split Time logic!")

    # ------------------------------------------------------------------
    # OCR helpers
    # ------------------------------------------------------------------

    def _run_ocr_on_frame(self, frame, h, ocr, zoom_factor=2.0):
        y1 = int(h * self.roi_y_start)
        y2 = int(h * self.roi_y_end)
        roi = frame[max(0, y1): min(h, y2), :]
        if roi.size == 0:
            return []

        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        zoomed   = cv2.resize(gray_roi, None, fx=zoom_factor, fy=zoom_factor,
                              interpolation=cv2.INTER_CUBIC)
        kernel   = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
        enhanced = cv2.filter2D(zoomed, -1, kernel)
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

        res = ocr.ocr(enhanced_bgr, cls=False)
        valid_boxes = []
        if not res or not res[0]:
            return valid_boxes

        for line in res[0]:
            if len(line) < 2:
                continue
            pts       = np.array(line[0], dtype=np.float32) / zoom_factor
            txt, conf = line[1]
            if conf < 0.70:
                continue
            letters = [c for c in str(txt).strip()
                       if c.isalpha() or ('\u4e00' <= c <= '\u9fff') or c.isdigit()]
            if not letters:
                continue

            x_min    = int(np.min(pts[:, 0]))
            x_max    = int(np.max(pts[:, 0]))
            y_min_r  = int(np.min(pts[:, 1]))
            y_max_r  = int(np.max(pts[:, 1]))
            box_w    = x_max - x_min
            box_h    = y_max_r - y_min_r

            if box_h > h * 0.20:  continue
            if box_h < int(h * 0.015): continue
            if box_w / max(1, box_h) < 0.5: continue

            valid_boxes.append({
                "x_min": x_min,
                "x_max": x_max,
                "y_min": y_min_r + y1,
                "y_max": y_max_r + y1,
                "cy":    ((y_min_r + y_max_r) // 2) + y1,
                "h":     box_h,
                "w":     box_w,
            })
        return valid_boxes

    def _boxes_to_meta(self, boxes, video_w, video_h):
        if not boxes:
            return None
        boxes.sort(key=lambda b: b['cy'])
        lowest_cy   = boxes[-1]['cy']
        bottom_line = [b for b in boxes if abs(b['cy'] - lowest_cy) < b['h']]

        return {
            "cx": int((min(b['x_min'] for b in bottom_line) + max(b['x_max'] for b in bottom_line)) / 2),
            "cy": int((min(b['y_min'] for b in bottom_line) + max(b['y_max'] for b in bottom_line)) / 2),
            "x1": min(b['x_min'] for b in bottom_line),
            "x2": max(b['x_max'] for b in bottom_line),
            "y1": min(b['y_min'] for b in bottom_line),
            "y2": max(b['y_max'] for b in bottom_line),
            "ch": int(np.median([b['h'] for b in bottom_line])),
        }

    # ------------------------------------------------------------------
    # Main process
    # ------------------------------------------------------------------

    def process(self, video_path, srt_path) -> Path:
        video_path = Path(video_path)
        srt_path   = Path(srt_path)
        self.ensure_dir(self.out_dir)

        logger.info(f"🔍 [Step 5] Bắt đầu xử lý overlay cho {video_path.name}")

        abs_v      = str(video_path.absolute())
        out_f_path = self.out_dir / f"{video_path.stem}.mp4"
        ass_f      = srt_path.with_suffix(".ass")

        # ==================== SỬ DỤNG OCR LANG TỪ REGISTRY ====================
        ocr = PaddleOCR(
            use_angle_cls=False,
            lang=self.ocr_lang,                    # ← ĐÃ SỬA: lấy từ Registry
            use_gpu=getattr(self.cfg.step3, 'image_use_gpu', True),
            show_log=False,
        )
        # =================================================================
        cap = cv2.VideoCapture(abs_v)
        h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))

        subs_list = pysrt.open(str(srt_path), encoding='utf-8')

        sub_times = []
        for s in subs_list:
            try:
                sub_times.append((int(s.start.ordinal), int(s.end.ordinal)))
            except Exception:
                sub_times.append((0, 0))

        logger.info(f"[Step 5] Đang dò OCR đa điểm ({len(subs_list)} câu)...")

        raw_meta = [None] * len(subs_list)

        for idx, s in enumerate(subs_list):
            start_ms, end_ms = sub_times[idx]
            duration = end_ms - start_ms
            mid_ms   = start_ms + (duration // 2)

            checkpoints = [
                mid_ms,
                start_ms + int(duration * 0.2),
                start_ms + int(duration * 0.8),
            ]

            info = None
            for pt_ms in checkpoints:
                cap.set(cv2.CAP_PROP_POS_MSEC, pt_ms)
                ret, frame = cap.read()
                if not ret:
                    continue
                boxes = self._run_ocr_on_frame(frame, h, ocr)
                if boxes:
                    info = self._boxes_to_meta(boxes, w, h)
                    if info:
                        break

            raw_meta[idx] = info 

        cap.release()

        # Xử lý look-ahead để bù đắp các frame OCR bị mù (Do chớp sáng/chuyển cảnh)
        last_valid = None
        for idx in range(len(raw_meta) - 1, -1, -1):
            if raw_meta[idx] is not None:
                last_valid = raw_meta[idx]
                break

        next_valid = last_valid 
        for idx in range(len(raw_meta) - 1, -1, -1):
            if raw_meta[idx] is not None:
                next_valid = raw_meta[idx]
            else:
                raw_meta[idx] = next_valid 

        default_meta = {
            "cx": w // 2, "cy": int(h * 0.8),
            "x1": w // 2, "x2": w // 2,
            "y1": int(h * 0.86), "y2": int(h * 0.90),
            "ch": int(h * 0.025),
        }
        meta_info = [m if m is not None else default_meta for m in raw_meta]

        del ocr
        gc.collect()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()

        # Tạo ASS
        self._generate_pill_ass(srt_path, ass_f, w, h, meta_info)

        # --- ÉP FFMPEG PHẢI SCAN THƯ MỤC CHỨA FONT CỦA BẠN ---
        safe_ass = str(ass_f.absolute()).replace("\\", "/").replace(":", "\\:")
        
        _, font_dir = self._get_font_name_and_dir()
        if font_dir:
            # Lệnh này cực kỳ quan trọng, nó báo cho bộ render ASS biết tìm file font ở đâu
            sub_filter = f"subtitles='{safe_ass}':fontsdir='{font_dir}'"
        else:
            sub_filter = f"subtitles='{safe_ass}'"

        cmd = [
            self.ffmpeg_bin, "-y", "-hwaccel", "cuda", "-i", abs_v,
            "-vf", sub_filter,
            "-c:v", "h264_nvenc", "-preset", "p5", "-rc", "vbr", "-cq", "23",
            "-pix_fmt", "yuv420p", "-c:a", "copy", str(out_f_path),
        ]

        logger.info("🚀 [Step 5] Đang render video...")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, encoding="utf-8")
            logger.success(f"✅ [Step 5] Hoàn thành overlay: {out_f_path.name}")
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ FFmpeg Step 5 lỗi:\n{e.stderr}")
            raise
        finally:
            if ass_f.exists():
                ass_f.unlink()

        return out_f_path