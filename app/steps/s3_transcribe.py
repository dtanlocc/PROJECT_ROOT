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

    def _run_ocr(self, video_path, out_path):
        # --- LOGIC GỐC CỦA BẠN: PADDLE OCR + SEQUENCEMATCHER ---
        if not self._ocr:
            from paddleocr import PaddleOCR
            logging.getLogger("ppocr").setLevel(logging.ERROR)
            # Khởi tạo không dùng tham số show_log (bản mới đã bỏ)
            self._ocr = PaddleOCR(use_angle_cls=False, lang=self.cfg.step3.image_ocr_lang, use_gpu=self.cfg.step3.image_use_gpu)
        
        import cv2
        from difflib import SequenceMatcher
        
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        interval = int(fps * self.cfg.step3.image_frame_interval) or 1
        
        subs = []
        last_text = ""
        start_ms = 0.0
        
        frame_idx = 0
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            if frame_idx % interval == 0:
                curr_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                h, w = frame.shape[:2]
                roi = frame[int(h*0.75):h, 0:w] # Crop 25% đáy
                
                # Preprocess Otsu
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                _, bin_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                
                res = self._ocr.ocr(bin_img, cls=False)
                # Parse text từ result của Paddle
                txt = ""
                if res and res[0]:
                    txt = " ".join([line[1][0] for line in res[0]]).strip()
                
                if txt:
                    # Logic gộp sub trùng của bạn
                    sim = SequenceMatcher(None, last_text, txt).ratio()
                    if sim < self.cfg.step3.similarity_threshold:
                        if last_text:
                            subs.append((start_ms, curr_ms, last_text))
                        last_text = txt
                        start_ms = curr_ms
            frame_idx += 1
            
        if last_text:
            subs.append((start_ms, cap.get(cv2.CAP_PROP_POS_MSEC), last_text))
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