import os
import re
import subprocess
import asyncio
import json
from pathlib import Path
import time
from gtts import gTTS
from loguru import logger
from app.core.language.registry import LanguageRegistry
from app.steps.base import BaseStep
from vietnormalizer import VietnameseNormalizer
import pysrt
from pydub import AudioSegment, silence
import random


class Step6Mix(BaseStep):
    def __init__(self, cfg, ffmpeg):
        super().__init__(cfg)
        self.ffmpeg_bin = ffmpeg.bin
        self.out_dir = Path(self.cfg.pipeline.step6_final)
        self.cache_dir = Path(self.cfg.pipeline.step6_voices_cache)

        # ==================== LANGUAGE REGISTRY ====================
        self.registry = LanguageRegistry()
        target_code = getattr(self.cfg, 'target_lang', 'vi')
        tgt = self.registry.get(target_code)

        self.target_lang = target_code                    # "vi", "en", ...
        self.qwen_language = tgt.qwen_tts                 # ngôn ngữ cho Qwen
        self.edge_voice_prefix = tgt.edge_prefix          # "vi-VN", "en-US", ...
        # ============================================================

        # ==================== CẤU HÌNH TTS ====================
        self.tts_engine = getattr(self.cfg.step6, "tts_engine", "qwen").lower()
        self.stretch_ratio = getattr(self.cfg.step6, "stretch_ratio", 1.99)
        self.pitch_factor = getattr(self.cfg.step6, "pitch_factor", 1.2)
        self.music_volume = getattr(self.cfg.step6, "music_volume", 0.35)
        self.tts_volume = getattr(self.cfg.step6, "tts_volume", 1.4)
        self.audio_mode = getattr(self.cfg.step6, "audio_mode", 1)
        self.extra_voice_volume = getattr(self.cfg.step6, "extra_voice_volume", 0.05)
        self.speed = getattr(self.cfg.step6, "speedup_when_short", 1.5)

        self.random_bgm_dir = Path(getattr(self.cfg.step6, "random_bgm_dir", "C:\\hoathinh\\tesst"))
        self.edge_voice = getattr(self.cfg.step6, "edge_voice", "vi-VN-NamMinhNeural")

        self.ensure_dir(self.out_dir)
        self.ensure_dir(self.cache_dir)
        self.random_bgm_dir.mkdir(parents=True, exist_ok=True)

        # Qwen reference audio (giữ nguyên logic cũ)
        qwen_voice_id = getattr(self.cfg.step6, "qwen_voice", "ai_vy")
        json_path = Path("gwen-tts/data/ref_info.json")
       
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    ref_info = json.load(f)
                if qwen_voice_id in ref_info:
                    voice_data = ref_info[qwen_voice_id]
                    self.ref_audio = Path("gwen-tts") / voice_data["audio_path"]
                    self.ref_text = voice_data["text"]
                else:
                    logger.warning(f"⚠️ Giọng Qwen '{qwen_voice_id}' không tồn tại. Dùng mặc định Ái Vy.")
                    self.ref_audio = Path("gwen-tts/data/ref_audio/ai_vy.wav")
                    self.ref_text = "việt nam đang kiêu hãnh bước vào kỷ nguyên vươn mình rực rỡ với khát vọng mãnh liệt, trí tuệ đổi mới và tinh thần đoàn kết đất nước, tự tin bứt phá, kiến tạo một tương lai thịnh vượng và vươn tầm quốc tế."
            except Exception:
                self.ref_audio = Path("gwen-tts/data/ref_audio/ai_vy.wav")
                self.ref_text = "việt nam đang kiêu hãnh bước vào kỷ nguyên vươn mình rực rỡ với khát vọng mãnh liệt, trí tuệ đổi mới và tinh thần đoàn kết đất nước, tự tin bứt phá, kiến tạo một tương lai thịnh vượng và vươn tầm quốc tế."
        else:
            logger.warning(f"⚠️ Không tìm thấy {json_path}. Dùng mặc định Ái Vy.")
            self.ref_audio = Path("gwen-tts/data/ref_audio/ai_vy.wav")
            self.ref_text = "việt nam đang kiêu hãnh bước vào kỷ nguyên vươn mình rực rỡ với khát vọng mãnh liệt, trí tuệ đổi mới và tinh thần đoàn kết đất nước, tự tin bứt phá, kiến tạo một tương lai thịnh vượng và vươn tầm quốc tế."

        self.normalizer = VietnameseNormalizer()

        if self.tts_engine == "qwen" and not self.ref_audio.exists():
            logger.warning(f"⚠️ Reference audio không tồn tại: {self.ref_audio}")

    # ================================================================
    #  QWEN TTS - GIỮ NGUYÊN LOGIC CODE 1
    # ================================================================
    def _normalize_text(self, text: str) -> str:
        if not text:
            return ""
        
        if self.target_lang == "vi":
            try:
                return self.normalizer.normalize(text).strip()
            except:
                pass
                
        # NẾU LÀ NGÔN NGỮ KHÁC (Nhật, Trung, Anh...): Giữ nguyên 100% bản gốc
        return text.strip()

    def _get_tts_python_path(self) -> Path:
        base = Path("venv_tts")
        if os.name == "nt":
            return base / "Scripts" / "python.exe"
        return base / "bin" / "python"

    def _run_tts_in_separate_venv(self, texts: list[str], output_dir: Path):
        tts_python = self._get_tts_python_path()
        worker_script = Path("app/steps/s6_tts_worker.py")

        if not tts_python.exists():
            raise RuntimeError(f"Không tìm thấy venv_tts: {tts_python}")

        processed_texts = [self._normalize_text(t) for t in texts]

        temp_json = output_dir / "tts_input.json"
        data = {
            "texts": processed_texts,
            "output_dir": str(output_dir),
            "ref_audio": str(self.ref_audio),
            "ref_text": self.ref_text,
            "language": self.qwen_language,
        }
        with open(temp_json, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        cmd = [str(tts_python), str(worker_script), str(temp_json)]
        logger.info(f"🎙️ [Qwen] Đang sinh {len(texts)} đoạn thoại bằng Qwen-TTS...")
        result = subprocess.run(cmd, capture_output=True, text=True, cwd=Path.cwd(), encoding="utf-8", errors="replace")

        if temp_json.exists():
            temp_json.unlink()

        if result.returncode != 0:
            logger.error(f"TTS worker failed: {result.stderr[-1000:]}")
            raise RuntimeError(f"Qwen-TTS error: {result.stderr[-800:]}")

        logger.success(f"✅ Đã sinh xong {len(texts)} đoạn TTS (Qwen)")

    def _get_dur(self, p: Path) -> float:
        """Lấy thời lượng audio bằng ffprobe - dùng cho Qwen"""
        ffprobe = self.ffmpeg_bin.replace("ffmpeg.exe", "ffprobe.exe") if os.name == "nt" \
                  else self.ffmpeg_bin.replace("ffmpeg", "ffprobe")
        try:
            res = subprocess.run([
                ffprobe, "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(p)
            ], capture_output=True, text=True, check=True)
            return float(res.stdout.strip() or 0.0)
        except:
            return 0.0

    def _process_qwen(self, video_path: Path, srt_path: Path, bg_music: Path) -> Path:
        """Luồng Qwen - giữ nguyên hoàn toàn logic code 1"""
        v_cache = self.cache_dir / video_path.stem
        v_cache.mkdir(parents=True, exist_ok=True)

        subs = pysrt.open(str(srt_path), encoding='utf-8')
        texts = [s.text for s in subs]
        self._run_tts_in_separate_venv(texts, v_cache)

        logger.info(f"🎬 [Qwen] STRICT SYNC - Stretch={self.stretch_ratio}x | "
                    f"Voice ngắn → silence, Voice dài → speedup")

        inputs = ["-i", str(video_path), "-i", str(bg_music)]
        filters = []
        current_input_idx = 2

        filters.append(f"[0:v]setpts={self.stretch_ratio}*PTS[vout]")

        bg_atempo = 1.0 / self.stretch_ratio
        filters.append(f"[1:a]atempo={bg_atempo:.5f},volume={self.music_volume}[bg]")

        mix_tags = ["[bg]"]
        
        # ================= FIX: MIX TẠP ÂM (EXTRA VOICE) CHO QWEN =================
        # if self.audio_mode == 1:
        bg_music_path = Path(bg_music)
        step2_dir = Path(self.cfg.pipeline.step2_separated)
        extra_voice_path = step2_dir / video_path.stem / "vocals.wav"
        
        if extra_voice_path.exists():
            logger.info(f"🔊 [Qwen] Tìm thấy Tạp âm gốc. Đang Mix (Vol={self.extra_voice_volume})")
            inputs.extend(["-i", str(extra_voice_path)])
            filters.append(f"[{current_input_idx}:a]atempo={bg_atempo:.5f},volume={self.extra_voice_volume}[extra]")
            mix_tags.append("[extra]")
            current_input_idx += 1
        # =========================================================================

        for i, s in enumerate(subs):
            voice_p = v_cache / f"{i:03d}.wav"
            if not voice_p.exists():
                logger.warning(f"Voice file missing: {voice_p.name}, bỏ qua")
                continue

            inputs.extend(["-i", str(voice_p)])

            target_dur = ((s.end.ordinal - s.start.ordinal) / 1000.0) * self.stretch_ratio
            orig_dur = self._get_dur(voice_p)

            if target_dur <= 0:
                target_dur = 0.6

            start_ms = int(s.start.ordinal * self.stretch_ratio)

            if orig_dur >= target_dur * 0.95:
                speed = max(self.speed, min(orig_dur / target_dur, 3.5))
                voice_filter = f"atempo={speed:.4f}"
            else:
                voice_filter = "atempo=1.0,apad=pad_dur=" + f"{target_dur - orig_dur:.3f}"

            filters.append(
                f"[{current_input_idx}:a]{voice_filter},"
                f"rubberband=pitch={self.pitch_factor},"
                f"adelay={start_ms}|{start_ms},"
                f"volume={self.tts_volume}[v{i}]"
            )
            mix_tags.append(f"[v{i}]")
            current_input_idx += 1

        filters.append(f"{''.join(mix_tags)}amix=inputs={len(mix_tags)}:normalize=0[aout]")

        out_file = self.out_dir / f"{video_path.stem}.mp4"
        filter_script = out_file.with_suffix(".filter")
        filter_script.write_text(";".join(filters), encoding="utf-8")

        cmd = [
            self.ffmpeg_bin, "-y", "-hwaccel", "cuda",
            *inputs,
            "-filter_complex_script", str(filter_script),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "22",
            "-c:a", "aac", "-b:a", "192k",
            str(out_file)
        ]

        logger.info("🚀 [Qwen] Đang render video cuối cùng...")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.success(f"✅ Hoàn thành Step 6 (Qwen): {out_file}")
            return out_file
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ FFmpeg Error:\n{e.stderr}")
            raise
        finally:
            if filter_script.exists():
                filter_script.unlink()
                
    def _clean_text(self, text: str) -> str:
        
        # Chỉ xóa dấu câu nếu là tiếng Việt (theo logic cũ của bạn)
        if self.target_lang == "vi":
            text = re.sub(r"[.,?!;:()\[\]{}]", "", text)
            
        # Với tiếng Nhật/Trung/Anh, ta GIỮ LẠI DẤU CÂU để AI biết ngắt nghỉ lấy hơi cho tự nhiên
        text = re.sub(r"\s+", " ", text).strip()
        return text
    
    def _preprocess_voices(self, voice_dir: Path, stretched_subs):
        final_dir = voice_dir / "final"
        final_dir.mkdir(parents=True, exist_ok=True)

        for idx, (_, start, end, _) in enumerate(stretched_subs):
            src = voice_dir / f"{idx:03d}.mp3"
            dst = final_dir / f"{idx:03d}.mp3"
            target_duration = end - start

            if not src.exists() or src.stat().st_size < 500:
                AudioSegment.silent(int(target_duration)).export(dst, format="mp3")
                continue

            audio = AudioSegment.from_file(src)
            orig_dur = len(audio)

            if orig_dur <= 0 or target_duration <= 0:
                AudioSegment.silent(int(target_duration)).export(dst, format="mp3")
                continue

            calculated_factor = orig_dur / target_duration
            speed_factor = max(self.speed, min(calculated_factor, 4))

            try:
                cmd = [self.ffmpeg_bin, "-y", "-i", str(src),
                       "-filter:a", f"atempo={speed_factor:.4f}", str(dst)]
                subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

                audio_sped = AudioSegment.from_file(dst)
                if len(audio_sped) < target_duration:
                    pad = target_duration - len(audio_sped)
                    (audio_sped + AudioSegment.silent(int(pad))).export(dst, format="mp3")
            except Exception as e:
                logger.warning(f"[Preprocess] idx={idx} lỗi → silent. {e}")
                AudioSegment.silent(int(target_duration)).export(dst, format="mp3")

        return final_dir
    
    def _parse_srt(self, srt_path: Path) -> list:
        """Y hệt hàm parse_srt trong code cũ"""
        with open(srt_path, "r", encoding="utf-8") as f:
            content = f.read().strip()
        blocks = re.split(r"\n\s*\n", content)
        parsed_subs = []
        for block in blocks:
            lines = block.strip().split("\n")
            if len(lines) < 3:
                continue
            try:
                idx = int(lines[0])
                times = re.findall(r"(\d+:\d+:\d+,\d+)", lines[1])
                if len(times) != 2:
                    continue
                start = self._parse_time(times[0])
                end = self._parse_time(times[1])
                text = " ".join(lines[2:]).strip()
                t = re.sub(r'[.,?!;:\s]+$', '', text)        # xóa dấu câu + khoảng trắng ở cuối
                t = re.sub(r'\s+', ' ', text).strip()
                text = self._normalize_text(text)
                text = self._clean_text(text)
                parsed_subs.append((idx, start, end, text))
            except:
                continue
        return parsed_subs

    def _parse_time(self, time_str: str) -> int:
        """Y hệt hàm parse_time trong code cũ"""
        h, m, s_ms = time_str.split(":")
        s, ms = s_ms.split(",")
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)


    def _prepare_text_for_tts(self, text: str) -> tuple[str, int]:
        """Đảm bảo logic lặp lại từ nếu câu quá ngắn giống hệt code cũ"""
        cleaned = self._clean_text(text)
        words = cleaned.split()
        wc = len(words)
        
        # Lấy cấu hình min_words từ config, mặc định là 0 như code cũ
        min_words = getattr(self.cfg.step6, "min_words_for_tts", 0)
        
        if 0 < wc < min_words:
            repeat_count = max(1, min_words // wc)
            prepared = " ".join([cleaned.strip() + '.'] * repeat_count)
            return prepared, repeat_count
        return cleaned, 1

    # ================================================================
    #  GOOGLE TTS (TRIM SILENCE & RETRY - GIỐNG CODE CŨ)
    # ================================================================
    async def gen_tts_google(self, idx: int, text: str, out_path: Path):
        def sync_generate():
            if not text.strip():
                AudioSegment.silent(duration=800).export(str(out_path), format="mp3")
                print(f"⏩ idx {idx} rỗng, tạo file im lặng.")
                return

            prepared_text, repeat_count = self._prepare_text_for_tts(text)

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    print(f"🎙️ Sinh giọng Google idx {idx} (Lần {attempt+1}): '{text[:50]}...'")
                    tts = gTTS(prepared_text, lang=self.target_lang, slow=False)
                    tts.save(out_path)

                    if repeat_count > 1:
                        full_audio = AudioSegment.from_file(out_path)
                        nonsilent = silence.detect_nonsilent(full_audio, min_silence_len=150, silence_thresh=full_audio.dBFS - 64)
                        if nonsilent:
                            first_end = nonsilent[0][1]
                            trimmed = full_audio[:first_end + 50].fade_out(20)
                        else:
                            trimmed = full_audio[:len(full_audio)//repeat_count]
                        trimmed.export(out_path, format="mp3")
                    break 

                except Exception as e:
                    err = str(e)
                    if attempt < max_retries - 1:
                        print(f"⚠️ Lỗi TTS idx {idx}, đang đợi 3s để thử lại... (Chi tiết: {err})")
                        time.sleep(3) 
                    else:
                        print(f"❌ Lỗi TTS idx {idx} sau 3 lần thử: {err}")
                        if "429" in err or "Too Many Requests" in err or "Connection" in err:
                            try:
                                import winsound
                                for _ in range(4):
                                    winsound.Beep(1500, 300)
                            except:
                                pass
                        if out_path.exists():
                            os.remove(out_path)

        await asyncio.to_thread(sync_generate)

    # ================================================================
    #  EDGE TTS (GIỐNG CODE CŨ)
    # ================================================================
    async def gen_tts_edge(self, idx: int, text: str, out_path: Path):
        if not text.strip():
            AudioSegment.silent(duration=800).export(str(out_path), format="mp3")
            return
        
        prepared_text, _ = self._prepare_text_for_tts(text)
        try:
            import edge_tts
            voice_id = getattr(self.cfg.step6, "edge_voice", None)
            communicate = edge_tts.Communicate(prepared_text, voice_id)
            await communicate.save(str(out_path))
        except Exception as e:
            print(f"Lỗi TTS: {e}")

    # ================================================================
    #  CĂN CHỈNH THỜI GIAN (FFMPEG SPEEDUP - GIỐNG CODE CŨ)
    # ================================================================
    # Đã bổ sung biến bg_music vào hàm này
    async def process_one_video(self, video_path: Path, srt_path: Path, bg_music: Path, model=None) -> Path:
        base_name = video_path.stem
        if not srt_path.exists(): raise FileNotFoundError(f"Lỗi thiếu sub: {srt_path}")
        
        final_video_path = self.out_dir / f"{base_name}.mp4"
        voice_dir = self.cache_dir / f"{base_name}_voices"
        final_voice_dir = voice_dir / "final"
        
        voice_dir.mkdir(parents=True, exist_ok=True)
        final_voice_dir.mkdir(parents=True, exist_ok=True)

        raw_subs = self._parse_srt(srt_path)
        subs = [(idx, int(s * self.stretch_ratio), int(e * self.stretch_ratio), t) for idx, s, e, t in raw_subs]

        logger.info(f"🎬 [API TTS] Xử lý video: {base_name} | STRETCH: {self.stretch_ratio}x")

        # 1. Sinh TTS
        tts_tasks = []
        for idx, start, end, text in subs:
            out_path = voice_dir / f"{idx:03d}.mp3"
            if not out_path.exists():
                if model == "google": tts_tasks.append(self.gen_tts_google(idx, text, out_path))
                elif model == "edge": tts_tasks.append(self.gen_tts_edge(idx, text, out_path))
        
        if tts_tasks: await asyncio.gather(*tts_tasks)

        # 2. Căn chỉnh Audio Pydub
        logger.info("⌛ Đang ép tốc độ Audio (Atempo)...")
        final_sub_data = []
        for idx, start, end, text in subs:
            target_dur = end - start 
            src = voice_dir / f"{idx:03d}.mp3"
            dst = final_voice_dir / f"{idx:03d}.mp3"

            if not src.exists(): raise RuntimeError(f"Thiếu file voice: {src}")
            audio = AudioSegment.from_file(src)
            orig_dur = len(audio)

            if orig_dur <= 0 or target_dur <= 0:
                AudioSegment.silent(duration=max(600, target_dur)).export(dst, format="mp3")
                final_sub_data.append((idx, start, end, text, orig_dur))
                continue

            speed_factor = max(self.speed, min(orig_dur / target_dur, 4.0))

            try:
                subprocess.run([self.ffmpeg_bin, "-y", "-i", str(src), "-filter:a", f"atempo={speed_factor:.4f}", str(dst)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                audio_sped = AudioSegment.from_file(dst)
                if len(audio_sped) < target_dur:
                    (audio_sped + AudioSegment.silent(duration=target_dur - len(audio_sped))).export(dst, format="mp3")
            except Exception as e:
                AudioSegment.silent(duration=max(600, target_dur)).export(dst, format="mp3")

            final_sub_data.append((idx, start, end, text, orig_dur))

        # 3. Mix FFmpeg
        ffmpeg_inputs = ["-i", str(video_path)]
        filter_chains = [f"[0:v]setpts={self.stretch_ratio}*PTS[vout]"]
        audio_atempo = 1.0 / self.stretch_ratio
        mix_inputs = []

        if self.audio_mode == 1:
            bg_audio_path = Path(bg_music)
            
            step2_dir = Path(self.cfg.pipeline.step2_separated)
            extra_voice_path = step2_dir / video_path.stem / "vocals.wav"
            if not extra_voice_path.exists():
                AudioSegment.silent(duration=1000).export(str(extra_voice_path), format="wav")

            ffmpeg_inputs.extend(["-i", str(bg_audio_path), "-i", str(extra_voice_path)])
            filter_chains.extend([
                f"[1:a]atempo={audio_atempo:.5f},volume={self.music_volume}[bg]",
                f"[2:a]atempo={audio_atempo:.5f},volume={self.extra_voice_volume}[extra]"
            ])
            mix_inputs = ["[bg]", "[extra]"]
            tts_start_idx = 3

        elif self.audio_mode == 2:
            # FIX LỖI CRASH Ở ĐÂY: Dùng self.random_bgm_dir.exists() thay vì self.music_volume.exists()
            if not self.random_bgm_dir.exists() or not self.random_bgm_dir.is_dir():
                raise FileNotFoundError(f"Không tìm thấy thư mục nhạc ngẫu nhiên: {self.random_bgm_dir}")
                
            bg_files = list(self.random_bgm_dir.glob("*.wav"))
            if not bg_files: raise FileNotFoundError(f"Không có file .wav nào trong: {self.random_bgm_dir}")
                
            new_bg_path = random.choice(bg_files)
            ffmpeg_inputs.extend(["-stream_loop", "-1", "-i", str(new_bg_path)])
            filter_chains.append(f"[1:a]atempo={audio_atempo:.5f},volume={self.music_volume}[bg]")
            mix_inputs.append("[bg]")
            tts_start_idx = 2

        # Gắn Voice
        for i, (idx, start, *_) in enumerate(final_sub_data):
            vpath = final_voice_dir / f"{idx:03d}.mp3"
            ffmpeg_inputs.extend(["-i", str(vpath)])
            start_ms = int(start)
            input_idx = tts_start_idx + i

            filter_chains.append(f"[{input_idx}:a]adelay={start_ms}|{start_ms}[dly{idx}]")
            filter_chains.append(f"[dly{idx}]rubberband=pitch={self.pitch_factor}[pitched_{idx}]")
            filter_chains.append(f"[pitched_{idx}]volume={self.tts_volume}[tts{idx}]")
            mix_inputs.append(f"[tts{idx}]")

        filter_chains.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0[outa]")
        
        filter_script_path = self.out_dir / f"{base_name}_filter.txt"
        with open(filter_script_path, "w", encoding="utf-8") as f:
            f.write(";".join(filter_chains))

        cmd_mix = [
            self.ffmpeg_bin, "-y", "-hwaccel", "cuda", *ffmpeg_inputs,
            "-filter_complex_script", str(filter_script_path),
            "-map", "[vout]", "-map", "[outa]",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "23", "-c:a", "aac", "-b:a", "192k", "-shortest",
            str(final_video_path)
        ]

        logger.info("🚀 [API TTS] Đang render Video cuối cùng...")
        try:
            subprocess.run(cmd_mix, check=True, stderr=subprocess.PIPE, text=True, encoding="utf-8")
            if filter_script_path.exists(): os.remove(filter_script_path)
            return final_video_path
        except subprocess.CalledProcessError as e: raise RuntimeError(f"FFmpeg Mix failed: {e.stderr}")

    # ================================================================
    #  ENTRY POINT - CHIA LUỒNG
    # ================================================================
    def process(self, video_path: Path, srt_path: Path, bg_music: Path) -> Path:
        if self.tts_engine == "qwen":
            return self._process_qwen(video_path, srt_path, bg_music)
        elif self.tts_engine in ("edge", "google"):
            # Chạy async function từ sync context
            try:
                loop = asyncio.get_event_loop()
            except RuntimeError:
                loop = asyncio.new_event_loop()
                asyncio.set_event_loop(loop)
            
            return loop.run_until_complete(
                self.process_one_video(video_path, srt_path, model=self.tts_engine, bg_music=bg_music)
            )
        else:
            raise ValueError(f"tts_engine không hợp lệ: '{self.tts_engine}'. Chọn: qwen | edge | google")