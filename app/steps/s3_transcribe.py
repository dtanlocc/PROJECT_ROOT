# file: app/steps/s3_transcribe.py
import os
import re
import gc
import cv2
import torch
import numpy as np
import subprocess
from pathlib import Path
from typing import List, Dict
from loguru import logger
from difflib import SequenceMatcher
from paddleocr import PaddleOCR
from app.core.language.registry import LanguageRegistry
from app.steps.base import BaseStep
from lingua import Language, LanguageDetectorBuilder
import regex as re

class Step3Transcribe(BaseStep):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.out_dir = Path(getattr(self.cfg.pipeline, 'step3_srt_raw', 'workspace/03_srt_raw'))
      
        self._whisper = None
        self._ocr = None
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
      
        # === ROI từ config step5 ===
        self.roi_y_start = getattr(self.cfg.step5, 'roi_y_start', 0.65)
        self.roi_y_end = getattr(self.cfg.step5, 'roi_y_end', 1.0)
      
        self.debug_enabled = False

        # ==================== LANGUAGE REGISTRY ====================
        self.registry = LanguageRegistry()
        source_code = getattr(self.cfg, 'source_lang', 'zh')
        src = self.registry.get(source_code)

        self.whisper_lang = src.whisper      # "zh", "ja", "ko"...
        self.ocr_lang = src.paddleocr        # "ch", "japan", "korean"...
        # =========================================================

        self.detector = LanguageDetectorBuilder.from_languages(
            Language.CHINESE,
            Language.JAPANESE,
            Language.KOREAN,
            Language.ENGLISH,
        ).build()
    # ====================== DEBUG FRAMES ======================
    def _save_debug_frames(self, original_frame, zoomed_roi, current_text: str, fno: int, video_name: str):
        if not self.debug_enabled:
            return
           
        debug_dir = self.out_dir / "debug_frames" / video_name
        debug_dir.mkdir(parents=True, exist_ok=True)
        height = original_frame.shape[0]
        y1 = int(height * self.roi_y_start)
        y2 = int(height * self.roi_y_end)
        # ROI gốc để kiểm tra
        roi_debug = original_frame[max(0, y1-30):min(height, y2+30), :]
        cv2.imwrite(str(debug_dir / f"{fno:06d}_01_roi.jpg"), roi_debug)
        cv2.imwrite(str(debug_dir / f"{fno:06d}_02_zoomed.jpg"), zoomed_roi)
       
        # Overlay text để dễ nhìn
        overlay = zoomed_roi.copy()
        if current_text:
            cv2.putText(overlay, current_text[:75], (15, 45),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 3)
        cv2.imwrite(str(debug_dir / f"{fno:06d}_03_overlay.jpg"), overlay)
    # ====================== HELPERS ======================
    
    def _get_similarity(self, s1: str, s2: str) -> float:
            if not s1 or not s2:
                return 1.0 if s1 == s2 else 0.0
            
            s1_c = s1.replace(" ", "")
            s2_c = s2.replace(" ", "")
            
            # 1. Tính độ giống nhau tiêu chuẩn
            ratio = SequenceMatcher(None, s1_c, s2_c).ratio()
            
            # 2. Ngăn lỗi "bắc cầu": Chỉ tính độ bao hàm nếu chuỗi ngắn có ít nhất 3 ký tự
            len1, len2 = len(s1_c), len(s2_c)
            min_len = min(len1, len2)
            
            if min_len >= 3:
                shorter = s1_c if len1 < len2 else s2_c
                longer = s2_c if len1 < len2 else s1_c
                
                matcher = SequenceMatcher(None, shorter, longer)
                matched_chars = sum(block.size for block in matcher.get_matching_blocks())
                subset_ratio = matched_chars / min_len
                
                return max(ratio, subset_ratio)
                
            return ratio
    
    
    def _format_time(self, ms: float) -> str:
        seconds, milliseconds = divmod(int(ms), 1000)
        minutes, seconds = divmod(seconds, 60)
        hours, minutes = divmod(minutes, 60)
        return f"{hours:02d}:{minutes:02d}:{seconds:02d},{milliseconds:03d}"

    def _is_valid_chinese_sub(self, text: str) -> bool:
        if not text or len(text.strip()) < 2:
            return False
        text = str(text).strip()

        # Sử dụng ngôn ngữ từ config (không còn hardcode 'ch')
        lang = getattr(self.cfg.step4, 'language', 'ch').lower()

        if lang in ['ch', 'zh']:
            if not re.search(r'\p{Script=Han}', text):
                return False
        elif lang in ['ja', 'jp', 'japanese']:
            if not re.search(r'[\p{Script=Hiragana}\p{Script=Katakana}\p{Script=Han}]', text):
                return False
        elif lang in ['ko', 'kr', 'korean']:
            if not re.search(r'[\p{Script=Hangul}\p{Script=Han}]', text):
                return False
        else:
            if not re.search(r'\p{L}|\p{N}', text):
                return False

        # Lingua check (giữ nguyên logic cũ)
        clean_text_len = len(re.sub(r'[^\w\u4e00-\u9fff]', '', text))
        if clean_text_len <= 3:
            return True

        try:
            confidence_values = self.detector.compute_language_confidence_values(text)
            for confidence in confidence_values:
                if confidence.value < 0.65:
                    continue
                if lang in ['ch', 'zh'] and confidence.language == Language.CHINESE:
                    return True
                elif lang in ['ja', 'jp', 'japanese'] and confidence.language == Language.JAPANESE:
                    return True
                elif lang in ['ko', 'kr', 'korean'] and confidence.language == Language.KOREAN:
                    return True
        except Exception:
            pass
        return False
        
    def _final_polish_text(self, text: str) -> str:
        if not text:
            return ""
        t = str(text).strip()
        
        # 1. Dọn dẹp khoảng trắng thừa giữa các ký tự Hán
        t = re.sub(r'([\u4e00-\u9fff])\s+([\u4e00-\u9fff])', r'\1\2', t)
        t = re.sub(r'\s+', ' ', t)
        
        # 2. Quét sạch các dấu câu/ký tự nhiễu sinh ra ở hai đầu đoạn text do hiệu ứng viền
        t = re.sub(r'^[,.!?~`@#$%^&*()_+\-=\[\]{}|\\:;"\'<>/]+', '', t)
        t = re.sub(r'[,.~`@#$%^&*()_+\-=\[\]{}|\\:;"\'<>/]+$', '', t)
        
        return t.strip()
    # ====================== OCR CHỈ TRONG ROI ======================
    def _get_text_at_frame(self, cap_search, fno: int, video_name: str = ""):
        cap_search.set(cv2.CAP_PROP_POS_FRAMES, fno)
        ret, frame = cap_search.read()
        if not ret or frame is None:
            return ""
        height, width = frame.shape[:2]
        y1 = int(height * self.roi_y_start)
        y2 = int(height * self.roi_y_end)
        roi = frame[max(0, y1): min(height, y2), :]
        
        if roi.size == 0:
            return ""
        
        # 1. Chuyển sang ảnh xám (Grayscale) - Rất quan trọng để giảm nhiễu màu
        gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
        
        # 2. Phóng to (Zoom)
        zoomed = cv2.resize(gray_roi, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
        
        # 3. Làm nét (Sharpening filter) - Chỉnh kernel nhẹ lại để không vỡ hạt
        kernel_sharpen = np.array([
            [0, -1, 0],
            [-1, 5, -1],
            [0, -1, 0]
        ])
        enhanced = cv2.filter2D(zoomed, -1, kernel_sharpen)
        
        # Thêm dòng này nếu sub là chữ trắng viền đen (có thể test bật/tắt để xem hiệu quả):
        # _, enhanced = cv2.threshold(enhanced, 150, 255, cv2.THRESH_BINARY | cv2.THRESH_OTSU)

        # Convert lại thành 3 kênh màu vì PaddleOCR vẫn yêu cầu input 3 chiều
        enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)

        # OCR
        result = self._ocr.ocr(enhanced_bgr, cls=False)
        
        
       
        
        if not result or not result[0]:
            return ""
            
        # Sắp xếp các kết quả đọc được theo tọa độ Y (từ trên xuống dưới)
        # result[0] có cấu trúc: [ [[x1,y1], [x2,y2], [x3,y3], [x4,y4]], ('text', confidence) ]
        sorted_blocks = sorted(result[0], key=lambda block: block[0][0][1])

        valid_texts = [
            line[1][0].strip()
            for line in sorted_blocks
            if line[1][1] > 0.7 and self._is_valid_chinese_sub(line[1][0])
        ]
        final_text = self._final_polish_text(" ".join(valid_texts))
        
        if final_text and video_name and self.debug_enabled:
            self._save_debug_frames(frame, zoomed, final_text, fno, video_name)
        return final_text
    # ====================== TÌM FRAME THAY ĐỔI CHÍNH XÁC ======================
    # def _find_exact_change_frame(self, cap_search, start_f: int, end_f: int, start_text: str):
    #     low, high, ans = int(start_f), int(end_f), int(end_f)
    #     while low <= high:
    #         mid = (low + high) // 2
    #         mid_text = self._get_text_at_frame(cap_search, mid, "")
    #         if self._get_similarity(mid_text, start_text) >= getattr(self.cfg.step3, 'similarity_threshold', 0.65):
    #             low = mid + 1
    #         else:
    #             ans = mid
    #             high = mid - 1
    #     return ans
    
    def _find_exact_change_frame(self, cap_search, start_f: int, end_f: int, start_text: str):
        # Đặt mốc đọc từ đầu (chỉ set 1 lần duy nhất)
        cap_search.set(cv2.CAP_PROP_POS_FRAMES, start_f)
        
        ans = end_f
        # Đọc tuần tự tiến lên, cực kỳ nhẹ và nhanh
        for curr_f in range(int(start_f), int(end_f) + 1):
            ret, frame = cap_search.read()
            if not ret or frame is None:
                continue
                
            # Cắt và tiền xử lý y hệt như _get_text_at_frame
            height, width = frame.shape[:2]
            roi = frame[max(0, int(height * self.roi_y_start)): min(height, int(height * self.roi_y_end)), :]
            if roi.size == 0:
                continue
                
            gray_roi = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
            zoomed = cv2.resize(gray_roi, None, fx=2.0, fy=2.0, interpolation=cv2.INTER_CUBIC)
            kernel_sharpen = np.array([[0, -1, 0], [-1, 5, -1], [0, -1, 0]])
            enhanced = cv2.filter2D(zoomed, -1, kernel_sharpen)
            enhanced_bgr = cv2.cvtColor(enhanced, cv2.COLOR_GRAY2BGR)
            
            result = self._ocr.ocr(enhanced_bgr, cls=False)
            if not result or not result[0]:
                curr_text = ""
            else:
                sorted_blocks = sorted(result[0], key=lambda block: block[0][0][1])
                valid_texts = [l[1][0].strip() for l in sorted_blocks if l[1][1] > 0.7]
                curr_text = self._final_polish_text(" ".join(valid_texts))
            
            # Nếu text mới khác text cũ -> đây chính là điểm chuyển giao
            if self._get_similarity(curr_text, start_text) < getattr(self.cfg.step3, 'similarity_threshold', 0.65):
                ans = curr_f
                break # Dừng luôn, không cần đọc tiếp
                
        return ans
    # ====================== CHẠY OCR CHÍNH ======================
    def _run_ocr(self, video_path: Path, out_srt: Path, on_progress=None):
        if not self._ocr:
            self._ocr = PaddleOCR(
                use_angle_cls=False,
                lang=self.ocr_lang,
                use_gpu=getattr(self.cfg.step3, 'image_use_gpu', True),
                show_log=False,
                det_db_thresh=0.3,
                det_db_box_thresh=0.5,
                det_db_unclip_ratio=2.0,
                rec_batch_num=6
            )
        # Lấy thông tin video
        probe = subprocess.check_output([
            'ffprobe', '-v', 'error', '-select_streams', 'v:0',
            '-show_entries', 'stream=width,height,avg_frame_rate,nb_frames',
            '-of', 'default=noprint_wrappers=1:nokey=1', str(video_path)
        ]).decode('utf-8').split()
        width = int(probe[0])
        height = int(probe[1])
        fps = eval(probe[2])
        total_frames = int(probe[3]) if len(probe) > 3 and probe[3] != 'N/A' else 0
        step = getattr(self.cfg.step3, 'image_step_frames', 8)
        video_name = video_path.stem
        # Pipe ffmpeg đọc frame
        cmd = [
            'ffmpeg', '-hwaccel', 'cuda', '-i', str(video_path),
            '-vf', f"select='not(mod(n,{step}))'",
            '-vsync', '0', '-f', 'rawvideo', '-pix_fmt', 'bgr24', '-'
        ]
        pipe = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**8)
        cap_search = cv2.VideoCapture(str(video_path))
        extracted_subs = []
        last_text = ""
        last_fno = 0
        cur_idx = 0
        logger.info(f"🚀 Bắt đầu OCR chỉ trong ROI [{self.roi_y_start:.3f} - {self.roi_y_end:.3f}] | Step={step}")
        try:
            frame_size = width * height * 3
            while True:
                raw_frame = pipe.stdout.read(frame_size)
                if len(raw_frame) < frame_size:
                    break
                fno = cur_idx * step
                current_text = self._get_text_at_frame(cap_search, fno, video_name)
                
                # Phát hiện thay đổi text
                if self._get_similarity(current_text, last_text) < getattr(self.cfg.step3, 'similarity_threshold', 0.65):
                    if last_text.strip():
                        current_exact_fno = self._find_exact_change_frame(
                            cap_search, max(0, fno - step * 2), fno, last_text
                        )
                        start_ms = (last_fno / fps) * 1000
                        end_ms = (current_exact_fno / fps) * 1000
                        
                        # [QUAN TRỌNG] Hạ ngưỡng xuống 100ms để không ném nhầm các mảnh vụn của câu
                        if end_ms - start_ms >= 100:
                            extracted_subs.append({
                                'start': start_ms,
                                'end': end_ms,
                                'text': last_text
                            })
                        
                        last_text = current_text
                        last_fno = current_exact_fno
                    else:
                        last_text = current_text
                        # Chuyển từ khoảng trắng sang có chữ -> Lùi mốc thời gian lại nửa nhịp để không lẹm mất chữ
                        last_fno = max(0, fno - (step // 2))
                else:
                    # Nếu là cùng 1 câu, hãy cập nhật để lấy bản dài hơn/đầy đủ hơn
                    if len(current_text) > len(last_text):
                        last_text = current_text
                        
                cur_idx += 1
                if on_progress and total_frames > 0:
                    on_progress(min(fno / total_frames, 1.0))
                    
        finally:
            pipe.terminate()
            cap_search.release()
            
        # Sub cuối cùng
        if last_text.strip():
            final_end_fno = total_frames if (total_frames and total_frames > fno) else fno
            end_ms_final = (final_end_fno / fps) * 1000
            start_ms_final = (last_fno / fps) * 1000
            if end_ms_final - start_ms_final >= 100:
                extracted_subs.append({
                    'start': start_ms_final,
                    'end': end_ms_final,
                    'text': last_text
                })
            
        # Merge duplicate
        extracted_subs = self._merge_duplicate_subs(extracted_subs)
        
        # [BỘ LỌC CHỐT CHẶN]: Sau khi đã gộp hoàn chỉnh, mới quét dọn các rác thực sự (< 200ms)
        extracted_subs = [s for s in extracted_subs if s['end'] - s['start'] >= 200]
   
        # Ghi file SRT
        with open(out_srt, "w", encoding="utf-8") as f:
            for i, item in enumerate(extracted_subs, 1):
                polished = self._final_polish_text(item['text'])
                if polished:
                    f.write(f"{i}\n{self._format_time(item['start'])} --> {self._format_time(item['end'])}\n{polished}\n\n")
        logger.success(f"✅ OCR hoàn tất: {len(extracted_subs)} câu subtitle")
        if self.debug_enabled:
            logger.info(f"📸 Debug frames được lưu tại: {self.out_dir}/debug_frames/{video_name}")
            
   
    def _merge_duplicate_subs(self, subs: List[Dict]) -> List[Dict]:
        if not subs:
            return []
            
        # BƯỚC 1: KHỬ NHIỄU "SANDWICH" (Câu đúng -> Rác nháy chớp -> Câu đúng)
        i = 0
        while i < len(subs) - 2:
            # So sánh câu hiện tại (i) và câu cách nó 1 nhịp (i+2)
            sim = self._get_similarity(subs[i]['text'], subs[i+2]['text'])
            # Thời lượng của câu kẹp ở giữa (i+1)
            mid_duration = subs[i+1]['end'] - subs[i+1]['start']
            
            # Nếu câu 1 và 3 giống nhau, và câu 2 ở giữa quá ngắn (< 600ms)
            if sim > 0.60 and mid_duration < 600:
                # Bắc cầu nối dài thời gian từ câu 1 đến hết câu 3
                subs[i]['end'] = max(subs[i]['end'], subs[i+2]['end'])
                # Cập nhật text dài hơn nếu có
                if len(subs[i+2]['text']) > len(subs[i]['text']):
                    subs[i]['text'] = subs[i+2]['text']
                
                # Xóa câu 3 và câu 2 (phải pop index lớn trước để không bị lỗi dịch chuyển mảng)
                subs.pop(i+2)
                subs.pop(i+1)
                
                # Giữ nguyên i (continue) để kiểm tra tiếp lỡ có rác nháy liên tục
                continue
            i += 1

        # BƯỚC 2: GỘP CÁC CÂU LIÊN TIẾP GIỐNG NHAU (Thuật toán cũ)
        merged = [subs[0]]
        for curr in subs[1:]:
            last = merged[-1]
            gap = curr['start'] - last['end']
            sim = self._get_similarity(curr['text'], last['text'])
            
            if sim > 0.55 and gap < 2000:
                last['end'] = max(last['end'], curr['end'])
                if len(curr['text']) > len(last['text']):
                    last['text'] = curr['text']
            else:
                merged.append(curr)
                
        return merged
    # ====================== WHISPER (giữ nguyên) ======================
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
                str(audio_file), vad_filter=True, language=self.whisper_lang
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
                
    def _av_get_duration(self, file_path: str) -> float:
        try:
            import av
            with av.open(file_path) as container:
                return container.duration / 1_000_000 if container.duration else 0.0
        except Exception:
            return 0.0
    # ====================== MAIN PROCESS ======================
# ====================== MAIN PROCESS ======================
    def process(self, input_source: Path, on_progress=None) -> Path:
        self.ensure_dir(self.out_dir)
        out_srt = self.out_dir / f"{input_source.stem}.srt"
        mode = getattr(self.cfg.step3, 'srt_source', 'image').lower()

        if mode == "voice":
            audio_path = input_source / "vocals.wav" if input_source.is_dir() else input_source
            self._run_whisper_v3(audio_path, out_srt, on_progress)
        else:
            logger.info(f"[Step3] ROI Subtitle được thiết lập: {self.roi_y_start:.3f} → {self.roi_y_end:.3f}")
            self._run_ocr(input_source, out_srt, on_progress)

        gc.collect()
        if self.device == "cuda":
            torch.cuda.empty_cache()
        return out_srt