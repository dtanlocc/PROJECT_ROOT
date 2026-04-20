# app/steps/s6_tts_worker.py
import torch
import soundfile as sf
from loguru import logger
from qwen_tts import Qwen3TTSModel # Import trực tiếp vì chung venv rồi

# Biến model global để tránh load đi load lại mỗi lần gọi câu thoại

_QWEN_MODEL = None

def run_qwen_tts_logic(texts, output_dir, ref_audio, ref_text, language="Vietnamese"):
    global _QWEN_MODEL
    output_dir.mkdir(parents=True, exist_ok=True)
    
    if _QWEN_MODEL is None:
        logger.info("🚀 Đang khởi tạo Qwen-TTS Model nội bộ...")
        _QWEN_MODEL = Qwen3TTSModel.from_pretrained(
            "g-group-ai-lab/gwen-tts-0.6B",
            device_map="cuda:0" if torch.cuda.is_available() else "cpu",
            dtype=torch.bfloat16,
        )

    for i, text in enumerate(texts):
        out_path = output_dir / f"{i:03d}.wav"

        if not text or not text.strip():
            sf.write(str(out_path), torch.zeros(16000, dtype=torch.float32).numpy(), samplerate=16000)
            logger.warning(f"idx={i:03d} → silent")
            continue

        logger.info(f"Đang sinh [{i:03d}]...")

        try:
            wavs, sr = _QWEN_MODEL.generate_voice_clone(
                text=text.strip(),
                ref_audio=str(ref_audio),
                ref_text=ref_text,
                language=language,
                temperature=0.35,
                top_k=25,
                top_p=0.88,
                repetition_penalty=2.0,
            )

            sf.write(str(out_path), wavs[0], samplerate=sr)
            logger.success(f"✅ [{i:03d}] hoàn thành ({len(wavs[0])/sr:.2f}s)")

        except:
            pass
    return True