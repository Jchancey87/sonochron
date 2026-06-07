import os
from abc import ABC, abstractmethod
from pathlib import Path
import anyio

class StorageProvider(ABC):
    @abstractmethod
    async def store_file(self, path_key: str, data: bytes) -> str:
        """
        Stores file data under a unique key.
        Returns the canonical filepath or URL.
        """
        pass

    @abstractmethod
    async def retrieve_file(self, path_key: str) -> bytes:
        """
        Retrieves file binary contents by key.
        Raises FileNotFoundError if key is not found.
        """
        pass

    @abstractmethod
    async def delete_file(self, path_key: str) -> None:
        """
        Deletes the file associated with the key.
        """
        pass


class LocalStorageProvider(StorageProvider):
    def __init__(self, base_dir: str = "backend/storage"):
        self.base_dir = Path(base_dir).resolve()
        self.base_dir.mkdir(parents=True, exist_ok=True)

    def _get_safe_path(self, path_key: str) -> Path:
        """
        Calculates the target path and prevents directory traversal attacks.
        """
        path_obj = Path(path_key)
        
        # Block absolute paths
        if path_obj.is_absolute() or str(path_key).startswith("/"):
            raise ValueError(f"Path traversal attempt blocked: {path_key}")

        # Block explicit traversal patterns
        if ".." in path_key or ".." in path_obj.parts:
            raise ValueError(f"Path traversal attempt blocked: {path_key}")
            
        # Resolve target path relative to base_dir
        safe_path = (self.base_dir / path_key).resolve()
        
        # Verify target file is indeed nested under the base directory
        try:
            safe_path.relative_to(self.base_dir)
        except ValueError:
            raise ValueError(f"Path traversal attempt blocked: {path_key}")
            
        return safe_path

    async def store_file(self, path_key: str, data: bytes) -> str:
        target_path = self._get_safe_path(path_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        
        def _write():
            with open(target_path, "wb") as f:
                f.write(data)
            return str(target_path)
            
        return await anyio.to_thread.run_sync(_write)

    async def retrieve_file(self, path_key: str) -> bytes:
        target_path = self._get_safe_path(path_key)
        if not target_path.exists() or not target_path.is_file():
            raise FileNotFoundError(f"File not found: {path_key}")
            
        def _read():
            with open(target_path, "rb") as f:
                return f.read()
                
        return await anyio.to_thread.run_sync(_read)

    async def delete_file(self, path_key: str) -> None:
        target_path = self._get_safe_path(path_key)
        if not target_path.exists():
            return
            
        def _delete():
            if target_path.is_file():
                target_path.unlink()
                
        await anyio.to_thread.run_sync(_delete)
