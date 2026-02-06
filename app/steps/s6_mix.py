import os
import shutil
from pathlib import Path
from loguru import logger
from app.steps.base import BaseStep
from app.services.ffmpeg_manager import FFmpegManager

class Step6Mix(BaseStep):
    def __init__(self, cfg, ffmpeg: FFmpegManager):
        super().__init__(cfg)
        self.ffmpeg = ffmpeg
        self.out_dir = self.cfg.pipeline.step6_final
        self.cache_dir = self.cfg.pipeline.step6_voices_cache

    def process(self, video_path: Path, srt_path: Path, bg_music: Path) -> Path:
        self.ensure_dir(self.out_dir)
        self.ensure_dir(self.cache_dir)
        
        out_file = self.out_dir / f"{video_path.stem}.mp4"
        if out_file.exists(): return out_file

        logger.info(f"🎹 Mixing: {video_path.stem}")

        # Setup Pydub Environment (Cực kỳ quan trọng trên Windows)
        os.environ["FFMPEG_BINARY"] = self.ffmpeg.bin
        
        try:
            from pydub import AudioSegment
            from gtts import gTTS
            import pysrt
            
            # Chỉ định converter cho Pydub dùng đúng FFmpeg của mình
            AudioSegment.converter = self.ffmpeg.bin
            # Cố gắng tìm ffprobe cùng thư mục
            probe_path = str(Path(self.ffmpeg.bin).parent / "ffprobe.exe")
            if os.path.exists(probe_path):
                AudioSegment.ffprobe = probe_path
                
        except ImportError:
            logger.error("❌ Missing pydub/gtts/pysrt.")
            raise RuntimeError("Missing libraries for Step 6")

        # 1. Load Nhạc nền & Xử lý Volume
        try:
            bg = AudioSegment.from_file(str(bg_music))
        except:
            logger.warning("⚠️ Background music load failed, creating silence.")
            bg = AudioSegment.silent(duration=10000)

        # Giảm âm lượng nhạc nền (Ducking) theo config
        # bg_volume thường là số âm (ví dụ -12)
        bg = bg + self.cfg.step6.bg_volume

        # 2. Tạo TTS từ Subtitle
        subs = pysrt.open(str(srt_path))
        
        # Thư mục cache giọng cho video này
        voice_folder = self.cache_dir / video_path.stem
        voice_folder.mkdir(exist_ok=True)
        
        final_mix = bg
        max_duration = len(bg)

        # Duyệt qua từng câu sub
        for sub in subs:
            text = sub.text.replace("\n", " ").strip()
            if not text: continue
            
            # File tts cache: 1.mp3, 2.mp3...
            tts_file = voice_folder / f"{sub.index}.mp3"
            
            # Gọi gTTS (Google TTS)
            if not tts_file.exists():
                try:
                    tts = gTTS(text=text, lang=self.cfg.step6.tts_lang)
                    tts.save(str(tts_file))
                except Exception as e:
                    logger.warning(f"TTS Fail line {sub.index}: {e}")
                    continue
            
            # Ghép vào timeline
            try:
                seg = AudioSegment.from_file(str(tts_file))
                
                # Tính thời gian bắt đầu (ms)
                start_ms = (sub.start.hours*3600 + sub.start.minutes*60 + sub.start.seconds)*1000 + sub.start.milliseconds
                
                # Overlay giọng đọc lên nhạc nền
                final_mix = final_mix.overlay(seg, position=start_ms)
                
                # Nếu giọng đọc dài hơn nhạc nền, cập nhật max_duration
                end_ms = start_ms + len(seg)
                if end_ms > max_duration:
                    max_duration = end_ms
            except Exception as e:
                pass

        # 3. Kéo dài nhạc nền nếu thiếu (nối thêm silence)
        if max_duration > len(final_mix):
            silence = AudioSegment.silent(duration=(max_duration - len(final_mix)) + 500)
            final_mix = final_mix + silence

        # Xuất file Audio cuối cùng (temp)
        mix_audio_path = voice_folder / "final_mix.mp3"
        final_mix.export(str(mix_audio_path), format="mp3")

        # 4. Muxing: Ghép Video (Step 5) + Audio Mix (Step 6)
        # Dùng FFmpeg copy stream video để không render lại hình -> Tốc độ cực nhanh
        args = [
            "-i", str(video_path),        # Video Input (đã có sub từ B5)
            "-i", str(mix_audio_path),    # Audio Input (đã mix)
            "-c:v", "copy",               # Copy hình
            "-c:a", "aac", "-b:a", "192k", # Encode lại tiếng cho chuẩn
            "-map", "0:v:0",              # Lấy luồng hình từ file 0
            "-map", "1:a:0",              # Lấy luồng tiếng từ file 1
            "-shortest",                  # Cắt theo luồng ngắn nhất
            str(out_file)
        ]
        
        self.ffmpeg.run(args, use_gpu=False)
        
        # Dọn dẹp cache voice nếu cần (để tiết kiệm ổ cứng)
        # shutil.rmtree(voice_folder, ignore_errors=True)
        
        return out_file