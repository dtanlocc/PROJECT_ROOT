import os
import shutil
import subprocess
from loguru import logger
from pathlib import Path

class FFmpegManager:
    def __init__(self, bin_path: str = None):
        self.bin = None
        
        # 1. Check biến môi trường FORCE CPU (từ run_gui.py)
        self.force_cpu = os.environ.get("PIPELINE_FORCE_CPU") == "1"
        
        # 2. Resolve Binary Path (ưu tiên path tồn tại, fallback which)
        candidates = []
        if bin_path and str(bin_path).strip():
            candidates.append(str(bin_path).strip())
        env_bin = os.environ.get("FFMPEG_BIN")
        if env_bin and env_bin.strip():
            candidates.append(env_bin.strip())
        candidates.append("ffmpeg")  # để which() tìm trong PATH
        
        for c in candidates:
            if c == "ffmpeg":
                resolved = shutil.which("ffmpeg")
                if resolved:
                    self.bin = resolved
                    break
            else:
                p = Path(c)
                if p.is_file():
                    self.bin = str(p.resolve())
                    break
                if p.exists() and p.is_dir():
                    for exe in ("ffmpeg.exe", "ffmpeg"):
                        full = p / exe
                        if full.is_file():
                            self.bin = str(full.resolve())
                            break
                    if self.bin:
                        break
            
        if not self.bin:
            logger.error("❌ FFmpeg not found! Đặt đường dẫn trong Cấu hình (Hệ thống) hoặc thêm ffmpeg vào PATH.")
            raise RuntimeError("FFmpeg missing")
            
        self._hw_accel_args = self._detect_hardware()

    def _detect_hardware(self):
        """Logic thông minh: Detect NVENC/QSV nhưng tôn trọng cờ Force CPU"""
        if self.force_cpu:
            logger.info("⚠️ FORCE CPU MODE ACTIVE")
            return ["-c:v", "libx264", "-preset", "ultrafast"]

        try:
            cmd = [self.bin, "-encoders"]
            res = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
            
            if "h264_nvenc" in res.stdout:
                logger.success("🚀 NVIDIA GPU Detected (NVENC)")
                return ["-hwaccel", "cuda", "-c:v", "h264_nvenc"]
            if "h264_qsv" in res.stdout:
                logger.success("🚀 Intel GPU Detected (QSV)")
                return ["-c:v", "h264_qsv"]
        except:
            pass
            
        return ["-c:v", "libx264", "-preset", "medium"]

    def run(self, args, use_gpu=False):
        cmd = [self.bin, "-y"]
        # Chỉ inject HW Accel nếu task đó cần GPU (như render video step 5)
        if use_gpu:
            cmd.extend(self._hw_accel_args)
        cmd.extend(args)
        
        # Suppress log để không rác console
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, check=True)