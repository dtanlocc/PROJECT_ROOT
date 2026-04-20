import sys
import os

from app.core.security import start_watchdog, is_session_valid, check_local_license

def inject_venv_path():
    if getattr(sys, 'frozen', False) or '__compiled__' in globals():
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.abspath(os.path.dirname(__file__))
    venv_site = os.path.join(base_dir, "venv", "Lib", "site-packages")
    if os.path.exists(venv_site):
        sys.path.insert(0, venv_site)

def _on_license_expired(reason):
    try:
        from PyQt6.QtWidgets import QMessageBox, QApplication
        from PyQt6.QtCore import QTimer

        def _show_and_quit():
            app = QApplication.instance()
            if not app:
                return
            msg = QMessageBox()
            msg.setIcon(QMessageBox.Icon.Critical)
            msg.setWindowTitle("⛔ Bản quyền hết hạn")
            msg.setText(f"Bản quyền không còn hợp lệ:\n\n{reason}\n\nPhần mềm sẽ đóng ngay bây giờ.")
            msg.setStandardButtons(QMessageBox.StandardButton.Ok)
            msg.exec()
            app.quit()

        QTimer.singleShot(0, _show_and_quit)
    except:
        os._exit(1)

def setup_expiry_checker(main_window):
    """Kiểm tra license mỗi 60 giây trong Qt app"""
    from PyQt6.QtCore import QTimer
    def check_expiry():
        if not is_session_valid():
            _on_license_expired("Phiên bản của bạn đã hết hạn hoặc bị can thiệp.")
    
    timer = QTimer(main_window)
    timer.timeout.connect(check_expiry)
    timer.start(120 * 1000)  # 60 giây
    return timer

if __name__ == "__main__":
    inject_venv_path()
    
    if not os.path.exists("config.yaml") and os.path.exists("config.dist.yaml"):
        import shutil
        try: shutil.copy("config.dist.yaml", "config.yaml")
        except: pass

    # ==================== CHẶN MỞ FILE TRỰC TIẾP ====================
    if '_core_sys_x64' not in sys.modules:
        print("Fatal Error: Vui lòng mở phần mềm thông qua Launcher Reup_Video_Pro.exe")
        sys.exit(1)

    # ==================== KHỞI TẠO RAM TOKEN (FIX LỖI BÁO HẾT HẠN) ====================
    is_active, msg = check_local_license()
    if not is_active:
        # Xử lý trường hợp msg bị None để báo lỗi rõ ràng hơn
        if not msg:
            msg = "Phát hiện môi trường không an toàn (chạy máy ảo, tool hack) hoặc file system.lic bị hỏng!"
            
        print(f"Lỗi phiên làm việc: {msg}")
        sys.exit(1)

    # ==================== CHẠY QT APP CHÍNH ====================
    from PyQt6.QtWidgets import QApplication
    from app.ui.main_window import ProGUI

    app = QApplication(sys.argv)
    main_window = ProGUI()
    main_window.show()

    # Bật Watchdog kiểm tra bảo mật từ Server
    start_watchdog(_on_license_expired)
    
    # Kiểm tra RAM Token định kỳ mỗi 60 giây
    expiry_timer = setup_expiry_checker(main_window)

    if hasattr(app, "exec"):
        sys.exit(app.exec())
    else:
        sys.exit(app.exec_())