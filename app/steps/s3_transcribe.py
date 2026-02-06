from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep

class Step3Transcribe(BaseStep):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.out_dir = self.cfg.pipeline.step3_srt_raw
        self._whisper = None
        self._ocr = None

    def process(self, input_source: Path) -> Path:
        # Input source: là folder Demucs (nếu voice) HOẶC video gốc (nếu image)
        self.ensure_dir(self.out_dir)
        
        mode = self.cfg.step3.srt_source
        if mode == "voice":
            # input_source là folder output của step 2
            video_stem = input_source.name 
            audio_file = input_source / "vocals.wav"
            out_srt = self.out_dir / f"{video_stem}.srt"
            
            if not out_srt.exists():
                self._run_whisper(audio_file, out_srt)
        else:
            # input_source là video gốc
            video_stem = input_source.stem
            out_srt = self.out_dir / f"{video_stem}.srt"
            
            if not out_srt.exists():
                self._run_ocr(input_source, out_srt)
                
        return out_srt

    def _run_whisper(self, audio_path, out_path):
        if not self._whisper:
            from faster_whisper import WhisperModel
            import torch
            # Check force CPU
            import os
            force_cpu = os.environ.get("PIPELINE_FORCE_CPU") == "1"
            device = "cpu" if force_cpu else self.cfg.step3.device
            
            self._whisper = WhisperModel(
                self.cfg.step3.model_size, 
                device=device,
                compute_type="float16" if device == "cuda" else "float32"
            )
            
        segs, _ = self._whisper.transcribe(str(audio_path), language=self.cfg.step3.language, vad_filter=True)
        self._save_srt(segs, out_path)

    def _run_ocr(self, video_path, out_path):
        # Logic từ step3_ima_to_srt.py
        if not self._ocr:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(
                use_angle_cls=False, 
                lang=self.cfg.step3.image_ocr_lang,
                use_gpu=self.cfg.step3.image_use_gpu,
                show_log=False
            )
        
        import cv2
        from difflib import SequenceMatcher
        
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS)
        interval_frames = int(fps * self.cfg.step3.image_frame_interval)
        
        subs = []
        last_text = ""
        start_ms = 0
        
        idx = 0
        while True:
            ret, frame = cap.read()
            if not ret: break
            
            if idx % interval_frames == 0:
                curr_ms = cap.get(cv2.CAP_PROP_POS_MSEC)
                # Crop logic (bottom 25%)
                h, w = frame.shape[:2]
                roi = frame[int(h*0.75):h, 0:w]
                
                # Preprocess logic (Otsu)
                gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
                _, bin_img = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
                
                res = self._ocr.ocr(bin_img, cls=False)
                txt = " ".join([line[1][0] for line in res[0]]).strip() if res and res[0] else ""
                
                if txt:
                    sim = SequenceMatcher(None, last_text, txt).ratio()
                    if sim < self.cfg.step3.similarity_threshold:
                        if last_text:
                            subs.append((start_ms, curr_ms, last_text))
                        last_text = txt
                        start_ms = curr_ms
            idx += 1
            
        if last_text:
            subs.append((start_ms, cap.get(cv2.CAP_PROP_POS_MSEC), last_text))
        cap.release()
        
        # Write SRT thủ công
        with open(out_path, "w", encoding="utf-8") as f:
            for i, (s, e, t) in enumerate(subs, 1):
                f.write(f"{i}\n{self._fmt(s)} --> {self._fmt(e)}\n{t}\n\n")

    def _save_srt(self, segs, path):
        with open(path, "w", encoding="utf-8") as f:
            for i, s in enumerate(segs, 1):
                f.write(f"{i}\n{self._fmt(s.start*1000)} --> {self._fmt(s.end*1000)}\n{s.text.strip()}\n\n")

    def _fmt(self, ms):
        seconds = int(ms // 1000)
        m, s = divmod(seconds, 60)
        h, m = divmod(m, 60)
        mil = int(ms % 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{mil:03d}"