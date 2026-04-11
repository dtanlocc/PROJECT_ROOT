from vietnormalizer import VietnameseNormalizer

normalizer = VietnameseNormalizer()

text = "Mbappe kiếm 40.000 USD cho mỗi đường chuyền. Hôm nay là 25/12/2025."
normalized = normalizer.normalize(text)
print(normalized)
    def _get_tts_python_path(self) -> Path:
        """Lấy đường dẫn python của venv_tts"""
        base = Path("venv_tts")
        if os.name == "nt":  # Windows
            return base / "Scripts" / "python.exe"
        else:  # Linux/Mac
            return base / "bin" / "python"