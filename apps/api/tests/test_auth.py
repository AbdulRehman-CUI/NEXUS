import time

import pytest
from conftest import ready, upload
from fastapi.testclient import TestClient

from nexus.auth import COOKIE, add_user, csrf_token, system_scope, token_hash
from nexus.config import Settings
from nexus.database import AuthSession
from nexus.main import create_app


@pytest.fixture
def server(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        profile="server",
        embedding_provider="hash",
        secure_cookies=False,
        worker_enabled=True,
        rate_limit_per_minute=10000,
        login_limit_per_minute=30,
    )
    with TestClient(create_app(settings)) as client:
        with client.app.state.service.sessions.begin() as session:
            add_user(session, "alice", "Alice password 123", True)
            add_user(session, "bobby", "Bobby password 456")
        yield client


def login(client, username="alice"):
    password = "Alice password 123" if username == "alice" else "Bobby password 456"
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    client.headers["X-CSRF-Token"] = response.json()["csrf"]
    return response


def test_sessions_csrf_expiry_logout_roles(server):
    assert server.get("/health").json() == {"status": "ok"}
    unauthenticated = server.get("/api/workspaces", headers={"Origin": "http://127.0.0.1:3000"})
    assert unauthenticated.status_code == 401
    assert unauthenticated.headers["access-control-allow-origin"] == "http://127.0.0.1:3000"
    assert unauthenticated.headers["access-control-allow-credentials"] == "true"
    assert server.get("/api/workspaces").status_code == 401
    assert server.post("/api/auth/login", json={"username": "alice", "password": "bad"}).status_code == 401
    response = login(server)
    cookie = response.headers["set-cookie"]
    assert "HttpOnly" in cookie and "SameSite=strict" in cookie
    token = server.cookies.get(COOKIE)
    workspace = server.post("/api/workspaces", json={"name": "Private"}).json()["id"]
    server.headers.pop("X-CSRF-Token")
    assert server.patch(f"/api/workspaces/{workspace}", json={"name": "CSRF"}).status_code == 403
    server.headers["X-CSRF-Token"] = csrf_token(token)
    assert (
        server.put(
            f"/api/workspaces/{workspace}/members", json={"username": "bobby", "role": "viewer"}
        ).status_code
        == 200
    )
    login(server, "bobby")
    assert server.get(f"/api/workspaces/{workspace}/documents").status_code == 200
    assert server.post(f"/api/workspaces/{workspace}/chats").status_code == 403
    assert (
        server.post(
            f"/api/workspaces/{workspace}/compare", json={"question": "test", "policies": [{}, {}]}
        ).status_code
        == 403
    )
    assert (
        server.patch(f"/api/workspaces/{workspace}/retrieval-settings", json={"top_k": 1}).status_code == 403
    )
    assert (
        server.patch(
            "/api/settings/public",
            json={"generation_provider": "mock", "generation_model": "demo", "free_tier_confirmed": False},
        ).status_code
        == 403
    )
    session_token = server.cookies.get(COOKIE)
    with server.app.state.service.sessions.begin() as session:
        session.get(AuthSession, token_hash(session_token)).expires_at = int(time.time()) - 1
    assert server.get("/api/workspaces").status_code == 401
    login(server)
    assert server.post("/api/auth/logout").status_code == 204
    assert server.get("/api/workspaces").status_code == 401


def test_cross_user_all_scoped_surfaces(server):
    from test_vaults import import_zip

    login(server)
    workspace = server.post("/api/workspaces", json={"name": "Alice private"}).json()["id"]
    item = upload(server, workspace)
    ready(server, workspace, item["document"]["id"])
    vault = import_zip(server, workspace, {"a.md": "# A\n[[b]] #tag", "b.md": "# B\nOther source."})["vault"][
        "id"
    ]
    conversation = server.post(f"/api/workspaces/{workspace}/chats").json()["id"]
    answer = server.post(
        f"/api/chats/{conversation}/messages?workspace_id={workspace}", json={"content": "Aurora"}
    ).json()
    source = answer["citations"][0]["source_url"]
    index = server.get(f"/api/workspaces/{workspace}/index-versions").json()[0]["id"]
    note = server.get(f"/api/vaults/{vault}/notes?workspace_id={workspace}").json()["notes"][0]["id"]
    login(server, "bobby")
    assert server.get("/api/workspaces").json() == []
    document = item["document"]["id"]
    reads = [
        f"/api/workspaces/{workspace}/documents",
        f"/api/documents/{document}?workspace_id={workspace}",
        source,
        f"/api/documents/{document}/file?workspace_id={workspace}",
        f"/api/workspaces/{workspace}/chats",
        f"/api/chats/{conversation}?workspace_id={workspace}",
        f"/api/workspaces/{workspace}/graph",
        f"/api/workspaces/{workspace}/vaults",
        f"/api/vaults/{vault}/notes?workspace_id={workspace}",
        f"/api/vaults/{vault}/links?workspace_id={workspace}",
        f"/api/vaults/{vault}/sync-status?workspace_id={workspace}",
        f"/api/notes/{note}?workspace_id={workspace}",
        f"/api/jobs/{item['job_id']}?workspace_id={workspace}",
        f"/api/workspaces/{workspace}/index-versions",
        f"/api/workspaces/{workspace}/retrieval-settings",
        f"/api/workspaces/{workspace}/route-policy",
        f"/api/workspaces/{workspace}/diagnostics",
        f"/api/workspaces/{workspace}/settings-export",
        f"/api/workspaces/{workspace}/reviews",
        f"/api/workspaces/{workspace}/jobs",
    ]
    for path in reads:
        assert server.get(path).status_code == 404, path
    posts = [
        (f"/api/workspaces/{workspace}/search", {"query": "Aurora"}),
        (f"/api/chats/{conversation}/messages?workspace_id={workspace}", {"content": "Aurora"}),
        (f"/api/vaults/{vault}/sync?workspace_id={workspace}", None),
        (f"/api/vaults/{vault}/retry?workspace_id={workspace}", None),
        (f"/api/documents/{document}/reindex?workspace_id={workspace}", None),
        (f"/api/workspaces/{workspace}/indexes/rebuild", {}),
        (f"/api/index-versions/{index}/activate?workspace_id={workspace}", None),
    ]
    for path, body in posts:
        assert server.post(path, json=body).status_code == 404, path
    own = server.post("/api/workspaces", json={"name": "Bobby"}).json()["id"]
    assert (
        server.post(
            f"/api/workspaces/{own}/search", json={"query": "Aurora", "filters": {"document_ids": [document]}}
        ).status_code
        == 404
    )
    assert server.delete(f"/api/documents/{document}?workspace_id={workspace}").status_code == 404
    assert (
        server.post(f"/api/workspaces/{own}/batch-reindex", json={"document_ids": [document]}).status_code
        == 404
    )
    with server.app.state.service.sessions() as session:
        with pytest.raises(Exception) as error:
            server.app.state.service.repo.workspace(session, workspace)
        assert error.value.status_code == 401
        with system_scope():
            assert server.app.state.service.repo.workspace(session, workspace)


def test_local_profile_exposure_and_rate_limit(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", rate_limit_per_minute=5)
    with TestClient(create_app(settings), client=("203.0.113.9", 123)) as client:
        assert client.get("/api/workspaces").status_code == 403
    with TestClient(create_app(settings)) as client:
        for _ in range(5):
            assert client.get("/api/auth/me").status_code == 200
        response = client.get("/api/auth/me")
        assert response.status_code == 429 and response.headers["retry-after"] == "60"
        assert "x-request-id" in response.headers
