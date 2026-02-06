import os
import logging
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep

# Tắt check mạng Paddle
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

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
        if not self._whisper:
            from faster_whisper import WhisperModel
            import torch
            device = self.cfg.step3.device
            if device == "cuda" and not torch.cuda.is_available(): device = "cpu"
            compute = "float16" if device == "cuda" else "float32"
            self._whisper = WhisperModel(self.cfg.step3.model_size, device=device, compute_type=compute)
        
        segments, _ = self._whisper.transcribe(str(audio_path), language=self.cfg.step3.language, vad_filter=True)
        
        with open(out_path, "w", encoding="utf-8") as f:
            for i, s in enumerate(segments, 1):
                f.write(f"{i}\n{self._fmt(s.start)} --> {self._fmt(s.end)}\n{s.text.strip()}\n\n")

    def _preprocess_roi_all_colors(self, roi):
        """Tiền xử lý để nhận chữ nhiều màu (đỏ, xanh, vàng, trắng) như logic gốc step3_ima."""
        import cv2
        import numpy as np
        max_channel = np.max(roi, axis=2)
        enhanced = cv2.convertScaleAbs(max_channel, alpha=1.5, beta=10)
        _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    def _run_ocr(self, video_path, out_path):
        # --- PADDLE OCR + SEQUENCEMATCHER (căn logic gốc: ROI config, all-color preprocess, confidence, min_duration) ---
        if not self._ocr:
            from paddleocr import PaddleOCR
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            self._ocr = PaddleOCR(use_angle_cls=False, lang=self.cfg.step3.image_ocr_lang, use_gpu=self.cfg.step3.image_use_gpu)
        
        import cv2
        from difflib import SequenceMatcher
        
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        interval = max(1, int(fps * self.cfg.step3.image_frame_interval))
        min_duration_ms = self.cfg.step3.image_min_duration_ms
        conf_thresh = self.cfg.step3.image_confidence_threshold
        # ROI từ config step5 (vùng sub thường nằm dưới)
        roi_y_start = getattr(self.cfg.step5, "roi_y_start", 0.5)
        roi_y_end = getattr(self.cfg.step5, "roi_y_end", 0.9)
        
        subs = []
        last_text = ""
        start_ms = 0.0
        
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret:
                break
            if frame_idx % interval == 0:
                curr_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                h, w = frame.shape[:2]
                y1, y2 = int(h * roi_y_start), int(h * roi_y_end)
                roi = frame[y1:y2, 0:w]
                if roi.size == 0:
                    frame_idx += 1
                    continue
                bin_img = self._preprocess_roi_all_colors(roi)
                res = self._ocr.ocr(bin_img, cls=False)
                txt = ""
                if res and res[0]:
                    parts = [
                        line[1][0] for line in res[0]
                        if len(line[1]) > 1 and float(line[1][1] or 0) >= conf_thresh
                    ]
                    txt = " ".join(parts).strip()
                if txt:
                    sim = SequenceMatcher(None, last_text, txt).ratio()
                    if sim < self.cfg.step3.similarity_threshold:
                        if last_text:
                            dur_ms = curr_ms - start_ms
                            if dur_ms >= min_duration_ms:
                                subs.append((start_ms, curr_ms, last_text))
                        last_text = txt
                        start_ms = curr_ms
            frame_idx += 1

        if last_text:
            end_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
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