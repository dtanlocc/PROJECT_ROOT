# file: app/steps/s3_transcribe.py
import os
import re
import gc
import cv2
import av
import torch
import numpy as np
import subprocess
from pathlib import Path
from typing import Optional, Callable, List
from loguru import logger
from difflib import SequenceMatcher
from collections import defaultdict, Counter
from faster_whisper import WhisperModel
from app.steps.base import BaseStep

class Step3Transcribe(BaseStep):
    def __init__(self, cfg):
        super().__init__(cfg)
        # Tự động map đường dẫn output
        self.out_dir = Path(getattr(self.cfg.pipeline, 'step3_srt_raw', 'workspace/03_srt_raw'))
        self._whisper = None
        self._ocr = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"

    # ============================================================
    # HÀM HỖ TRỢ (HELPERS)
    # ============================================================
    def _get_similarity(self, s1: str, s2: str) -> float:
        """So sánh độ tương đồng giữa 2 chuỗi text."""
        if not s1 or not s2: 
            return 0.0 if s1 != s2 else 1.0
        return SequenceMatcher(None, s1, s2).ratio()

    def _format_time(self, ms: float) -> str:
        """Convert miliseconds sang chuẩn SRT HH:MM:SS,mmm"""
        seconds, milliseconds = divmod(int(ms), 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    def _is_valid_chinese_sub(self, text):
        if not text: return False
        return bool(re.search(r'[\u4e00-\u9fff]', str(text)))

    def _final_polish_text(self, text):
        if not text: return ""
        t = str(text)
        t = re.sub(r'\s+[^\s]{1}$', '', t) # Xóa ký tự lẻ cuối
        t = re.sub(r'^[^\s]{1}\s+', '', t) # Xóa ký tự lẻ đầu
        if not re.search(r'[\u4e00-\u9fff]', t): return ""
        return t.strip()

    # ============================================================
    # WHISPER LOGIC (VOICE TO SRT)
    # ============================================================
    def _av_get_duration(self, file_path: str) -> float:
        try:
            with av.open(file_path) as container:
                return container.duration / 1e6 if container.duration else 0.0
        except: return 0.0

    def _run_whisper_v3(self, audio_file: Path, out_path: Path, on_progress):
        from faster_whisper import WhisperModel
        if not self._whisper:
            self._whisper = WhisperModel(
                self.cfg.step3.model_size,
                device=self.device,
                compute_type="float16" if self.device == "cuda" else "float32"
            )

        duration = self._av_get_duration(str(audio_file))
        subtitles = []
        
        try:
            segments, info = self._whisper.transcribe(
                str(audio_file), vad_filter=True, language=self.cfg.step3.language
            )
            for seg in segments:
                clean = re.sub(r'^[^\w\u4e00-\u9fff]+', '', seg.text.strip())
                clean = re.sub(r'[^\w\u4e00-\u9fff]+$', '', clean)
                if clean:
                    subtitles.append({'start': seg.start * 1000, 'end': seg.end * 1000, 'text': clean})
                if on_progress and duration > 0:
                    on_progress(min(seg.end / duration, 1.0))
        except Exception as e:
            logger.error(f"Whisper Error: {e}")

        with open(out_path, "w", encoding="utf-8") as f:
            for idx, sub in enumerate(subtitles, start=1):
                f.write(f"{idx}\n{self._format_time(sub['start'])} --> {self._format_time(sub['end'])}\n{sub['text']}\n\n")
    def _merge_duplicate_subs(self,subs, max_gap_ms=1500):
        if not subs: return []
        merged = []
        for current in subs:
            if not merged:
                merged.append(current)
                continue
                
            last = merged[-1]
            gap = current['start'] - last['end']
            similarity = self._get_similarity(current['text'], last['text'])
            dynamic_threshold = 0.55 if gap <= 100 else self.cfg.step3.similarity_threshold
            is_substring = (current['text'] in last['text']) or (last['text'] in current['text'])
            
            if (similarity >= dynamic_threshold or is_substring) and gap <= max_gap_ms:
                last['end'] = max(last['end'], current['end'])
                if len(current['text']) >= len(last['text']):
                    last['text'] = current['text']
            else:
                merged.append(current)
                
        return merged
    # ============================================================
    # OCR LOGIC (IMAGE TO SRT)
    # ============================================================
    def _detect_sub_geometry(self, video_path):
        """Đã tắt chế độ dò tự động. Chốt cứng tọa độ cắt theo cấu hình ROI."""
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened(): 
            return None, None, None

        h_video = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w_video = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cap.release()

        # Tính toán tọa độ dựa trực tiếp vào cấu hình ROI_Y_START_P (0.65) và ROI_Y_END_P (1.0)
        final_by = int(h_video * self.cfg.step5.roi_y_start)
        final_bh = int(h_video * self.cfg.step5.roi_y_end) - final_by
        final_bw = w_video # Lấy tràn viền chiều ngang

        print(f"✅ Bỏ qua quét tự động. Chốt cứng vùng Sub: Bắt đầu tại Y={final_by}, Cao={final_bh}px")
        return final_by, final_bh, final_bw

    def _get_text_at_frame_cv2(self, cap_search, fno, ocr, y1, y2):
        cap_search.set(cv2.CAP_PROP_POS_FRAMES, fno)
        ret, frame = cap_search.read()
        if not ret or frame is None: return ""
        
        height = frame.shape[0]
        
        # --- LOGIC CO GIÃN TỰ ĐỘNG ---
        # 1. Lề an toàn: 1.5% chiều cao video (tránh lẹm viền đen)
        dynamic_margin = int(height * 0.015) 
        # 2. Ngưỡng Zoom: Nếu chữ gốc cao dưới 5% video thì mới phóng to
        zoom_threshold = int(height * 0.05)
        
        # 3. Cắt vùng chứa chữ với lề an toàn
        safe_y1 = max(0, y1 - dynamic_margin)
        safe_y2 = min(height, y2 + dynamic_margin)
        roi = frame[safe_y1:safe_y2, :]
        
        h_roi, w_roi = roi.shape[:2]
        text_h_original = y2 - y1 # Chiều cao thực tế của chữ không tính lề
        
        # 4. Phóng to thông minh (Chỉ zoom khi chữ nhỏ)
        if 0 < text_h_original < zoom_threshold and w_roi > 0:
            zoomed_roi = cv2.resize(roi, (w_roi * 2, h_roi * 2), interpolation=cv2.INTER_CUBIC)
        else:
            zoomed_roi = roi
            
        # 5. Đưa ảnh vào AI (Dùng ảnh màu gốc để PaddleOCR tự xử lý)
        result = ocr.ocr(zoomed_roi, cls=False)
        
        if result and result[0]:
            # Hạ ngưỡng confidence xuống 0.5 để bắt được font chữ khó
            texts = [line[1][0] for line in result[0] if line[1][1] > 0.5 and self._is_valid_chinese_sub(line[1][0])]
            return " ".join(texts).strip()
        return ""

    def _find_exact_change_frame(self, cap_search, start_f, end_f, start_text, ocr, y1, y2):
        low, high, ans = int(start_f), int(end_f), int(end_f)
        while low <= high:
            mid = (low + high) // 2
            if self._get_similarity(self._get_text_at_frame_cv2(cap_search, mid, ocr, y1, y2), start_text) >= self.cfg.step3.similarity_threshold:
                low = mid + 1
            else: ans = mid; high = mid - 1
        return ans

    def _run_ocr_v3(self, video_path: Path, out_path: Path, on_progress):
        from paddleocr import PaddleOCR
        if not self._ocr:
            self._ocr = PaddleOCR(use_angle_cls=False, lang='ch', use_gpu=self.cfg.step3.image_use_gpu, show_log=False)
        
        sub_y, sub_h, sub_w = self._detect_sub_geometry(str(video_path))
        
        probe = subprocess.check_output(['ffprobe', '-v', 'error', '-select_streams', 'v:0', '-show_entries', 'stream=width,height,avg_frame_rate,nb_frames', '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)]).decode('utf-8').split()
        width, height, fps = int(probe[0]), int(probe[1]), eval(probe[2])
        total_frames = int(probe[3]) if probe[3] != 'N/A' else 0
        
        y1, y2 = (sub_y, sub_y + sub_h) if sub_y is not None else (int(height * self.cfg.step5.roi_y_start), int(height * self.cfg.step5.roi_y_end))
        step = self.cfg.step3.image_step_frames

        cmd = ['ffmpeg', '-hwaccel', 'cuda', '-i', str(video_path), '-vf', f"select='not(mod(n,{step}))'", '-vsync', '0', '-f', 'image2pipe', '-vcodec', 'rawvideo', '-pix_fmt', 'bgr24', '-']
        pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
        cap_search = cv2.VideoCapture(str(video_path))

        extracted_subs, last_text, last_fno, cur_idx = [], "", 0, 0
        try:
            while True:
                raw = pipe.stdout.read(width * height * 3)
                if not raw: break
                fno = cur_idx * step
                frame = np.frombuffer(raw, dtype=np.uint8).reshape((height, width, 3))
                dynamic_margin = int(height * 0.015) 
                zoom_threshold = int(height * 0.05)
                
                safe_y1 = max(0, y1 - dynamic_margin)
                safe_y2 = min(height, y2 + dynamic_margin)
                roi = frame[safe_y1:safe_y2, :]
                
                h_roi, w_roi = roi.shape[:2]
                text_h_original = y2 - y1
                
                # Phóng to nếu chữ nhỏ
                if 0 < text_h_original < zoom_threshold and w_roi > 0:
                    zoomed_roi = cv2.resize(roi, (w_roi * 2, h_roi * 2), interpolation=cv2.INTER_CUBIC)
                else:
                    zoomed_roi = roi
                
                result = self._ocr.ocr(zoomed_roi, cls=False)
                
                if result and result[0]:
                    valid_texts = [line[1][0] for line in result[0] if line[1][1] > 0.7 and self._is_valid_chinese_sub(line[1][0])]
                    current_text = " ".join(valid_texts).strip() if (len(valid_texts) <= 3 and sum(len(t) for t in valid_texts) <= 45) else ""
                else:
                    current_text = ""

                # Kiểm tra sự thay đổi nội dung (Similarity)
                if self._get_similarity(current_text, last_text) < self.cfg.step3.similarity_threshold:
                    # Dùng Binary Search để tìm frame chuyển cảnh chính xác
                    exact_fno = self._find_exact_change_frame(cap_search, max(0, fno - step), fno, last_text, self._ocr, y1, y2)
                    
                    if last_text:
                        start_ms, end_ms = (last_fno / fps) * 1000, (exact_fno / fps) * 1000
                        if (end_ms - start_ms) >= self.cfg.step3.image_min_duration_ms:
                            extracted_subs.append({'start': start_ms, 'end': end_ms, 'text': last_text})
                    
                    last_text, last_fno = current_text, exact_fno
                
                cur_idx += 1
                if on_progress and total_frames > 0: on_progress(fno / total_frames)

        finally:
            pipe.terminate()
            cap_search.release()

        # Ghi file kết quả
        if last_text:
            extracted_subs.append({'start': (last_fno/fps)*1000, 'end': (total_frames/fps)*1000, 'text': last_text})

        extracted_subs = self._remove_dynamic_watermark(extracted_subs)
        extracted_subs = self._merge_duplicate_subs(extracted_subs)

        with open(out_path, "w", encoding="utf-8") as f:
            sub_index = 1
            for item in extracted_subs:
                polished_text = self._final_polish_text(item['text'])
                if polished_text:
                    f.write(f"{sub_index}\n{self._format_time(item['start'])} --> {self._format_time(item['end'])}\n{polished_text}\n\n")
                    sub_index += 1
    def _remove_dynamic_watermark(self, raw_subs):
        """Quét và xóa Watermark không cần dấu cách (chuẩn cho Tiếng Trung, Nhật, Hàn)"""
        if not raw_subs or len(raw_subs) < 5: 
            return raw_subs

        texts = [sub['text'] for sub in raw_subs]
        total_subs = len(texts)
        
        # 1. Quét tìm tất cả các chuỗi con có độ dài >= 3 ký tự
        substring_counts = defaultdict(int)
        for t in texts:
            seen_substrings = set()
            length = len(t)
            for i in range(length):
                for j in range(i + 3, length + 1): # Chỉ xét chuỗi dài từ 3 ký tự trở lên
                    seen_substrings.add(t[i:j])
            
            for sub_str in seen_substrings:
                substring_counts[sub_str] += 1
                
        # 2. Nếu một chuỗi xuất hiện ở hơn 35% tổng số câu -> Đích thị là Logo/Watermark
        watermarks = [sub_str for sub_str, count in substring_counts.items() if count > (total_subs * 0.35)]
        
        if not watermarks:
            return raw_subs
            
        # 3. Lọc chỉ lấy cụm từ dài nhất (tránh việc xóa lẻ tẻ)
        watermarks.sort(key=len, reverse=True)
        final_watermarks = []
        for w in watermarks:
            if not any(w in fw for fw in final_watermarks):
                final_watermarks.append(w)
                
        print(f"\n🗑️ Đã tự động phát hiện và xóa Logo: {final_watermarks}")
        
        # 4. Cắt logo ra khỏi toàn bộ sub
        cleaned_subs = []
        for sub in raw_subs:
            clean_text = sub['text']
            for wm in final_watermarks:
                clean_text = clean_text.replace(wm, "").strip()
                # Bỏ thêm cụm 'bl' do OCR hay nhận diện nhầm viền logo
                clean_text = clean_text.replace("bl", "").strip() 
            
            if clean_text:
                sub['text'] = clean_text
                cleaned_subs.append(sub)
                
        return cleaned_subs

    def _merge_subs(self, subs):
        if not subs: return []
        merged = []
        for curr in subs:
            if not merged: merged.append(curr); continue
            last = merged[-1]
            if self._get_similarity(curr['text'], last['text']) >= self.cfg.step3.similarity_threshold and (curr['start'] - last['end'] <= 1500):
                last['end'] = max(last['end'], curr['end'])
            else: merged.append(curr)
        return merged

    def process(self, input_source: Path, on_progress=None) -> Path:
        self.ensure_dir(self.out_dir)
        mode = self.cfg.step3.srt_source
        out_srt = self.out_dir / f"{input_source.stem}.srt"
        if mode == "voice":
            self._run_whisper_v3(input_source / "vocals.wav" if input_source.is_dir() else input_source, out_srt, on_progress)
        else:
            self._run_ocr_v3(input_source, out_srt, on_progress)
        return out_srt