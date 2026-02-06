# -*- coding: utf-8 -*-
"""
Pipeline Reup Pro v2 - CLI.
  python run_cli.py           → chạy full pipeline
  python run_cli.py --list    → liệt kê thư mục pipeline (từ config)
"""
import sys
import os
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from loguru import logger

logger.remove()
logger.add(sys.stderr, format="<green>{time:HH:mm:ss}</green> | <level>{message}</level>")


def cmd_list(cfg):
    """In ra các thư mục pipeline (giống pipeline cũ --list)."""
    p = cfg.pipeline
    print("Thư mục pipeline (từ config):")
    for name in ["workspace_root", "input_videos", "step1_wav", "step2_separated",
                 "step3_srt_raw", "step4_srt_translated", "step5_video_subbed",
                 "step6_final", "step6_voices_cache", "done", "failed"]:
        if hasattr(p, name):
            path = getattr(p, name)
            if isinstance(path, Path):
                print(f"  {name}: {path}")


def main():
    parser = argparse.ArgumentParser(description="Pipeline Reup Pro v2 - CLI")
    parser.add_argument("--list", action="store_true", help="Liệt kê thư mục pipeline rồi thoát")
    args = parser.parse_args()

    try:
        from app.core.config_loader import ConfigLoader
        cfg = ConfigLoader.load()
    except FileNotFoundError as e:
        logger.error(str(e))
        return 1

    if args.list:
        cmd_list(cfg)
        return 0

    from app.core.engine import ProEngine
    engine = ProEngine()
    engine.run()
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
