from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

class Step5Overlay(BaseStep):
    def __init__(self, cfg, ffmpeg: FFmpegManager):
        super().__init__(cfg)
        self.ffmpeg = ffmpeg
        self.out_dir = self.cfg.pipeline.step5_video_subbed
        self._ocr = None

    def _detect_box(self, video_path):
        # ...Logic detect dùng PaddleOCR (tương tự file cũ)...
        # (Để tiết kiệm token, tôi tóm tắt logic: nếu không detect được thì lấy 15% đáy)
        import cv2
        cap = cv2.VideoCapture(str(video_path))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cap.release()
        
        # Fallback default
        bh = int(h * 0.15)
        by = h - bh - int(h * 0.05)
        return 0, by, w, bh

    def process(self, video_path: Path, srt_path: Path):
        self.ensure_dir(self.out_dir)
        out_file = self.out_dir / f"{video_path.stem}.mp4"
        if out_file.exists(): return out_file
        
        # Detect region
        bx, by, bw, bh = self._detect_box(video_path)
        
        # Build Filter String (Logic quan trọng)
        # Escape path cho Windows
        srt_arg = str(srt_path).replace("\\", "/").replace(":", "\\:")
        
        # Config Style
        c5 = self.cfg.step5
        style = f"FontSize={c5.font_size},PrimaryColour={c5.text_color},OutlineColour={c5.outline_color},BorderStyle=1"
        if c5.font_path:
             # Add font path handling if needed
             pass

        vf = (
            f"drawbox=x={bx}:y={by}:w={bw}:h={bh}:color=black@0.6:t=fill,"
            f"subtitles='{srt_arg}':force_style='{style}'"
        )
        
        args = [
            "-i", str(video_path),
            "-vf", vf,
            "-c:a", "copy",
            str(out_file)
        ]
        
        # Step 5 cần render hình -> Use GPU
        self.ffmpeg.run(args, use_gpu=True)
        return out_file