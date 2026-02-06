import re
import time
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
        if out_file.exists(): return out_file

        logger.info(f"🌐 [Step 4] Translate: {srt_path.name}")
        content = srt_path.read_text(encoding="utf-8", errors="ignore")
        
        # Regex split block (Logic cũ)
        raw_blocks = re.split(r'\n\s*\n', content.strip())
        blocks = []
        for r in raw_blocks:
            lines = [l.strip() for l in r.splitlines() if l.strip()]
            if len(lines) >= 3:
                blocks.append({"id": lines[0], "time": lines[1], "text": " ".join(lines[2:])})
        
        if not blocks: return srt_path

        # Translate Logic
        try:
            from deep_translator import GoogleTranslator
            src = self.cfg.step4.source_lang
            if src == "zh": src = "zh-CN"
            translator = GoogleTranslator(source=src, target=self.cfg.step4.target_lang)
            
            texts = [b["text"] for b in blocks]
            results = []
            
            # Batch 50 (Logic cũ)
            for i in range(0, len(texts), 50):
                chunk = texts[i:i+50]
                try:
                    res = translator.translate_batch(chunk)
                    results.extend(res)
                    time.sleep(0.5)
                except:
                    # Fallback single
                    for t in chunk:
                        try: results.append(translator.translate(t))
                        except: results.append(t)
            
            for i, b in enumerate(blocks):
                if i < len(results): b["text"] = results[i]
                
        except Exception as e:
            logger.error(f"Translate fail: {e}")
            return srt_path # Trả về gốc nếu lỗi

        with open(out_file, "w", encoding="utf-8") as f:
            for b in blocks:
                f.write(f"{b['id']}\n{b['time']}\n{b['text']}\n\n")
        return out_file