@echo off
chcp 65001 >nul
cd /d "%~dp0"

REM Luon dung Python trong venv de dam bao dung dung thu vien da cai (PyTorch, ...)
if exist "venv\Scripts\python.exe" (
    venv\Scripts\python.exe run_gui.py
) else (
    python run_gui.py
)
if errorlevel 1 pause
