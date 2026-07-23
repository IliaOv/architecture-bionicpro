from __future__ import annotations

import hashlib
import hmac
import logging
import threading
from datetime import date

import boto3
from botocore.client import Config
from botocore.exceptions import ClientError

from .config import settings

logger = logging.getLogger("reports-api.storage")

_client = None
_bucket_ready = False
_bucket_lock = threading.Lock()


def _s3():
    global _client
    if _client is None:
        _client = boto3.client(
            "s3",
            endpoint_url=settings.s3_endpoint_url,
            aws_access_key_id=settings.s3_access_key,
            aws_secret_access_key=settings.s3_secret_key,
            region_name=settings.s3_region,
            # MinIO: path-style http://host:9000/{bucket}/{key}
            config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
        )
    return _client


_PUBLIC_READ_POLICY = (
    '{{"Version":"2012-10-17","Statement":[{{'
    '"Effect":"Allow","Principal":{{"AWS":["*"]}},'
    '"Action":["s3:GetObject"],'
    '"Resource":["arn:aws:s3:::{bucket}/*"]}}]}}'
)


def ensure_bucket() -> None:
    """Идемпотентно создаёт бакет и политику анонимного GetObject для CDN."""
    global _bucket_ready
    if _bucket_ready:
        return
    with _bucket_lock:
        if _bucket_ready:
            return
        s3 = _s3()
        try:
            s3.head_bucket(Bucket=settings.s3_bucket)
        except ClientError:
            s3.create_bucket(Bucket=settings.s3_bucket)
        s3.put_bucket_policy(
            Bucket=settings.s3_bucket,
            Policy=_PUBLIC_READ_POLICY.format(bucket=settings.s3_bucket),
        )
        _bucket_ready = True
        logger.info("S3 bucket ready: %s", settings.s3_bucket)


def _ensure_bucket_or_raise() -> None:
    try:
        ensure_bucket()
    except Exception as exc:  # noqa: BLE001
        raise RuntimeError(
            f"S3/MinIO недоступен ({settings.s3_endpoint_url}): {exc}"
        ) from exc


def _signature(username: str, date_from: date, date_to: date, watermark: date) -> str:
    msg = (
        f"{username}|{date_from.isoformat()}|"
        f"{date_to.isoformat()}|{watermark.isoformat()}"
    )
    return hmac.new(
        settings.report_url_secret.encode(),
        msg.encode(),
        hashlib.sha256,
    ).hexdigest()[:16]


def object_key(username: str, date_from: date, date_to: date, watermark: date) -> str:
    """Версионно-адресуемый ключ.

    reports/user=<username>/wm=<watermark>/<from>_<to>-<sig>.json
    """
    sig = _signature(username, date_from, date_to, watermark)
    return (
        f"reports/user={username}/wm={watermark.isoformat()}/"
        f"{date_from.isoformat()}_{date_to.isoformat()}-{sig}.json"
    )


def report_exists(key: str) -> bool:
    _ensure_bucket_or_raise()
    try:
        _s3().head_object(Bucket=settings.s3_bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code", "")
        if code in ("404", "NoSuchKey", "NotFound"):
            return False
        raise


def put_report(key: str, body: bytes) -> None:
    _ensure_bucket_or_raise()
    _s3().put_object(
        Bucket=settings.s3_bucket,
        Key=key,
        Body=body,
        ContentType="application/json",
        CacheControl="public, max-age=31536000, immutable",
    )


def cdn_url(key: str) -> str:
    """Публичная ссылка через CDN (nginx → MinIO, path-style /{bucket}/{key})."""
    return f"{settings.cdn_public_url}/{settings.s3_bucket}/{key}"
