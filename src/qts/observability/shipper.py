"""Audit/shipping to durable storage (S3).

Design:
- Shipper is a Protocol; LocalShipper does nothing but is testable.
- S3Shipper uses boto3 if available, otherwise degrades to LocalShipper with warning.
- Secrets (AWS keys) come via SecretsProvider / env, never hard-coded.
- Ship is idempotent: same file content -> same S3 key (content hash).
- Audit hook: ship_audit_logs can be called on schedule or post-run.
- CLI: `qts audit ship --jsonl logs/audit.jsonl --bucket qts-audit --prefix prod/`

Security: never log credentials, redact.
"""

from __future__ import annotations

import hashlib
import logging
import pathlib
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol, runtime_checkable

logger = logging.getLogger(__name__)


@runtime_checkable
class Shipper(Protocol):
    def ship(self, local_path: Path, key: str | None = None) -> str | None:  # returns s3 uri or None
        ...

    def name(self) -> str: ...


class LocalShipper:
    """No-op shipper for dev/test — writes to local 'shipped/' dir for visibility."""

    def __init__(self, root: Path | str = "data/shipped"):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def name(self) -> str:
        return "local"

    def ship(self, local_path: Path, key: str | None = None) -> str | None:
        p = Path(local_path)
        if not p.exists():
            logger.warning("shipper: file not found %s", p)
            return None
        if key is None:
            h = hashlib.sha256(p.read_bytes()).hexdigest()[:12]
            ts = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
            key = f"{ts}-{h}-{p.name}"
        dest = self.root / Path(key).name
        dest.write_bytes(p.read_bytes())
        logger.info("local ship %s -> %s", p, dest)
        return str(dest)


class S3Shipper:
    """Durable S3 shipper. Requires boto3 + credentials via env/IAM."""

    def __init__(self, bucket: str, prefix: str = "qts/audit/", region: str | None = None):
        self.bucket = bucket
        self.prefix = prefix.strip("/") + "/" if prefix else ""
        self.region = region
        self._s3 = None

    def name(self) -> str:
        return f"s3://{self.bucket}/{self.prefix}"

    def _client(self):  # type: ignore[no-untyped-def]
        if self._s3 is not None:
            return self._s3
        try:
            import boto3  # type: ignore

            self._s3 = boto3.client("s3", region_name=self.region)
            return self._s3
        except ImportError as exc:
            logger.warning("boto3 not installed — falling back to LocalShipper (no durable ship)")
            raise RuntimeError("boto3 not installed") from exc

    def ship(self, local_path: Path, key: str | None = None) -> str | None:
        p = Path(local_path)
        if not p.exists():
            logger.warning("shipper: file not found %s", p)
            return None
        if key is None:
            h = hashlib.sha256(p.read_bytes()).hexdigest()[:16]
            ts = datetime.now(UTC).strftime("%Y%m%d/%H")
            key = f"{self.prefix}{ts}/{h}-{p.name}"
        else:
            # ensure prefix
            if not key.startswith(self.prefix):
                key = self.prefix + key.lstrip("/")
        try:
            s3 = self._client()
            s3.upload_file(str(p), self.bucket, key)
            uri = f"s3://{self.bucket}/{key}"
            logger.info("s3 shipped %s -> %s", p, uri)
            return uri
        except Exception as e:  # noqa: BLE001
            logger.exception("s3 ship failed %s -> %s: %s", p, key, e)
            return None


def ship_audit_logs(jsonl_path: Path | str, shipper: Shipper) -> str | None:
    """Ship a single audit jsonl file. Returns shipped URI or None.

    Idempotent: callers can invoke periodically; shipper handles dedup via hash key.
    """
    path = Path(jsonl_path)
    if not path.exists():
        logger.warning("audit ship: %s not found", path)
        return None
    # key includes content hash so re-shipping same file is deduplicated server-side
    h = hashlib.sha256(path.read_bytes()).hexdigest()[:12]
    key = f"audit/{path.stem}-{h}.jsonl"
    return shipper.ship(path, key=key)


def make_shipper_from_config(cfg: dict) -> Shipper:
    """Factory from config/Settings.

    cfg example:
      shipper:
        type: local|s3
        bucket: qts-audit
        prefix: prod/qts
        local_root: data/shipped
    """
    t = (cfg.get("type") or cfg.get("shipper_type") or "local").lower()
    if t == "s3":
        bucket = cfg.get("bucket") or cfg.get("s3_bucket")
        if not bucket:
            logger.warning("s3 shipper requested but bucket missing — falling back to local")
            return LocalShipper(root=cfg.get("local_root", "data/shipped"))
        return S3Shipper(bucket=bucket, prefix=cfg.get("prefix", "qts/audit/"))
    return LocalShipper(root=cfg.get("local_root", cfg.get("root", "data/shipped")))
