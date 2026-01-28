"""
Abstract storage backend for file operations.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import BinaryIO, Optional
import uuid


class StorageError(Exception):
    """Base exception for storage operations."""
    pass


class FileNotFoundError(StorageError):
    """File not found in storage."""
    pass


@dataclass
class StoredFile:
    """Information about a stored file."""
    path: str
    size_bytes: int
    content_type: str
    backend: str


class StorageBackend(ABC):
    """
    Abstract base class for storage backends.
    
    Implementations must provide methods for saving, retrieving,
    and deleting files.
    """

    @property
    @abstractmethod
    def backend_type(self) -> str:
        """Return the backend type identifier (e.g., 'local', 's3', 'gcs')."""
        pass

    @abstractmethod
    def save(
        self,
        file_obj: BinaryIO,
        filename: str,
        content_type: str,
        folder: Optional[str] = None,
    ) -> StoredFile:
        """
        Save a file to storage.
        
        Args:
            file_obj: File-like object to save
            filename: Original filename
            content_type: MIME type of the file
            folder: Optional subfolder within storage
            
        Returns:
            StoredFile with path and metadata
        """
        pass

    @abstractmethod
    def get(self, path: str) -> BinaryIO:
        """
        Retrieve a file from storage.
        
        Args:
            path: Storage path returned from save()
            
        Returns:
            File-like object for reading
            
        Raises:
            FileNotFoundError: If file doesn't exist
        """
        pass

    @abstractmethod
    def delete(self, path: str) -> bool:
        """
        Delete a file from storage.
        
        Args:
            path: Storage path to delete
            
        Returns:
            True if deleted, False if not found
        """
        pass

    @abstractmethod
    def exists(self, path: str) -> bool:
        """
        Check if a file exists in storage.
        
        Args:
            path: Storage path to check
            
        Returns:
            True if exists, False otherwise
        """
        pass

    @abstractmethod
    def get_url(self, path: str, expires_in: Optional[int] = None) -> str:
        """
        Get a URL for accessing the file.
        
        Args:
            path: Storage path
            expires_in: Optional expiration time in seconds for signed URLs
            
        Returns:
            URL string for accessing the file
        """
        pass

    def generate_unique_filename(self, original_filename: str) -> str:
        """Generate a unique filename to prevent collisions."""
        ext = ""
        if "." in original_filename:
            ext = "." + original_filename.rsplit(".", 1)[1]
        return f"{uuid.uuid4().hex}{ext}"


def get_storage_backend() -> StorageBackend:
    """
    Get the configured storage backend.
    
    Returns the appropriate backend based on settings.
    """
    from django_agent_runtime.conf import runtime_settings
    
    backend_type = runtime_settings.FILE_STORAGE_BACKEND
    
    if backend_type == "local":
        from django_agent_runtime.storage.local import LocalStorageBackend
        return LocalStorageBackend()
    elif backend_type == "s3":
        from django_agent_runtime.storage.s3 import S3StorageBackend
        return S3StorageBackend()
    elif backend_type == "gcs":
        from django_agent_runtime.storage.gcs import GCSStorageBackend
        return GCSStorageBackend()
    else:
        raise StorageError(f"Unknown storage backend: {backend_type}")

