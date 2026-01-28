"""
Local filesystem storage backend.
"""

import os
import shutil
from pathlib import Path
from typing import BinaryIO, Optional

from django_agent_runtime.storage.base import (
    StorageBackend,
    StoredFile,
    StorageError,
    FileNotFoundError,
)


class LocalStorageBackend(StorageBackend):
    """
    Local filesystem storage backend.
    
    Stores files in a configured directory on the local filesystem.
    """

    def __init__(self):
        from django_agent_runtime.conf import runtime_settings
        settings = runtime_settings()  # Call the function to get settings object
        self._root = Path(settings.FILE_STORAGE_ROOT)
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def backend_type(self) -> str:
        return "local"

    def save(
        self,
        file_obj: BinaryIO,
        filename: str,
        content_type: str,
        folder: Optional[str] = None,
    ) -> StoredFile:
        """Save a file to local filesystem."""
        # Generate unique filename
        unique_name = self.generate_unique_filename(filename)
        
        # Determine storage path
        if folder:
            storage_dir = self._root / folder
        else:
            storage_dir = self._root
        
        storage_dir.mkdir(parents=True, exist_ok=True)
        file_path = storage_dir / unique_name
        
        # Write file
        try:
            with open(file_path, "wb") as f:
                # Handle both file objects and Django UploadedFile
                if hasattr(file_obj, "chunks"):
                    for chunk in file_obj.chunks():
                        f.write(chunk)
                else:
                    shutil.copyfileobj(file_obj, f)
            
            # Get file size
            size_bytes = file_path.stat().st_size
            
            # Return relative path from root
            relative_path = str(file_path.relative_to(self._root))
            
            return StoredFile(
                path=relative_path,
                size_bytes=size_bytes,
                content_type=content_type,
                backend=self.backend_type,
            )
        except Exception as e:
            raise StorageError(f"Failed to save file: {e}")

    def get(self, path: str) -> BinaryIO:
        """Retrieve a file from local filesystem."""
        file_path = self._root / path
        
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")
        
        return open(file_path, "rb")

    def delete(self, path: str) -> bool:
        """Delete a file from local filesystem."""
        file_path = self._root / path
        
        if not file_path.exists():
            return False
        
        try:
            file_path.unlink()
            return True
        except Exception:
            return False

    def exists(self, path: str) -> bool:
        """Check if file exists in local filesystem."""
        file_path = self._root / path
        return file_path.exists()

    def get_url(self, path: str, expires_in: Optional[int] = None) -> str:
        """
        Get URL for local file.
        
        For local storage, returns a relative URL path that should be
        served by the application. The actual serving is handled by
        the download endpoint.
        """
        from django.urls import reverse
        # Return the download endpoint URL
        # The path is stored in the model, so we use the file ID for download
        return f"/api/agent/files/{path}/download/"

