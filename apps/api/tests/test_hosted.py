"""PostgreSQL integration: persistence, private setup, tenancy, retrieval and deletion."""

import base64
import os
import secrets
import shutil

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from nexus.auth import token_hash
from nexus.config import Settings
from nexus.main import create_app

pytestmark = pytest.mark.skipif(
    not os.getenv("NEXUS_TEST_DATABASE_URL"), reason="requires isolated PostgreSQL with pgvector"
)


def test_hosted_full_flow_survives_cold_start(tmp_path):
    schema = "nexus_test_" + secrets.token_hex(6)
    token = secrets.token_urlsafe(32)
    settings = Settings(
        _env_file=None,
        hosted=True,
        database_url=os.environ["NEXUS_TEST_DATABASE_URL"],
        database_schema=schema,
        data_dir=tmp_path,
        secure_cookies=False,
        setup_token_hash=token_hash(token),
        byok_master_key=base64.b64encode(os.urandom(32)).decode(),
        embedding_provider="hash",
        rate_limit_per_minute=10000,
        login_limit_per_minute=30,
    )
    engine = None
    content = b"# Aurora\nAurora launch is on 14 November 2026. The escalation code is QUARTZ-971."
    credentials = {"username": "owner", "password": "test-only-long-password"}
    try:
        with TestClient(create_app(settings)) as client:
            engine = client.app.state.engine
            assert client.get("/health").json() == {"status": "ok"}
            assert client.get("/api/workspaces").status_code == 401
            assert client.get("/api/auth/setup").json()["available"]
            assert client.post("/api/auth/setup", json={**credentials, "token": "x" * 40}).status_code == 403
            assert client.post("/api/auth/setup", json={**credentials, "token": token}).status_code == 201
            assert client.post("/api/auth/setup", json={**credentials, "token": token}).status_code == 409
            login = client.post("/api/auth/login", json=credentials)
            assert login.status_code == 200, login.text
            client.headers["X-CSRF-Token"] = login.json()["csrf"]
            workspace_response = client.post("/api/workspaces", json={"name": "Cloud integration"})
            assert workspace_response.status_code == 201, workspace_response.text
            workspace = workspace_response.json()["id"]
            uploaded = client.post(
                f"/api/workspaces/{workspace}/documents",
                files={"file": ("aurora.md", content, "text/markdown")},
            )
            assert uploaded.status_code == 202, uploaded.text
            document = uploaded.json()["document"]["id"]
            status = client.get(f"/api/documents/{document}?workspace_id={workspace}")
            assert status.status_code == 200, status.text
            assert status.json()["status"] == "ready", status.text
            assert client.app.state.service.thread is None
            for mode in ("keyword", "semantic", "hybrid"):
                result = client.post(
                    f"/api/workspaces/{workspace}/search",
                    json={"query": "Aurora launch", "options": {"mode": mode}},
                )
                assert result.status_code == 200, result.text
                assert result.json()["results"][0]["document_id"] == document
            other = client.post("/api/workspaces", json={"name": "Other"}).json()["id"]
            assert (
                client.post(f"/api/workspaces/{other}/search", json={"query": "Aurora"}).json()["results"]
                == []
            )
            assert client.get(f"/api/documents/{document}/file?workspace_id={other}").status_code == 404
            assert client.get(f"/api/documents/{document}/file?workspace_id={workspace}").content == content
            # Persist the provider configuration and session alongside the document.
            saved = client.patch(
                "/api/settings/public",
                json={
                    "generation_provider": "mock",
                    "generation_model": "test-model",
                    "free_tier_confirmed": False,
                },
            )
            assert saved.status_code == 200, saved.text
            cookies = dict(client.cookies)
        shutil.rmtree(tmp_path)
        with TestClient(create_app(settings.model_copy())) as client:
            client.cookies.update(cookies)
            identity = client.get("/api/auth/me")
            assert identity.status_code == 200, identity.text
            client.headers["X-CSRF-Token"] = identity.json()["csrf"]
            assert not client.get("/api/auth/setup").json()["available"]
            assert client.get("/api/settings/public").json()["generation_model"] == "test-model"
            assert client.get(f"/api/documents/{document}/file?workspace_id={workspace}").content == content
            assert client.get("/health").json()["database"] == "postgresql"
            chat = client.post(f"/api/workspaces/{workspace}/chats").json()["id"]
            answer = client.post(
                f"/api/chats/{chat}/messages?workspace_id={workspace}",
                json={"content": "When is Aurora launch?"},
            )
            assert answer.status_code == 200, answer.text
            assert client.delete(f"/api/documents/{document}?workspace_id={workspace}").status_code == 202
            client.get(f"/api/workspaces/{workspace}/documents")
            assert (
                client.post(f"/api/workspaces/{workspace}/search", json={"query": "Aurora"}).json()["results"]
                == []
            )
    finally:
        # Only the randomly named test schema can be removed, never an application schema.
        if engine:
            assert schema.startswith("nexus_test_")
            with engine.begin() as connection:
                connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            engine.dispose()
