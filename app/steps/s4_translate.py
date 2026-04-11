# file: app/steps/s4_translate.py
"""
Step 4: Dịch SRT bằng Gemini API.
"""
import re
import json
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep

# ==================== THÊM IMPORT REGISTRY ====================
from app.core.language.registry import LanguageRegistry
# ============================================================


def _parse_srt_blocks(raw_text: str):
    """Parse SRT linh hoạt."""
    blocks = re.split(r"\n\s*\n", raw_text.strip(), flags=re.MULTILINE)
    parsed = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        idx = lines[0].strip()
        if len(lines) >= 2 and "-->" in lines[1]:
            timestamp = lines[1].strip()
            text_lines = lines[2:]
        elif "-->" in lines[0]:
            idx = ""
            timestamp = lines[0].strip()
            text_lines = lines[1:]
        else:
            ts_line = None
            for i, ln in enumerate(lines):
                if "-->" in ln:
                    ts_line = ln.strip()
                    ts_index = i
                    break
            if ts_line is None:
                continue
            idx = "".join(lines[:ts_index]).strip()
            timestamp = ts_line
            text_lines = lines[ts_index + 1 :]
        parsed.append({
            "index": idx,
            "timestamp": timestamp,
            "text": [t.strip() for t in text_lines if t.strip()],
        })
    return parsed


def _build_srt(blocks):
    """Ghép lại SRT từ blocks."""
    out = []
    for i, b in enumerate(blocks, start=1):
        idx = b.get("index") or str(i)
        out.append(idx)
        out.append(b["timestamp"])
        out.extend(b["text"])
        out.append("")
    return "\n".join(out).strip() + "\n"


def _extract_json_array(text: str):
    """Lấy JSON array từ response."""
    if text is None:
        return None
    txt = (text or "").strip()
    try:
        val = json.loads(txt)
        if isinstance(val, list):
            return val
    except Exception:
        pass
    start = txt.find("[")
    end = txt.rfind("]")
    if start != -1 and end != -1 and end > start:
        candidate = txt[start : end + 1].replace(""", '"').replace(""", '"').replace("'", "'")
        try:
            val = json.loads(candidate)
            if isinstance(val, list):
                return val
        except Exception:
            pass
    return None


class Step4Translate(BaseStep):
    def __init__(self, cfg):
        super().__init__(cfg)
        self.out_dir = self.cfg.pipeline.step4_srt_translated
        self.registry = LanguageRegistry()   # ← Thêm Registry

    def _translate_chunk_gemini(self, chunk_entries, key_idx_start, keys, model_name, source_lang, target_lang):
        """Dịch 1 chunk bằng Gemini."""
        import google.generativeai as genai
        original_lines = [line for e in chunk_entries for line in e["text"]]
        expected = len(original_lines)
        num_keys = len(keys)
        if num_keys == 0:
            return None, 0

        joined_lines = "\n".join(original_lines)
        key_idx = key_idx_start
        attempt = 0

        # Gợi ý tên ngôn ngữ cho prompt (cải thiện chất lượng dịch)
        lang_hint = "Chinese" if source_lang.startswith("zh") else source_lang
        target_hint = "Vietnamese" if target_lang == "vi" else target_lang

        while attempt < num_keys:
            key = keys[key_idx]
            genai.configure(api_key=key)
            model = genai.GenerativeModel(model_name)

            prompt = f"""
You are an expert subtitle translator. Translate the following {lang_hint} subtitle lines into natural, conversational {target_hint}.
Focus on the true meaning rather than translating word-for-word. Keep it concise for video subtitles.
Read the entire context to understand sentences that span across multiple lines, but strictly maintain the original line breaks.

Requirements:
1) Output MUST be a raw JSON array of strings, containing EXACTLY {expected} items.
2) Do NOT merge, split, add, or remove lines. The structure must map 1:1 with the input.
3) Output ONLY the JSON array. No explanations, no extra text.

Input lines:
{joined_lines}
"""

            try:
                resp = model.generate_content(prompt)
                if not resp or not getattr(resp, "text", None):
                    raise Exception("Empty response")

                arr = _extract_json_array(resp.text)
                if not arr or len(arr) != expected:
                    raise Exception("JSON array length mismatch")

                return [str(x).strip() for x in arr], (key_idx + 1) % num_keys

            except Exception as e:
                logger.warning(f"Chunk lỗi với key {key[:6]}...: {e}, thử key tiếp theo.")
                key_idx = (key_idx + 1) % num_keys
                attempt += 1

        return None, key_idx

    def process(self, srt_path: Path) -> Path:
        self.ensure_dir(self.out_dir)
        out_file = self.out_dir / srt_path.name
        if out_file.exists():
            return out_file

        logger.info(f"🌐 [Step 4] Translate: {srt_path.name}")

        try:
            content = srt_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"Đọc SRT: {e}")
            return srt_path

        entries = _parse_srt_blocks(content)
        if not entries:
            logger.warning("SRT không có block hợp lệ.")
            return srt_path

        keys = list(self.cfg.step4.gemini_api_keys or [])
        model_name = self.cfg.step4.model_name or "gemini-2.5-flash"

        # ==================== LẤY NGÔN NGỮ TỪ REGISTRY ====================
        source_code = getattr(self.cfg, 'source_lang', 'zh')
        target_code = getattr(self.cfg, 'target_lang', 'vi')

        src_lang = self.registry.get(source_code)
        tgt_lang = self.registry.get(target_code)

        gemini_source = src_lang.gemini
        google_source = getattr(src_lang, 'google_translate', gemini_source)
        google_target = getattr(tgt_lang, 'google_translate', target_code)                     # ← Đây là dòng quan trọng nhất

        logger.info(f"Dịch: {src_lang.name} → {tgt_lang.name} | Google: {google_source} → {google_target}")
        # =================================================================

        try:
            content = srt_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            logger.error(f"Đọc SRT thất bại: {e}")
            return srt_path

        entries = _parse_srt_blocks(content)
        if not entries:
            logger.warning("SRT không có block hợp lệ.")
            return srt_path

        keys = list(getattr(self.cfg.step4, 'gemini_api_keys', []) or [])
        model_name = getattr(self.cfg.step4, 'model_name', "gemini-2.5-flash")
        max_lines = getattr(self.cfg.step4, "max_lines_per_chunk", 250)

        if keys:
            # ===================== GEMINI =====================
            logger.info(f"Dịch bằng Gemini: {src_lang.name} → {tgt_lang.name} ({gemini_source} → {google_target})")

            # Phần chunking và dịch Gemini (giữ nguyên logic cũ của bạn)
            chunks = []
            current_chunk = []
            current_count = 0
            for entry in entries:
                line_count = len(entry["text"])
                if current_count + line_count > max_lines and current_chunk:
                    chunks.append(current_chunk)
                    current_chunk = []
                    current_count = 0
                current_chunk.append(entry)
                current_count += line_count
            if current_chunk:
                chunks.append(current_chunk)

            translated_all = []
            key_idx = 0
            for ci, chunk_entries in enumerate(chunks):
                translated_lines, key_idx = self._translate_chunk_gemini(
                    chunk_entries, key_idx, keys, model_name, gemini_source, google_target
                )
                if translated_lines is None:
                    logger.error(f"Không thể dịch chunk {ci} bằng Gemini.")
                    return srt_path
                translated_all.extend(translated_lines)

            # Gán kết quả dịch vào entries
            idx = 0
            for entry in entries:
                cnt = len(entry["text"])
                entry["text"] = translated_all[idx : idx + cnt]
                idx += cnt

            out_file.write_text(_build_srt(entries), encoding="utf-8")
            logger.success(f"✅ Đã dịch xong bằng Gemini: {out_file.name}")

        else:
            # ===================== GOOGLE TRANSLATOR =====================
            logger.info(f"Dịch bằng Google Translator: {src_lang.name} → {tgt_lang.name} "
                       f"({google_source} → {google_target})")

            from deep_translator import GoogleTranslator
            import time

            translator = GoogleTranslator(source=google_source, target=google_target)

            texts = [line for entry in entries for line in entry["text"]]

            results = []
            for i in range(0, len(texts), 50):
                chunk = texts[i:i + 50]
                try:
                    res = translator.translate_batch(chunk)
                    results.extend(res)
                    time.sleep(0.5)
                except Exception as e:
                    logger.warning(f"Google Translator lỗi: {e}")
                    for t in chunk:
                        try:
                            results.append(translator.translate(t))
                        except:
                            results.append(t)

            # Gán kết quả trở lại
            idx = 0
            for entry in entries:
                n = len(entry["text"])
                entry["text"] = results[idx : idx + n] if idx + n <= len(results) else entry["text"]
                idx += n

            out_file.write_text(_build_srt(entries), encoding="utf-8")
            logger.success(f"✅ Đã dịch xong bằng Google Translator: {out_file.name}")

        return out_file