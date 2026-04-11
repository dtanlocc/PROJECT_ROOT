# file: app/core/config_loader.py
import os
from loguru import logger
import yaml
from pathlib import Path
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Union, Any

# ====================== STEP CONFIGS ======================
class Step1Config(BaseModel):
    sample_rate: int = 16000
    channels: int = 1


class Step2Config(BaseModel):
    model: str = "htdemucs"
    device: str = "auto"
    jobs: int = 1
    two_stems: bool = True
    shifts: int = 2
    output_float32: bool = False


class Step3Config(BaseModel):
    srt_source: str = "voice"
    model_size: str = "large-v2"
    device: str = "cuda"
    language: str = "zh"                    # Whisper language
    cpu_threads: int = 1
    image_frame_interval: float = 0.5
    image_step_frames: int = 10
    image_ocr_lang: str = "ch"              # PaddleOCR language
    image_use_gpu: bool = True
    similarity_threshold: float = 0.65
    image_min_duration_ms: int = 350
    image_confidence_threshold: float = 0.5


class Step4Config(BaseModel):
    model_name: str = "gemini-2.5-flash"
    source_lang: str             # Gemini code
    target_lang: str
    gemini_api_keys: List[str] = Field(default_factory=list)
    max_lines_per_chunk: int = 250


class Step5Config(BaseModel):
    ocr_lang: str = "ch"
    roi_y_start: float = 0.5
    roi_y_end: float = 0.9
    font_path: str = ""
    font_size: int = 45
    max_words_per_line: int = 10
    text_color: Union[List[int], str] = Field(default=[255, 255, 0, 255])
    outline_color: Union[List[int], str] = Field(default=[0, 0, 0, 255])
    pill_background_color: Union[List[int], str] = Field(default=[0, 0, 0, 200])

    @field_validator('text_color', 'outline_color', 'pill_background_color')
    @classmethod
    def convert_rgba_to_ass(cls, v: Any) -> str:
        if isinstance(v, str) and str(v).strip().upper().startswith("&H"):
            return v
        if isinstance(v, list) and len(v) >= 3:
            r, g, b = v[0], v[1], v[2]
            a = v[3] if len(v) > 3 else 255
            ass_a = 255 - a
            return f"&H{ass_a:02X}{b:02X}{g:02X}{r:02X}"
        return "&H0000FFFF"


class Step6Config(BaseModel):
    tts_engine: str = "edge"
    tts_lang: str 
    google_lang: str 
    edge_voice: str 
    qwen_voice: Optional[str] = None
    tts_volume: float = 1.4
    music_volume: float = 0.35
    extra_voice_volume: float = 0.05
    stretch_ratio: float = 1.1
    pitch_factor: float = 1.2
    audio_mode: int = 1
    random_bgm_dir: str = "bgm"
    min_words_for_tts: int = 0
    speedup_when_short: float = 1.5
    original_voice_volume: float = 0.2
    speedup_when_short: float = 2.0


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
    """Config chính - Nên để source_lang và target_lang ở đây"""
    source_lang: str = "zh"
    target_lang: str = "vi"
    language_profile: str = ""          # để tương thích cũ

    pipeline: PipelineConfig = Field(default_factory=PipelineConfig)
    ffmpeg_bin: Optional[str] = None

    step1: Step1Config = Field(default_factory=Step1Config)
    step2: Step2Config = Field(default_factory=Step2Config)
    step3: Step3Config = Field(default_factory=Step3Config)
    step4: Step4Config = Field(default_factory=Step4Config)
    step5: Step5Config = Field(default_factory=Step5Config)
    step6: Step6Config = Field(default_factory=Step6Config)


# ====================== CONFIG LOADER ======================
class ConfigLoader:
    INSTALL_MODE_FILE = "install_mode.txt"

    @classmethod
    def _resolve_config_path(cls, config_path: str = "config.yaml") -> Path:
        p = Path(config_path)
        if p.exists():
            return p
        dist = Path("config.dist.yaml")
        if dist.exists():
            return dist
        return p

    @classmethod
    def get_install_mode(cls, config_path: str = "config.yaml") -> str:
        resolved = cls._resolve_config_path(config_path)
        mode_file = resolved.parent / cls.INSTALL_MODE_FILE
        if not mode_file.exists():
            return "both"
        try:
            raw = mode_file.read_text(encoding="utf-8").strip().lower()
            return raw if raw in ("cpu", "gpu", "both") else "both"
        except:
            return "both"

    @classmethod
    def load(cls, config_path="config.yaml") -> GlobalConfig:
        resolved = cls._resolve_config_path(config_path)
        if not resolved.exists():
            raise FileNotFoundError(f"Không tìm thấy config: {resolved}")

        with open(resolved, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f) or {}

        cfg = GlobalConfig(**raw)

        # Áp dụng install_mode (CPU/GPU)
        install_mode = cls.get_install_mode(config_path)
        if install_mode == "cpu":
            cfg.step2.device = "cpu"
            cfg.step3.device = "cpu"
            cfg.step3.image_use_gpu = False

        return cfg

    @classmethod
    def save(cls, config: GlobalConfig, config_path: str = "config.yaml"):
        """Hàm lưu config an toàn"""
        try:
            data = config.model_dump(mode='python')   # Pydantic v2
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.dump(data, f, allow_unicode=True, sort_keys=False, default_flow_style=False)
            logger.success(f"✅ Đã lưu config vào: {config_path}")
            return True
        except Exception as e:
            logger.error(f"Lỗi lưu config: {e}")
            return False