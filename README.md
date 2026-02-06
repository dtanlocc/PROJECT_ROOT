# Pipeline Reup Pro v2.0.0

Pipeline xử lý video reup: chuẩn hóa âm → tách nhạc (Demucs) → tạo SRT (Whisper/OCR) → dịch → che sub → TTS & mix.

## Cấu trúc thư mục (v2)

```
PROJECT_ROOT/
├── app/                    # Code chính v2
│   ├── core/               # config_loader (Pydantic), engine
│   ├── steps/              # s1_normalize, s2_demucs, s3_transcribe, s4_translate, s5_overlay, s6_mix
│   ├── services/           # ffmpeg_manager
│   └── ui/                 # main_window (GUI)
├── config.yaml             # Cấu hình (tạo từ config.dist.yaml nếu chưa có)
├── config.dist.yaml        # Mẫu config, không dán đường dẫn máy
├── run_gui.py              # Chạy GUI
├── run_cli.py              # CLI: full pipeline hoặc --list
├── run.py                  # Entry point in log ra file
├── requirements.txt        # Thư viện (trừ Torch/Paddle)
├── setup_venv.bat          # Cài GPU (CUDA 11.8)
├── setup_venv_cpu.bat      # Cài CPU (tránh lỗi shm.dll)
└── pipeline/               # Project cũ (legacy), tham khảo
```

## Cách dùng

1. **Cài môi trường**
   - GPU: `setup_venv.bat` (PyTorch + PaddlePaddle CUDA 11.8)
   - CPU: `setup_venv_cpu.bat` nếu gặp lỗi shm.dll

2. **Cấu hình**
   - Copy `config.dist.yaml` → `config.yaml` (nếu chưa có).
   - Sửa `config.yaml`: `input_videos`, `step6_final` (output), `ffmpeg_bin`, ngôn ngữ, v.v.
   - Hoặc mở GUI và chỉnh trong giao diện rồi lưu.

3. **Chạy**
   - **GUI:** double-click `RUN_GUI.bat` hoặc `python run_gui.py` (từ thư mục gốc project)
   - **CLI full:** `python run_cli.py` hoặc `python run.py`
   - **Liệt kê thư mục pipeline:** `python run_cli.py --list`

4. **Input/Output**
   - Bỏ video (mp4) vào thư mục `input_videos` (mặc định: `input/`).
   - Video xong → `step6_final` (mặc định: `output/`) và file gốc chuyển vào `done/`.
   - Video lỗi → `failed/`.

## Logic pipeline (một video)

B1 Normalize → B2 Demucs (vocals + no_vocals) → B3 Transcribe (voice→SRT hoặc image→SRT) → B4 Translate → B5 Overlay sub → B6 TTS + mix → ra file cuối.

Engine dùng tên file an toàn (vid_xxx.mp4) trong `workspace/processing` để tránh lỗi đường dẫn; kết quả ra output với tên gốc.

## Bảo trì & phát triển

- **Config:** Chỉnh trong `app/core/config_loader.py` (Pydantic models) và `config.dist.yaml`.
- **Từng bước:** Logic trong `app/steps/s1_*.py` … `s6_*.py`, kế thừa `BaseStep`.
- **Pipeline cũ:** Xem `pipeline/README.md`.
