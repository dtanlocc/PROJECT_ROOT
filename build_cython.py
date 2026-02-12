# build_cython.py
from setuptools import setup
from Cython.Build import cythonize
import os

# Danh sách các file cần bảo mật tuyệt đối (Logic + AI)
files_to_protect = [
    "app/core/engine.py",
    "app/core/security.py",       # File bảo mật vừa tạo
    "app/steps/s1_normalize.py",
    "app/steps/s2_demucs.py",
    "app/steps/s3_transcribe.py",
    "app/steps/s4_translate.py",
    "app/steps/s5_overlay.py",
    "app/steps/s6_mix.py",
    "app/services/ffmpeg_manager.py",
    "app/core/config_loader.py"
]

setup(
    ext_modules=cythonize(
        files_to_protect,
        compiler_directives={'language_level': "3"}, # Python 3
        build_dir="build_temp"  # Thư mục tạm để build
    )
)