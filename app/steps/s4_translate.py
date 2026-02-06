import re
import time
import os
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep

class Step4Translate(BaseStep):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.out_dir = self.cfg.pipeline.step4_srt_translated

    def process(self, srt_path: Path) -> Path:
        self.ensure_dir(self.out_dir)
        out_file = self.out_dir / srt_path.name
        
        # Resume: Nếu đã dịch rồi thì bỏ qua
        if out_file.exists() and out_file.stat().st_size > 0:
            return out_file

        logger.info(f"🌐 Translating: {srt_path.name}")
        
        try:
            content = srt_path.read_text(encoding="utf-8")
        except:
            # Fallback nếu lỗi encoding
            content = srt_path.read_text(encoding="utf-8-sig", errors="ignore")

        blocks = self._parse_srt(content)
        if not blocks:
            logger.warning("Empty SRT file")
            return srt_path

        # Quyết định dùng Gemini hay Google Free dựa vào config
        api_keys = self.cfg.step4.gemini_api_keys
        if api_keys and len(api_keys) > 0:
             # Logic Gemini (Placeholder - bạn có thể paste code Gemini từ file cũ vào đây)
             # Hiện tại tôi để mặc định fallback sang Google Free cho ổn định
             translated_blocks = self._translate_google_free(blocks)
        else:
             translated_blocks = self._translate_google_free(blocks)
        
        # Ghi file
        with open(out_file, "w", encoding="utf-8") as f:
            for b in translated_blocks:
                f.write(f"{b['id']}\n{b['time']}\n{b['text']}\n\n")
        
        return out_file

    def _parse_srt(self, content):
        # Logic parse SRT chuẩn regex
        raw_blocks = re.split(r'\n\s*\n', content.strip())
        blocks = []
        for r in raw_blocks:
            lines = [l.strip() for l in r.splitlines() if l.strip()]
            if len(lines) >= 3:
                blocks.append({
                    "id": lines[0],
                    "time": lines[1],
                    "text": " ".join(lines[2:])
                })
        return blocks

    def _translate_google_free(self, blocks):
        try:
            from deep_translator import GoogleTranslator
            src = self.cfg.step4.source_lang
            tgt = self.cfg.step4.target_lang
            
            if src == "zh": src = "zh-CN"
            
            translator = GoogleTranslator(source=src, target=tgt)
            texts = [b["text"] for b in blocks]
            results = []
            
            # Batch 50 lines
            batch_size = 50
            for i in range(0, len(texts), batch_size):
                chunk = texts[i:i+batch_size]
                try:
                    res = translator.translate_batch(chunk)
                    results.extend(res)
                    time.sleep(0.5) # Tránh rate limit
                except Exception as e:
                    logger.warning(f"Batch translate failed: {e}, retry single...")
                    for t in chunk:
                        try:
                            results.append(translator.translate(t))
                            time.sleep(0.2)
                        except:
                            results.append(t)
            
            for i, b in enumerate(blocks):
                if i < len(results):
                    b["text"] = results[i]
            return blocks
            
        except ImportError:
            logger.error("Missing deep-translator library")
            return blocks