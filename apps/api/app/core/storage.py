from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import HTTPException

from app.core.config import Settings, get_settings


@dataclass(frozen=True)
class StoredObject:
    storage_path: str
    backend: str


def _s3_enabled(settings: Settings) -> bool:
    return settings.storage_backend.lower() == "s3"


def _storage_root(settings: Settings) -> Path:
    return Path(settings.storage_dir)


def _s3_client(settings: Settings):
    try:
        import boto3
        from botocore.config import Config
    except ImportError as exc:
        raise RuntimeError("boto3 is required when STORAGE_BACKEND=s3") from exc

    return boto3.client(
        "s3",
        endpoint_url=settings.s3_endpoint_url,
        aws_access_key_id=settings.s3_access_key,
        aws_secret_access_key=settings.s3_secret_key,
        region_name=settings.s3_region,
        config=Config(signature_version="s3v4"),
    )


def _ensure_bucket(settings: Settings) -> None:
    client = _s3_client(settings)
    try:
        client.head_bucket(Bucket=settings.s3_bucket)
    except Exception:
        client.create_bucket(Bucket=settings.s3_bucket)


def _s3_key(storage_path: str, settings: Settings) -> str:
    prefix = f"s3://{settings.s3_bucket}/"
    if not storage_path.startswith(prefix):
        raise HTTPException(status_code=404, detail="Stored object not found")
    return storage_path.removeprefix(prefix)


def put_bytes(key: str, content: bytes, content_type: str) -> StoredObject:
    settings = get_settings()
    clean_key = key.strip("/").replace("\\", "/")
    if _s3_enabled(settings):
        _ensure_bucket(settings)
        _s3_client(settings).put_object(
            Bucket=settings.s3_bucket,
            Key=clean_key,
            Body=content,
            ContentType=content_type,
        )
        return StoredObject(storage_path=f"s3://{settings.s3_bucket}/{clean_key}", backend="s3")

    path = _storage_root(settings) / clean_key
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    return StoredObject(storage_path=str(path), backend="local")


def read_bytes(storage_path: str) -> bytes:
    settings = get_settings()
    if storage_path.startswith("s3://"):
        client = _s3_client(settings)
        try:
            response = client.get_object(Bucket=settings.s3_bucket, Key=_s3_key(storage_path, settings))
            return response["Body"].read()
        except Exception as exc:
            raise HTTPException(status_code=404, detail="Stored object not found") from exc

    path = Path(storage_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Stored file not found")
    return path.read_bytes()


def delete_object(storage_path: str) -> None:
    settings = get_settings()
    if storage_path.startswith("s3://"):
        try:
            _s3_client(settings).delete_object(Bucket=settings.s3_bucket, Key=_s3_key(storage_path, settings))
        except Exception:
            return
        return

    Path(storage_path).unlink(missing_ok=True)
