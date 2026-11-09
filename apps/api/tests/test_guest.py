import json
import os
import secrets
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from threading import Barrier

import httpx
import pytest
from conftest import chat, ready, upload
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from test_byok import KEY, MASTER, ROOT, mock_http, payload

from nexus.auth import GUEST_COOKIE, add_user
from nexus.config import Settings
from nexus.database import GuestSession, ProviderConfiguration, Workspace
from nexus.main import create_app

ORIGIN = "https://testserver"
REPLACEMENT = "replacement-test-key-12345"


@pytest.fixture(params=["sqlite", "postgresql"])
def guest_apps(request, tmp_path):
    database_url = ""
    engine = None
    schema = "nexus_guest_test_" + secrets.token_hex(8)
    if request.param == "postgresql":
        url = os.environ.get("NEXUS_TEST_POSTGRES_URL")
        if not url:
            pytest.skip("Set NEXUS_TEST_POSTGRES_URL to a disposable PostgreSQL database.")
        url = make_url(url).set(drivername="postgresql+psycopg")
        engine = create_engine(url, hide_parameters=True)
        with engine.begin() as connection:
            connection.execute(text(f"CREATE SCHEMA {schema}"))
        database_url = url.update_query_dict({"options": f"-csearch_path={schema}"}).render_as_string(
            hide_password=False
        )
    try:
        with ExitStack() as stack:
            apps = []
            for index in range(2 if engine else 1):
                settings = Settings(
                    _env_file=None,
                    profile="server",
                    data_dir=tmp_path / str(index),
                    database_url=database_url,
                    cors_origins=[ORIGIN],
                    guest_access=True,
                    guest_session_secret="test-only-guest-secret-" + "s" * 32,
                    byok_master_key=MASTER,
                    embedding_provider="hash",
                    worker_enabled=index == 0,
                    login_limit_per_minute=30,
                    rate_limit_per_minute=10000,
                )
                app = create_app(settings)
                stack.enter_context(TestClient(app, base_url=ORIGIN))
                apps.append(app)
            yield apps[0], apps[-1]
    finally:
        if engine:
            with engine.begin() as connection:
                connection.execute(text(f"DROP SCHEMA {schema} CASCADE"))
            engine.dispose()


def bootstrap(client, nonce=None):
    response = client.post("/api/auth/guest", json={"nonce": nonce or secrets.token_hex(32)})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    assert response.json()["guest"] and response.json()["user"] is None
    return response


def browser(app):
    return TestClient(app, base_url=ORIGIN, headers={"Origin": ORIGIN})


def workspace(client):
    spaces = client.get("/api/workspaces").json()
    assert len(spaces) == 1
    return spaces[0]["id"]


def test_guest_bootstrap_concurrency_expiry_and_csrf(guest_apps):
    app, other_app = guest_apps
    first, second = browser(app), browser(other_app)
    nonce, barrier = secrets.token_hex(32), Barrier(2)

    def initialize(client):
        barrier.wait()
        return bootstrap(client, nonce)

    with ThreadPoolExecutor(2) as pool:
        results = list(pool.map(initialize, [first, second]))

    cookie = results[0].headers["set-cookie"]
    assert cookie.startswith(GUEST_COOKIE + "=")
    assert all(
        attribute in cookie.lower() for attribute in ("secure", "httponly", "samesite=strict", "path=/")
    )
    assert "domain=" not in cookie.lower()
    assert first.cookies.get(GUEST_COOKIE) == second.cookies.get(GUEST_COOKIE)
    original = workspace(first)
    assert workspace(second) == original
    with app.state.service.sessions.begin() as session:
        assert len(list(session.scalars(select(Workspace)))) == 1
        assert len(list(session.scalars(select(GuestSession)))) == 1
    assert first.get("/api/auth/me").json()["csrf"] == first.headers["X-CSRF-Token"]
    assert first.post(f"/api/workspaces/{original}/chats", headers={"X-CSRF-Token": ""}).status_code == 403
    assert (
        first.post(
            f"/api/workspaces/{original}/chats", headers={"Origin": "https://other.example"}
        ).status_code
        == 403
    )
    with app.state.service.sessions.begin() as session:
        session.scalar(select(GuestSession)).expires_at = 0
    assert first.get("/api/workspaces").status_code == 401
    assert first.post("/api/auth/guest", json={"nonce": nonce}).status_code == 409
    bootstrap(first)
    assert workspace(first) != original
    assert first.get(f"/api/workspaces/{original}/chats").status_code == 404


def test_guest_model_activation_and_private_workspaces(guest_apps, monkeypatch):
    app, other_app = guest_apps
    first, second, account = browser(app), browser(other_app), browser(other_app)
    bootstrap(first)
    bootstrap(second)
    one, two = workspace(first), workspace(second)
    assert one != two
    assert first.get("/health").json() == {"status": "ok"}
    conversation = chat(first, one)
    send = f"/api/chats/{conversation}/messages?workspace_id={one}"
    request = {"content": "How does this work?"}
    missing = first.post(send, json=request)
    assert missing.status_code == 409 and "Select an LLM" in missing.text

    calls = []

    def provider(upstream):
        key = upstream.headers["authorization"].removeprefix("Bearer ")
        if key not in {KEY, REPLACEMENT}:
            return httpx.Response(401, json={"error": key})
        if upstream.url.path.endswith("/auth/key"):
            return httpx.Response(200, json={"data": {}})
        if upstream.url.path.endswith("/models"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {"id": model, "name": model, "pricing": {"prompt": "0", "completion": "0"}}
                        for model in ("test-model", "replacement-model")
                    ]
                },
            )
        body = json.loads(upstream.content)
        calls.append((body["model"], key))
        content = body["messages"][-1]["content"]
        answer = "Answer from the selected model."
        if content.startswith('{"question"'):
            answer += " [" + json.loads(content)["evidence"][0]["citation_id"] + "]"
        return httpx.Response(200, json={"choices": [{"message": {"content": answer}}]})

    mock_http(monkeypatch, provider)
    selection = f"/api/workspaces/{one}/ai-selection"
    save = selection + "/configuration"
    invalid_key = "invalid-test-secret-67890"
    result = first.post(ROOT + "/preview", json=payload(api_key=invalid_key))
    assert result.json()["connection"]["status"] == "invalid_credentials"
    assert invalid_key not in result.text
    body = payload(allow_workspace_cloud=True, allow_paid=False, streaming=False)
    assert first.put(save, json={**body, "remote_consent": False}).status_code == 403
    assert first.get(ROOT).json()["configurations"] == []
    result = first.put(save, json=body)
    assert result.status_code == 200, result.text
    identifier = result.json()["id"]
    assert KEY not in result.text
    with other_app.state.service.sessions() as session:
        row = session.get(ProviderConfiguration, identifier)
        assert KEY not in row.encrypted_key
        assert other_app.state.service.byok.vault.decrypt(row) == KEY
    assert first.get(selection).json()["active"]["id"] == identifier
    assert first.post(send, json=request).json()["content"] == "Answer from the selected model."

    updated = {**body, "configuration_id": identifier, "model": "replacement-model", "api_key": REPLACEMENT}
    assert first.put(save, json=updated).status_code == 200
    document = upload(first, one, content=b"# Private proof\nAurora workspace proof.")["document"]["id"]
    ready(first, one, document)
    grounded = first.post(send, json={"content": "What is the Aurora workspace proof?"})
    assert grounded.status_code == 200 and grounded.json()["citations"], grounded.text
    assert calls == [("test-model", KEY), ("replacement-model", REPLACEMENT)]
    assert browser(other_app).get("/api/workspaces").status_code == 401
    assert first.get(f"/api/documents/{document}/file?workspace_id={one}").content.startswith(b"# Private")
    assert second.get(f"/api/documents/{document}?workspace_id={one}").status_code == 404
    assert second.get(f"/api/documents/{document}?workspace_id={two}").status_code == 404
    assert second.get(f"/api/chats/{conversation}?workspace_id={one}").status_code == 404
    assert second.get(f"/api/chats/{conversation}?workspace_id={two}").status_code == 404
    assert second.get(ROOT).json()["configurations"] == []
    assert second.delete(f"{ROOT}/{identifier}/credential").status_code == 404
    assert second.post(ROOT + "/preview", json=payload(configuration_id=identifier)).status_code == 404
    assert (
        second.put(f"/api/workspaces/{two}/ai-selection", json={"configuration_id": identifier}).status_code
        == 404
    )

    with app.state.service.sessions.begin() as session:
        add_user(session, "private-admin", "Test account password 123", admin=True)
    login = account.post(
        "/api/auth/login", json={"username": "private-admin", "password": "Test account password 123"}
    )
    account.headers["X-CSRF-Token"] = login.json()["csrf"]
    private = account.post("/api/workspaces", json={"name": "Private account workspace"}).json()["id"]
    assert workspace(account) == private
    assert first.get(f"/api/workspaces/{private}/chats").status_code == 404
    assert account.get(f"/api/workspaces/{one}/chats").status_code == 404
    assert first.patch("/api/settings/public", json={}).status_code == 403
    assert first.post("/api/providers/groq/check").status_code == 403
    assert first.get(f"/api/workspaces/{one}/members").status_code == 403
    assert first.post(f"/api/workspaces/{one}/provider-check").status_code == 403
    assert first.delete(f"{ROOT}/{identifier}/credential").status_code == 204
    assert not first.get(selection).json()["active"]["credential_configured"]
    assert first.post(send, json=request).status_code == 409
    assert len(calls) == 2
