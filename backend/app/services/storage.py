import abc
import os
from pathlib import Path
from app.core.config import get_settings

class StorageBackend(abc.ABC):
    @abc.abstractmethod
    def save(self, file_data: bytes, filename: str) -> str:
        """
        Save file data to storage and return the storage path/key.
        """
        pass

    @abc.abstractmethod
    def get(self, path: str) -> bytes:
        """
        Retrieve file bytes from storage.
        """
        pass

    @abc.abstractmethod
    def delete(self, path: str) -> None:
        """
        Delete file from storage.
        """
        pass


class LocalStorageBackend(StorageBackend):
    def __init__(self, upload_dir: str):
        self.upload_dir = Path(upload_dir).resolve()
        # Ensure upload directory exists
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    def save(self, file_data: bytes, filename: str) -> str:
        # Prevent directory traversal by extracting basename
        safe_filename = os.path.basename(filename)
        dest_path = (self.upload_dir / safe_filename).resolve()
        
        # Security check: ensure path is within the upload directory
        if not str(dest_path).startswith(str(self.upload_dir)):
            raise ValueError("Directory traversal attempt blocked")
        
        # Write bytes
        with open(dest_path, "wb") as f:
            f.write(file_data)
        
        return str(dest_path)

    def get(self, path: str) -> bytes:
        target_path = Path(path).resolve()
        
        # Security check: ensure path is within the upload directory
        if not str(target_path).startswith(str(self.upload_dir)):
            raise ValueError("Directory traversal attempt blocked")
            
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError("File not found")
            
        with open(target_path, "rb") as f:
            return f.read()

    def delete(self, path: str) -> None:
        target_path = Path(path).resolve()
        
        # Security check: ensure path is within the upload directory
        if not str(target_path).startswith(str(self.upload_dir)):
            raise ValueError("Directory traversal attempt blocked")
            
        if target_path.exists() and target_path.is_file():
            os.remove(target_path)


def get_storage_backend() -> StorageBackend:
    settings = get_settings()
    return LocalStorageBackend(settings.upload_directory)
