from pathlib import Path
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

class Step1Normalize(BaseStep):
    def __init__(self, cfg, ffmpeg: FFmpegManager):
        super().__init__(cfg)
        self.ffmpeg = ffmpeg
        self.out_dir = self.cfg.pipeline.step1_wav

    def process(self, video_path: Path):
        self.ensure_dir(self.out_dir)
        out_file = self.out_dir / f"{video_path.stem}.wav"
        
        if out_file.exists() and out_file.stat().st_size > 0:
            return out_file

        # Logic từ step1_normalize_audio.py
        args = [
            "-i", str(video_path),
            "-vn", "-ac", str(self.cfg.step1.channels),
            "-ar", str(self.cfg.step1.sample_rate),
            "-acodec", "pcm_s16le",
            str(out_file)
        ]
        self.ffmpeg.run(args, use_gpu=False)
        return out_file