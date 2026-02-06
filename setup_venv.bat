@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

TITLE Pipeline Reup Pro - Setup GPU (CUDA 11.8)

echo ===============================================================================
echo   CAI DAT MOI TRUONG AO - BAN GPU
echo   PyTorch + PaddlePaddle cung CUDA 11.8 (chi can 1 bo NVIDIA Driver/CUDA)
echo   Neu loi shm.dll: chay setup_venv_cpu.bat hoac cai VC++ Redistributable
echo ===============================================================================
echo.

REM 1. KIEM TRA PYTHON
where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Cai Python 3.10+ va tich "Add to PATH".
    pause
    exit /b 1
)

REM 2. TAO VENV
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

echo.
echo [1/3] PyTorch GPU (CUDA 11.8)...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu118
if errorlevel 1 (
    echo [LOI] PyTorch that bai. Thu setup_venv_cpu.bat.
    pause
    exit /b 1
)

echo.
echo [2/3] PaddlePaddle GPU (CUDA 11.8)...
pip install --no-cache-dir paddlepaddle-gpu==2.6.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/ --trusted-host www.paddlepaddle.org.cn
if errorlevel 1 (
    echo [CANH BAO] Paddle GPU that bai. May khong GPU: pip install paddlepaddle==2.6.1
    pause
)

echo.
echo [3/3] Thu vien phu tro (requirements.txt)...
pip install -r requirements.txt
if errorlevel 1 (
    echo [LOI] Cai requirements that bai.
    pause
    exit /b 1
)

echo.
echo ===============================================================================
echo   CAI DAT GPU HOAN TAT - Dong bo CUDA 11.8
echo ===============================================================================
python -c "import torch; print('PyTorch:', torch.__version__, '| CUDA:', torch.cuda.is_available())"
pause