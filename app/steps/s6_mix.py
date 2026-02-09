import os
import re
import asyncio
import subprocess
import shutil
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

class Step6Mix(BaseStep):
    def __init__(self, cfg, ffmpeg: FFmpegManager):
        super().__init__(cfg)
        self.ffmpeg_bin = ffmpeg.bin
        self.out_dir = self.cfg.pipeline.step6_final
        self.cache_dir = self.cfg.pipeline.step6_voices_cache
        self.final_voice_cache = self.cache_dir.parent / "voices_final"

        os.environ["FFMPEG_BINARY"] = self.ffmpeg_bin
        try:
            from pydub import AudioSegment
            AudioSegment.converter = self.ffmpeg_bin
            ffprobe = str(Path(self.ffmpeg_bin).parent / ("ffprobe.exe" if os.name == "nt" else "ffprobe"))
            if os.path.isfile(ffprobe):
                AudioSegment.ffprobe = ffprobe
        except ImportError:
            pass

    def _parse_srt_time(self, t_str):
        h, m, s_ms = t_str.split(":")
        s, ms = s_ms.split(",")
        return (int(h) * 3600 + int(m) * 60 + int(s)) * 1000 + int(ms)

    def _parse_srt(self, path):
        content = path.read_text(encoding="utf-8").strip()
        blocks = re.split(r"\n\s*\n", content)
        parsed = []
        for b in blocks:
            lines = b.strip().split("\n")
            if len(lines) < 3:
                continue
            try:
                idx = int(lines[0])
                times = re.findall(r"(\d+:\d+:\d+,\d+)", lines[1])
                if len(times) != 2:
                    continue
                start = self._parse_srt_time(times[0])
                end = self._parse_srt_time(times[1])
                text = " ".join(lines[2:]).strip()
                parsed.append((idx, start, end, text))
            except Exception:
                continue
        return parsed

    def _clean_text(self, text: str) -> str:
        """Như text-to-voice: bỏ dấu câu, chuẩn hóa khoảng trắng."""
        text = re.sub(r"[.,?!;:()\[\]{}]", "", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _prepare_text_for_tts(self, text: str):
        """Như text-to-voice: nếu ít từ hơn min_words_for_tts thì lặp text rồi trả (prepared, repeat_count)."""
        cleaned = self._clean_text(text)
        words = cleaned.split()
        wc = len(words)
        min_words = getattr(self.cfg.step6, "min_words_for_tts", 0) or 0
        if min_words > 0 and 0 < wc < min_words:
            repeat_count = max(1, min_words // wc)
            prepared = " ".join([cleaned.strip() + "."] * repeat_count)
            return prepared, repeat_count
        return cleaned, 1

    async def _gen_tts(self, idx, text, out_path):
        """Logic text-to-voice: rỗng → silent 800ms; prepare_text_for_tts; nếu repeat_count>1 thì cắt lại đoạn đầu."""
        from gtts import gTTS
        from pydub import AudioSegment, silence

        def job():
            if not (text or "").strip():
                AudioSegment.silent(duration=800).export(str(out_path), format="mp3")
                logger.debug(f"TTS idx {idx} rỗng → file im lặng.")
                return
            prepared_text, repeat_count = self._prepare_text_for_tts(text)
            try:
                tts = gTTS(prepared_text, lang=self.cfg.step6.tts_lang, slow=False)
                tts.save(str(out_path))
                if repeat_count > 1:
                    full_audio = AudioSegment.from_file(str(out_path))
                    nonsilent = silence.detect_nonsilent(
                        full_audio, min_silence_len=150, silence_thresh=full_audio.dBFS - 64
                    )
                    if nonsilent:
                        first_end = nonsilent[0][1]
                        trimmed = full_audio[: first_end + 50].fade_out(20)
                    else:
                        trimmed = full_audio[: len(full_audio) // repeat_count]
                    trimmed.export(str(out_path), format="mp3")
            except Exception as e:
                logger.error(f"TTS Error idx {idx}: {e}")
                if out_path.exists():
                    out_path.unlink(missing_ok=True)

        await asyncio.to_thread(job)

    def process(self, video_path: Path, srt_path: Path, bg_music: Path) -> Path:
        self.ensure_dir(self.out_dir)
        self.ensure_dir(self.cache_dir)
        self.ensure_dir(self.final_voice_cache)
        
        out_file = self.out_dir / f"{video_path.stem}.mp4"
        if out_file.exists(): return out_file

        logger.info(f"🎹 [Step 6] Mix & TTS: {video_path.name}")
        
        # Audio phụ (Vocals) - có thể có hoặc không
        extra_voice = bg_music.parent / "vocals.wav" # Logic mặc định của Demucs

        # 1. Parse SRT & Gen TTS
        subs = self._parse_srt(srt_path)
        voice_sub_dir = self.cache_dir / video_path.stem
        final_voice_sub_dir = self.final_voice_cache / video_path.stem
        voice_sub_dir.mkdir(exist_ok=True)
        final_voice_sub_dir.mkdir(exist_ok=True)

        # Chạy Async TTS
        async def run_all_tts():
            tasks = []
            for idx, _, _, text in subs:
                p = voice_sub_dir / f"{idx:03d}.mp3"
                if not p.exists():
                    tasks.append(self._gen_tts(idx, text, p))
            if tasks: await asyncio.gather(*tasks)
        
        try:
            asyncio.run(run_all_tts())
        except Exception as e:
            logger.error(f"Async TTS Failed: {e}")

        # 2. Căn chỉnh thời gian (logic text-to-voice: speed + pad khi ngắn)
        from pydub import AudioSegment
        final_sub_data = []
        speedup = getattr(self.cfg.step6, "speedup_when_short", 1.5)

        for idx, start, end, text in subs:
            src = voice_sub_dir / f"{idx:03d}.mp3"
            dst = final_voice_sub_dir / f"{idx:03d}.mp3"
            target_dur = end - start
            if target_dur <= 0:
                target_dur = 600

            if not src.exists() or (src.exists() and src.stat().st_size < 500):
                AudioSegment.silent(duration=max(600, target_dur)).export(str(dst), format="mp3")
                final_sub_data.append((idx, start))
                continue

            audio = AudioSegment.from_file(str(src))
            orig_dur = len(audio)
            if orig_dur <= 0:
                AudioSegment.silent(duration=max(600, target_dur)).export(str(dst), format="mp3")
                final_sub_data.append((idx, start))
                continue

            sped_dur = int(orig_dur / speedup)
            try:
                if sped_dur > target_dur:
                    speed_factor = orig_dur / target_dur
                    speed_factor = max(0.5, min(speed_factor, 2.0))
                    subprocess.run(
                        [self.ffmpeg_bin, "-y", "-i", str(src), "-filter:a", f"atempo={speed_factor:.4f}", str(dst)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
                    )
                else:
                    subprocess.run(
                        [self.ffmpeg_bin, "-y", "-i", str(src), "-filter:a", f"atempo={speedup}", str(dst)],
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True
                    )
                    audio_sped = AudioSegment.from_file(str(dst))
                    actual_dur = len(audio_sped)
                    if actual_dur < target_dur:
                        pad = target_dur - actual_dur
                        padded = audio_sped + AudioSegment.silent(duration=pad)
                        padded.export(str(dst), format="mp3")
            except Exception as e:
                logger.warning(f"Speedup idx {idx}: {e} → silent")
                AudioSegment.silent(duration=max(600, target_dur)).export(str(dst), format="mp3")

            final_sub_data.append((idx, start))

        # 3. Build FFmpeg Complex Filter
        # Inputs: 0:Video, 1:BG, 2:Extra(Optional) ... TTS files
        inputs = ["-i", str(video_path), "-i", str(bg_music)]
        filter_chains = [f"[1:a]volume={self.cfg.step6.bg_volume}dB[bg]"]
        mix_inputs = ["[bg]"]
        
        # Nếu có extra voice
        input_idx = 2
        if extra_voice.exists():
            inputs.extend(["-i", str(extra_voice)])
            filter_chains.append(f"[{input_idx}:a]volume=0.2[extra]")
            mix_inputs.append("[extra]")
            input_idx += 1
            
        # Thêm TTS inputs (như text-to-voice: adelay + volume)
        tts_vol = getattr(self.cfg.step6, "tts_volume", 1.4)
        for idx, start in final_sub_data:
            path = final_voice_sub_dir / f"{idx:03d}.mp3"
            inputs.extend(["-i", str(path)])
            filter_chains.append(f"[{input_idx}:a]adelay={start}|{start}[dly{idx}]")
            filter_chains.append(f"[dly{idx}]volume={tts_vol}[tts{idx}]")
            mix_inputs.append(f"[tts{idx}]")
            input_idx += 1
            
        # Mix tất cả
        filter_chains.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0[mixed]")
        pitch = getattr(self.cfg.step6, "pitch_factor", 1.0)
        if pitch != 1.0:
            filter_chains.append(f"[mixed]rubberband=pitch={pitch}[outa]")
            map_audio = "[outa]"
        else:
            map_audio = "[mixed]"
        full_filter = ";".join(filter_chains)

        cmd = [
            self.ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", full_filter,
            "-map", "0:v", "-map", map_audio,
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out_file)
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return out_file