import os
import re
import gc
import logging
from pathlib import Path
from typing import Optional, Callable
from loguru import logger
from app.steps.base import BaseStep

# Tắt check mạng Paddle
os.environ["PADDLE_PDX_DISABLE_MODEL_SOURCE_CHECK"] = "True"

def _clean_whisper_text(raw: str) -> str:
    """Dọn dẹp text: cắt khoảng trắng và các ký tự không phải chữ/CJK ở đầu/cuối."""
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

    def process(self, input_source: Path, on_progress: Optional[Callable[[float], None]] = None) -> Path:
        self.ensure_dir(self.out_dir)
        mode = self.cfg.step3.srt_source
        
        # Xác định file nguồn dựa trên mode (voice hoặc image)
        if mode == "voice":
            video_stem = input_source.name
            src_file = input_source / "vocals.wav"
            out_srt = self.out_dir / f"{video_stem}.srt"
        else:
            video_stem = input_source.stem
            src_file = input_source
            out_srt = self.out_dir / f"{video_stem}.srt"

        # Resume Check: Nếu file đã tồn tại thì bỏ qua
        if out_srt.exists() and out_srt.stat().st_size > 0:
            return out_srt

        logger.info(f"📝 [Step 3] Transcribe ({mode}): {video_stem}")

        if mode == "voice":
            self._run_whisper(src_file, out_srt, on_progress=on_progress)
        else:
            self._run_ocr(src_file, out_srt)
        
        return out_srt

    def _add_subtitle(self, subtitles, words):
        """Hàm hỗ trợ đóng gói subtitle từ danh sách từ (words)."""
        if not words:
            return
        start_t = float(words[0].start)
        end_t = float(words[-1].end)
        raw_text = "".join([w.word for w in words]).strip()
        clean_text = _clean_whisper_text(raw_text)
        if clean_text:
            subtitles.append((start_t, end_t, clean_text))

    def _run_whisper(self, audio_path, out_path, on_progress: Optional[Callable[[float], None]] = None):
        """Logic nhận diện giọng nói: Sử dụng Word-level kết hợp ngắt câu thông minh."""
        import torch
        from faster_whisper import WhisperModel

        if not self._whisper:
            device = self.cfg.step3.device
            if device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            compute = "float16" if device == "cuda" else "float32"
            
            try:
                self._whisper = WhisperModel(
                    self.cfg.step3.model_size,
                    device=device,
                    compute_type=compute,
                    cpu_threads=getattr(self.cfg.step3, "cpu_threads", 1),
                )
            except Exception as e:
                logger.warning(f"Lỗi khởi tạo GPU, chuyển sang CPU: {e}")
                self._whisper = WhisperModel(
                    self.cfg.step3.model_size,
                    device="cpu",
                    compute_type="float32"
                )

        if torch.cuda.is_available():
            torch.cuda.empty_cache()
        gc.collect()

        lang = self.cfg.step3.language
        subtitles = []
        current_words = []
        
        # Cấu hình Prompt để ép Whisper tạo dấu câu (Punctuation)
        # Nếu không có prompt này, Whisper thường trả về text trơn không dấu.
        initial_prompt = "Chào bạn. Hôm nay bạn thế nào? Tôi là trợ lý AI. Tôi sẽ giúp bạn dịch thuật và làm phụ đề chính xác."
        if lang == "zh":
            initial_prompt = "你好，这是一个准确的字幕翻译。我们会加上标点符号，如句号、问号和感叹号。"

        max_chars = 25 if lang in ["zh", "ja", "ko"] else 80

        try:
            with open(str(audio_path), "rb") as f:
                segments_iter, info = self._whisper.transcribe(
                    f,
                    word_timestamps=True,
                    vad_filter=True,
                    language=lang,
                    initial_prompt=initial_prompt, # QUAN TRỌNG: Ép tạo dấu câu
                    beam_size=5
                )
                
                duration = float(getattr(info, "duration", 0.0) or 0.0)
                
                for seg in segments_iter:
                    if not seg.words:
                        continue
                    
                    for w in seg.words:
                        current_words.append(w)
                        # Loại bỏ khoảng trắng để đếm ký tự chuẩn cho CJK
                        text_so_far = "".join([x.word for x in current_words]).replace(" ", "").strip()
                        
                        # LOGIC NGẮT CÂU MẠNH (Strong Splitting)
                        # 1. Kiểm tra dấu câu ở cuối từ hiện tại
                        last_word_clean = w.word.strip()
                        has_punc = re.search(r'[.!?;。！？；,，]$', last_word_clean)
                        
                        # 2. Ngắt theo độ dài ký tự
                        too_long = len(text_so_far) >= max_chars
                        
                        # 3. Ngắt nếu có khoảng lặng lớn giữa 2 từ (Gap > 0.5s)
                        has_gap = False
                        if len(current_words) > 1:
                            gap = w.start - current_words[-2].end
                            if gap > 0.5:
                                has_gap = True

                        if has_punc or too_long or has_gap:
                            self._add_subtitle(subtitles, current_words)
                            current_words = []
                    
                    if on_progress and duration > 0:
                        on_progress(min(seg.end / duration, 1.0))

                if current_words:
                    self._add_subtitle(subtitles, current_words)

        except Exception as e:
            logger.error(f"Whisper logic failed: {e}")

        # Ghi kết quả ra file SRT
        with open(out_path, "w", encoding="utf-8") as f:
            for i, (start, end, text) in enumerate(subtitles, 1):
                f.write(f"{i}\n{self._fmt(start)} --> {self._fmt(end)}\n{text}\n\n")

    # --- Các hàm bổ trợ OCR giữ nguyên theo logic hiện tại của bạn ---
    def _run_ocr(self, video_path, out_path):
        """Logic trích xuất sub từ ảnh (PaddleOCR)."""
        if not self._ocr:
            from paddleocr import PaddleOCR
            self._ocr = PaddleOCR(lang=self.cfg.step3.image_ocr_lang, use_gpu=self.cfg.step3.image_use_gpu, show_log=False)
        
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        
        step_frames = getattr(self.cfg.step3, "image_step_frames", 10)
        y1, y2 = int(h * self.cfg.step5.roi_y_start), int(h * self.cfg.step5.roi_y_end)

        subs = []
        last_text, last_fno = "", 0

        for fno in range(0, total_frames, step_frames):
            current_text = self._get_text_at_frame(cap, fno, y1, y2)
            if self._get_similarity(current_text, last_text) < self.cfg.step3.similarity_threshold:
                exact_fno = self._find_exact_change_frame(cap, max(0, fno - step_frames), fno, last_text, y1, y2)
                if last_text:
                    subs.append(((last_fno/fps)*1000, (exact_fno/fps)*1000, last_text))
                last_text, last_fno = current_text, exact_fno

        if last_text:
            subs.append(((last_fno/fps)*1000, (total_frames/fps)*1000, last_text))
        
        cap.release()
        with open(out_path, "w", encoding="utf-8") as f:
            for i, (s, e, t) in enumerate(subs, 1):
                f.write(f"{i}\n{self._fmt(s/1000)} --> {self._fmt(e/1000)}\n{t}\n\n")

    def _preprocess_roi_all_colors(self, roi):
        import cv2
        import numpy as np
        max_channel = np.max(roi, axis=2)
        enhanced = cv2.convertScaleAbs(max_channel, alpha=1.5, beta=10)
        _, thresh = cv2.threshold(enhanced, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        return thresh

    def _get_text_at_frame(self, cap, fno, y1, y2):
        import cv2
        cap.set(cv2.CAP_PROP_POS_FRAMES, fno)
        ret, frame = cap.read()
        if not ret or frame[y1:y2, :].size == 0: return ""
        processed = self._preprocess_roi_all_colors(frame[y1:y2, :])
        res = self._ocr.ocr(processed, cls=False)
        if res and res[0]:
            return " ".join([line[1][0] for line in res[0] if line[1][1] >= self.cfg.step3.image_confidence_threshold]).strip()
        return ""

    def _get_similarity(self, s1, s2):
        from difflib import SequenceMatcher
        return SequenceMatcher(None, s1 or "", s2 or "").ratio()

    def _find_exact_change_frame(self, cap, start_f, end_f, start_text, y1, y2):
        low, high, ans = int(start_f), int(end_f), int(end_f)
        while low <= high:
            mid = (low + high) // 2
            if self._get_similarity(self._get_text_at_frame(cap, mid, y1, y2), start_text) >= self.cfg.step3.similarity_threshold:
                low = mid + 1
            else:
                ans, high = mid, mid - 1
        return ans

    def _fmt(self, seconds):
        if seconds is None: seconds = 0
        h, m = int(seconds // 3600), int((seconds % 3600) // 60)
        s, ms = int(seconds % 60), int((seconds - int(seconds)) * 1000)
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"