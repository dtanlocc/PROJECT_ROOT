import concurrent.futures
import threading
import shutil
import hashlib
import time
from pathlib import Path
from loguru import logger

from app.core.config_loader import ConfigLoader
from app.services.ffmpeg_manager import FFmpegManager

# Import Steps
from app.steps.s1_normalize import Step1Normalize
from app.steps.s2_demucs import Step2Demucs
from app.steps.s3_transcribe import Step3Transcribe
from app.steps.s4_translate import Step4Translate
from app.steps.s5_overlay import Step5Overlay
from app.steps.s6_mix import Step6Mix

class ProEngine:
    def __init__(self):
        self.cfg = ConfigLoader.load()
        self.ffmpeg = FFmpegManager(self.cfg.ffmpeg_bin)
        
        # Init Steps
        self.s1 = Step1Normalize(self.cfg, self.ffmpeg)
        self.s2 = Step2Demucs(self.cfg)
        self.s3 = Step3Transcribe(self.cfg)
        self.s4 = Step4Translate(self.cfg)
        self.s5 = Step5Overlay(self.cfg, self.ffmpeg)
        self.s6 = Step6Mix(self.cfg, self.ffmpeg)
        
        self.gpu_lock = threading.Semaphore(1)

    def _get_safe_name(self, original_name):
        """Tạo tên file ngắn gọn an toàn từ tên gốc"""
        ext = Path(original_name).suffix
        # Hash tên file để đảm bảo ngắn và duy nhất
        safe_hash = hashlib.md5(original_name.encode('utf-8')).hexdigest()[:10]
        return f"vid_{safe_hash}{ext}"

    def process_one(self, video_path: Path):
        original_stem = video_path.stem
        safe_filename = self._get_safe_name(video_path.name)
        
        # Tạo thư mục tạm để xử lý (workspace/processing)
        work_dir = self.cfg.pipeline.workspace_root / "processing"
        work_dir.mkdir(parents=True, exist_ok=True)
        
        # File làm việc an toàn (tên ngắn)
        safe_video_path = work_dir / safe_filename
        
        try:
            logger.info(f"🚀 Processing: {original_stem} (SafeID: {safe_filename})")
            
            # BƯỚC 0: Copy file gốc vào môi trường làm việc an toàn
            # Để tránh FFmpeg lỗi vì tên dài/ký tự lạ
            if not safe_video_path.exists():
                shutil.copy2(str(video_path), str(safe_video_path))

            # --- PIPELINE CHẠY TRÊN FILE TÊN NGẮN ---
            
            # B1: Normalize
            wav = self.s1.process(safe_video_path)
            
            # B2: Demucs (Lock GPU)
            with self.gpu_lock:
                sep_dir = self.s2.process(wav)
            vocals = sep_dir / "vocals.wav"
            bg_music = sep_dir / "no_vocals.wav"
            
            # B3: Transcribe (Lock GPU)
            # Input s3 là video ngắn (nếu image) hoặc vocals ngắn
            input_s3 = safe_video_path if self.cfg.step3.srt_source == "image" else sep_dir
            with self.gpu_lock:
                srt_raw = self.s3.process(input_s3)
                
            # B4: Translate
            srt_trans = self.s4.process(srt_raw)
            
            # B5: Overlay (FFmpeg dùng GPU)
            # Quan trọng: FFmpeg sẽ đọc sub từ file srt_trans (tên ngắn)
            # và video từ safe_video_path (tên ngắn) -> KHÔNG BAO GIỜ LỖI PATH NỮA
            vid_sub = self.s5.process(safe_video_path, srt_trans)
            
            # B6: Mix
            final_temp = self.s6.process(vid_sub, srt_trans, bg_music)
            
            # --- KẾT THÚC & TRẢ KẾT QUẢ ---
            
            # Move kết quả ra Output và đổi lại tên gốc
            self.cfg.pipeline.step6_final.mkdir(parents=True, exist_ok=True)
            final_output = self.cfg.pipeline.step6_final / f"{original_stem}.mp4"
            
            if final_temp.exists():
                shutil.move(str(final_temp), str(final_output))
                logger.success(f"✅ DONE: {final_output.name}")
            else:
                raise RuntimeError("B6 không tạo ra file output")

            # Move file gốc vào Done
            self.cfg.pipeline.done.mkdir(parents=True, exist_ok=True)
            shutil.move(str(video_path), str(self.cfg.pipeline.done / video_path.name))

        except Exception as e:
            logger.error(f"❌ FAILED {original_stem}: {e}")
            # Move file gốc vào Failed
            self.cfg.pipeline.failed.mkdir(parents=True, exist_ok=True)
            try:
                if video_path.exists():
                    shutil.move(str(video_path), str(self.cfg.pipeline.failed / video_path.name))
            except: pass
            
        finally:
            # Dọn dẹp file tạm tên ngắn
            try:
                if safe_video_path.exists(): os.remove(safe_video_path)
            except: pass

    def run(self):
        input_dir = self.cfg.pipeline.input_videos
        videos = list(input_dir.glob("*.mp4"))
        
        if not videos:
            logger.warning(f"📭 Input empty: {input_dir}")
            return

        logger.info(f"⚡ Pipeline Queue: {len(videos)} videos")
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            ex.map(self.process_one, videos)