# -*- coding: utf-8 -*-
"""
Pipeline Reup Pro v2 - Entry point chính.
Chạy full pipeline (B1→B6) cho mọi video trong thư mục input.
"""
import sys
import os
import warnings
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# Tắt cảnh báo Hugging Face Hub
if "HF_HUB_DISABLE_SYMLINKS_WARNING" not in os.environ:
    os.environ["HF_HUB_DISABLE_SYMLINKS_WARNING"] = "1"
warnings.filterwarnings("ignore", message=".*unauthenticated requests to the HF Hub.*", category=UserWarning)

# Ép FFmpeg dùng CPU nếu lúc cài đã chọn "Chỉ CPU"
try:
    from app.core.config_loader import ConfigLoader
    if ConfigLoader.get_install_mode() == "cpu":
        os.environ["PIPELINE_FORCE_CPU"] = "1"
except Exception:
    pass

from loguru import logger

# Log ra console + file
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
logger.add("logs/pipeline_pro.log", rotation="5 MB", level="DEBUG")

if __name__ == "__main__":
    print("==================================================")
    print("   PIPELINE REUP PRO v2.0.0")
    print("==================================================")
    try:
        from app.core.config_loader import ConfigLoader
        from app.core.engine import ProEngine
        cfg = ConfigLoader.load()
        engine = ProEngine()
        engine.run()
    except FileNotFoundError as e:
        logger.error(str(e))
        input("Nhấn Enter để thoát...")
        sys.exit(1)
    except KeyboardInterrupt:
        logger.warning("Đã dừng bởi người dùng.")
    except Exception as e:
        logger.exception("Lỗi")
        input("Nhấn Enter để thoát...")
        sys.exit(1)
