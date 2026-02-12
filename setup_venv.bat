@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0"

TITLE Pipeline Reup Pro - Cài đặt môi trường

echo ===============================================================================
echo   CHON LOAI CAI DAT
echo   1 = Chi CPU       (nhe, khong can NVIDIA/CUDA)
echo   2 = Chi GPU       (NVIDIA + CUDA 11.8, nhanh hon)
echo   3 = Ca hai        (cai GPU, trong app co the chon Auto/CPU/GPU)
echo ===============================================================================
echo.
set /p CHOICE="Nhap 1, 2 hoac 3 roi Enter: "

if "%CHOICE%"=="1" goto INSTALL_CPU
if "%CHOICE%"=="2" goto INSTALL_GPU
if "%CHOICE%"=="3" goto INSTALL_BOTH
echo Lua chon khong hop le. Thoat.
pause
exit /b 1

:INSTALL_CPU
echo.
echo [CHON: CHI CPU]
echo cpu> install_mode.txt
call :DO_INSTALL_CPU
goto DONE

:INSTALL_GPU
echo.
echo [CHON: CHI GPU]
echo gpu> install_mode.txt
call :DO_INSTALL_GPU
goto DONE

:INSTALL_BOTH
echo.
echo [CHON: CA HAI - Cai GPU, trong app chon duoc Auto/CPU/GPU]
echo both> install_mode.txt
call :DO_INSTALL_GPU
goto DONE

:DO_INSTALL_CPU
echo ===============================================================================
echo   CAI DAT MOI TRUONG AO - BAN CPU
echo ===============================================================================
goto COMMON_START

:DO_INSTALL_GPU
echo ===============================================================================
echo   CAI DAT MOI TRUONG AO - BAN GPU (CUDA)
echo   Neu loi shm.dll: chay setup_venv_cpu.bat hoac cai VC++ Redistributable
echo ===============================================================================
goto COMMON_START

:COMMON_START
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

if "%CHOICE%"=="1" goto PIP_CPU
goto PIP_GPU

:PIP_CPU
echo.
echo [1/3] PyTorch CPU...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cpu
if errorlevel 1 (
    echo [LOI] PyTorch CPU that bai.
    pause
    exit /b 1
)
echo.
echo [2/3] PaddlePaddle CPU...
pip install paddlepaddle==2.6.1
if errorlevel 1 (
    echo Thu mirror Trung Quoc...
    pip install paddlepaddle==2.6.1 -i https://mirror.baidu.com/pypi/simple
)
if errorlevel 1 (
    echo [LOI] PaddlePaddle CPU that bai. Thu: pip install paddlepaddle
    pause
    exit /b 1
)
python -c "import paddle; print('Paddle:', paddle.__version__)"
if errorlevel 1 (
    echo [LOI] Paddle import loi. Thu cai lai: pip install paddlepaddle==2.6.1
    pause
    exit /b 1
)
echo.
echo [3/3] Thu vien phu tro (requirements.txt)...
pip install -r requirements.txt
if errorlevel 1 (
    echo [LOI] Cai requirements that bai.
    pause
    exit /b 1
)
goto VERIFY

:PIP_GPU
echo.
echo [1/3] PyTorch GPU (CUDA 12.1)...
pip install torch torchaudio --index-url https://download.pytorch.org/whl/cu121
if errorlevel 1 (
    echo [LOI] PyTorch that bai. Thu setup_venv_cpu.bat.
    pause
    exit /b 1
)
echo.
echo [2/3] PaddlePaddle GPU (CUDA 11.8)...
pip install --no-cache-dir paddlepaddle-gpu==2.6.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu118/ --trusted-host www.paddlepaddle.org.cn
if errorlevel 1 (
    echo [CANH BAO] Paddle GPU that bai. Cai Paddle CPU: pip install paddlepaddle==2.6.1
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
goto VERIFY

:VERIFY
echo.
echo ===============================================================================
echo   CAI DAT HOAN TAT
echo ===============================================================================
python -c "import torch; print('PyTorch:', torch.__version__, '| CUDA:', torch.cuda.is_available())"
echo.
echo install_mode.txt da duoc ghi: noi dung phu hop voi lua chon cua ban.
goto :eof

:DONE
echo.
pause
