import os
import uuid
import aiofiles
from pathlib import Path
from app.core.config import settings


class StorageService:
    """Unified storage: local filesystem in dev, S3-compatible in prod."""

    def __init__(self):
        if not settings.USE_S3:
            self.base_path = Path(settings.MEDIA_LOCAL_PATH)
            self.base_path.mkdir(parents=True, exist_ok=True)
            (self.base_path / "thumbnails").mkdir(exist_ok=True)

    async def save_at_key(self, key: str, file_data: bytes) -> str:
        """Save bytes at an exact storage key (e.g. sibling subtitle next to video)."""
        if settings.USE_S3:
            return await self._save_s3(file_data, key)
        return await self._save_local(file_data, key)

    def exists(self, path: str) -> bool:
        if not path:
            return False
        if settings.USE_S3:
            try:
                import boto3
                s3 = boto3.client(
                    "s3",
                    endpoint_url=settings.S3_ENDPOINT_URL or None,
                    aws_access_key_id=settings.S3_ACCESS_KEY,
                    aws_secret_access_key=settings.S3_SECRET_KEY,
                )
                s3.head_object(Bucket=settings.S3_BUCKET, Key=path)
                return True
            except Exception:
                return False
        return (self.base_path / path).is_file()

    async def save_file(self, file_data: bytes, filename: str, folder: str = "") -> str:
        """Save file bytes and return its storage path (relative key)."""
        ext = Path(filename).suffix.lower() or ".bin"
        unique_name = f"{uuid.uuid4().hex}{ext}"
        key = f"{folder}/{unique_name}" if folder else unique_name

        if settings.USE_S3:
            return await self._save_s3(file_data, key)
        return await self._save_local(file_data, key)

    async def _save_local(self, data: bytes, key: str) -> str:
        dest = self.base_path / key
        dest.parent.mkdir(parents=True, exist_ok=True)
        async with aiofiles.open(dest, "wb") as f:
            await f.write(data)
        return key  # Return relative key, not absolute path

    async def _save_s3(self, data: bytes, key: str) -> str:
        import boto3
        s3 = boto3.client(
            "s3",
            endpoint_url=settings.S3_ENDPOINT_URL or None,
            aws_access_key_id=settings.S3_ACCESS_KEY,
            aws_secret_access_key=settings.S3_SECRET_KEY,
        )
        s3.put_object(Bucket=settings.S3_BUCKET, Key=key, Body=data)
        return key

    async def read_file_bytes(self, path: str) -> bytes:
        if not path:
            raise FileNotFoundError(path)
        if settings.USE_S3:
            import boto3
            s3 = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT_URL or None,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
            )
            obj = s3.get_object(Bucket=settings.S3_BUCKET, Key=path)
            return obj["Body"].read()
        full = self.base_path / path
        if not full.is_file():
            raise FileNotFoundError(path)
        async with aiofiles.open(full, "rb") as f:
            return await f.read()

    def get_url(self, path: str) -> str:
        """Return an absolute URL the frontend can use to display the file."""
        if not path:
            return ""
        if settings.USE_S3:
            base = settings.S3_ENDPOINT_URL or f"https://{settings.S3_BUCKET}.s3.amazonaws.com"
            return f"{base}/{path}"
        # Local dev: served via FastAPI /media static mount
        # MEDIA_BASE_URL allows overriding (e.g. in Docker: http://localhost:8000)
        base = (settings.MEDIA_BASE_URL or "http://localhost:8000").rstrip("/")
        return f"{base}/media/{path}"

    async def delete_file(self, path: str) -> None:
        if not path:
            return
        if settings.USE_S3:
            import boto3
            s3 = boto3.client(
                "s3",
                endpoint_url=settings.S3_ENDPOINT_URL or None,
                aws_access_key_id=settings.S3_ACCESS_KEY,
                aws_secret_access_key=settings.S3_SECRET_KEY,
            )
            s3.delete_object(Bucket=settings.S3_BUCKET, Key=path)
        else:
            full = self.base_path / path
            if full.exists():
                full.unlink(missing_ok=True)


storage = StorageService()
