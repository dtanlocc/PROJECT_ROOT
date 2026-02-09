import os
import re
import gc
import logging
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep

# Tắt check mạng Paddle
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"


def _clean_whisper_text(raw: str) -> str:
    """Giống voice-to-srt: cắt ký tự không phải chữ/CJK ở đầu và cuối."""
    clean = (raw or "").strip()
    clean = re.sub(r"^[^\w\u4e00-\u9fff]+", "", clean)
    clean = re.sub(r"[^\w\u4e00-\u9fff]+$", "", clean)
    return clean

class Step3Transcribe(BaseStep):
    def __init__(self, cfg):  
        super().__init__(cfg)
        self.out_dir = self.cfg.pipeline.step3_srt_raw
        self._whisper = None
        self._ocr = None

    def process(self, input_source: Path) -> Path:
        self.ensure_dir(self.out_dir)
        mode = self.cfg.step3.srt_source
        
        # Xác định file nguồn
        if mode == "voice":
            video_stem = input_source.name
            src_file = input_source / "vocals.wav"
            out_srt = self.out_dir / f"{video_stem}.srt"
        else: # image
            video_stem = input_source.stem
            src_file = input_source
            out_srt = self.out_dir / f"{video_stem}.srt"

        # Resume Check
        if out_srt.exists() and out_srt.stat().st_size > 0:
            return out_srt

        logger.info(f"📝 [Step 3] Transcribe ({mode}): {video_stem}")

        if mode == "voice":
            self._run_whisper(src_file, out_srt)
        else:
            self._run_ocr(src_file, out_srt)
        
        return out_srt

    def _run_whisper(self, audio_path, out_path):
        """Logic voice-to-srt: binary input, VAD, Plan A (word-level) rồi Plan B (segment-level), clean text CJK."""
        import torch
        from faster_whisper import WhisperModel

        if not self._whisper:
            device = self.cfg.step3.device
            if device == "cuda" and not torch.cuda.is_available():
                device = "cpu"
            compute = "float16" if device == "cuda" else "float32"
            cpu_threads = getattr(self.cfg.step3, "cpu_threads", 1)
            try:
                self._whisper = WhisperModel(
                    self.cfg.step3.model_size,
                    device=device,
                    compute_type=compute,
                    cpu_threads=cpu_threads,
                )
            except RuntimeError as e:
                if "cublas64_12" in str(e) or "cublas" in str(e).lower():
                    logger.warning("Whisper GPU (cublas64_12) không khả dụng, dùng CPU cho B3.")
                    device = "cpu"
                    compute = "float32"
                    self._whisper = WhisperModel(
                        self.cfg.step3.model_size,
                        device="cpu",
                        compute_type=compute,
                        cpu_threads=cpu_threads,
                    )
                else:
                    raise

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

        input_path_str = str(Path(audio_path).resolve())
        lang = self.cfg.step3.language
        subtitles = []

        try:
            with open(input_path_str, "rb") as binary_file:
                segments_iter, info = self._whisper.transcribe(
                    binary_file,
                    word_timestamps=False,
                    vad_filter=True,
                    language=lang,
                )
                segs = list(segments_iter)
        except Exception as e:
            logger.error(f"Whisper transcribe failed: {e}")
            with open(out_path, "w", encoding="utf-8") as f:
                pass
            return

        # Plan A: dùng word-level nếu segment có .words (như voice-to-srt)
        temp_subs = []
        try:
            for segm in segs:
                words = getattr(segm, "words", None) or []
                if not words:
                    continue
                start = None
                text_buffer = ""
                for idx, word in enumerate(words):
                    w_text = getattr(word, "word", "") or ""
                    w_start = float(getattr(word, "start", 0.0))
                    w_end = float(getattr(word, "end", 0.0))
                    if start is None:
                        start = w_start
                    text_buffer += w_text
                    next_start = (
                        float(getattr(words[idx + 1], "start", 0.0))
                        if idx + 1 < len(words)
                        else None
                    )
                    if idx == len(words) - 1 or (
                        w_end > 0 and next_start is not None and next_start > 0 and w_end != next_start
                    ):
                        clean = _clean_whisper_text(text_buffer)
                        if clean:
                            temp_subs.append((start, w_end, clean))
                        start = None
                        text_buffer = ""
            if temp_subs:
                subtitles = temp_subs
                logger.debug("Whisper: dùng Plan A (word-level).")
        except Exception as e:
            logger.debug(f"Plan A (word) bỏ qua: {e}")

        # Plan B: segment-level (như voice-to-srt Safe Mode)
        if not subtitles:
            for segm in segs:
                raw_text = getattr(segm, "text", "") or ""
                start = float(getattr(segm, "start", 0.0))
                end = float(getattr(segm, "end", 0.0))
                clean = _clean_whisper_text(raw_text)
                if clean:
                    subtitles.append((start, end, clean))
            logger.debug("Whisper: dùng Plan B (segment-level).")

        with open(out_path, "w", encoding="utf-8") as f:
            for i, (start_sec, end_sec, text) in enumerate(subtitles, 1):
                f.write(f"{i}\n{self._fmt(start_sec)} --> {self._fmt(end_sec)}\n{text}\n\n")

    def _preprocess_roi_all_colors(self, roi):
        """Tiền xử lý để nhận chữ nhiều màu (đỏ, xanh, vàng, trắng) – logic img-to-srt."""
        import cv2
        import numpy as np
        max_channel = np.max(roi, axis=2)
        enhanced = cv2.convertScaleAbs(max_channel, alpha=1.5, beta=10)
        _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    def _get_text_at_frame(self, cap, fno, y1, y2):
        """Lấy text OCR tại đúng frame fno (nhảy tới frame rồi đọc) – như img-to-srt get_text_at_frame."""
        import cv2
        cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
        ret, frame = cap.read()
        if not ret:
            return ""
        roi = frame[y1:y2, :]
        if roi.size == 0:
            return ""
        processed = self._preprocess_roi_all_colors(roi)
        res = self._ocr.ocr(processed, cls=False)
        if res and res[0]:
            conf_thresh = self.cfg.step3.image_confidence_threshold
            texts = [
                line[1][0] for line in res[0]
                if len(line[1]) > 1 and float(line[1][1] or 0) >= conf_thresh
            ]
            return " ".join(texts).strip()
        return ""

    def _get_similarity(self, s1, s2):
        """Giống img-to-srt get_similarity."""
        if not s1 or not s2:
            return 0.0 if s1 != s2 else 1.0
        from difflib import SequenceMatcher
        return SequenceMatcher(None, s1, s2).ratio()

    def _find_exact_change_frame(self, cap, start_f, end_f, start_text, y1, y2):
        """Binary search tìm frame chính xác đổi sub trong [start_f, end_f] – như img-to-srt find_exact_change_frame."""
        low, high = int(start_f), int(end_f)
        ans = end_f
        while low <= high:
            mid = (low + high) // 2
            mid_text = self._get_text_at_frame(cap, mid, y1, y2)
            if self._get_similarity(mid_text, start_text) >= self.cfg.step3.similarity_threshold:
                low = mid + 1
            else:
                ans = mid
                high = mid - 1
        return ans

    def _run_ocr(self, video_path, out_path):
        """Logic img-to-srt: bước STEP_FRAME (từ config giây → frame), khi đổi text thì binary search tìm frame đổi chính xác."""
        if not self._ocr:
            from paddleocr import PaddleOCR
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            self._ocr = PaddleOCR(
                use_angle_cls=False,
                lang=self.cfg.step3.image_ocr_lang,
                use_gpu=self.cfg.step3.image_use_gpu,
                show_log=False,
            )
        import cv2

        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        # Ưu tiên bước frame (img-to-srt); nếu <= 0 thì dùng giây
        step_frames_cfg = getattr(self.cfg.step3, "image_step_frames", 0)
        if step_frames_cfg > 0:
            step_frames = step_frames_cfg
        else:
            step_frames = max(1, int(fps * self.cfg.step3.image_frame_interval))
        min_duration_ms = self.cfg.step3.image_min_duration_ms  
        roi_y_start = getattr(self.cfg.step5, "roi_y_start", 0.5)
        roi_y_end = getattr(self.cfg.step5, "roi_y_end", 0.9)
        y1, y2 = int(h * roi_y_start), int(h * roi_y_end)

        subs = []
        last_text = ""
        last_fno = 0

        for fno in range(0, total_frames, step_frames):
            current_text = self._get_text_at_frame(cap, fno, y1, y2)
            if self._get_similarity(current_text, last_text) < self.cfg.step3.similarity_threshold:
                exact_fno = self._find_exact_change_frame(
                    cap, max(0, fno - step_frames), fno, last_text, y1, y2
                )
                if last_text:
                    start_ms = (last_fno / fps) * 1000
                    end_ms = (exact_fno / fps) * 1000
                    if (end_ms - start_ms) >= min_duration_ms:
                        subs.append((start_ms, end_ms, last_text))
                last_text = current_text
                last_fno = exact_fno
            logger.debug(f"OCR tiến độ: {int((fno / total_frames) * 100)}% | đã lấy {len(subs)} câu")

        if last_text:
            start_ms = (last_fno / fps) * 1000
            end_ms = (total_frames / fps) * 1000
            if (end_ms - start_ms) >= min_duration_ms:
                subs.append((start_ms, end_ms, last_text))

        cap.release()

        with open(out_path, "w", encoding="utf-8") as f:
            for i, (s, e, t) in enumerate(subs, 1):
                f.write(f"{i}\n{self._fmt(s/1000)} --> {self._fmt(e/1000)}\n{t}\n\n")

    def _fmt(self, seconds):
        if seconds is None: seconds = 0
        h = int(seconds // 3600)
        m = int((seconds % 3600) // 60)
        s = int(seconds % 60)
        ms = int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"