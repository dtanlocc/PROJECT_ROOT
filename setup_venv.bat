@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

TITLE Pipeline Reup Pro - Universal Setup

echo ===============================================================================
echo   CAI DAT MOI TRUONG VAN NANG (GPU + CPU)
echo   (Ban nay chay duoc tren ca may co Card roi va may chi co CPU)
echo ===============================================================================
echo.

REM 1. KIEM TRA PYTHON
where python >nul 2>&1
if errorlevel 1 (
    echo [LOI] Khong tim thay Python. Hay cai Python 3.10 va tich "Add to PATH".
    pause
    exit /b 1
)

REM 2. TAO VENV
if exist "venv" (
    echo Phat hien venv cu. Dang xoa de cai moi cho sach se...
    rmdir /s /q venv
)
echo Dang tao moi truong ao 'venv'...
python -m venv venv

REM 3. KICH HOAT & UPDATE PIP
call venv\Scripts\activate
python -m pip install --upgrade pip

echo.
echo [BUOC 1/3] Cai dat PyTorch (Ho tro GPU & CPU)...
echo -------------------------------------------------------
REM Cài bản CUDA 11.8 (Bản ổn định nhất hiện nay). 
REM Nếu máy không có GPU, nó sẽ tự chạy bằng CPU.
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121

echo.
echo [BUOC 2/3] Cai dat PaddlePaddle (Ho tro GPU & CPU)...
echo -------------------------------------------------------
REM Tương tự, cài bản GPU CUDA 11.8
pip install --no-cache-dir paddlepaddle-gpu==2.6.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/ --trusted-host www.paddlepaddle.org.cn

echo.
echo [BUOC 3/3] Cai dat cac thu vien phu tro...
echo -------------------------------------------------------
pip install -r requirements.txt

echo.
echo ===============================================================================
echo   CAI DAT HOAN TAT!
echo   Tool nay gio co the chay tren moi may.
echo ===============================================================================
echo.
python -c "import torch; print('Torch:', torch.__version__, '| CUDA:', torch.cuda.is_available())"
pause