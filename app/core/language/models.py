from pydantic import BaseModel

class LanguageConfig(BaseModel):
    code: str
    name: str
    whisper: str           # Step 3 Whisper
    paddleocr: str         # Step 3 OCR
    gemini: str            # Step 4 Gemini
    google_translate: str
    qwen_tts: str          # Step 6 Qwen
    edge_prefix: str       # Edge TTS