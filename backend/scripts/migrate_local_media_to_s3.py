"""Idempotently copy the local media volume to configured S3/R2 storage."""

import mimetypes
from pathlib import Path

import boto3
from botocore.exceptions import ClientError

from app.core.config import settings


def main() -> None:
    if not settings.USE_S3:
        raise RuntimeError("USE_S3 is disabled")

    root = Path(settings.MEDIA_LOCAL_PATH).resolve()
    files = sorted(path for path in root.rglob("*") if path.is_file())
    client = boto3.client(
        "s3",
        endpoint_url=settings.S3_ENDPOINT_URL or None,
        aws_access_key_id=settings.S3_ACCESS_KEY,
        aws_secret_access_key=settings.S3_SECRET_KEY,
    )

    uploaded = 0
    skipped = 0
    for path in files:
        key = path.relative_to(root).as_posix()
        try:
            remote = client.head_object(Bucket=settings.S3_BUCKET, Key=key)
            if int(remote.get("ContentLength", -1)) == path.stat().st_size:
                skipped += 1
                continue
        except ClientError as exc:
            status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode")
            if status != 404:
                raise

        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        client.upload_file(
            str(path),
            settings.S3_BUCKET,
            key,
            ExtraArgs={
                "ContentType": content_type,
                "CacheControl": "public, max-age=31536000, immutable",
            },
        )
        uploaded += 1

    print(f"R2 migration complete: uploaded={uploaded}, skipped={skipped}, total={len(files)}")


if __name__ == "__main__":
    main()
