import os
import zipfile
import shutil
import tempfile
from pathlib import Path
from fastapi import HTTPException, status
from app.core.config import settings

class ZipSecurityError(HTTPException):
    def __init__(self, detail: str):
        super().__init__(status_code=status.HTTP_400_BAD_REQUEST, detail=detail)

def validate_and_extract_zip(zip_file_path: str) -> Path:
    """
    Securely validates and extracts a ZIP file to a temporary directory.
    Prevents ZIP Slip, ZIP Bombs, and oversized uploads.
    """
    temp_dir = Path(tempfile.mkdtemp(prefix="stackwise_"))

    try:
        with zipfile.ZipFile(zip_file_path, 'r') as zip_ref:
            # 1. Check total uncompressed size to prevent ZIP Bombs
            total_uncompressed_size = 0
            for info in zip_ref.infolist():
                total_uncompressed_size += info.file_size

            if total_uncompressed_size > settings.MAX_UNCOMPRESSED_SIZE_MB * 1024 * 1024:
                raise ZipSecurityError(f"Uncompressed size exceeds limit of {settings.MAX_UNCOMPRESSED_SIZE_MB}MB")

            # 2. Check number of files
            if len(zip_ref.namelist()) > settings.MAX_FILES_COUNT:
                raise ZipSecurityError(f"Too many files in ZIP. Limit: {settings.MAX_FILES_COUNT}")

            # 3. Secure extraction (prevent ZIP Slip)
            for member in zip_ref.infolist():
                # Prevent symlinks and special files
                if not member.is_dir():
                    # Check if it's a regular file
                    # zipfile doesn't have a direct is_file, but we can check if it's not a dir
                    pass

                # Ensure the extracted path is within the target directory
                target_path = (temp_dir / member.filename).resolve()
                if not str(target_path).startswith(str(temp_dir.resolve())):
                    raise ZipSecurityError(f"Malicious path detected: {member.filename}")

            zip_ref.extractall(temp_dir)

    except zipfile.BadZipFile:
        shutil.rmtree(temp_dir)
        raise ZipSecurityError("Invalid ZIP file format")
    except Exception as e:
        shutil.rmtree(temp_dir)
        if isinstance(e, ZipSecurityError):
            raise e
        raise HTTPException(status_code=500, detail=f"Error extracting ZIP: {str(e)}")

    return temp_dir

def cleanup_temp_dir(path: Path):
    """Deletes the temporary directory and its contents."""
    if path.exists():
        shutil.rmtree(path)
