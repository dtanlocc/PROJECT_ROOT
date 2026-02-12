from PIL import Image
import os

def create_ico(source_png, output_ico):
    if not os.path.exists(source_png):
        print(f"❌ Lỗi: Không tìm thấy file {source_png}")
        return

    # Mở ảnh gốc
    img = Image.open(source_png)
    
    # Nếu ảnh gốc không phải hình vuông, nó sẽ bị méo khi làm icon.
    # Thông thường ảnh AI tạo ra đã vuông rồi (1024x1024), nên ta cứ yên tâm.
    
    # Các kích thước chuẩn Windows yêu cầu để hiển thị nét từ Taskbar đến Desktop
    icon_sizes = [(16, 16), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    
    # Lưu dưới định dạng ICO với nhiều layer kích thước
    img.save(output_ico, format='ICO', sizes=icon_sizes)
    print(f"✅ Đã tạo icon Windows xịn tại: {output_ico}")

if __name__ == "__main__":
    # Đảm bảo thư mục tồn tại
    os.makedirs("app/assets", exist_ok=True)
    
    source = "app/assets/logo.png"
    output = "app/assets/icon.ico"
    
    create_ico(source, output)