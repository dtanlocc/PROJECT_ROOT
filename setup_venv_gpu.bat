@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

TITLE Pipeline Reup Pro - Cài đặt bản GPU (CUDA)

echo gpu> install_mode.txt

echo ===============================================================================
echo   CAI DAT MOI TRUONG AO - BAN GPU (CUDA)
echo   Neu loi shm.dll: chay setup_venv_cpu.bat
echo ===============================================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Cai Python 3.10+ va tich "Add to PATH".
    exit /b 1
)

if exist "venv" (
    echo Xoa venv cu...
    rmdir /s /q venv
)
echo Tao venv...
python -m venv venv
if errorlevel 1 (
    echo [LOI] Tao venv that bai.
    exit /b 1
)

call venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo [1/3] PyTorch GPU (CUDA 11.8)...
pip install torch==2.6.0+cu118 torchaudio==2.6.0+cu118 --index-url https://download.pytorch.org/whl/cu118
if errorlevel 1 (
    echo [LOI] PyTorch that bai. Thu setup_venv_cpu.bat.
    exit /b 1
)

echo [2/3] PaddlePaddle GPU (CUDA 11.8)...
pip install paddlepaddle-gpu==2.5.2 -f https://www.paddlepaddle.org.cn/whl/windows/mkl/avx/stable.html
if errorlevel 1 (
    echo [CANH BAO] Paddle GPU that bai. Co the cai: pip install paddlepaddle==2.6.2
    REM Bo pause, chi canh bao roi cho chay tiep
)

echo [3/3] Thu vien phu tro (requirements.txt)...
pip install -r requirements.txt
if errorlevel 1 (
    echo [LOI] Cai requirements that bai.
    exit /b 1
)

pip uninstall paddleocr paddlex numpy opencv-python scikit-learn -y
pip install numpy==1.26.4 opencv-python==4.6.0.66 paddleocr==2.7.3

pip install "huggingface-hub==0.36.2" "transformers==4.57.3" --force-reinstall --no-cache-dir
pip install numpy==1.26.4 PyYAML==6.0.2 click==8.1.7 protobuf==3.20.2 --force-reinstall --no-cache-dir




echo.
echo ===============================================================================
echo   CAI DAT GPU HOAN TAT - install_mode.txt = gpu
echo ===============================================================================
python -c "import torch; print('PyTorch:', torch.__version__, '| CUDA:', torch.cuda.is_available())"

:: --- CHOT HA DE BAO CAO HOAN THANH CHO POWERSHELL ---
exit /b 0