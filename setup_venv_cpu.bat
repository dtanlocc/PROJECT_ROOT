@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

TITLE Pipeline Reup Pro - Cài đặt bản CHỈ CPU

echo cpu> install_mode.txt

echo ===============================================================================
echo   CAI DAT MOI TRUONG AO - BAN CPU (khong can NVIDIA/CUDA)
echo ===============================================================================
echo.

where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Cai Python 3.10+ va tich "Add to PATH".
    pause
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
    pause
    exit /b 1
)

call venv\Scripts\activate.bat
python -m pip install --upgrade pip

echo [1/3] PyTorch CPU...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
    echo [LOI] PyTorch CPU that bai.
    pause
    exit /b 1
)

echo [2/3] PaddlePaddle CPU...
pip install paddlepaddle==2.6.2
if errorlevel 1 (
    echo Thu mirror Trung Quoc...
    pip install paddlepaddle==2.6.2 -i https://mirror.baidu.com/pypi/simple
)
if errorlevel 1 (
    echo [LOI] PaddlePaddle CPU that bai. Thu: pip install paddlepaddle
    pause
    exit /b 1
)
python -c "import paddle; print('Paddle:', paddle.__version__)"
if errorlevel 1 (
    echo [LOI] Paddle cai xong nhung import loi. Thu cai lai: pip install paddlepaddle==2.6.1
    pause
    exit /b 1
)

echo [3/3] Thu vien phu tro (requirements.txt)...
pip install -r requirements.txt
if errorlevel 1 (
    echo [LOI] Cai requirements that bai.
    pause
    exit /b 1
)

echo.
echo ===============================================================================
echo   CAI DAT CPU HOAN TAT - install_mode.txt = cpu
echo ===============================================================================
python -c "import torch; print('PyTorch:', torch.__version__, '| CUDA:', torch.cuda.is_available())"
python -c "import paddle; print('Paddle:', paddle.__version__)"
python -c "from paddleocr import PaddleOCR; print('PaddleOCR: OK')"
pause
