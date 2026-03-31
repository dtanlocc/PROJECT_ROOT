#file: app/steps/s1_normalize.py
import subprocess
import os
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

        video_path = Path(video_path)
        if not video_path.exists():
            raise FileNotFoundError(f"File video không tồn tại: {video_path}")
        if not Path(self.ffmpeg.bin).exists() and os.path.sep in self.ffmpeg.bin:
            raise FileNotFoundError(
                f"Không tìm thấy FFmpeg tại: {self.ffmpeg.bin}. "
                "Vào Cấu hình > Hệ thống sửa đường dẫn FFmpeg hoặc cài FFmpeg và thêm vào PATH."
            )

        logger.info(f"🔊 [Step 1] Normalize: {video_path.name}")
        
        sr = self.cfg.step1.sample_rate
        channels = self.cfg.step1.channels

        cmd = [
            self.ffmpeg.bin, "-y", 
            "-i", str(video_path),
            "-vn", 
            "-ac", str(channels), 
            "-ar", str(sr),
            "-acodec", "pcm_s16le", 
            str(out_path)
        ]
        
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)
        except FileNotFoundError:
            raise FileNotFoundError(
                "Không tìm thấy FFmpeg. Vào Cấu hình > Hệ thống đặt đường dẫn tới ffmpeg.exe hoặc thêm FFmpeg vào PATH."
            )
        except OSError as e:
            if getattr(e, "winerror", None) == 2:
                raise FileNotFoundError(
                    "Hệ thống không tìm thấy FFmpeg (WinError 2). "
                    "Kiểm tra đường dẫn FFmpeg trong Cấu hình > Hệ thống hoặc cài FFmpeg và thêm vào PATH."
                ) from e
            raise
        return out_path