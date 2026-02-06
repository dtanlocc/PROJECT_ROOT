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
        self.final_voice_cache = self.cache_dir.parent / "voices_final" # Cache đã chỉnh tốc độ

        # Setup Env Pydub/gTTS
        os.environ["FFMPEG_BINARY"] = self.ffmpeg_bin
        try:
            from gtts import gTTS
            from pydub import AudioSegment, silence
            AudioSegment.converter = self.ffmpeg_bin
        except ImportError:
            pass

    def _parse_srt_time(self, t_str):
        # 00:00:05,123 -> ms
        h, m, s_ms = t_str.split(":")
        s, ms = s_ms.split(",")
        return (int(h)*3600 + int(m)*60 + int(s))*1000 + int(ms)

    def _parse_srt(self, path):
        content = path.read_text(encoding="utf-8").strip()
        blocks = re.split(r"\n\s*\n", content)
        parsed = []
        for b in blocks:
            lines = b.strip().split("\n")
            if len(lines) < 3: continue
            try:
                idx = int(lines[0])
                times = re.findall(r"(\d+:\d+:\d+,\d+)", lines[1])
                start = self._parse_srt_time(times[0])
                end = self._parse_srt_time(times[1])
                text = " ".join(lines[2:]).strip()
                parsed.append((idx, start, end, text))
            except: continue
        return parsed

    async def _gen_tts(self, idx, text, out_path):
        from gtts import gTTS
        from pydub import AudioSegment
        
        def job():
            clean_text = re.sub(r"[.,?!]", "", text).strip()
            if not clean_text: return
            try:
                tts = gTTS(clean_text, lang=self.cfg.step6.tts_lang, slow=False)
                tts.save(str(out_path))
            except Exception as e:
                logger.error(f"TTS Error {idx}: {e}")

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

        # 2. Adjust Speed (Atempo) logic
        from pydub import AudioSegment
        final_sub_data = [] # List[(idx, start, end)]
        
        for idx, start, end, text in subs:
            src = voice_sub_dir / f"{idx:03d}.mp3"
            dst = final_voice_sub_dir / f"{idx:03d}.mp3"
            
            if not src.exists(): continue
            
            target_dur = end - start
            if target_dur <= 0: target_dur = 1000
            
            audio = AudioSegment.from_file(str(src))
            orig_dur = len(audio)
            
            # Logic tốc độ (Speed up nếu dài quá)
            if orig_dur > target_dur:
                speed = max(0.5, min(orig_dur / target_dur, 2.0))
                subprocess.run(
                    [self.ffmpeg_bin, "-y", "-i", str(src), "-filter:a", f"atempo={speed:.4f}", str(dst)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
                )
            else:
                shutil.copy2(str(src), str(dst)) # Giữ nguyên nếu ngắn hơn
            
            final_sub_data.append((idx, start))

        # 3. Build FFmpeg Complex Filter
        # Inputs: 0:Video, 1:BG, 2:Extra(Optional) ... TTS files
        inputs = ["-i", str(video_path), "-i", str(bg_music)]
        filter_chains = [f"[1:a]volume={self.cfg.step6.bg_volume}[bg]"] # bg_volume ở đây là float (VD: 0.3)
        mix_inputs = ["[bg]"]
        
        # Nếu có extra voice
        input_idx = 2
        if extra_voice.exists():
            inputs.extend(["-i", str(extra_voice)])
            filter_chains.append(f"[{input_idx}:a]volume=0.2[extra]")
            mix_inputs.append("[extra]")
            input_idx += 1
            
        # Thêm TTS inputs
        for idx, start in final_sub_data:
            path = final_voice_sub_dir / f"{idx:03d}.mp3"
            inputs.extend(["-i", str(path)])
            filter_chains.append(f"[{input_idx}:a]adelay={start}|{start}[tts{idx}]")
            mix_inputs.append(f"[tts{idx}]")
            input_idx += 1
            
        # Mix tất cả
        filter_chains.append(f"{''.join(mix_inputs)}amix=inputs={len(mix_inputs)}:normalize=0[mixed]")
        # Pitch (nếu cần, mặc định 1.0)
        # filter_chains.append(f"[mixed]rubberband=pitch=1.0[outa]") 
        
        full_filter = ";".join(filter_chains)
        
        cmd = [
            self.ffmpeg_bin, "-y",
            *inputs,
            "-filter_complex", full_filter,
            "-map", "0:v", "-map", "[mixed]", # Map video gốc và audio đã mix
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
            "-shortest",
            str(out_file)
        ]
        
        subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
        return out_file