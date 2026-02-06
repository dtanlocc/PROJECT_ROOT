import shutil
import sys
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep

class Step2Demucs(BaseStep):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.out_dir = self.cfg.pipeline.step2_separated
        self._model = None

    def _load_model(self):
        if self._model: return self._model
        
        # --- LOGIC PATCH TỪ CODE CŨ CỦA BẠN ---
        try:
            import torchaudio
            # Patch lỗi save của torchaudio trên Windows
            if hasattr(torchaudio, "save"):
                _orig_save = torchaudio.save
                def _patch(uri, src, sample_rate, **kwargs):
                    if kwargs.get("format") is None and str(uri).lower().endswith(".wav"):
                        kwargs["format"] = "wav"
                    return _orig_save(uri, src, sample_rate, **kwargs)
                torchaudio.save = _patch
            
            from demucs import separate
            self._model = separate
        except ImportError:
            raise RuntimeError("Demucs/Torchaudio missing!")
        return self._model

    def process(self, wav_path: Path):
        self.ensure_dir(self.out_dir)
        stem = wav_path.stem
        final_dir = self.out_dir / stem
        
        # Resume Check
        if (final_dir / "vocals.wav").exists():
            return final_dir

        logger.info(f"🎸 Demucs separating: {stem}")
        separator = self._load_model()
        
        # Config
        model = self.cfg.step2.model
        device = self.cfg.step2.device
        
        # Logic xử lý device "auto"
        if device == "auto":
            import torch
            device = "cuda" if torch.cuda.is_available() else "cpu"

        temp_out = self.out_dir / f"_temp_{stem}"
        
        cmd = [
            "-n", model, "-d", device,
            "-o", str(temp_out),
            "--two-stems=vocals",
            "-j", str(self.cfg.step2.jobs),
            "--float32",
            str(wav_path)
        ]

        try:
            separator.main(cmd)
        except Exception as e:
            if device == "cuda":
                logger.warning("GPU OOM, switching to CPU for Demucs...")
                cmd[3] = "cpu"
                separator.main(cmd)
            else:
                raise e

        # Move file đúng cấu trúc
        src_path = temp_out / model / stem
        final_dir.mkdir(parents=True, exist_ok=True)
        
        shutil.move(str(src_path / "vocals.wav"), str(final_dir / "vocals.wav"))
        shutil.move(str(src_path / "no_vocals.wav"), str(final_dir / "no_vocals.wav"))
        
        # Cleanup
        shutil.rmtree(temp_out, ignore_errors=True)
        return final_dir