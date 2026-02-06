import concurrent.futures
import threading
import shutil
from pathlib import Path
from loguru import logger

from app.core.config_loader import ConfigLoader
from app.services.ffmpeg_manager import FFmpegManager

# Import TẤT CẢ Steps
from app.steps.s1_normalize import Step1Normalize
from app.steps.s2_demucs import Step2Demucs
from app.steps.s3_transcribe import Step3Transcribe
from app.steps.s4_translate import Step4Translate # <--- Đã có
from app.steps.s5_overlay import Step5Overlay
from app.steps.s6_mix import Step6Mix             # <--- Đã có

class ProEngine:
    def __init__(self):
        self.cfg = ConfigLoader.load()
        self.ffmpeg = FFmpegManager(self.cfg.ffmpeg_bin)
        
        # Init Steps (Full Pipeline)
        self.s1 = Step1Normalize(self.cfg, self.ffmpeg)
        self.s2 = Step2Demucs(self.cfg)
        self.s3 = Step3Transcribe(self.cfg)
        self.s4 = Step4Translate(self.cfg)         # <--- Uncomment
        self.s5 = Step5Overlay(self.cfg, self.ffmpeg)
        self.s6 = Step6Mix(self.cfg, self.ffmpeg)  # <--- Uncomment
        
        # GPU Semaphore: 1 task nặng (Demucs/Whisper) chạy cùng lúc
        self.gpu_lock = threading.Semaphore(1)

    def process_one(self, video_path: Path):
        try:
            stem = video_path.stem
            logger.info(f"🚀 Processing: {stem}")
            
            # B1: Chuẩn hóa Audio
            wav = self.s1.process(video_path)
            
            # B2: Tách nhạc (Cần GPU Lock)
            with self.gpu_lock:
                sep_dir = self.s2.process(wav)
            vocals = sep_dir / "vocals.wav"
            bg_music = sep_dir / "no_vocals.wav"
            
            # B3: Transcribe (Cần GPU Lock)
            input_s3 = video_path if self.cfg.step3.srt_source == "image" else sep_dir
            with self.gpu_lock:
                srt_raw = self.s3.process(input_s3)
                
            # B4: Dịch (CPU/Mạng)
            srt_trans = self.s4.process(srt_raw)
            
            # B5: Vẽ Sub (Render GPU riêng)
            # Lưu ý: s5.process tự handle GPU call trong ffmpeg_manager
            vid_sub = self.s5.process(video_path, srt_trans)
            
            # B6: Mix & Mux (CPU Pydub + FFmpeg)
            final = self.s6.process(vid_sub, srt_trans, bg_music)
            
            # Done logic
            self.cfg.pipeline.done.mkdir(exist_ok=True)
            done_path = self.cfg.pipeline.done / video_path.name
            
            # Copy file gốc vào folder done (để backup)
            shutil.move(str(video_path), str(done_path))
            
            logger.success(f"✅ Completed: {stem} -> {final.name}")
            
        except Exception as e:
            logger.exception(f"❌ Failed {video_path.name}: {e}")
            # Move to failed (Optional)
            failed_dir = self.cfg.pipeline.failed
            failed_dir.mkdir(exist_ok=True)
            try:
                shutil.move(str(video_path), str(failed_dir / video_path.name))
            except: pass

    def run(self):
        # Scan videos
        input_dir = self.cfg.pipeline.input_videos
        input_dir.mkdir(parents=True, exist_ok=True)
        videos = list(input_dir.glob("*.mp4"))
        
        if not videos:
            logger.warning(f"📭 Input empty: {input_dir}")
            return

        logger.info(f"⚡ Pipeline Pro Queue: {len(videos)} videos")
        
        # Chạy Multithread
        # 2 workers là tối ưu cho hầu hết PC (1 cái chạy GPU Demucs, 1 cái chạy CPU Mix/Download)
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
            ex.map(self.process_one, videos)