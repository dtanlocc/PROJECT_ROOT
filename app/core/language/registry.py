from pathlib import Path
import json
from loguru import logger
import asyncio
import edge_tts
from loguru import logger
from .models import LanguageConfig

class LanguageRegistry:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self.file = Path("language_mapping.json")
        self.languages = {}
        self.load()
        self._initialized = True

    def load(self):
        """Load từ JSON, nếu không có hoặc lỗi thì tạo file mặc định"""
        if self.file.exists():
            try:
                with open(self.file, "r", encoding="utf-8") as f:
                    raw = json.load(f)
                self.languages = {
                    k: LanguageConfig(**v) 
                    for k, v in raw.get("languages", {}).items()
                }
                logger.success(f"✅ Loaded {len(self.languages)} languages from {self.file}")
                return
            except Exception as e:
                logger.error(f"❌ Lỗi đọc language_mapping.json: {e}. Sẽ tạo file mặc định.")

        # Nếu không có file hoặc lỗi → tạo file mặc định lần đầu
        logger.info("📄 language_mapping.json chưa tồn tại hoặc lỗi → Tạo file mặc định...")
        self._create_default_file()
        self.load()  # load lại sau khi tạo

    def _create_default_file(self):
        """Tạo file JSON mặc định với các ngôn ngữ phổ biến"""
        default_languages = {
            "zh": {"code": "zh", "name": "Tiếng Trung", "whisper": "zh", "paddleocr": "ch", "gemini": "zh-CN", "google_translate": "zh-CN", "qwen_tts": "Chinese", "edge_prefix": "zh-CN"},
            "ja": {"code": "ja", "name": "Tiếng Nhật", "whisper": "ja", "paddleocr": "japan", "gemini": "ja", "google_translate": "ja", "qwen_tts": "Japanese", "edge_prefix": "ja-JP"},
            "ko": {"code": "ko", "name": "Tiếng Hàn", "whisper": "ko", "paddleocr": "korean", "gemini": "ko", "google_translate": "ko", "qwen_tts": "Korean", "edge_prefix": "ko-KR"},
            "en": {"code": "en", "name": "Tiếng Anh", "whisper": "en", "paddleocr": "en", "gemini": "en", "google_translate": "en", "qwen_tts": "English", "edge_prefix": "en-US"},
            "vi": {"code": "vi", "name": "Tiếng Việt", "whisper": "vi", "paddleocr": "vi", "gemini": "vi", "google_translate": "vi", "qwen_tts": "Vietnamese", "edge_prefix": "vi-VN"},
            "th": {"code": "th", "name": "Tiếng Thái", "whisper": "th", "paddleocr": "th", "gemini": "th", "google_translate": "th", "qwen_tts": "Thai", "edge_prefix": "th-TH"},
            "id": {"code": "id", "name": "Tiếng Indonesia", "whisper": "id", "paddleocr": "id", "gemini": "id", "google_translate": "id", "qwen_tts": "Indonesian", "edge_prefix": "id-ID"},
            "fr": {"code": "fr", "name": "Tiếng Pháp", "whisper": "fr", "paddleocr": "fr", "gemini": "fr", "google_translate": "fr", "qwen_tts": "French", "edge_prefix": "fr-FR"},
            "de": {"code": "de", "name": "Tiếng Đức", "whisper": "de", "paddleocr": "de", "gemini": "de", "google_translate": "de", "qwen_tts": "German", "edge_prefix": "de-DE"},
            "ru": {"code": "ru", "name": "Tiếng Nga", "whisper": "ru", "paddleocr": "ru", "gemini": "ru", "google_translate": "ru", "qwen_tts": "Russian", "edge_prefix": "ru-RU"},
            "es": {"code": "es", "name": "Tiếng Tây Ban Nha", "whisper": "es", "paddleocr": "es", "gemini": "es", "google_translate": "es", "qwen_tts": "Spanish", "edge_prefix": "es-ES"},
            "ar": {"code": "ar", "name": "Tiếng Ả Rập", "whisper": "ar", "paddleocr": "ar", "gemini": "ar", "google_translate": "ar", "qwen_tts": "Arabic", "edge_prefix": "ar-SA"}
        }

        data = {"languages": default_languages}
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        
        logger.success(f"✅ Đã tạo file mặc định: {self.file}")

    def save(self):
        """Lưu lại khi người dùng chỉnh sửa qua GUI"""
        data = {"languages": {k: v.model_dump() for k, v in self.languages.items()}}
        with open(self.file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

    def get(self, code: str) -> LanguageConfig:
        return self.languages.get(code) or self.languages.get("vi") or list(self.languages.values())[0]

    def get_all(self):
        return [(code, cfg.name) for code, cfg in self.languages.items()]
    
async def get_edge_voices_for_language(edge_prefix: str):
    """Lấy danh sách voice của Edge TTS theo ngôn ngữ (ví dụ: 'vi-VN', 'zh-CN')"""
    try:
        all_voices = await edge_tts.list_voices()
        
        # Lọc voice theo prefix (ví dụ: vi-VN-*, zh-CN-*)
        filtered = [
            {
                "id": voice["ShortName"],
                "name": f"{voice.get('FriendlyName', voice['ShortName'])} ({voice.get('Gender', 'Unknown')})",
                "gender": voice.get("Gender", "Unknown"),
                "locale": voice["Locale"]
            }
            for voice in all_voices
            if voice["Locale"].startswith(edge_prefix)
        ]
        
        if not filtered:
            logger.warning(f"Không tìm thấy voice nào cho prefix {edge_prefix}, dùng fallback.")
            # Fallback một vài voice phổ biến
            if "vi" in edge_prefix:
                return [{"id": "vi-VN-NamMinhNeural", "name": "Nam Minh (Nam)"}, 
                        {"id": "vi-VN-HoaiMyNeural", "name": "Hoài My (Nữ)"}]
            elif "zh" in edge_prefix:
                return [{"id": "zh-CN-XiaoxiaoNeural", "name": "Tiêu Tiêu (Nữ)"}, 
                        {"id": "zh-CN-YunxiNeural", "name": "Vân Hi (Nam)"}]
            # ... thêm fallback khác nếu cần
        
        logger.success(f"✅ Tìm thấy {len(filtered)} voice cho {edge_prefix}")
        return filtered
        
    except Exception as e:
        logger.error(f"Lỗi lấy Edge voices: {e}")
        return []  # fallback rỗng hoặc hardcode tối thiểu