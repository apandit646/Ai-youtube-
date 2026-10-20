"""Test fixtures. Tests never call real external services: all HTTP goes through httpx.MockTransport."""

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="rhymepilot-test-"))
os.environ.update({
    "ENVIRONMENT": "test",
    "DATABASE_URL": os.environ.get("TEST_DATABASE_URL", f"sqlite:///{_TMP / 'test.db'}"),
    "MEDIA_ROOT": str(_TMP / "media"),
    "SECRET_KEY": "test-secret-key-for-unit-tests-only",
    "XAI_API_KEY": "", "XAI_MODEL": "", "OPENAI_API_KEY": "", "OPENAI_MODEL": "", "GEMINI_API_KEY": "",
    "GEMINI_MODEL": "", "YOUTUBE_API_KEY": "", "GOOGLE_OAUTH_CLIENT_ID": "test-client",
    "GOOGLE_OAUTH_CLIENT_SECRET": "test-secret", "LLM_MAX_RETRIES": "1", "TTS_BINARY": "definitely-not-installed",
})

import httpx  # noqa: E402
import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402
from sqlalchemy import create_engine, event  # noqa: E402

from app.core.config import get_settings  # noqa: E402
from app.core.security import create_access_token, hash_password  # noqa: E402
from app.db.base import Base  # noqa: E402
from app.db.session import SessionLocal, set_engine  # noqa: E402
from app.models import User  # noqa: E402
from app.services.media.audio import ProceduralMelodyProvider, SilentNarrationProvider  # noqa: E402
from app.services.media.pipeline import Providers  # noqa: E402
from app.services.media.visuals import PillowVisualProvider  # noqa: E402
from app.services.settings_service import get_app_settings  # noqa: E402

get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _db():
    url = os.environ["DATABASE_URL"]
    engine = create_engine(url, connect_args={"check_same_thread": False} if url.startswith("sqlite") else {})
    if url.startswith("sqlite"):
        @event.listens_for(engine, "connect")
        def _fk(dbapi_conn, _):
            dbapi_conn.execute("PRAGMA foreign_keys=ON")
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    set_engine(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


@pytest.fixture
def user(db):
    u = User(email="owner@example.com", hashed_password=hash_password("correct horse battery"), display_name="Owner")
    db.add(u)
    db.flush()
    s = get_app_settings(db, u.id)
    s.shorts_resolution = "270x480"  # tiny renders keep tests fast
    s.long_resolution = "480x270"
    s.fps = 12
    db.commit()
    return u


@pytest.fixture
def other_user(db):
    u = User(email="intruder@example.com", hashed_password=hash_password("another password!"))
    db.add(u)
    db.commit()
    return u


@pytest.fixture
def client():
    from app.main import app

    return TestClient(app)


@pytest.fixture
def auth(user):
    return {"Authorization": f"Bearer {create_access_token(str(user.id))}"}


@pytest.fixture
def fast_providers():
    return Providers(visual=PillowVisualProvider(), narration=SilentNarrationProvider(),
                     music=ProceduralMelodyProvider())


def mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)
