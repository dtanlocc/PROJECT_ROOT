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

class Step3Config(BaseModel):
    srt_source: str = "voice"
    model_size: str = "large-v2"
    device: str = "cuda"
    language: str = "zh"
    image_frame_interval: float = 0.5
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

class Step5Config(BaseModel):
    ocr_lang: str = "ch"
    roi_y_start: float = 0.5
    roi_y_end: float = 0.9
    font_path: str = ""
    font_size: int = 18
    # Cho phép nhập List[int] hoặc String
    text_color: Union[List[int], str] = "&H00FFFFFF" 
    outline_color: Union[List[int], str] = "&H00000000"

    # --- VALIDATOR: Tự động chuyển List [r,g,b,a] sang Hex String ASS ---
    @field_validator('text_color', 'outline_color')
    @classmethod
    def convert_rgba_to_ass(cls, v: Any) -> str:
        # Nếu người dùng đã nhập string đúng chuẩn (VD: &H00FFFFFF) thì giữ nguyên
        if isinstance(v, str):
            return v
        
        # Nếu là List [R, G, B, A]
        if isinstance(v, list) and len(v) >= 3:
            r = v[0]
            g = v[1]
            b = v[2]
            # Alpha trong config: 255 là hiện rõ, 0 là trong suốt
            # Alpha trong ASS: 00 là hiện rõ, FF là trong suốt -> Cần đảo ngược
            a = v[3] if len(v) > 3 else 255 
            ass_a = 255 - a
            
            # Format ASS là &H(Alpha)(Blue)(Green)(Red) - Lưu ý thứ tự BGR
            return f"&H{ass_a:02X}{b:02X}{g:02X}{r:02X}"
            
        return "&H00FFFFFF" # Fallback màu trắng

class Step6Config(BaseModel):
    tts_lang: str = "vi"
    bg_volume: float = -12.0  # dB (VD: -12.0 = giảm 12dB)
    pitch_factor: float = 1.0  # 1.0 = giữ nguyên, 1.2 = cao hơn (như bản gốc)

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

        return GlobalConfig(**raw)