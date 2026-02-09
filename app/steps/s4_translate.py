"""
Step 4: Dịch SRT bằng Gemini API.
Logic dich_srt.py: parse_srt_blocks, chunk theo max_lines_per_chunk, xoay key (gemini_api_keys),
prompt JSON array, extract_json_array, build_srt.
"""
import re
import json
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep


def _parse_srt_blocks(raw_text: str):
    """Parse SRT linh hoạt như dich_srt.py: index, timestamp, text (list lines)."""
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
    """Ghép lại SRT từ blocks (index, timestamp, text list)."""
    out = []
    for i, b in enumerate(blocks, start=1):
        idx = b.get("index") or str(i)
        out.append(idx)
        out.append(b["timestamp"])
        out.extend(b["text"])
        out.append("")
    return "\n".join(out).strip() + "\n"


def _extract_json_array(text: str):
    """Lấy JSON array từ response (có thể bọc trong markdown/text) – như dich_srt.py."""
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

    def _translate_chunk_gemini(self, chunk_entries, key_idx_start, keys, model_name, source_lang, target_lang):
        """Dịch 1 chunk bằng Gemini, xoay key khi lỗi – như dich_srt translate_chunk."""
        import google.generativeai as genai

        original_lines = [line for e in chunk_entries for line in e["text"]]
        expected = len(original_lines)
        num_keys = len(keys)
        if num_keys == 0:
            return None, 0
        joined_lines = "\n".join(original_lines)
        key_idx = key_idx_start
        attempt = 0

        # Gợi ý tên ngôn ngữ cho prompt
        lang_hint = "Chinese" if source_lang.startswith("zh") else source_lang
        target_hint = "Vietnamese" if target_lang == "vi" else target_lang

        while attempt < num_keys:
            key = keys[key_idx]
            genai.configure(api_key=key)
            model = genai.GenerativeModel(model_name)
            prompt = f"""Translate the following {lang_hint} subtitle lines into {target_hint}.

                Requirements:
                1) Output MUST be a JSON array of strings, exactly {expected} items.
                2) Do NOT merge/split/add/remove lines.
                3) No extra text or formatting.

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
        source_lang = self.cfg.step4.source_lang or "zh-CN"
        target_lang = self.cfg.step4.target_lang or "vi"
        max_lines = getattr(self.cfg.step4, "max_lines_per_chunk", 250) or 250

        if keys:
            # --- Dịch bằng Gemini (logic dich_srt.py) ---
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
                    chunk_entries, key_idx, keys, model_name, source_lang, target_lang
                )
                if translated_lines is None:
                    logger.error(f"Không thể dịch chunk {ci}.")
                    return srt_path
                translated_all.extend(translated_lines)

            idx = 0
            for entry in entries:
                cnt = len(entry["text"])
                entry["text"] = translated_all[idx : idx + cnt]
                idx += cnt

            out_file.write_text(_build_srt(entries), encoding="utf-8")
            logger.success(f"Đã dịch xong: {out_file.name}")
            return out_file
        else:
            # --- Fallback: GoogleTranslator (khi không có gemini key) ---
            from deep_translator import GoogleTranslator
            import time

            src = "zh-CN" if source_lang.startswith("zh") else source_lang
            translator = GoogleTranslator(source=src, target=target_lang)
            texts = []
            for b in entries:
                texts.extend(b["text"])
            results = []
            for i in range(0, len(texts), 50):
                chunk = texts[i : i + 50]
                try:
                    res = translator.translate_batch(chunk)
                    results.extend(res)
                    time.sleep(0.5)
                except Exception:
                    for t in chunk:
                        try:
                            results.append(translator.translate(t))
                        except Exception:
                            results.append(t)
            idx = 0
            for entry in entries:
                n = len(entry["text"])
                entry["text"] = results[idx : idx + n] if idx + n <= len(results) else entry["text"]
                idx += n
            out_file.write_text(_build_srt(entries), encoding="utf-8")
            logger.info(f"Đã dịch (GoogleTranslator): {out_file.name}")
            return out_file
