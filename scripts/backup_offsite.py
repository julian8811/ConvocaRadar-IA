#!/usr/bin/env python3
"""Off-site copy of ConvocaRadar pg_dump archives to S3/MinIO.

Stdlib only (urllib + hmac + hashlib): it runs inside the ``backup:`` sidecar
(which only has python3) and on any operator machine. Reuses the object-storage
backend the app already uses (MinIO in the server compose, same bucket unless
``BACKUP_S3_BUCKET`` overrides it); archives land under ``BACKUP_S3_PREFIX``.

Exit codes (contract with ``backup-cycle.sh``):
  0  success
  1  error / degraded (S3 reachable-but-failed, missing file, …)
  2  skipped (off-site disabled via ``BACKUP_S3_ENABLED=false``, or ``auto``
     with S3 not configured). The caller must NOT fail the local cycle.

Environment (all optional unless forcing ``BACKUP_S3_ENABLED=true``):
  BACKUP_S3_ENABLED        auto (default) | true | false
  S3_ENDPOINT_URL          e.g. http://minio:9000 (required to attempt)
  S3_ACCESS_KEY / S3_SECRET_KEY   (required to attempt)
  S3_REGION                signing region; "auto"/empty means us-east-1,
                           which MinIO ignores
  S3_BUCKET                app bucket, default "convocaradar"
  BACKUP_S3_BUCKET         override bucket for backups (default: S3_BUCKET)
  BACKUP_S3_PREFIX         key prefix, default "backups"
  BACKUP_S3_RETENTION_DAYS off-site retention, default 30
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_SKIPPED = 2

DEFAULT_BUCKET = "convocaradar"
DEFAULT_PREFIX = "backups"
DEFAULT_RETENTION_DAYS = 30
SIGNING_FALLBACK_REGION = "us-east-1"
_EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


class S3Error(RuntimeError):
    """An S3 request failed; carries the HTTP status and S3 error code."""

    def __init__(self, status: int | None, code: str, message: str) -> None:
        super().__init__(f"S3 request failed (http={status} code={code}): {message}")
        self.status = status
        self.code = code


# ── Config ────────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class OffsiteConfig:
    enabled: str  # "auto" | "true" | "false"
    endpoint: str | None
    bucket: str
    prefix: str
    access_key: str | None
    secret_key: str | None
    region: str  # sanitized signing region (never "auto"/empty)
    retention_days: int


def sanitize_region(region: str | None) -> str:
    """MinIO accepts any signing region; AWS needs a real one.

    The server compose ships ``S3_REGION=auto`` (meaning "whatever MinIO
    wants"), which is NOT a valid SigV4 region — signing with it produces a
    signature the server rejects. Map it (and empties) to us-east-1.
    """
    cleaned = (region or "").strip().lower()
    if not cleaned or cleaned == "auto":
        return SIGNING_FALLBACK_REGION
    return cleaned


def config_from_env(env: dict | os._Environ = os.environ) -> OffsiteConfig:  # type: ignore[name-defined]
    bucket = (env.get("BACKUP_S3_BUCKET") or env.get("S3_BUCKET") or DEFAULT_BUCKET).strip()
    try:
        retention = int(env.get("BACKUP_S3_RETENTION_DAYS") or DEFAULT_RETENTION_DAYS)
    except ValueError:
        retention = DEFAULT_RETENTION_DAYS
    return OffsiteConfig(
        enabled=(env.get("BACKUP_S3_ENABLED") or "auto").strip().lower(),
        endpoint=(env.get("S3_ENDPOINT_URL") or "").strip() or None,
        bucket=bucket,
        prefix=(env.get("BACKUP_S3_PREFIX") or DEFAULT_PREFIX).strip().strip("/"),
        access_key=(env.get("S3_ACCESS_KEY") or "").strip() or None,
        secret_key=(env.get("S3_SECRET_KEY") or "").strip() or None,
        region=sanitize_region(env.get("S3_REGION")),
        retention_days=max(retention, 1),
    )


def should_attempt(config: OffsiteConfig) -> tuple[bool, str]:
    """Decide whether to touch S3. Never raises; returns (attempt, reason)."""
    if config.enabled == "false":
        return False, "disabled (BACKUP_S3_ENABLED=false)"
    missing = [
        name
        for name, value in (
            ("S3_ENDPOINT_URL", config.endpoint),
            ("S3_ACCESS_KEY", config.access_key),
            ("S3_SECRET_KEY", config.secret_key),
        )
        if not value
    ]
    if missing:
        return False, f"S3 not configured (missing: {', '.join(missing)})"
    if config.enabled not in ("auto", "true"):
        return False, f"unknown BACKUP_S3_ENABLED={config.enabled!r}, treating as disabled"
    return True, "forced (BACKUP_S3_ENABLED=true)" if config.enabled == "true" else "auto"


def build_key(prefix: str, filename: str) -> str:
    """Join prefix + basename into an S3 key without duplicate slashes."""
    name = filename.rsplit("/", 1)[-1]
    clean_prefix = prefix.strip().strip("/")
    return f"{clean_prefix}/{name}" if clean_prefix else name


def s3_uri(config: OffsiteConfig, key: str) -> str:
    return f"s3://{config.bucket}/{key}"


# ── SigV4 (AWS Signature Version 4, path-style) ───────────────────────────


def _uri_encode(value: str, keep_slash: bool) -> str:
    return urllib.parse.quote(value, safe="/-_.~" if keep_slash else "-_.~")


def _canonical_query(params: list[tuple[str, str]]) -> str:
    return "&".join(
        f"{_uri_encode(k, False)}={_uri_encode(v, False)}" for k, v in sorted(params)
    )


def sigv4_authorization(
    *,
    secret_key: str,
    access_key: str,
    region: str,
    service: str,
    method: str,
    path: str,
    query: list[tuple[str, str]],
    host: str,
    payload_hash: str,
    amz_date: str,
) -> str:
    """Build the SigV4 ``Authorization`` header value for one request."""
    date_stamp = amz_date[:8]
    canonical_headers = (
        f"host:{host}\n" f"x-amz-content-sha256:{payload_hash}\n" f"x-amz-date:{amz_date}\n"
    )
    signed_headers = "host;x-amz-content-sha256;x-amz-date"
    canonical_request = "\n".join(
        [method.upper(), _uri_encode(path, True), _canonical_query(query),
         canonical_headers, signed_headers, payload_hash]
    )
    scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join(
        ["AWS4-HMAC-SHA256", amz_date, scope, hashlib.sha256(
            canonical_request.encode("utf-8")).hexdigest()]
    )

    def _sign(key: bytes, msg: str) -> bytes:
        return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()

    signing_key = _sign(
        _sign(_sign(_sign(("AWS4" + secret_key).encode("utf-8"), date_stamp), region),
              service), "aws4_request")
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"),
                         hashlib.sha256).hexdigest()
    return (
        f"AWS4-HMAC-SHA256 Credential={access_key}/{scope}, "
        f"SignedHeaders={signed_headers}, Signature={signature}"
    )


# ── Minimal S3 client ─────────────────────────────────────────────────────


@dataclass(frozen=True)
class S3Object:
    key: str
    last_modified: datetime
    size: int


def parse_s3_timestamp(value: str) -> datetime:
    cleaned = value.strip()
    for fmt in ("%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ"):
        try:
            return datetime.strptime(cleaned, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    raise ValueError(f"unparseable S3 timestamp: {value!r}")


def parse_list_xml(payload: bytes) -> tuple[list[S3Object], bool, str | None]:
    """Parse ListBucketResult v2 → (objects, is_truncated, next_token)."""
    root = ET.fromstring(payload)
    ns = {"s3": "http://s3.amazonaws.com/doc/2006-03-01/"}

    def _find(parent: ET.Element, tag: str) -> str:
        node = parent.find(f"s3:{tag}", ns)
        if node is not None and node.text:
            return node.text
        node = parent.find(tag)  # MinIO omits the namespace on some responses
        return node.text if node is not None and node.text else ""

    objects: list[S3Object] = []
    for contents in list(root.findall("s3:Contents", ns)) or list(root.findall("Contents")):
        key = _find(contents, "Key")
        try:
            last_modified = parse_s3_timestamp(_find(contents, "LastModified"))
        except ValueError:
            continue
        try:
            size = int(_find(contents, "Size") or 0)
        except ValueError:
            size = 0
        objects.append(S3Object(key=key, last_modified=last_modified, size=size))
    truncated = _find(root, "IsTruncated").strip().lower() == "true"
    token = _find(root, "NextContinuationToken").strip() or None
    return objects, truncated, token


def lifecycle_xml(prefix: str, retention_days: int) -> str:
    """Bucket lifecycle document expiring ``prefix/`` objects after N days."""
    clean = prefix.strip().strip("/")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<LifecycleConfiguration xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
        "<Rule>"
        "<ID>convocaradar-backup-retention</ID>"
        "<Status>Enabled</Status>"
        f"<Filter><Prefix>{clean}/</Prefix></Filter>"
        f"<Expiration><Days>{retention_days}</Days></Expiration>"
        "</Rule>"
        "</LifecycleConfiguration>"
    )


def select_expired(
    objects: list[S3Object], now: datetime, retention_days: int
) -> list[S3Object]:
    """Objects strictly older than ``retention_days`` (boundary day is kept)."""
    cutoff = timedelta(days=retention_days)
    return [obj for obj in objects if now - obj.last_modified > cutoff]


class S3Client:
    """Path-style S3 client (MinIO-first; works with AWS existing buckets)."""

    def __init__(self, config: OffsiteConfig) -> None:
        assert config.endpoint and config.access_key and config.secret_key
        self._config = config
        self._base = config.endpoint.rstrip("/")
        self._parsed = urllib.parse.urlsplit(self._base)

    def _request(
        self,
        method: str,
        path: str,
        query: list[tuple[str, str]] | None = None,
        body: bytes | None = None,
        content_type: str | None = None,
        file_path: str | None = None,
        content_length: int | None = None,
    ) -> tuple[int, dict, bytes]:
        query = query or []
        qs = (("?" + urllib.parse.urlencode(query)) if query else "")
        url = f"{self._base}{path}{qs}"
        amz_date = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        payload_hash = _EMPTY_SHA256
        data: bytes | object = None
        headers = {"host": self._parsed.netloc}
        if body is not None:
            payload_hash = hashlib.sha256(body).hexdigest()
            data = body
        elif file_path is not None:
            digest = hashlib.sha256()
            with open(file_path, "rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            payload_hash = digest.hexdigest()
            data = open(file_path, "rb")  # closed by _send_and_close below
            headers["Content-Length"] = str(content_length)
        headers["x-amz-content-sha256"] = payload_hash
        headers["x-amz-date"] = amz_date
        headers["Authorization"] = sigv4_authorization(
            secret_key=self._config.secret_key or "",
            access_key=self._config.access_key or "",
            region=self._config.region,
            service="s3",
            method=method,
            path=path,
            query=query,
            host=self._parsed.netloc,
            payload_hash=payload_hash,
            amz_date=amz_date,
        )
        if content_type:
            headers["Content-Type"] = content_type
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            return self._send_and_close(request, data)
        except urllib.error.HTTPError as exc:
            raise S3Error(exc.code, _s3_code(exc), _s3_message(exc)) from exc
        except OSError as exc:
            raise S3Error(None, "ConnectionError", str(exc)) from exc

    @staticmethod
    def _send_and_close(
        request: urllib.request.Request, data: bytes | object
    ) -> tuple[int, dict, bytes]:
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return response.status, dict(response.headers.items()), response.read()
        finally:
            if hasattr(data, "close"):
                try:
                    data.close()  # type: ignore[union-attr]
                except OSError:
                    pass

    # -- bucket -----------------------------------------------------------
    def head_bucket(self) -> bool:
        try:
            status, _, _ = self._request("HEAD", f"/{self._config.bucket}")
            return status < 400
        except S3Error as exc:
            if exc.status in (403, 404):
                return False
            raise

    def ensure_bucket(self) -> None:
        if self.head_bucket():
            return
        try:
            self._request("PUT", f"/{self._config.bucket}")
        except S3Error as exc:
            if exc.code not in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                raise

    # -- objects ----------------------------------------------------------
    def put_file(self, key: str, file_path: str) -> int:
        import os as _os

        size = _os.path.getsize(file_path)
        self._request(
            "PUT",
            f"/{self._config.bucket}/{_uri_encode(key, True)}",
            body=None,
            file_path=file_path,
            content_length=size,
            content_type="application/gzip",
        )
        return size

    def get_to_file(self, key: str, dest_path: str) -> int:
        status, headers, payload = self._request(
            "GET", f"/{self._config.bucket}/{_uri_encode(key, True)}")
        if status >= 400:  # pragma: no cover - _request raises on HTTP errors
            raise S3Error(status, "GetFailed", key)
        with open(dest_path, "wb") as handle:
            handle.write(payload)
        # Preserve the remote Last-Modified as the file mtime, so the shell
        # staleness gate (`find -mtime +1`) measures remote age, not
        # download time. Pure os.utime — portable, no `touch -d` needed.
        last_modified = headers.get("Last-Modified") or headers.get("last-modified")
        if last_modified:
            try:
                import email.utils as _email_utils

                remote_ts = _email_utils.parsedate_to_datetime(last_modified).timestamp()
                os.utime(dest_path, (remote_ts, remote_ts))
            except (ValueError, TypeError, OverflowError):
                pass
        return len(payload)

    def list_all(self, prefix: str, max_pages: int = 100) -> list[S3Object]:
        collected: list[S3Object] = []
        token: str | None = None
        for _ in range(max_pages):
            query = [("list-type", "2"), ("prefix", prefix), ("max-keys", "1000")]
            if token:
                query.append(("continuation-token", token))
            _, _, payload = self._request("GET", f"/{self._config.bucket}", query=query)
            objects, truncated, token = parse_list_xml(payload)
            collected.extend(objects)
            if not truncated or not token:
                break
        return collected

    def delete_object(self, key: str) -> None:
        self._request("DELETE", f"/{self._config.bucket}/{_uri_encode(key, True)}")

    def put_lifecycle(self, prefix: str, retention_days: int) -> None:
        body = lifecycle_xml(prefix, retention_days).encode("utf-8")
        self._request(
            "PUT",
            f"/{self._config.bucket}",
            query=[("lifecycle", "")],
            body=body,
            content_type="application/xml",
        )


def _s3_code(exc: urllib.error.HTTPError) -> str:
    try:
        payload = exc.read()
    except OSError:
        return "HTTPError"
    try:
        node = ET.fromstring(payload).find(".//Code")
        return node.text if node is not None and node.text else "HTTPError"
    except ET.ParseError:
        return "HTTPError"


def _s3_message(exc: urllib.error.HTTPError) -> str:
    try:
        payload = exc.read()
    except OSError:  # pragma: no cover - body already consumed by _s3_code
        return exc.reason if isinstance(exc.reason, str) else "request failed"
    try:
        node = ET.fromstring(payload).find(".//Message")
        if node is not None and node.text:
            return node.text
    except ET.ParseError:
        pass
    return exc.reason if isinstance(exc.reason, str) else "request failed"


# ── CLI ───────────────────────────────────────────────────────────────────


def _client_or_skip(config: OffsiteConfig) -> S3Client | None:
    attempt, reason = should_attempt(config)
    if not attempt:
        print(f"SKIP: off-site S3 copy skipped: {reason}")
        return None
    return S3Client(config)


def cmd_upload(config: OffsiteConfig, local_file: str, key: str | None) -> int:
    client = _client_or_skip(config)
    if client is None:
        return EXIT_SKIPPED
    if not os.path.isfile(local_file):
        print(f"ERROR: local file not found: {local_file}", file=sys.stderr)
        return EXIT_ERROR
    object_key = key or build_key(config.prefix, os.path.basename(local_file))
    try:
        client.ensure_bucket()
        size = client.put_file(object_key, local_file)
    except S3Error as exc:
        print(f"ERROR: upload failed for {s3_uri(config, object_key)}: {exc}",
              file=sys.stderr)
        return EXIT_ERROR
    print(f"uploaded {s3_uri(config, object_key)} ({size} bytes)")
    return EXIT_OK


def cmd_latest(config: OffsiteConfig, prefix: str | None) -> int:
    client = _client_or_skip(config)
    if client is None:
        return EXIT_SKIPPED
    wanted = prefix if prefix is not None else config.prefix
    try:
        objects = client.list_all(wanted.strip().strip("/") + "/")
    except S3Error as exc:
        print(f"ERROR: S3 list failed on bucket {config.bucket}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    if not objects:
        print(f"ERROR: no backups under s3://{config.bucket}/{wanted}/", file=sys.stderr)
        return EXIT_ERROR
    newest = max(objects, key=lambda obj: obj.last_modified)
    print(newest.key)
    return EXIT_OK


def cmd_download(config: OffsiteConfig, key: str, dest: str) -> int:
    client = _client_or_skip(config)
    if client is None:
        return EXIT_SKIPPED
    try:
        size = client.get_to_file(key, dest)
    except S3Error as exc:
        print(f"ERROR: download failed for {s3_uri(config, key)}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    print(f"downloaded {s3_uri(config, key)} -> {dest} ({size} bytes)")
    return EXIT_OK


def cmd_prune(
    config: OffsiteConfig, prefix: str | None, retention_days: int | None,
    now: datetime | None = None,
) -> int:
    client = _client_or_skip(config)
    if client is None:
        return EXIT_SKIPPED
    wanted = (prefix if prefix is not None else config.prefix).strip().strip("/")
    days = retention_days if retention_days is not None else config.retention_days
    moment = now or datetime.now(timezone.utc)
    try:
        objects = client.list_all(wanted + "/")
    except S3Error as exc:
        print(f"ERROR: S3 list failed on bucket {config.bucket}: {exc}", file=sys.stderr)
        return EXIT_ERROR
    expired = select_expired(objects, moment, days)
    deleted = 0
    for obj in expired:
        try:
            client.delete_object(obj.key)
            deleted += 1
        except S3Error as exc:
            print(f"WARN: could not delete {s3_uri(config, obj.key)}: {exc}",
                  file=sys.stderr)
    kept = len(objects) - len(expired)
    print(f"prune: deleted {deleted}/{len(expired)} expired, kept {kept} "
          f"(retention {days}d, prefix {wanted}/)")
    return EXIT_OK


def cmd_ensure_lifecycle(
    config: OffsiteConfig, prefix: str | None, retention_days: int | None
) -> int:
    client = _client_or_skip(config)
    if client is None:
        return EXIT_SKIPPED
    wanted = (prefix if prefix is not None else config.prefix).strip().strip("/")
    days = retention_days if retention_days is not None else config.retention_days
    try:
        client.put_lifecycle(wanted, days)
    except S3Error as exc:
        print(f"ERROR: lifecycle configuration failed on bucket {config.bucket}: {exc}",
              file=sys.stderr)
        return EXIT_ERROR
    print(f"lifecycle: s3://{config.bucket}/{wanted}/ expires after {days}d")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="ConvocaRadar off-site backup copy (S3/MinIO, stdlib only).")
    sub = parser.add_subparsers(dest="command", required=True)

    upload = sub.add_parser("upload", help="upload a validated .sql.gz archive")
    upload.add_argument("local_file")
    upload.add_argument("--key", default=None)

    latest = sub.add_parser("latest", help="print the newest remote backup key")
    latest.add_argument("--prefix", default=None)

    download = sub.add_parser("download", help="download a remote backup key to a file")
    download.add_argument("key")
    download.add_argument("dest")

    prune = sub.add_parser("prune", help="delete remote backups older than retention")
    prune.add_argument("--prefix", default=None)
    prune.add_argument("--retention-days", type=int, default=None)

    lifecycle = sub.add_parser(
        "ensure-lifecycle", help="declare bucket lifecycle expiry for the prefix")
    lifecycle.add_argument("--prefix", default=None)
    lifecycle.add_argument("--retention-days", type=int, default=None)
    return parser


def main(argv: list[str] | None = None, env: dict | None = None) -> int:
    args = build_parser().parse_args(argv)
    config = config_from_env(env if env is not None else os.environ)
    if args.command == "upload":
        return cmd_upload(config, args.local_file, args.key)
    if args.command == "latest":
        return cmd_latest(config, args.prefix)
    if args.command == "download":
        return cmd_download(config, args.key, args.dest)
    if args.command == "prune":
        return cmd_prune(config, args.prefix, args.retention_days)
    if args.command == "ensure-lifecycle":
        return cmd_ensure_lifecycle(config, args.prefix, args.retention_days)
    raise AssertionError(f"unknown command {args.command}")  # pragma: no cover


if __name__ == "__main__":
    sys.exit(main())
