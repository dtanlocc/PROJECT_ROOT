import concurrent.futures
import gc
import threading
import shutil
import hashlib
import os
import time
from pathlib import Path
from loguru import logger

from app.core.config_loader import ConfigLoader
from app.services.ffmpeg_manager import FFmpegManager

# --- [BẢO MẬT]: ĐÃ TẠM TẮT ĐỂ TEST ---
# from app.core.security import is_session_valid

# --- Helper Check Lỗi PyTorch (Giữ nguyên) ---
def is_shm_dll_error(ex):
    if ex is None: return False
    msg = str(ex).lower()
    return "shm.dll" in msg or "winerror 127" in msg or "error 127" in msg

SHM_FIX_MESSAGE = "Lỗi PyTorch GPU trên Windows (shm.dll)..."

def is_meth_static_error(ex):
    if ex is None: return False
    return "meth_class" in msg or "meth_static" in msg

METH_FIX_MESSAGE = "Lỗi tương thích Python / PyTorch / NumPy..."

from app.steps.s1_normalize import Step1Normalize

class ProEngine:
    def __init__(self):
        self.cfg = ConfigLoader.load()
        self.ffmpeg = FFmpegManager(self.cfg.ffmpeg_bin)
        self.s1 = Step1Normalize(self.cfg, self.ffmpeg)
        self._s2 = None
        self._s3 = None
        self._s4 = None
        self._s5 = None
        self._s6 = None
        self.gpu_lock = threading.Semaphore(1)
        self._progress_lock = threading.Lock()
        self._progress_completed = 0
        self._progress_total = 0
        self._progress_current = {}
        self._on_progress_cb = None

    # --- HÀM TÌM FILE CŨ (Nếu skip bước) ---
    def get_existing_output(self, step: int, original_stem: str, safe_stem: str):
        """Tìm file đã xử lý trước đó nếu người dùng không chọn chạy bước này."""
        if step == 1: return self.cfg.pipeline.step1_wav / f"{safe_stem}.wav"
        if step == 2: return self.cfg.pipeline.step2_separated / safe_stem
        if step == 3: return self.cfg.pipeline.step3_srt_raw / f"{safe_stem}.srt"
        if step == 4: return self.cfg.pipeline.step4_srt_translated / f"{safe_stem}.srt"
        if step == 5: return self.cfg.pipeline.step5_video_subbed / f"{safe_stem}.mp4"
        return None

    # --- Lazy Load Steps ---
    def _get_s2(self):
        if self._s2 is None:
            from app.steps.s2_demucs import Step2Demucs
            self._s2 = Step2Demucs(self.cfg)
        return self._s2

    def _get_s3(self):
        if self._s3 is None:
            from app.steps.s3_transcribe import Step3Transcribe
            self._s3 = Step3Transcribe(self.cfg)
        return self._s3

    def _get_s4(self):
        if self._s4 is None:
            from app.steps.s4_translate import Step4Translate
            self._s4 = Step4Translate(self.cfg)
        return self._s4

    def _get_s5(self):
        if self._s5 is None:
            from app.steps.s5_overlay import Step5Overlay
            self._s5 = Step5Overlay(self.cfg, self.ffmpeg)
        return self._s5

    def _get_s6(self):
        if self._s6 is None:
            from app.steps.s6_mix import Step6Mix
            self._s6 = Step6Mix(self.cfg, self.ffmpeg)
        return self._s6

    def _get_safe_name(self, original_name):
        ext = Path(original_name).suffix
        safe_hash = hashlib.md5(original_name.encode('utf-8')).hexdigest()[:10]
        return f"vid_{safe_hash}{ext}"

    def process_one(self, video_path: Path):
        # [BYPASS BẢO MẬT CHO TEST]
        # if not is_session_valid(): os._exit(0)

        original_stem = video_path.stem
        # BẮT BUỘC: Mọi xử lý dùng safe_video_path để tránh lỗi Unicode/Long Path của OpenCV
        safe_filename = self._get_safe_name(video_path.name)
        work_dir = self.cfg.pipeline.workspace_root / "processing"
        work_dir.mkdir(parents=True, exist_ok=True)
        
        safe_video_path = work_dir / safe_filename
        safe_stem = safe_video_path.stem
        
        try:
            logger.info(f"🚀 Processing: {original_stem[:50]}... (ID: {safe_stem})")
            
            if not safe_video_path.exists():
                shutil.copy2(str(video_path), str(safe_video_path))

            # --- B1: Normalize ---
            if getattr(self.cfg.pipeline, "run_s1", True):
                self._report_progress("B1 Normalize", safe_stem)
                wav = self.s1.process(safe_video_path)
            else:
                wav = self.get_existing_output(1, original_stem, safe_stem)

            # --- B2: Demucs ---
            if getattr(self.cfg.pipeline, "run_s2", True):
                self._report_progress("B2 Demucs", safe_stem)
                with self.gpu_lock:
                    sep_dir = self._get_s2().process(wav)
            else:
                sep_dir = self.get_existing_output(2, original_stem, safe_stem)
            
            bg_music = sep_dir / "no_vocals.wav" if (sep_dir and sep_dir.exists()) else None
            
            # --- B3: Transcribe ---
            if getattr(self.cfg.pipeline, "run_s3", True):
                logger.info(f"📝 [Step 3] Nhận diện SRT: {original_stem[:30]}...") # THÊM LOG NÀY
                self._report_progress("B3 Transcribe", safe_stem)
                input_s3 = safe_video_path if self.cfg.step3.srt_source == "image" else sep_dir
                
                def _b3_progress(r): self._report_step_ratio("B3 SRT", safe_stem, r)
                
                with self.gpu_lock:
                    srt_raw = self._get_s3().process(input_s3, on_progress=_b3_progress)
            else:
                logger.info(f"⏭️ [Skip] Step 3: Dùng file SRT có sẵn.")
                srt_raw = self.get_existing_output(3, original_stem, safe_stem)
                
            # --- B4: Translate ---
            if getattr(self.cfg.pipeline, "run_s4", True):
                self._report_progress("B4 Translate", safe_stem)
                srt_trans = self._get_s4().process(srt_raw)
            else:
                srt_trans = self.get_existing_output(4, original_stem, safe_stem)
            
            # --- B5: Overlay ---
            if getattr(self.cfg.pipeline, "run_s5", True):
                self._report_progress("B5 Overlay", safe_stem)
                # Dùng video đã hash tên để Step 5 (OpenCV) không bị crash
                vid_sub = self._get_s5().process(safe_video_path, srt_trans)
            else:
                vid_sub = self.get_existing_output(5, original_stem, safe_stem) or safe_video_path
            
            # --- B6: Mix ---
            if getattr(self.cfg.pipeline, "run_s6", True):
                self._report_progress("B6 Mix", safe_stem)
                final_temp = self._get_s6().process(vid_sub, srt_trans, bg_music)
                
                # CHỐT HẠ: Xuất file về tên gốc Unicode
                self.cfg.pipeline.step6_final.mkdir(parents=True, exist_ok=True)
                final_output = self.cfg.pipeline.step6_final / f"{original_stem}.mp4"
                
                if final_temp and final_temp.exists():
                    shutil.move(str(final_temp), str(final_output))
                    logger.success(f"✅ DONE: {final_output.name}")
                
                # Move video gốc sang done
                self.cfg.pipeline.done.mkdir(parents=True, exist_ok=True)
                shutil.move(str(video_path), str(self.cfg.pipeline.done / video_path.name))
                
                # Dọn dẹp
                self._cleanup_intermediates(safe_stem, wav, sep_dir, srt_raw, srt_trans, vid_sub)
            else:
                logger.info(f"⏭️ Đã xong các bước được chọn cho: {original_stem}")

        except Exception as e:
            logger.error(f"❌ FAILED {original_stem}: {e}")
            self.cfg.pipeline.failed.mkdir(parents=True, exist_ok=True)
            if video_path.exists():
                shutil.move(str(video_path), str(self.cfg.pipeline.failed / video_path.name))
            
        finally:
            self._report_progress(done=True, safe_stem=safe_stem)
            if safe_video_path.exists(): os.remove(safe_video_path)

    def _cleanup_intermediates(self, safe_stem, wav, sep_dir, srt_raw, srt_trans, vid_sub):
        import time, shutil
        
        # Ép Garbage Collector chạy để giải phóng các handle file còn sót trong RAM
        gc.collect() 
        time.sleep(1) # Cho hệ thống 1 giây để "thở" và đóng các stream

        def force_delete_folder(folder_path):
            if not folder_path or not Path(folder_path).exists():
                return
            
            for i in range(5): # Thử lại 5 lần
                try:
                    shutil.rmtree(folder_path)
                    logger.info(f"🧹 Đã xóa folder tạm: {folder_path.name}")
                    break
                except Exception as e:
                    if i < 4:
                        logger.warning(f"⚠️ Đang bận, thử lại xóa folder {folder_path.name} sau 1s...")
                        time.sleep(1)
                    else:
                        logger.error(f"❌ Không thể xóa folder {folder_path}: {e}")

        # Thực hiện dọn dẹp
        force_delete_folder(sep_dir)
        
        # Đối với các file đơn lẻ, dùng unlink với missing_ok
        for p in [wav, srt_raw, srt_trans, vid_sub]:
            if p and Path(p).exists():
                try: Path(p).unlink(missing_ok=True)
                except: pass

    def run(self, on_progress=None):
        # [BYPASS BẢO MẬT]
        # if not is_session_valid(): os._exit(0)

        input_dir = self.cfg.pipeline.input_videos
        videos = list(input_dir.glob("*.mp4"))
        if not videos:
            logger.warning(f"📭 Thư mục input trống: {input_dir}")
            return

        self._on_progress_cb = on_progress
        with self._progress_lock:
            self._progress_completed = 0
            self._progress_total = len(videos)
            self._progress_current.clear()

        logger.info(f"⚡ Pipeline khởi động: {len(videos)} videos. GPU Lock: ON")
        
        # Để test nhanh, ta chạy tuần tự từng video (max_workers=1)
        # Nếu muốn nhanh hơn trên máy mạnh, có thể nâng lên 2.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            ex.map(self.process_one, videos)

    # --- Các hàm progress giữ nguyên ---
    def _report_progress(self, step_name=None, safe_stem=None, done=False):
        if not self._on_progress_cb: return
        with self._progress_lock:
            if done and safe_stem: self._progress_current.pop(safe_stem, None); self._progress_completed += 1
            elif step_name and safe_stem: self._progress_current[safe_stem] = step_name
            cur = list(self._progress_current.values())
            self._on_progress_cb(self._progress_completed, self._progress_total, cur)

    def _report_step_ratio(self, step_name, safe_stem, ratio):
        if not self._on_progress_cb or self._progress_total <= 0: return
        with self._progress_lock:
            self._progress_current[safe_stem] = f"{step_name} {int(ratio * 100)}%"
            cur = list(self._progress_current.values())
            self._on_progress_cb(self._progress_completed + ratio, self._progress_total, cur)