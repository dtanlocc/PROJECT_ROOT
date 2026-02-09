import shutil
import sys
import os
import hashlib
import subprocess
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep


def _optimize_for_whisper(src_path: Path, dest_path: Path, ffmpeg_bin: str = None) -> bool:
    """Chuyển vocals sang 16kHz mono 16-bit PCM cho Whisper – như demucs.py optimize_for_whisper."""
    try:
        from pydub import AudioSegment
        if ffmpeg_bin:
            AudioSegment.converter = ffmpeg_bin
            ffprobe = Path(ffmpeg_bin).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe")
            if ffprobe.exists():
                AudioSegment.ffprobe = str(ffprobe)
        audio = AudioSegment.from_file(str(src_path))
        audio = audio.set_frame_rate(16000).set_channels(1).set_sample_width(2)
        audio.export(str(dest_path), format="wav")
        return True
    except Exception as e:
        logger.warning(f"Optimize Whisper: {e}")
        return False


class Step2Demucs(BaseStep):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.out_dir = self.cfg.pipeline.step2_separated
        self._model = None

    def _load_model(self):
        if self._model: return self._model
        
        try:
            import torch
            import torchaudio
            import soundfile as sf
            
            # --- PATCH: Ghi đè hàm save của torchaudio bằng soundfile ---
            # Giúp tránh hoàn toàn lỗi "TorchCodec required" trên Windows
            def _manual_soundfile_save(uri, src, sample_rate, **kwargs):
                if isinstance(src, torch.Tensor):
                    src = src.detach().cpu().numpy()
                # Transpose nếu shape là (Channels, Time) -> (Time, Channels)
                if src.ndim == 2 and src.shape[0] < src.shape[1]: 
                    src = src.transpose()
                
                subtype = None
                bits = kwargs.get('bits_per_sample', 16)
                if bits == 24: subtype = 'PCM_24'
                elif bits == 32: subtype = 'FLOAT'
                
                sf.write(file=uri, data=src, samplerate=sample_rate, subtype=subtype)

            torchaudio.save = _manual_soundfile_save
            
            from demucs import separate
            self._model = separate
        except ImportError as e:
            raise RuntimeError(f"Thiếu thư viện: {e}. Chạy: pip install demucs torchaudio soundfile")
        return self._model

    def process(self, wav_path: Path):
        self.ensure_dir(self.out_dir)
        stem = wav_path.stem
        
        # Xử lý tên folder output (tránh lỗi tên quá dài)
        try:
            final_dir = self.out_dir / stem
            final_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            short_name = hashlib.md5(stem.encode('utf-8')).hexdigest()[:12]
            final_dir = self.out_dir / f"LongName_{short_name}"
            final_dir.mkdir(parents=True, exist_ok=True)

        # Resume Check
        if (final_dir / "vocals.wav").exists():
            return final_dir

        logger.info(f"🎸 [Step 2] Demucs: {stem}")
        separator = self._load_model()
        
        # --- SAFE PROCESSING (Tránh lỗi WinError 3) ---
        # 1. Tạo thư mục tạm với tên ngắn gọn
        stem_hash = hashlib.md5(stem.encode('utf-8')).hexdigest()[:10]
        # Dùng tên biến thống nhất 'safe_temp_dir'
        safe_temp_dir = self.out_dir / f"tmp_{stem_hash}" 
        safe_temp_dir.mkdir(parents=True, exist_ok=True)
        
        safe_input_wav = safe_temp_dir / "input.wav"
        
        try:
            # 2. Copy file input vào đó
            shutil.copy2(str(wav_path), str(safe_input_wav))
            
            # 3. Cấu hình & Chạy Demucs (logic demucs.py: --two-stems=vocals, --int24, --shifts=2)
            model = self.cfg.step2.model
            device = self.cfg.step2.device
            if device == "auto":
                import torch
                device = "cuda" if torch.cuda.is_available() else "cpu"

            shifts = getattr(self.cfg.step2, "shifts", 2)
            use_float32 = getattr(self.cfg.step2, "output_float32", False)
            cmd = [
                "-n", model, "-d", device,
                "-o", str(safe_temp_dir),
                "--two-stems=vocals",
                "-j", str(self.cfg.step2.jobs),
                "--shifts", str(shifts),
            ]
            if use_float32:
                cmd.append("--float32")
            else:
                cmd.append("--int24")
            cmd.append(str(safe_input_wav))

            separator.main(cmd)

            # 4. Di chuyển kết quả về đích (Demucs: temp/model/input/vocals.wav)
            demucs_out_inner = safe_temp_dir / model / "input"
            ffmpeg_bin = getattr(self.cfg, "ffmpeg_bin", None) or os.environ.get("FFMPEG_BIN")

            for track in ["vocals.wav", "no_vocals.wav"]:
                src = demucs_out_inner / track
                dst = final_dir / track
                if src.exists():
                    shutil.move(str(src), str(dst))
                else:
                    logger.warning(f"⚠️ Không thấy file {track} sau khi tách.")

            # 5. Tối ưu vocals cho Whisper (16kHz mono 16-bit) – như demucs.py restore_and_organize
            vocals_path = final_dir / "vocals.wav"
            if vocals_path.exists():
                tmp_vocals = final_dir / "vocals_tmp.wav"
                if _optimize_for_whisper(vocals_path, tmp_vocals, ffmpeg_bin):
                    shutil.move(str(tmp_vocals), str(vocals_path))
                    logger.debug("Đã tối ưu vocals 16kHz mono cho Whisper.")
                elif tmp_vocals.exists():
                    tmp_vocals.unlink(missing_ok=True)

        except Exception as e:
            if "CUDA" in str(e) or "memory" in str(e).lower():
                logger.warning("GPU OOM, đang thử lại bằng CPU...")
                # Nếu cần fallback CPU thì thêm logic ở đây
            raise e
        finally:
            # 5. Dọn dẹp file tạm (QUAN TRỌNG: Dùng đúng tên biến safe_temp_dir)
            if safe_temp_dir.exists():
                try:
                    shutil.rmtree(safe_temp_dir, ignore_errors=True)
                except: pass
        
        return final_dir