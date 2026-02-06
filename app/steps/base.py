from abc import ABC, abstractmethod
from pathlib import Path
from app.core.config_loader import GlobalConfig

class BaseStep(ABC):
    def __init__(self, cfg: GlobalConfig):
        self.cfg = cfg
        
    @abstractmethod
    def process(self, input_path: Path) -> Path:
        pass
        
    def ensure_dir(self, path: Path):
        path.mkdir(parents=True, exist_ok=True)