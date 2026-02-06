import os
import yaml
from pathlib import Path
from pydantic import BaseModel, Field
from typing import List, Optional

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
    srt_source: str = "voice" # voice | image
    model_size: str = "large-v2"
    device: str = "cuda"
    language: str = "zh"
    # Config cho Image OCR
    image_frame_interval: float = 0.5
    image_ocr_lang: str = "ch"
    image_use_gpu: bool = True
    similarity_threshold: float = 0.7

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
    text_color: str = "&H00FFFFFF" # Style ASS
    outline_color: str = "&H00000000"

class Step6Config(BaseModel):
    tts_lang: str = "vi"
    bg_volume: float = -12.0

class PipelineConfig(BaseModel):
    workspace_root: Path = Path(".")
    input_videos: Path = Path("input")
    # Các path output
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
    def load(cls, config_path="config.yaml") -> GlobalConfig:
        if not Path(config_path).exists():
            raise FileNotFoundError("config.yaml missing!")
            
        with open(config_path, "r", encoding="utf-8") as f:
            raw = yaml.safe_load(f)

        # Map dữ liệu từ config cũ của bạn sang cấu trúc mới
        # Xử lý .env (API Keys, FFmpeg path)
        from dotenv import load_dotenv
        load_dotenv()
        
        # Inject API Keys từ env vào config nếu có
        env_keys = os.getenv("GEMINI_API_KEYS")
        if env_keys:
            if "step4" not in raw: raw["step4"] = {}
            raw["step4"]["gemini_api_keys"] = [k.strip() for k in env_keys.split(",") if k.strip()]

        ffmpeg_env = os.getenv("FFMPEG_BIN")
        if ffmpeg_env:
            raw["ffmpeg_bin"] = ffmpeg_env

        return GlobalConfig(**raw)