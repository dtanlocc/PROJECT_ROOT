import subprocess
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

class Step1Normalize(BaseStep):
    def __init__(self, cfg, ffmpeg: FFmpegManager):
        super().__init__(cfg)
        self.ffmpeg = ffmpeg
        self.out_dir = self.cfg.pipeline.step1_wav

    def process(self, video_path: Path) -> Path:
        self.ensure_dir(self.out_dir)
        out_path = self.out_dir / f"{video_path.stem}.wav"
        
        # Resume logic cũ của bạn
        if out_path.exists() and out_path.stat().st_size > 0:
            return out_path

        logger.info(f"🔊 [Step 1] Normalize: {video_path.name}")
        
        sr = self.cfg.step1.sample_rate
        channels = self.cfg.step1.channels

        # Lệnh nguyên bản từ step1_normalize_audio.py
        cmd = [
            self.ffmpeg.bin, "-y", 
            "-i", str(video_path),
            "-vn", 
            "-ac", str(channels), 
            "-ar", str(sr),
            "-acodec", "pcm_s16le", 
            str(out_path)
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        return out_path