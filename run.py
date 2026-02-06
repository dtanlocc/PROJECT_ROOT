import sys
from loguru import logger
from app.core.pipeline import VideoPipeline

# Cấu hình Log đẹp mắt
logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")
logger.add("logs/pipeline_pro.log", rotation="5 MB", level="DEBUG")

if __name__ == "__main__":
    print("==================================================")
    print("   PIPELINE REUP VIDEO - PROFESSIONAL EDITION")
    print("==================================================")
    
    try:
        app = VideoPipeline("config.yaml")
        app.run()
    except KeyboardInterrupt:
        logger.warning("🛑 Stopped by user.")
    except Exception as e:
        logger.critical(f"🔥 System Crash: {e}")
        input("Press Enter to exit...")