import base64
import json
import threading

import httpx
import pytest
from conftest import chat, ready, upload
from fastapi.testclient import TestClient

from nexus.auth import add_user
from nexus.byok import ConfigurationInput, CredentialVault
from nexus.config import Settings
from nexus.database import ProviderConfiguration, ProviderUsage
from nexus.main import create_app
from nexus.provider_transport import ProviderTransport

KEY = "test-secret-only-DO-NOT-USE-12345"
MASTER = base64.b64encode(b"m" * 32).decode()
ROOT = "/api/me/provider-configurations"


@pytest.fixture
def byok(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        embedding_provider="hash",
        byok_master_key=MASTER,
        rate_limit_per_minute=10000,
    )
    with TestClient(create_app(settings)) as client:
        yield client


def payload(provider="openrouter", **changes):
    return {
        "name": "My private model",
        "provider": provider,
        "model": "test-model",
        "api_key": KEY if provider != "ollama" else None,
        "remote_consent": True,
        "allow_paid": True,
        **changes,
    }


def save(client, provider="openrouter", **changes):
    response = client.post(ROOT, json=payload(provider, **changes))
    assert response.status_code == 201, response.text
    assert KEY not in response.text and "encrypted_key" not in response.text
    return response.json()


def mock_http(monkeypatch, handler):
    real = httpx.Client

    def guarded(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        return handler(request)

    monkeypatch.setattr(
        "nexus.provider_transport.httpx.Client",
        lambda **kwargs: real(transport=httpx.MockTransport(guarded), **kwargs),
    )


def enable(client, config):
    workspace = client.get("/api/workspaces").json()[0]["id"]
    client.patch(f"/api/workspaces/{workspace}", json={"cloud_opt_in": True})
    response = client.put(
        f"/api/workspaces/{workspace}/ai-selection", json={"configuration_id": config["id"]}
    )
    assert response.status_code == 200, response.text
    return workspace


def evidence_chat(client, workspace):
    document = upload(
        client,
        workspace,
        content=b"# Evidence\nBYOKPROOF preserves source-grounded answers and private models.",
    )
    ready(client, workspace, document["document"]["id"])
    return chat(client, workspace)


def test_encryption_replacement_validation_and_removal(byok, caplog):
    config = save(byok)
    svc = byok.app.state.service
    with svc.sessions() as session:
        row = session.get(ProviderConfiguration, config["id"])
        ciphertext = row.encrypted_key
        assert ciphertext.startswith("v1.") and KEY not in ciphertext
        assert svc.byok.vault.decrypt(row) == KEY
        assert "api_key" not in row.configuration
    updated = byok.put(f"{ROOT}/{config['id']}", json=payload(api_key="replacement-secret-12345"))
    assert updated.status_code == 200 and "replacement-secret" not in updated.text
    with svc.sessions() as session:
        row = session.get(ProviderConfiguration, config["id"])
        assert row.encrypted_key != ciphertext
        assert svc.byok.vault.decrypt(row) == "replacement-secret-12345"
        row.owner = "another-owner"
        with pytest.raises(Exception, match="cannot be decrypted"):
            svc.byok.vault.decrypt(row)
    invalid = byok.put(f"{ROOT}/{config['id']}", json=payload(api_key=KEY + "\nsuffix"))
    assert invalid.status_code == 422 and KEY not in invalid.text
    moved = byok.put(f"{ROOT}/{config['id']}", json=payload("openai"))
    assert moved.status_code == 409
    assert byok.delete(f"{ROOT}/{config['id']}/credential").status_code == 204
    assert not byok.get(ROOT).json()["configurations"][0]["credential_configured"]
    assert KEY not in caplog.text and "replacement-secret" not in caplog.text
    assert KEY.encode() not in (svc.settings.data_dir / "nexus.sqlite3").read_bytes()


def test_missing_or_wrong_master_fails_closed(client):
    response = client.post(ROOT, json=payload())
    assert response.status_code == 503 and KEY not in response.text
    assert client.get(ROOT).json()["credential_storage"]["enabled"] is False
    assert save(client, "ollama")["credential_configured"] is False
    assert CredentialVault(Settings(_env_file=None, byok_master_key="invalid")).enabled is False


def test_two_users_never_share_configs_keys_models_or_usage(tmp_path, monkeypatch):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        profile="server",
        secure_cookies=False,
        embedding_provider="hash",
        byok_master_key=MASTER,
        rate_limit_per_minute=10000,
        login_limit_per_minute=30,
    )
    with TestClient(create_app(settings)) as client:
        with client.app.state.service.sessions.begin() as session:
            add_user(session, "alice", "Alice password 123")
            add_user(session, "bobby", "Bobby password 456")

        def login(name, password):
            result = client.post("/api/auth/login", json={"username": name, "password": password})
            client.headers["X-CSRF-Token"] = result.json()["csrf"]

        login("alice", "Alice password 123")
        workspace = client.post("/api/workspaces", json={"name": "Shared"}).json()["id"]
        client.put(f"/api/workspaces/{workspace}/members", json={"username": "bobby", "role": "editor"})
        config = save(client, model="alice-private-model")
        client.post(f"{ROOT}/{config['id']}/default")
        client.patch(f"/api/workspaces/{workspace}", json={"cloud_opt_in": True})
        conversation = evidence_chat(client, workspace)

        def handler(request):
            assert request.headers["authorization"] == "Bearer " + KEY
            body = json.loads(request.content)
            assert body["model"] == "alice-private-model"
            citation = json.loads(body["messages"][-1]["content"])["evidence"][0]["citation_id"]
            chunk = {
                "choices": [{"delta": {"content": f"Source grounded [{citation}]"}, "finish_reason": "stop"}],
                "usage": {"prompt_tokens": 20, "completion_tokens": 6, "cost": 0.001},
            }
            return httpx.Response(200, text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n")

        mock_http(monkeypatch, handler)
        result = client.post(
            f"/api/chats/{conversation}/messages/stream",
            params={"workspace_id": workspace},
            json={"content": "What does BYOKPROOF preserve?"},
        )
        assert "event: complete" in result.text and KEY not in result.text
        own_usage = client.get("/api/me/provider-usage").json()["events"][0]
        assert own_usage["cost_source"] == "provider_reported" and own_usage["cost_usd"] == 0.001
        with client.app.state.service.sessions.begin() as session:
            session.add(
                ProviderUsage(
                    owner="user:" + client.get("/api/auth/me").json()["user"]["id"],
                    configuration_id=config["id"],
                    workspace_id=workspace,
                    provider="openrouter",
                    model="alice-private-model",
                    status="ok",
                )
            )
        login("bobby", "Bobby password 456")
        assert client.get(ROOT).json()["configurations"] == []
        assert client.get("/api/me/provider-usage").json()["events"] == []
        assert client.get(f"/api/workspaces/{workspace}/ai-selection").json()["active"] is None
        for method, path in [
            ("get", "/models"),
            ("post", "/test"),
            ("post", "/models"),
            ("delete", "/credential"),
            ("post", "/default"),
            ("delete", ""),
        ]:
            response = getattr(client, method)(f"{ROOT}/{config['id']}{path}")
            assert response.status_code == 404
            assert KEY not in response.text and "alice-private-model" not in response.text
        assert (
            client.put(
                f"/api/workspaces/{workspace}/ai-selection", json={"configuration_id": config["id"]}
            ).status_code
            == 404
        )
        client.headers.pop("X-CSRF-Token")
        assert client.post(ROOT, json=payload()).status_code == 403


@pytest.mark.parametrize(
    "status,code",
    [
        (401, "invalid_credentials"),
        (402, "insufficient_quota"),
        (429, "rate_limit_exceeded"),
        (503, "provider_unavailable"),
        (404, "model_unavailable"),
    ],
)
def test_connection_errors_are_real_sanitized_and_do_not_log_out(byok, monkeypatch, status, code):
    config = save(byok)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(status, json={"error": {"message": f"raw provider leak {KEY}"}})

    mock_http(monkeypatch, handler)
    response = byok.post(f"{ROOT}/{config['id']}/test")
    assert response.status_code == 200 and response.json()["status"] == code
    assert calls and str(calls[0].url).endswith("/auth/key")
    assert KEY not in response.text and "raw provider" not in response.text


def test_models_preview_manual_ids_pricing_and_temperature(byok, monkeypatch):
    calls = []

    def handler(request):
        calls.append(str(request.url))
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "id": "free-model",
                        "name": "A free text model",
                        "context_length": 8192,
                        "pricing": {"prompt": "0", "completion": "0"},
                        "supported_parameters": ["temperature"],
                    },
                    {"id": "unknown-model"},
                    {"id": KEY},
                ]
            },
        )

    mock_http(monkeypatch, handler)
    preview = byok.post(ROOT + "/preview", json=payload(model="new-manual-model"))
    assert preview.status_code == 200 and preview.json()["connection"]["model_status"] == "not_listed"
    assert byok.get(ROOT).json()["configurations"] == []
    assert KEY not in preview.text
    config = save(byok, model="new-manual-model")
    models = byok.post(f"{ROOT}/{config['id']}/models").json()["models"]
    assert models[0]["cost_status"] == "free" and models[1]["cost_status"] == "unknown"
    changes = payload(model="free-model", temperature=0.2)
    changes.pop("api_key")
    assert byok.put(f"{ROOT}/{config['id']}", json=changes).status_code == 200
    assert (
        byok.put(
            f"{ROOT}/{config['id']}", json=payload(model="not-cached-model", temperature=None)
        ).status_code
        == 200
    )
    assert all("api_key=" not in url for url in calls)


@pytest.mark.parametrize(
    "provider", ["openrouter", "openai", "groq", "anthropic", "google", "ollama", "compatible"]
)
@pytest.mark.parametrize("streaming", [False, True])
def test_provider_protocols_model_routing_streams_and_usage(monkeypatch, provider, streaming):
    settings = Settings(_env_file=None, provider_allowed_origins=["https://example.test"])
    config = ConfigurationInput.model_validate(payload(provider, streaming=streaming)).model_dump(
        exclude={"api_key"}
    )
    if provider == "compatible":
        config["base_url"] = "https://example.test/v1"
        monkeypatch.setattr(
            "nexus.gateway.socket.getaddrinfo", lambda *a, **kw: [(2, 1, 6, "", ("93.184.216.34", 443))]
        )
    adapter = ProviderTransport(settings, config, "" if provider == "ollama" else KEY)
    records = []

    def handler(request):
        body = json.loads(request.content)
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        records.append((request, body))
        assert body.get("model", config["model"]) == "test-model"
        assert KEY not in request.content.decode()
        if provider == "anthropic":
            assert request.headers["x-api-key"] == KEY
            chunks = [
                {"type": "message_start", "message": {"usage": {"input_tokens": 7}}},
                {"type": "content_block_delta", "delta": {"type": "text_delta", "text": "Grounded [C1]"}},
                {"type": "message_delta", "usage": {"output_tokens": 4}},
                {"type": "message_stop"},
            ]
            result = {
                "content": [{"type": "text", "text": "Grounded [C1]"}],
                "usage": {"input_tokens": 7, "output_tokens": 4},
            }
        elif provider == "google":
            assert request.headers["x-goog-api-key"] == KEY and "maxOutputTokens" in body["generationConfig"]
            result = {
                "candidates": [{"content": {"parts": [{"text": "Grounded [C1]"}]}}],
                "usageMetadata": {"promptTokenCount": 7, "candidatesTokenCount": 4},
            }
            result["candidates"][0]["finishReason"] = "STOP"
            chunks = [result]
        elif provider == "ollama":
            result = {
                "message": {"content": "Grounded [C1]"},
                "done": True,
                "prompt_eval_count": 7,
                "eval_count": 4,
            }
            chunks = [result]
        else:
            assert request.headers["authorization"] == "Bearer " + KEY
            result = {
                "choices": [{"message": {"content": "Grounded [C1]"}}],
                "usage": {"prompt_tokens": 7, "completion_tokens": 4, "cost": 0.0001},
            }
            chunks = [
                {"choices": [{"delta": {"content": "Grounded "}}]},
                {"choices": [{"delta": {"content": "[C1]"}}], "usage": result["usage"]},
            ]
            chunks[-1]["choices"][0]["finish_reason"] = "stop"
        if streaming:
            wire = "\n".join(
                json.dumps(c) if provider == "ollama" else "data: " + json.dumps(c) + "\n" for c in chunks
            )
            return httpx.Response(
                200,
                text=wire,
                headers={
                    "content-type": "application/x-ndjson" if provider == "ollama" else "text/event-stream"
                },
            )
        return httpx.Response(200, json=result)

    real = httpx.Client
    adapter.client_factory = lambda **kwargs: real(transport=httpx.MockTransport(handler), **kwargs)
    deltas = []
    assert (
        adapter.generate("proof", [{"citation_id": "C1", "excerpt": "Grounded"}], deltas.append)
        == "Grounded [C1]"
    )
    assert "".join(deltas) == "Grounded [C1]"
    assert adapter.input_tokens == 7 and adapter.output_tokens == 4
    if provider == "compatible":
        assert records[0][0].url.host == "93.184.216.34" and records[0][0].headers["host"] == "example.test"
        assert records[0][0].extensions["sni_hostname"] == "example.test"


def test_streaming_rag_final_citations_usage_and_revocation(byok, monkeypatch):
    config = save(byok, "ollama", streaming=True, max_calls_per_day=2)
    workspace = enable(byok, config)
    identifier = evidence_chat(byok, workspace)

    def handler(request):
        body = json.loads(request.content)
        evidence = json.loads(body["messages"][-1]["content"])["evidence"]
        cite = evidence[0]["citation_id"]
        return httpx.Response(
            200,
            text="\n".join(
                [
                    json.dumps({"message": {"content": "BYOKPROOF "}}),
                    json.dumps(
                        {
                            "message": {"content": f"preserves sources [{cite}]"},
                            "done": True,
                            "prompt_eval_count": 50,
                            "eval_count": 10,
                        }
                    ),
                ]
            ),
        )

    mock_http(monkeypatch, handler)
    response = byok.post(
        f"/api/chats/{identifier}/messages/stream",
        params={"workspace_id": workspace},
        json={"content": "What does BYOKPROOF preserve?"},
    )
    assert (
        response.status_code == 200
        and "event: delta" in response.text
        and '"provisional": true' in response.text
    )
    completed = [
        json.loads(event.split("data: ", 1)[1])
        for event in response.text.split("\n\n")
        if event.startswith("event: complete")
    ][0]
    assert completed["citations"] and "BYOKPROOF" in completed["content"]
    assert byok.get(completed["citations"][0]["source_url"]).status_code == 200
    usage = byok.get("/api/me/provider-usage").json()["events"][0]
    assert usage["input_tokens"] == 50 and usage["output_tokens"] == 10 and usage["cost_usd"] is None
    assert byok.delete(f"{ROOT}/{config['id']}").status_code == 204
    assert byok.get(ROOT).json()["configurations"] == []
    blocked = byok.post(
        f"/api/chats/{identifier}/messages", params={"workspace_id": workspace}, json={"content": "proof"}
    )
    assert blocked.status_code == 409 and "no fallback" in blocked.text.lower()


def test_privacy_budget_unknown_citations_and_secret_stream_redaction(byok, monkeypatch):
    config = save(byok, streaming=True, allow_paid=False)
    workspace = byok.get("/api/workspaces").json()[0]["id"]
    assert (
        byok.put(
            f"/api/workspaces/{workspace}/ai-selection", json={"configuration_id": config["id"]}
        ).status_code
        == 403
    )
    config = byok.put(f"{ROOT}/{config['id']}", json=payload(streaming=True, max_calls_per_day=1)).json()
    workspace = enable(byok, config)
    identifier = evidence_chat(byok, workspace)

    def handler(request):
        return httpx.Response(
            200,
            text="\n\n".join(
                "data: " + json.dumps({"choices": [{"delta": {"content": part}}]})
                for part in [KEY[:12], KEY[12:], " invalid citation [C99999]"]
            )
            + "\n\ndata: [DONE]\n\n",
        )

    mock_http(monkeypatch, handler)
    response = byok.post(
        f"/api/chats/{identifier}/messages/stream",
        params={"workspace_id": workspace},
        json={"content": "What does BYOKPROOF preserve?"},
    )
    assert KEY not in response.text
    delta_text = "".join(
        json.loads(e.split("data: ", 1)[1])["text"]
        for e in response.text.split("\n\n")
        if e.startswith("event: delta")
    )
    assert KEY not in delta_text and "[redacted]" in delta_text
    assert "event: error" in response.text and "event: complete" not in response.text
    assert byok.get(f"/api/chats/{identifier}", params={"workspace_id": workspace}).json()["messages"] == []
    limited = byok.post(
        f"/api/chats/{identifier}/messages",
        params={"workspace_id": workspace},
        json={"content": "What does BYOKPROOF preserve?"},
    )
    assert limited.status_code == 429


def test_cancellation_and_custom_endpoint_restrictions(byok, monkeypatch):
    config = ConfigurationInput.model_validate(payload("ollama")).model_dump(exclude={"api_key"})
    cancel = threading.Event()
    cancel.set()
    adapter = ProviderTransport(byok.app.state.service.settings, config, cancelled=cancel)
    with pytest.raises(Exception, match="stopped"):
        adapter.generate("q", [])
    assert byok.post(ROOT, json=payload("compatible", base_url="http://127.0.0.1:8000/v1")).status_code >= 400
    assert (
        byok.post(ROOT, json=payload("compatible", base_url="https://not-allowlisted.example/v1")).status_code
        >= 400
    )


def test_removed_default_is_blocked_until_explicit_default_clear(byok):
    config = save(byok, "ollama")
    workspace = byok.get("/api/workspaces").json()[0]["id"]
    byok.post(f"{ROOT}/{config['id']}/default")
    byok.delete(f"{ROOT}/{config['id']}")
    assert byok.get(ROOT).json()["default_unavailable"] is True
    assert byok.get(f"/api/workspaces/{workspace}/ai-selection").json()["unavailable"] is True
    assert byok.delete("/api/me/provider-default").status_code == 204
    assert byok.get(ROOT).json()["default_unavailable"] is False
    assert byok.get(f"/api/workspaces/{workspace}/ai-selection").json()["active"] is None


def test_incomplete_provider_stream_is_not_accepted(monkeypatch):
    config = ConfigurationInput.model_validate(payload("ollama")).model_dump(exclude={"api_key"})
    adapter = ProviderTransport(Settings(_env_file=None), config)
    real = httpx.Client
    adapter.client_factory = lambda **kwargs: real(
        transport=httpx.MockTransport(
            lambda request: (
                httpx.Response(200, json={"capabilities": ["completion"]})
                if request.url.path == "/api/show"
                else httpx.Response(200, text=json.dumps({"message": {"content": "Incomplete [C1]"}}))
            )
        ),
        **kwargs,
    )
    with pytest.raises(Exception, match="before completion"):
        adapter.generate("question", [{"citation_id": "C1", "excerpt": "Incomplete"}])


def test_ollama_remote_alias_cannot_transmit_private_evidence():
    config = ConfigurationInput.model_validate(payload("ollama", model="local-looking-alias")).model_dump(
        exclude={"api_key"}
    )
    adapter = ProviderTransport(Settings(_env_file=None), config)
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "remote_model": "cloud-model",
                "remote_host": "https://ollama.com",
                "capabilities": ["completion"],
            },
        )

    adapter.client_factory = lambda **kwargs: httpx.Client(transport=httpx.MockTransport(handler), **kwargs)
    with pytest.raises(Exception, match="remote-backed"):
        adapter.generate("private question", [{"excerpt": "private evidence"}])
    assert len(calls) == 1 and calls[0].url.path == "/api/show"
    assert b"private" not in calls[0].content


def test_exhausted_quota_uses_sanitized_structured_status(byok, monkeypatch):
    config = save(byok)
    mock_http(
        monkeypatch,
        lambda request: httpx.Response(429, json={"error": {"type": "insufficient_quota", "message": KEY}}),
    )
    response = byok.post(f"{ROOT}/{config['id']}/test")
    assert response.json()["status"] == "insufficient_quota" and KEY not in response.text


def test_metadata_redaction_handles_json_escaped_credentials():
    secret = 'test-key-with-"quotes"-and-\\-slashes'
    config = ConfigurationInput.model_validate(payload()).model_dump(exclude={"api_key"})
    adapter = ProviderTransport(Settings(_env_file=None), config, secret)
    adapter.client_factory = lambda **kwargs: httpx.Client(
        transport=httpx.MockTransport(
            lambda request: httpx.Response(
                200, json={"data": [{"id": secret, "name": "reflected " + secret}]}
            )
        ),
        **kwargs,
    )
    models = adapter.models()
    assert models[0]["id"] == "[redacted]" and secret not in models[0]["name"]
