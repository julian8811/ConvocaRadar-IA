"""Off-site backup copy (T6): S3/MinIO helper contract tests.

Covers scripts/backup_offsite.py without any network: SigV4 signing against
the AWS documented vector, enabled-mode truth table, key/retention/lifecycle
logic, LIST parsing, and prune selection with a stub client.
"""

from __future__ import annotations

import hashlib
import importlib.util
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
OFFSITE_PATH = REPO_ROOT / "scripts" / "backup_offsite.py"


def _load():
    # Register under its own name before exec: dataclasses resolves
    # `str | None` annotations via sys.modules (same as a normal import).
    spec = importlib.util.spec_from_file_location("backup_offsite", OFFSITE_PATH)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules["backup_offsite"] = mod
    spec.loader.exec_module(mod)
    return mod


FULL_ENV = {
    "BACKUP_S3_ENABLED": "auto",
    "S3_ENDPOINT_URL": "http://minio:9000",
    "S3_ACCESS_KEY": "minio",
    "S3_SECRET_KEY": "secret",
    "S3_REGION": "auto",
    "S3_BUCKET": "convocaradar",
    "BACKUP_S3_PREFIX": "backups",
    "BACKUP_S3_RETENTION_DAYS": "30",
}


class TestSigV4:
    def test_matches_botocore_for_s3_put(self):
        """Our SigV4 must agree byte-for-byte with botocore (independent oracle).

        Frozen clock + identical S3 PUT (path-style URL, one query param);
        both sign host / x-amz-content-sha256 / x-amz-date over the real
        payload hash.
        """
        import datetime as dt_module
        from unittest.mock import patch

        botocore_auth = pytest.importorskip("botocore.auth")
        awsrequest = pytest.importorskip("botocore.awsrequest")
        credentials_mod = pytest.importorskip("botocore.credentials")

        mod = _load()
        body = b"hello-backup-test"
        payload_hash = hashlib.sha256(body).hexdigest()
        amz_date = "20260925T033000Z"
        frozen = dt_module.datetime(2026, 9, 25, 3, 30, tzinfo=dt_module.timezone.utc)

        class _Frozen(dt_module.datetime):
            @classmethod
            def now(cls, tz=None):
                return frozen

            @classmethod
            def utcnow(cls):
                return frozen.replace(tzinfo=None)

        mine = mod.sigv4_authorization(
            secret_key="sk", access_key="ak", region="us-east-1", service="s3",
            method="PUT", path="/convocaradar/backups/f.sql.gz", query=[("x", "1")],
            host="minio:9000", payload_hash=payload_hash, amz_date=amz_date,
        )
        request = awsrequest.AWSRequest(
            method="PUT",
            url="http://minio:9000/convocaradar/backups/f.sql.gz?x=1",
            data=body,
            headers={"x-amz-content-sha256": payload_hash, "x-amz-date": amz_date},
        )
        with patch.object(botocore_auth.datetime, "datetime", _Frozen):
            botocore_auth.SigV4Auth(
                credentials_mod.Credentials("ak", "sk"), "s3", "us-east-1"
            ).add_auth(request)
        assert request.headers["Authorization"] == mine

    def test_signature_changes_with_payload(self):
        mod = _load()
        kwargs = dict(
            secret_key="secret", access_key="ak", region="us-east-1", service="s3",
            method="PUT", path="/b/k", query=[], host="minio:9000",
            amz_date="20260925T033000Z",
        )
        first = mod.sigv4_authorization(payload_hash="a" * 64, **kwargs)
        second = mod.sigv4_authorization(payload_hash="b" * 64, **kwargs)
        assert first != second


class TestEnabledMode:
    def test_auto_attempts_when_configured(self):
        mod = _load()
        attempt, _ = mod.should_attempt(mod.config_from_env(dict(FULL_ENV)))
        assert attempt is True

    def test_auto_skips_when_endpoint_missing(self):
        mod = _load()
        env = dict(FULL_ENV)
        del env["S3_ENDPOINT_URL"]
        attempt, reason = mod.should_attempt(mod.config_from_env(env))
        assert attempt is False
        assert "S3_ENDPOINT_URL" in reason

    def test_false_disables_even_when_configured(self):
        mod = _load()
        env = dict(FULL_ENV, BACKUP_S3_ENABLED="false")
        attempt, reason = mod.should_attempt(mod.config_from_env(env))
        assert attempt is False
        assert "disabled" in reason

    def test_true_forces_attempt_when_configured(self):
        mod = _load()
        env = dict(FULL_ENV, BACKUP_S3_ENABLED="true")
        attempt, reason = mod.should_attempt(mod.config_from_env(env))
        assert attempt is True
        assert "forced" in reason

    def test_true_without_config_stays_skipped(self):
        """Forced mode without credentials must skip loudly, never crash."""
        mod = _load()
        attempt, _ = mod.should_attempt(mod.config_from_env({"BACKUP_S3_ENABLED": "true"}))
        assert attempt is False

    def test_upload_returns_skipped_exit_code(self, tmp_path, capsys):
        mod = _load()
        target = tmp_path / "convocaradar-20260925T033000Z.sql.gz"
        target.write_bytes(b"x" * 200)
        rc = mod.cmd_upload(mod.config_from_env({}), str(target), None)
        assert rc == mod.EXIT_SKIPPED
        assert "SKIP" in capsys.readouterr().out


class TestKeysAndRegion:
    def test_build_key_normalizes_prefix(self):
        mod = _load()
        assert mod.build_key("backups", "convocaradar-2026.sql.gz") == \
            "backups/convocaradar-2026.sql.gz"
        assert mod.build_key("/backups/", "/tmp/convocaradar-2026.sql.gz") == \
            "backups/convocaradar-2026.sql.gz"
        assert mod.build_key("", "f.sql.gz") == "f.sql.gz"

    def test_region_auto_sanitized(self):
        mod = _load()
        assert mod.config_from_env(dict(FULL_ENV)).region == "us-east-1"
        assert mod.config_from_env({**FULL_ENV, "S3_REGION": ""}).region == "us-east-1"
        assert mod.config_from_env({**FULL_ENV, "S3_REGION": "eu-west-1"}).region == \
            "eu-west-1"

    def test_backup_bucket_overrides_app_bucket(self):
        mod = _load()
        config = mod.config_from_env({**FULL_ENV, "BACKUP_S3_BUCKET": "offsite-vault"})
        assert config.bucket == "offsite-vault"
        assert mod.config_from_env(dict(FULL_ENV)).bucket == "convocaradar"


class TestRetentionAndLifecycle:
    def _objects(self, mod):
        now = datetime(2026, 9, 25, 3, 30, tzinfo=timezone.utc)
        return now, [
            mod.S3Object("backups/new.sql.gz", now - timedelta(days=1), 500),
            mod.S3Object("backups/boundary.sql.gz", now - timedelta(days=30), 500),
            mod.S3Object("backups/old.sql.gz", now - timedelta(days=31), 500),
        ]

    def test_select_expired_keeps_boundary_day(self):
        mod = _load()
        now, objects = self._objects(mod)
        expired = mod.select_expired(objects, now, 30)
        assert [obj.key for obj in expired] == ["backups/old.sql.gz"]

    def test_lifecycle_xml_declares_expiry(self):
        mod = _load()
        xml = mod.lifecycle_xml("backups", 30)
        assert "<Days>30</Days>" in xml
        assert "<Prefix>backups/</Prefix>" in xml
        assert "<Status>Enabled</Status>" in xml

    def test_prune_deletes_only_expired(self, monkeypatch):
        mod = _load()
        now, objects = self._objects(mod)

        class StubClient:
            def __init__(self, config):
                self.deleted: list[str] = []

            def list_all(self, prefix):
                assert prefix == "backups/"
                return objects

            def delete_object(self, key):
                self.deleted.append(key)

        stub = StubClient(None)
        monkeypatch.setattr(mod, "S3Client", lambda config: stub)
        config = mod.config_from_env(dict(FULL_ENV))
        rc = mod.cmd_prune(config, None, None, now=now)
        assert rc == mod.EXIT_OK
        assert stub.deleted == ["backups/old.sql.gz"]

    def test_parse_list_xml_with_pagination_token(self):
        mod = _load()
        payload = (
            b'<?xml version="1.0" encoding="UTF-8"?>'
            b'<ListBucketResult xmlns="http://s3.amazonaws.com/doc/2006-03-01/">'
            b"<IsTruncated>true</IsTruncated>"
            b"<NextContinuationToken>tok123</NextContinuationToken>"
            b"<Contents><Key>backups/a.sql.gz</Key>"
            b"<LastModified>2026-09-20T03:30:00.000Z</LastModified>"
            b"<Size>512</Size></Contents>"
            b"<Contents><Key>backups/b.sql.gz</Key>"
            b"<LastModified>2026-09-24T03:30:00Z</LastModified>"
            b"<Size>1024</Size></Contents>"
            b"</ListBucketResult>"
        )
        objects, truncated, token = mod.parse_list_xml(payload)
        assert [obj.key for obj in objects] == ["backups/a.sql.gz", "backups/b.sql.gz"]
        assert objects[0].size == 512
        assert objects[1].last_modified == datetime(2026, 9, 24, 3, 30,
                                                     tzinfo=timezone.utc)
        assert truncated is True
        assert token == "tok123"
