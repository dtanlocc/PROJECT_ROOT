"""
Step 5: Che sub cũ + vẽ sub mới (hard burn).
Logic y hệt che_sub-B5.py: cố định kích thước hiển thị (chunk theo MAX_WORDS),
font target cố định (chỉ thu nhỏ khi tràn), detect geometry có lọc tiêu đề tĩnh, blur từ vùng mẫu.
"""
import os
import subprocess
import numpy as np
import pysrt
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

try:
    import cv2
    from PIL import Image, ImageDraw, ImageFont
    from paddleocr import PaddleOCR
except ImportError:
    PaddleOCR = None


def _color_to_rgb(val) -> tuple:
    """Chuyển màu từ config sang (R, G, B) cho PIL. Hỗ trợ List [R,G,B,A] hoặc chuỗi ASS &HAABBGGRR."""
    if isinstance(val, list) and len(val) >= 3:
        return (int(val[0]) & 255, int(val[1]) & 255, int(val[2]) & 255)
    if isinstance(val, str) and str(val).strip().upper().startswith("&H"):
        try:
            s = str(val).strip().upper().replace("&H", "")
            if len(s) >= 6:
                r = int(s[6:8], 16) if len(s) >= 8 else 0
                g = int(s[4:6], 16)
                b = int(s[2:4], 16)
                return (r, g, b)
        except Exception:
            pass
    return (255, 255, 0)  # Mặc định vàng


class Step5Overlay(BaseStep):
    def __init__(self, cfg, ffmpeg: FFmpegManager):
        super().__init__(cfg)
        self.ffmpeg_bin = ffmpeg.bin
        self.out_dir = self.cfg.pipeline.step5_video_subbed
        self._ocr = None

    def _resolve_font(self):
        cfg_font = self.cfg.step5.font_path
        if cfg_font and Path(cfg_font).exists():
            return str(cfg_font)
        for name in ["arialbd.ttf", "arial.ttf", "seguiemj.ttf", "tahoma.ttf"]:
            p = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / name
            if p.exists():
                return str(p)
        return "arial.ttf"

    def _get_optimal_font_size(self, text, font_path, max_width, max_height):
        """Như che_sub-B5: target size cố định, chỉ thu nhỏ khi chữ tràn khung."""
        target_size = max(15, min(120, self.cfg.step5.font_size))
        font_size = target_size
        try:
            font = ImageFont.truetype(font_path, font_size)
        except Exception:
            font = ImageFont.load_default()
            return font
        while font_size > 15:
            bbox = font.getbbox(text)
            w = bbox[2] - bbox[0]
            h = bbox[3] - bbox[1]
            if w <= (max_width - 40) and h <= (max_height * 0.8):
                break
            font_size -= 2
            font = ImageFont.truetype(font_path, font_size)
        return font

    def _get_active_sub_split(self, subs, current_time_ms):
        """Y hệt che_sub-B5: chia sub theo MAX_WORDS, hiển thị đúng chunk theo thời gian."""
        max_words = max(1, self.cfg.step5.max_words_per_line)
        for s in subs:
            if s.start.ordinal <= current_time_ms <= s.end.ordinal:
                words = s.text.replace("<br />", " ").replace("\n", " ").split()
                if not words:
                    return None
                chunks = [words[i : i + max_words] for i in range(0, len(words), max_words)]
                num_chunks = len(chunks)
                if num_chunks == 1:
                    return " ".join(words)
                total_duration = s.end.ordinal - s.start.ordinal
                chunk_duration = total_duration / num_chunks
                elapsed = current_time_ms - s.start.ordinal
                current_chunk_index = min(int(elapsed // chunk_duration), num_chunks - 1)
                return " ".join(chunks[current_chunk_index])
        return None

    def _detect_geometry(self, video_path):
        """Y hệt che_sub-B5: quét 120 mẫu, lọc theo count + len(texts)>3 (bỏ tiêu đề tĩnh)."""
        if not self._ocr:
            import logging
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            try:
                self._ocr = PaddleOCR(
                    use_angle_cls=False,
                    lang=self.cfg.step5.ocr_lang,
                    use_gpu=getattr(self.cfg.step3, "image_use_gpu", True),
                    show_log=False,
                )
            except Exception:
                self._ocr = PaddleOCR(use_angle_cls=False, lang=self.cfg.step5.ocr_lang, use_gpu=False, show_log=False)

        cap = cv2.VideoCapture(str(video_path))
        if not cap.isOpened():
            return None, None, None
        h_video = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w_video = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        y_roi_start = int(h_video * self.cfg.step5.roi_y_start)
        y_roi_end = int(h_video * self.cfg.step5.roi_y_end)
        # Quét 120 mẫu như che_sub-B5 (tránh quá ít/ quá nhiều)
        dynamic_interval = max(1, total_frames // 120)
        candidates = {}
        y_tol = 15

        for fno in range(0, total_frames, dynamic_interval):
            cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
            ret, frame = cap.read()
            if not ret:
                break
            try:
                result = self._ocr.ocr(frame[y_roi_start:y_roi_end, :], cls=False)
            except Exception:
                continue
            if not result or not result[0]:
                continue
            for line in result[0]:
                pts = np.array(line[0], np.int32)
                text_content = line[1][0]
                y1 = int(pts[:, 1].min()) + y_roi_start
                y2 = int(pts[:, 1].max()) + y_roi_start
                x1, x2 = int(pts[:, 0].min()), int(pts[:, 0].max())
                h_text, w_text = y2 - y1, x2 - x1
                if h_text > (h_video * 0.12):
                    continue
                matched = False
                for y_key in list(candidates.keys()):
                    if abs(y_key - y1) <= y_tol:
                        candidates[y_key]["heights"].append(h_text)
                        candidates[y_key]["widths"].append(w_text)
                        candidates[y_key]["texts"].add(text_content)
                        candidates[y_key]["count"] += 1
                        matched = True
                        break
                if not matched:
                    candidates[y1] = {
                        "heights": [h_text],
                        "widths": [w_text],
                        "texts": {text_content},
                        "count": 1,
                    }
        cap.release()

        valid_candidates = []
        for y_key, data in candidates.items():
            if data["count"] > 5 and len(data["texts"]) > 3:
                avg_h = sum(data["heights"]) / len(data["heights"])
                max_w = max(data["widths"])
                valid_candidates.append((y_key, avg_h, max_w, data["count"]))
        if not valid_candidates:
            logger.warning("Không tìm thấy vùng nào có chữ thay đổi nội dung (Subtitle).")
            return None, None, None
        valid_candidates.sort(key=lambda x: x[3], reverse=True)
        best_y, best_h, best_w, count = valid_candidates[0]
        num_texts = len(candidates[best_y]["texts"])
        final_bw = min(w_video, int(best_w + w_video * 0.05))
        final_bh = int(best_h * 1.3)
        final_by = int(best_y - (best_h * 0.15))
        logger.info(f"Đã lọc tiêu đề tĩnh. Chọn Sub tại Y={final_by} (nội dung thay đổi {num_texts} lần)")
        return final_by, final_bh, final_bw

    def process(self, video_path: Path, srt_path: Path):
        self.ensure_dir(self.out_dir)
        out_file = self.out_dir / f"{video_path.stem}.mp4"
        if out_file.exists():
            return out_file

        logger.info(f"🎨 [Step 5] Overlay Sub (Hard Burn): {video_path.name}")

        cap = cv2.VideoCapture(str(video_path))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0

        sub_y, sub_h, sub_w = self._detect_geometry(video_path)
        if sub_y is None:
            sub_h = int(h * 0.15)
            sub_y = int(h * 0.8)
            sub_w = int(w * 0.9)
        bw, bh = sub_w, sub_h
        bx = (w - bw) // 2
        by = sub_y

        try:
            subs = pysrt.open(str(srt_path), encoding="utf-8")
        except Exception:
            logger.warning("SRT error, skip overlay text.")
            subs = []

        font_path = self._resolve_font()
        text_color = _color_to_rgb(getattr(self.cfg.step5, "text_color", [255, 255, 0, 255]))
        outline_color = _color_to_rgb(getattr(self.cfg.step5, "outline_color", [0, 0, 0, 255]))

        temp_raw = self.out_dir / f"raw_{video_path.stem}.mp4"
        # Tối ưu cho shorts như che_sub-B5: p4 (tốc độ/chất lượng), cq 22, profile high
        calculated_bitrate = "2M"
        max_bitrate = "4M"
        buf_size = "6M"
        force_cpu = os.environ.get("PIPELINE_FORCE_CPU") == "1"
        encodings = []
        if not force_cpu:
            encodings.append([
                "-c:v", "h264_nvenc", "-preset", "p4", "-rc", "vbr", "-cq", "22",
                "-b:v", calculated_bitrate, "-maxrate", max_bitrate, "-bufsize", buf_size,
                "-profile:v", "high", "-pix_fmt", "yuv420p",
            ])
        encodings.append(["-c:v", "libx264", "-preset", "ultrafast", "-crf", "22", "-pix_fmt", "yuv420p"])
        proc = None
        for enc in encodings:
            cmd = [
                self.ffmpeg_bin, "-y",
                "-f", "rawvideo", "-vcodec", "rawvideo", "-s", f"{w}x{h}",
                "-pix_fmt", "bgr24", "-r", str(fps), "-i", "-",
            ] + enc + [str(temp_raw)]
            try:
                proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                break
            except Exception:
                continue
        if not proc:
            cap.release()
            raise RuntimeError("FFmpeg start failed")

        frame_count = 0
        try:
            while True:
                ret, frame = cap.read()
                if not ret:
                    break
                sample_y = (h - bh) // 2
                roi_sample = frame[sample_y : sample_y + bh, bx : bx + bw].copy()
                frame[by : by + bh, bx : bx + bw] = cv2.GaussianBlur(roi_sample, (51, 51), 0)

                current_time_ms = (frame_count / fps) * 1000
                text_to_draw = self._get_active_sub_split(subs, current_time_ms)
                if text_to_draw:
                    img_pil = Image.fromarray(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    draw = ImageDraw.Draw(img_pil)
                    dynamic_font = self._get_optimal_font_size(text_to_draw, font_path, bw, bh)
                    bbox = draw.textbbox((0, 0), text_to_draw, font=dynamic_font)
                    lw, lh = bbox[2] - bbox[0], bbox[3] - bbox[1]
                    lx = bx + (bw - lw) // 2
                    ly = by + (bh - lh) // 2 - bbox[1]
                    for ox, oy in [(-2, -2), (2, -2), (-2, 2), (2, 2), (0, -2), (0, 2), (-2, 0), (2, 0)]:
                        draw.text((lx + ox, ly + oy), text_to_draw, font=dynamic_font, fill=outline_color)
                    draw.text((lx, ly), text_to_draw, font=dynamic_font, fill=text_color)
                    frame = cv2.cvtColor(np.array(img_pil), cv2.COLOR_RGB2BGR)
                proc.stdin.write(frame.tobytes())
                frame_count += 1
        except Exception as e:
            logger.error(f"Render loop error: {e}")
        finally:
            cap.release()
            if proc:
                proc.stdin.close()
                proc.wait()

        if temp_raw.exists():
            subprocess.run([
                self.ffmpeg_bin, "-y", "-i", str(temp_raw), "-i", str(video_path),
                "-map", "0:v", "-map", "1:a?", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
                str(out_file)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            temp_raw.unlink()
        return out_file
