# file: app/steps/s6_mix.py
import os
import asyncio
import subprocess
import pysrt
import edge_tts
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep

class Step6Mix(BaseStep):
    def __init__(self, cfg, ffmpeg):
        super().__init__(cfg)
        self.ffmpeg_bin = ffmpeg.bin
        self.out_dir = Path(self.cfg.pipeline.step6_final)
        self.cache_dir = Path(self.cfg.pipeline.step6_voices_cache)

    async def _gen_tts(self, text, out_path):
        """Sinh giọng đọc Edge TTS."""
        if not text.strip():
            # Tạo file im lặng 0.5s nếu text trống bằng ffmpeg
            subprocess.run([
                self.ffmpeg_bin, "-y", "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono", 
                "-t", "0.5", str(out_path)
            ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return

        voice = getattr(self.cfg.step6, "voice_name", "vi-VN-NamMinhNeural")
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(out_path))

    def _get_dur(self, p):
        """Lấy thời lượng file audio bằng ffprobe."""
        ffprobe = self.ffmpeg_bin.replace("ffmpeg.exe", "ffprobe.exe")
        try:
            res = subprocess.run([
                ffprobe, "-v", "error", "-show_entries", "format=duration", 
                "-of", "default=noprint_wrappers=1:nokey=1", str(p)
            ], capture_output=True, text=True, check=True)
            return float(res.stdout.strip()) if res.stdout.strip() else 0.0
        except:
            return 0.0

    def process(self, video_path: Path, srt_path: Path, bg_music: Path) -> Path:
        """Hàm xử lý chính điều hướng Mode 1 và Mode 2."""
        self.ensure_dir(self.out_dir)
        mode = getattr(self.cfg.step6, "audio_mode", 1)
        subs = pysrt.open(str(srt_path), encoding='utf-8')
        v_cache = self.cache_dir / video_path.stem
        v_cache.mkdir(parents=True, exist_ok=True)
        
        logger.info(f"🎙️ [Step 6] Đang sinh {len(subs)} câu thoại Edge TTS...")

        # FIX: Tạo mới một event loop cho thread hiện tại để tránh lỗi "no current event loop"
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            tasks = [self._gen_tts(s.text, v_cache / f"{i:03d}.mp3") for i, s in enumerate(subs)]
            loop.run_until_complete(asyncio.gather(*tasks))
        finally:
            loop.close()

        # Cấu hình chung
        inputs = ["-i", str(video_path), "-i", str(bg_music)]
        filters = []
        current_input_idx = 2  # 0: video subbed, 1: no_vocals.wav
        pitch = getattr(self.cfg.step6, "pitch_factor", 1.0)
        tts_vol = getattr(self.cfg.step6, "tts_volume", 1.4)
        bg_vol_db = getattr(self.cfg.step6, "bg_volume", -12.0)

        if mode == 1:
            # --- MODE 1: STRICT SRT SYNC ---
            ratio = getattr(self.cfg.step6, "stretch_ratio", 1.1)
            logger.info(f"🎬 Chế độ 1: Đồng bộ SRT (Stretch {ratio}x)")
            
            filters.append(f"[0:v]setpts={ratio}*PTS[vout]")
            filters.append(f"[1:a]atempo={1/ratio:.4f},volume={bg_vol_db}dB[bg]")
            mix_tags = ["[bg]"]

            for i, s in enumerate(subs):
                voice_p = v_cache / f"{i:03d}.mp3"
                inputs.extend(["-i", str(voice_p)])
                
                # Tính toán tốc độ ép giọng nói
                target_dur = ((s.end.ordinal - s.start.ordinal) / 1000) * ratio
                orig_dur = self._get_dur(voice_p)
                # Tốc độ ép tối thiểu 0.5x, tối đa 3.0x
                speed = max(0.5, min(orig_dur / target_dur, 3.0))
                
                start_ms = int(s.start.ordinal * ratio)
                # Filter chuỗi: Tốc độ -> Chỉnh Pitch -> Delay đúng vị trí -> Âm lượng
                filters.append(
                    f"[{current_input_idx}:a]atempo={speed:.4f},rubberband=pitch={pitch},"
                    f"adelay={start_ms}|{start_ms},volume={tts_vol}[v{i}]"
                )
                mix_tags.append(f"[v{i}]")
                current_input_idx += 1
            
            filters.append(f"{''.join(mix_tags)}amix=inputs={len(mix_tags)}:normalize=0[aout]")

        else:
            # --- MODE 2: ELASTIC (VIDEO WAITS FOR VOICE) ---
            logger.info("🎬 Chế độ 2: Video co giãn theo Voice")
            v_segs, a_tags, timeline_ms = [], ["[bg]"], 0.0
            filters.append(f"[1:a]volume={bg_vol_db}dB[bg]")
            
            for i, s in enumerate(subs):
                voice_p = v_cache / f"{i:03d}.mp3"
                v_dur_orig = (s.end.ordinal - s.start.ordinal) / 1000
                voice_dur = self._get_dur(voice_p)
                
                # Hệ số kéo giãn video đoạn này
                v_pts = max(0.5, voice_dur / v_dur_orig) if v_dur_orig > 0 else 1.0
                
                # Cắt video và giãn PTS
                filters.append(
                    f"[0:v]trim=start={s.start.ordinal/1000}:end={s.end.ordinal/1000},"
                    f"setpts={v_pts}*(PTS-STARTPTS)[vs{i}]"
                )
                v_segs.append(f"[vs{i}]")
                
                inputs.extend(["-i", str(voice_p)])
                delay_ms = int(timeline_ms)
                filters.append(
                    f"[{current_input_idx}:a]rubberband=pitch={pitch},"
                    f"adelay={delay_ms}|{delay_ms},volume={tts_vol}[as{i}]"
                )
                a_tags.append(f"[as{i}]")
                
                timeline_ms += (v_dur_orig * v_pts * 1000)
                current_input_idx += 1
                
            filters.append(f"{''.join(v_segs)}concat=n={len(v_segs)}:v=1:a=0[vout]")
            filters.append(f"{''.join(a_tags)}amix=inputs={len(a_tags)}:normalize=0[aout]")

        # --- XUẤT FILE FINAL ---
        out_file = self.out_dir / f"{video_path.stem}.mp4"
        filter_script = out_file.with_suffix(".filter")
        # Ghi filter ra file để tránh lỗi "command line too long" trên Windows
        filter_script.write_text(";".join(filters), encoding="utf-8")

        cmd = [
            self.ffmpeg_bin, "-y", "-hwaccel", "cuda",
            *inputs,
            "-filter_complex_script", str(filter_script),
            "-map", "[vout]", "-map", "[aout]",
            "-c:v", "h264_nvenc", "-preset", "p4", "-cq", "24",
            "-c:a", "aac", "-b:a", "192k",
            str(out_file)
        ]
        
        logger.info(f"🚀 [Step 6] Đang render Final Video bằng GPU NVENC...")
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True)
            if filter_script.exists():
                filter_script.unlink()
            return out_file
        except subprocess.CalledProcessError as e:
            logger.error(f"❌ FFmpeg Render Error:\n{e.stderr}")
            if filter_script.exists():
                logger.debug(f"Filter gây lỗi: {filter_script.read_text(encoding='utf-8')}")
            raise RuntimeError("FFmpeg Step 6 failed.")