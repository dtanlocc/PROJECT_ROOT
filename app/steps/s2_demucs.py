# file: app/steps/s2_demucs.py
import shutil
import os
import hashlib
import subprocess
import gc
import torch
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep

class Step2Demucs(BaseStep):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.out_dir = Path(self.cfg.pipeline.step2_separated)
        self._model = None

    def _optimize_for_whisper_ffmpeg(self, src: Path, dst: Path):
        """Dùng FFmpeg thuần để convert. Đây là bí kíp để CPU không nhảy 100%."""
        ffmpeg_bin = self.cfg.ffmpeg_bin or "ffmpeg"
        cmd = [
            ffmpeg_bin, "-y", "-i", str(src),
            "-ar", "16000", "-ac", "1", "-c:a", "pcm_s16le", str(dst)
        ]
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
            return True
        except:
            return False

    def _load_model(self):
        if self._model: return self._model
        try:
            # Ép torchaudio nhường việc lưu file cho soundfile (tránh lỗi backend)
            import torchaudio
            import soundfile as sf
            def _sf_save(uri, src, sample_rate, **kwargs):
                data = src.detach().cpu().numpy().T if isinstance(src, torch.Tensor) else src
                sf.write(uri, data, sample_rate, subtype='PCM_24' if kwargs.get('bits_per_sample') == 24 else None)
            torchaudio.save = _sf_save
            
            from demucs import separate
            self._model = separate
        except ImportError:
            raise RuntimeError("Cài đặt thiếu: pip install demucs soundfile")
        return self._model

    def process(self, wav_path: Path):
        self.ensure_dir(self.out_dir)
        stem = wav_path.stem
        final_dir = self.out_dir / stem
        final_dir.mkdir(parents=True, exist_ok=True)

        if (final_dir / "vocals.wav").exists():
            return final_dir

        separator = self._load_model()
        
        import torch
        # FORCE CHECK CUDA
        device = self.cfg.step2.device
        if device == "auto" or device == "cuda":
            if torch.cuda.is_available():
                device = "cuda"
                # Quan trọng: Ép torch sử dụng đúng card 0
                torch.cuda.set_device(0)
            else:
                device = "cpu"
        
        logger.info(f"🎸 [Step 2] Demucs khởi động: {wav_path.stem}")
        logger.info(f"💻 Chế độ xử lý: {device.upper()}") # Kiểm tra log xem nó hiện gì ở đây

        # 2. Tạo vùng làm việc an toàn
        tmp_dir = self.out_dir / f"tmp_{hashlib.md5(stem.encode()).hexdigest()[:8]}"
        tmp_dir.mkdir(parents=True, exist_ok=True)
        safe_input = tmp_dir / "input.wav"
        shutil.copy2(str(wav_path), str(safe_input))

        try:
            # 3. Cấu hình Demucs - Tắt bớt Jobs CPU nếu dùng GPU
            model = self.cfg.step2.model or "htdemucs"
            # Nếu dùng GPU, chỉ cần 1 job load dữ liệu là đủ, tránh tranh chấp CPU
            jobs = 1 if "cuda" in device else self.cfg.step2.jobs
            
            cmd = [
                "-n", model, "-d", device, "-o", str(tmp_dir),
                "--two-stems=vocals", "-j", str(jobs),
                "--int24" if not getattr(self.cfg.step2, "output_float32", False) else "--float32",
                str(safe_input)
            ]

            # CHẠY TÁCH NHẠC
            separator.main(cmd)

            # 4. Thu hoạch kết quả
            out_inner = tmp_dir / model / "input"
            for track in ["vocals.wav", "no_vocals.wav"]:
                if (out_inner / track).exists():
                    # Trước khi move vocals, tối ưu luôn cho Whisper
                    if track == "vocals.wav":
                        logger.info("⚡ Đang tối ưu Vocals cho Whisper (16kHz Mono)...")
                        self._optimize_for_whisper_ffmpeg(out_inner / track, final_dir / track)
                    else:
                        shutil.move(str(out_inner / track), str(final_dir / track))

        finally:
            # 5. GIẢI PHÓNG VRAM/RAM NGAY LẬP TỨC
            if "cuda" in device:
                torch.cuda.empty_cache()
            gc.collect()
            if tmp_dir.exists():
                shutil.rmtree(tmp_dir, ignore_errors=True)
        
        logger.success(f"✅ Đã tách xong nhạc cho: {stem}")
        return final_dir