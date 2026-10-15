"""Image storage: local disk for dev, S3 in the cloud."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from crashcase.config import Settings


class Storage(Protocol):
    def save(self, key: str, data: bytes) -> str: ...
    def load(self, key: str) -> bytes: ...


class LocalStorage:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, key: str, data: bytes) -> str:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return key

    def load(self, key: str) -> bytes:
        return (self.root / key).read_bytes()


class S3Storage:
    def __init__(self, bucket: str):
        import boto3  # only needed in the cloud

        self.bucket = bucket
        self.client = boto3.client("s3")

    def save(self, key: str, data: bytes) -> str:
        self.client.put_object(Bucket=self.bucket, Key=f"uploads/{key}", Body=data)
        return key

    def load(self, key: str) -> bytes:
        obj = self.client.get_object(Bucket=self.bucket, Key=f"uploads/{key}")
        return obj["Body"].read()


def get_storage(settings: Settings) -> Storage:
    if settings.storage_backend == "s3":
        return S3Storage(settings.s3_bucket)
    return LocalStorage(settings.upload_dir)
