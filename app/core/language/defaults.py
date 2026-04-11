from .models import LanguageConfig

def get_default_languages():
    return {
        "zh": LanguageConfig(code="zh", name="Tiếng Trung", whisper="zh", paddleocr="ch", gemini="zh-CN", google_translate="zh-CN", qwen_tts="zh", edge_prefix="zh-CN"),
        "ja": LanguageConfig(code="ja", name="Tiếng Nhật", whisper="ja", paddleocr="japan", gemini="ja", google_translate="ja", qwen_tts="ja", edge_prefix="ja-JP"),
        "ko": LanguageConfig(code="ko", name="Tiếng Hàn", whisper="ko", paddleocr="korean", gemini="ko", google_translate="ko", qwen_tts="ko", edge_prefix="ko-KR"),
        "en": LanguageConfig(code="en", name="Tiếng Anh", whisper="en", paddleocr="en", gemini="en", google_translate="en", qwen_tts="en", edge_prefix="en-US"),
        "vi": LanguageConfig(code="vi", name="Tiếng Việt", whisper="vi", paddleocr="vi", gemini="vi", google_translate="vi", qwen_tts="vi", edge_prefix="vi-VN"),
        "th": LanguageConfig(code="th", name="Tiếng Thái", whisper="th", paddleocr="th", gemini="th", google_translate="th", qwen_tts="th", edge_prefix="th-TH"),
    }