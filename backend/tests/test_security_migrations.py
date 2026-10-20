import logging
import subprocess
import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.logging import JsonFormatter, redact
from app.core.security import (
    create_access_token,
    decode_access_token,
    decrypt_secret,
    encrypt_secret,
    hash_password,
    mask_secret,
    verify_password,
)
from app.schemas.api import SettingsUpdate


def test_password_hashing():
    h = hash_password("correct horse battery")
    assert h.startswith("pbkdf2_sha256$") and "correct" not in h
    assert verify_password("correct horse battery", h)
    assert not verify_password("wrong", h)
    assert not verify_password("x", "garbage")


def test_jwt_roundtrip_and_expiry():
    assert decode_access_token(create_access_token("7")) == "7"
    assert decode_access_token(create_access_token("7", expires_minutes=-1)) is None
    assert decode_access_token("not.a.token") is None


def test_encryption_and_masking():
    ct = encrypt_secret("refresh-token-value")
    assert "refresh" not in ct and decrypt_secret(ct) == "refresh-token-value"
    assert decrypt_secret("tampered") is None
    assert mask_secret("abcdefghijkl") == "…ijkl" and mask_secret(None) is None


def test_log_redaction():
    text = redact("api_key=xai-abcdefghijklmnop Authorization: Bearer ya29.secret refresh_token: 1//abc "
                  "AIza" + "x" * 30)
    assert "abcdefghijklmnop" not in text and "ya29.secret" not in text and "1//abc" not in text
    rec = logging.LogRecord("t", logging.INFO, __file__, 1, "token sk-proj_ABCDEFGHIJKL leaked", None, None)
    assert "ABCDEFGHIJKL" not in JsonFormatter().format(rec)


def test_settings_validation():
    with pytest.raises(ValidationError):
        SettingsUpdate(publish_days=[7])
    with pytest.raises(ValidationError):
        SettingsUpdate(llm_models={"claude": "x"})
    with pytest.raises(ValidationError):
        SettingsUpdate(llm_models={"grok": "bad model; rm -rf"})
    with pytest.raises(ValidationError):
        SettingsUpdate(shorts_resolution="huge")
    assert SettingsUpdate(publish_days=[3, 1, 1]).publish_days == [1, 3]


def test_alembic_migrations_upgrade_and_match_models(tmp_path):
    backend = Path(__file__).resolve().parents[1]
    env = {"DATABASE_URL": f"sqlite:///{tmp_path / 'mig.db'}", "PATH": "/usr/bin:/bin",
           "SECRET_KEY": "test-secret-key-for-unit-tests-only"}
    alembic = [sys.executable, "-m", "alembic"]
    up = subprocess.run([*alembic, "upgrade", "head"], cwd=backend, env=env, capture_output=True, text=True)
    assert up.returncode == 0, up.stderr
    check = subprocess.run([*alembic, "check"], cwd=backend, env=env, capture_output=True, text=True)
    assert check.returncode == 0, check.stderr + check.stdout
    down = subprocess.run([*alembic, "downgrade", "base"], cwd=backend, env=env, capture_output=True, text=True)
    assert down.returncode == 0, down.stderr
