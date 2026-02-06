# -*- coding: utf-8 -*-
"""
Pipeline Reup Pro v2 - Entry point chính.
Chạy full pipeline (B1→B6) cho mọi video trong thư mục input.
"""
import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

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
