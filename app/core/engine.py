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

# --- [BỔ SUNG BẢO MẬT]: Kích hoạt Giai đoạn 4 ---
from app.core.security import is_session_valid

# --- Lỗi shm.dll (PyTorch GPU trên Windows) ---
def is_shm_dll_error(ex):
    """True nếu là lỗi WinError 127 / shm.dll khi load PyTorch."""
    if ex is None:
        return False
    msg = str(ex).lower()
    if "shm.dll" in msg or "winerror 127" in msg or "error 127" in msg:
        return True
    if getattr(ex, "winerror", None) == 127:
        return True
    return False

SHM_FIX_MESSAGE = (
    "Lỗi PyTorch GPU trên Windows (shm.dll).\n\n"
    "Cách xử lý:\n"
    "1. Đóng app, xóa thư mục venv, chạy setup_venv_cpu.bat (cài PyTorch CPU – ổn định).\n"
    "2. Hoặc cài Visual C++ Redistributable x64 rồi khởi động lại máy:\n"
    "   https://aka.ms/vs/17/release/vc_redist.x64.exe"
)

def is_meth_static_error(ex):
    """True nếu là lỗi METH_CLASS / METH_STATIC (Python vs PyTorch/NumPy không tương thích)."""
    if ex is None:
        return False
    msg = str(ex).lower()
    return "meth_class" in msg or "meth_static" in msg

METH_FIX_MESSAGE = (
    "Lỗi tương thích Python / PyTorch / NumPy (METH_CLASS hoặc METH_STATIC).\n\n"
    "Cách xử lý:\n"
    "1. Dùng Python 3.10 hoặc 3.11 (tránh 3.12+ với PyTorch 2.2.2):\n"
    "   - Xóa venv, tạo lại: py -3.11 -m venv venv (hoặc py -3.10 -m venv venv)\n"
    "   - Rồi chạy lại setup_venv.bat\n"
    "2. Trong venv thử: pip install --force-reinstall numpy\n"
    "   Sau đó chạy lại pipeline."
)

# Chỉ import step nhẹ (B1) lúc khởi tạo; B2–B6 import khi chạy (tránh torch/paddle/whisper load cùng GUI → lỗi METH_STATIC, already registered)
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
        self._progress_current = {}  # safe_stem -> "B2 Demucs"
        self._on_progress_cb = None

    def _report_progress(self, step_name: str = None, safe_stem: str = None, done: bool = False):
        """Gọi callback với (completed, total, list_current). Thread-safe."""
        if self._on_progress_cb is None:
            return
        with self._progress_lock:
            if done and safe_stem is not None:
                self._progress_current.pop(safe_stem, None)
                self._progress_completed += 1
            elif step_name and safe_stem:
                self._progress_current[safe_stem] = step_name
            cur = list(self._progress_current.values())
            self._on_progress_cb(self._progress_completed, self._progress_total, cur)

    def _report_step_ratio(self, step_name: str, safe_stem: str, ratio: float):
        """
        Gửi tiến độ chi tiết của một bước ra GUI mà không làm tăng completed.
        ratio: 0.0–1.0 cho video hiện tại.
        """
        if self._on_progress_cb is None or self._progress_total <= 0:
            return
        try:
            ratio_val = float(ratio)
        except Exception:
            return
        if ratio_val < 0.0: ratio_val = 0.0
        if ratio_val > 1.0: ratio_val = 1.0
        with self._progress_lock:
            self._progress_current[safe_stem] = f"{step_name} {int(ratio_val * 100)}%"
            cur = list(self._progress_current.values())
            effective_completed = self._progress_completed + ratio_val
            self._on_progress_cb(effective_completed, self._progress_total, cur)

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
        """Tạo tên file ngắn gọn an toàn từ tên gốc"""
        ext = Path(original_name).suffix
        safe_hash = hashlib.md5(original_name.encode('utf-8')).hexdigest()[:10]
        return f"vid_{safe_hash}{ext}"

    def process_one(self, video_path: Path):
        # [CHỐT BẢO MẬT 2]: Kiểm tra Token mỗi khi bắt đầu xử lý 1 video mới
        # Dùng lock để tránh xung đột làm hỏng Rolling Key khi chạy đa luồng
        with self._progress_lock:
            if not is_session_valid():
                logger.error("Phát hiện môi trường không an toàn. Đang đóng băng hệ thống!")
                os._exit(0) # Tắt nguồn toàn bộ tiến trình ngay lập tức

        original_stem = video_path.stem
        safe_filename = self._get_safe_name(video_path.name)
        
        work_dir = self.cfg.pipeline.workspace_root / "processing"
        work_dir.mkdir(parents=True, exist_ok=True)
        safe_video_path = work_dir / safe_filename
        safe_stem = safe_video_path.stem
        
        try:
            logger.info(f"🚀 Processing: {original_stem} (SafeID: {safe_filename})")
            
            if not safe_video_path.exists():
                shutil.copy2(str(video_path), str(safe_video_path))

            # --- PIPELINE ---
            self._report_progress("B1 Normalize", safe_stem)
            wav = self.s1.process(safe_video_path)
            
            self._report_progress("B2 Demucs", safe_stem)
            with self.gpu_lock:
                # [CHỐT BẢO MẬT 3]: Kiểm tra ngay trước khi load model AI nặng
                if not is_session_valid(): os._exit(0)
                sep_dir = self._get_s2().process(wav)
            vocals = sep_dir / "vocals.wav"
            bg_music = sep_dir / "no_vocals.wav"
            
            self._report_progress("B3 Transcribe", safe_stem)
            input_s3 = safe_video_path if self.cfg.step3.srt_source == "image" else sep_dir

            def _b3_progress(ratio: float):
                try: self._report_step_ratio("B3 Transcribe", safe_stem, ratio)
                except Exception: pass

            with self.gpu_lock:
                srt_raw = self._get_s3().process(input_s3, on_progress=_b3_progress)
                
            self._report_progress("B4 Translate", safe_stem)
            srt_trans = self._get_s4().process(srt_raw)
            
            self._report_progress("B5 Overlay", safe_stem)
            vid_sub = self._get_s5().process(safe_video_path, srt_trans)
            
            self._report_progress("B6 Mix", safe_stem)
            final_temp = self._get_s6().process(vid_sub, srt_trans, bg_music)
            
            # --- KẾT THÚC ---
            self.cfg.pipeline.step6_final.mkdir(parents=True, exist_ok=True)
            final_output = self.cfg.pipeline.step6_final / f"{original_stem}.mp4"
            
            if final_temp.exists():
                shutil.move(str(final_temp), str(final_output))
                logger.success(f"✅ DONE: {final_output.name}")
            else:
                raise RuntimeError("B6 không tạo ra file output")

            self.cfg.pipeline.done.mkdir(parents=True, exist_ok=True)
            shutil.move(str(video_path), str(self.cfg.pipeline.done / video_path.name))

            self._cleanup_intermediates(safe_video_path.stem, wav, sep_dir, srt_raw, srt_trans, vid_sub)

        except Exception as e:
            logger.error(f"❌ FAILED {original_stem}: {e}")
            if is_shm_dll_error(e): logger.error(SHM_FIX_MESSAGE)
            elif is_meth_static_error(e): logger.error(METH_FIX_MESSAGE)
            self.cfg.pipeline.failed.mkdir(parents=True, exist_ok=True)
            try:
                if video_path.exists():
                    shutil.move(str(video_path), str(self.cfg.pipeline.failed / video_path.name))
            except: pass
            
        finally:
            self._report_progress(done=True, safe_stem=safe_stem)
            try:
                if safe_video_path.exists(): os.remove(safe_video_path)
            except Exception: pass

    def _cleanup_intermediates(self, safe_stem, wav_path, sep_dir, srt_raw, srt_trans, vid_sub):
        try:
            if wav_path and Path(wav_path).exists(): Path(wav_path).unlink(missing_ok=True)
        except: pass
        try:
            if sep_dir and Path(sep_dir).is_dir(): shutil.rmtree(sep_dir, ignore_errors=True)
        except: pass
        try:
            if srt_raw and Path(srt_raw).exists(): Path(srt_raw).unlink(missing_ok=True)
        except: pass
        try:
            if srt_trans and Path(srt_trans).exists(): Path(srt_trans).unlink(missing_ok=True)
        except: pass
        try:
            if vid_sub and Path(vid_sub).exists(): Path(vid_sub).unlink(missing_ok=True)
        except: pass
        try:
            step5_dir = self.cfg.pipeline.step5_video_subbed
            raw_file = step5_dir / f"raw_{safe_stem}.mp4"
            if raw_file.exists(): raw_file.unlink()
        except: pass
        gc.collect()

    def run(self, on_progress=None):
        # [CHỐT BẢO MẬT 1]: Kiểm tra ngay khi khách hàng ấn nút Bắt Đầu
        if not is_session_valid():
            logger.error("Truy cập bị từ chối!")
            os._exit(0)

        input_dir = self.cfg.pipeline.input_videos
        videos = list(input_dir.glob("*.mp4"))
        
        if not videos:
            logger.warning(f"📭 Input empty: {input_dir}")
            return

        self._on_progress_cb = on_progress
        with self._progress_lock:
            self._progress_completed = 0
            self._progress_total = len(videos)
            self._progress_current.clear()
        if on_progress:
            on_progress(0, len(videos), [])

        logger.info(f"⚡ Pipeline Queue: {len(videos)} videos")
        try:
            with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
                ex.map(self.process_one, videos)
        finally:
            work_dir = self.cfg.pipeline.workspace_root / "processing"
            if work_dir.is_dir():
                try:
                    shutil.rmtree(work_dir, ignore_errors=True)
                    logger.info("🧹 Đã xóa thư mục tạm processing/")
                except Exception as e:
                    logger.debug(f"Cleanup processing: {e}")
            gc.collect()