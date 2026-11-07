"""Create only synthetic browser accounts in an explicitly named artifacts directory."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from fastapi.testclient import TestClient
from nexus.auth import add_user
from nexus.config import Settings
from nexus.main import create_app

root = Path("artifacts/phase3-server-browser").resolve()
if (root / "nexus.sqlite3").exists():
    raise SystemExit(
        "Use a fresh isolated fixture directory; refusing to replace data."
    )
settings = Settings(
    _env_file=None,
    data_dir=root,
    profile="server",
    embedding_provider="hash",
    secure_cookies=False,
    worker_enabled=False,
)
with (
    TestClient(create_app(settings)) as client,
    client.app.state.service.sessions.begin() as session,
):
    add_user(session, "release-owner", "Synthetic owner password 123", True)
    add_user(session, "release-viewer", "Synthetic viewer password 456")
print(
    "Synthetic server browser fixture ready. Never use these test accounts in normal data."
)
