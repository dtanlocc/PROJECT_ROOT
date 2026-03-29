import os
import yaml
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union, Any

# Định nghĩa các Model dữ liệu (Validation)
class Step1Config(BaseModel):
    sample_rate: int = 16000
    channels: int = 1

class Step2Config(BaseModel):
    model: str = "htdemucs"
    device: str = "auto"
    jobs: int = 1
    two_stems: bool = True
    shifts: int = 2  # Số lần shift tách (như demucs.py --shifts=2, tăng chất lượng)
    output_float32: bool = False  # False = --int24 (như demucs.py), True = --float32

class Step3Config(BaseModel):
    srt_source: str = "voice"
    model_size: str = "large-v2"
    device: str = "cuda"
    language: str = "zh"
    cpu_threads: int = 1  # Whisper CPU threads (như voice-to-srt NB_THREADS)
    image_frame_interval: float = 0.5  # Fallback khi image_step_frames <= 0
    image_step_frames: int = 10  # Cứ N frame lấy 1 lần (như img-to-srt STEP_FRAME)
    image_ocr_lang: str = "ch"
    image_use_gpu: bool = True
    similarity_threshold: float = 0.7
    image_min_duration_ms: int = 300
    image_confidence_threshold: float = 0.5

class Step4Config(BaseModel):
    model_name: str = "gemini-2.5-flash"
    source_lang: str = "zh-CN"
    target_lang: str = "vi"
    gemini_api_keys: List[str] = []
    max_lines_per_chunk: int = 250  # Chunk theo số dòng (như dich_srt MAX_LINES_PER_CHUNK)

class Step5Config(BaseModel):
    ocr_lang: str = "ch"
    roi_y_start: float = 0.5
    roi_y_end: float = 0.9
    font_path: str = ""
    font_size: int = 45  # Target size như che_sub-B5 (chỉ thu nhỏ khi tràn)
    max_words_per_line: int = 10  # Số từ tối đa mỗi dòng (cố định kích thước hiển thị)
    # Cho phép nhập List [R,G,B,A] hoặc chuỗi ASS &HAABBGGRR. Mặc định: vàng chữ, đen viền.
    text_color: Union[List[int], str] = [255, 255, 0, 255]
    outline_color: Union[List[int], str] = [0, 0, 0, 255]

    # --- VALIDATOR: Tự động chuyển List [r,g,b,a] sang Hex String ASS (lưu nội bộ) ---
    @field_validator('text_color', 'outline_color')
    @classmethod
    def convert_rgba_to_ass(cls, v: Any) -> str:
        if isinstance(v, str) and str(v).strip().upper().startswith("&H"):
            return v
        if isinstance(v, list) and len(v) >= 3:
            r, g, b = v[0], v[1], v[2]
            a = v[3] if len(v) > 3 else 255
            ass_a = 255 - a
            return f"&H{ass_a:02X}{b:02X}{g:02X}{r:02X}"
        return "&H0000FFFF"  # Fallback vàng (R255 G255 B0)

class Step6Config(BaseModel):
    tts_lang: str = "vi"
    bg_volume: float = -12.0  # dB (VD: -12.0 = giảm 12dB)
    pitch_factor: float = 1.0  # 1.0 = giữ nguyên, 1.2 = cao hơn (như text-to-voice)
    tts_volume: float = 1.4  # Âm lượng TTS khi mix (như text-to-voice TTS_VOLUME)
    min_words_for_tts: int = 0  # 0 = tắt; nếu > 0 và câu ít từ thì lặp text cho TTS rồi cắt lại
    speedup_when_short: float = 1.5  # Khi TTS ngắn hơn slot: speed up rồi pad (như text-to-voice)
    
    original_voice_volume: float = 0.2

class PipelineConfig(BaseModel):
    workspace_root: Path = Path(".")
    input_videos: Path = Path("input")
    step1_wav: Path = Path("workspace/01_wav")
    step2_separated: Path = Path("workspace/02_separated")
    step3_srt_raw: Path = Path("workspace/03_srt_raw")
    step4_srt_translated: Path = Path("workspace/04_srt_translated")
    step5_video_subbed: Path = Path("workspace/05_video_subbed")
    step6_final: Path = Path("output")
    step6_voices_cache: Path = Path("workspace/06_voices")
    done: Path = Path("done")
    failed: Path = Path("failed")

class GlobalConfig(BaseModel):
    pipeline: PipelineConfig
    ffmpeg_bin: Optional[str] = None
    step1: Step1Config
    step2: Step2Config
    step3: Step3Config
    step4: Step4Config
    step5: Step5Config
    step6: Step6Config

# Singleton Config Loader
class ConfigLoader:
    _instance = None

    # File lưu lựa chọn khi cài: cpu | gpu | both (do setup_venv*.bat ghi)
    INSTALL_MODE_FILE = "install_mode.txt"

    @classmethod
    def _resolve_config_path(cls, config_path: str) -> Path:
        """Tìm file config: ưu tiên config_path, không có thì dùng config.dist.yaml."""
        p = Path(config_path)
        if p.exists():
            return p
        dist = Path("config.dist.yaml")
        if dist.exists():
            return dist
        return p

    @classmethod
    def get_install_mode(cls, config_path: str = "config.yaml") -> str:
        """
        Đọc chế độ cài đặt từ install_mode.txt (do setup chọn CPU/GPU/Cả hai).
        Trả về: "cpu" | "gpu" | "both". Mặc định "both" nếu không có file.
        """
        resolved = cls._resolve_config_path(config_path)
        mode_file = resolved.parent / cls.INSTALL_MODE_FILE
        if not mode_file.exists():
            return "both"
        try:
            raw = mode_file.read_text(encoding="utf-8").strip().lower()
            if raw in ("cpu", "gpu", "both"):
                return raw
        except Exception:
            pass
        return "both"

    @classmethod
    def load(cls, config_path="config.yaml") -> GlobalConfig:
        resolved = cls._resolve_config_path(config_path)
        if not resolved.exists():
            raise FileNotFoundError(
                "config.yaml không tồn tại. Copy config.dist.yaml thành config.yaml và sửa cấu hình."
            )
        with open(resolved, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        from dotenv import load_dotenv
        load_dotenv()
        
        env_keys = os.getenv("GEMINI_API_KEYS")
        if env_keys:
            if "step4" not in raw: raw["step4"] = {}
            raw["step4"]["gemini_api_keys"] = [k.strip() for k in env_keys.split(",") if k.strip()]

        ffmpeg_env = os.getenv("FFMPEG_BIN")
        if ffmpeg_env:
            raw["ffmpeg_bin"] = ffmpeg_env

        cfg = GlobalConfig(**raw)

        # Áp dụng chế độ cài đặt: nếu chọn "cpu" thì ép mọi bước dùng CPU
        install_mode = cls.get_install_mode(config_path)
        if install_mode == "cpu":
            if "step2" not in raw:
                raw["step2"] = {}
            raw["step2"]["device"] = "cpu"
            cfg.step2.device = "cpu"
            if "step3" not in raw:
                raw["step3"] = {}
            raw["step3"]["device"] = "cpu"
            raw["step3"]["image_use_gpu"] = False
            cfg.step3.device = "cpu"
            cfg.step3.image_use_gpu = False

        return cfg