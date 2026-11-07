import json

import httpx
import pytest
from conftest import chat, ready, upload
from sqlalchemy import select

from nexus.database import UsageEvent
from nexus.gateway import GenerationPolicy, RemoteAdapter, destination
from nexus.providers import SYSTEM_PROMPT, ProviderError


@pytest.mark.parametrize(
    "provider,payload",
    [
        (
            "openai",
            {
                "choices": [{"message": {"content": "Answer [C123]"}}],
                "usage": {"prompt_tokens": 17, "completion_tokens": 6},
            },
        ),
        ("groq", {"choices": [{"message": {"content": "Answer [C123]"}}]}),
        ("compatible", {"choices": [{"message": {"content": "Answer [C123]"}}]}),
        (
            "anthropic",
            {
                "content": [{"type": "text", "text": "Answer [C123]"}],
                "usage": {"input_tokens": 17, "output_tokens": 6},
            },
        ),
        (
            "google",
            {
                "candidates": [{"content": {"parts": [{"text": "Answer [C123]"}]}}],
                "usageMetadata": {"promptTokenCount": 17, "candidatesTokenCount": 6},
            },
        ),
        ("ollama", {"message": {"content": "Answer [C123]"}, "prompt_eval_count": 17, "eval_count": 6}),
    ],
)
def test_realistic_adapter_contracts(monkeypatch, provider, payload):
    from nexus.config import Settings

    settings = Settings(
        _env_file=None,
        **{
            f"{p}_api_key": "secret-for-tests"
            for p in ("openai", "groq", "anthropic", "google", "compatible")
        },
    )
    settings.compatible_base_url = "https://provider.example/v1"
    settings.provider_allowed_origins = ["https://provider.example"]
    monkeypatch.setattr("nexus.gateway.socket.getaddrinfo", lambda *a, **k: [(2, 1, 6, "", ("8.8.8.8", 443))])
    seen = []

    def handle(request):
        if request.url.path == "/api/show":
            return httpx.Response(200, json={"capabilities": ["completion"]})
        seen.append(request)
        body = json.loads(request.content)
        text = json.dumps(body)
        assert json.dumps(SYSTEM_PROMPT) in text
        assert "untrusted content" in text
        assert "secret-for-tests" not in text
        if provider in {"openai", "groq", "compatible"}:
            assert body["messages"][0]["role"] == "system"
            assert body["messages"][1]["role"] == "user"
            assert request.headers["authorization"] == "Bearer secret-for-tests"
        if provider == "anthropic":
            assert request.headers["x-api-key"] == "secret-for-tests"
            assert body["system"] == SYSTEM_PROMPT
        if provider == "google":
            assert request.headers["x-goog-api-key"] == "secret-for-tests"
            assert "key=" not in str(request.url)
        if provider == "ollama":
            assert "authorization" not in request.headers
            assert body["options"]["num_thread"] == 2
        return httpx.Response(200, json=payload)

    real_client = httpx.Client
    monkeypatch.setattr(
        "nexus.gateway.httpx.Client",
        lambda **kwargs: real_client(transport=httpx.MockTransport(handle), **kwargs),
    )
    adapter = RemoteAdapter(settings, GenerationPolicy(provider=provider, model="manual-model"))
    assert (
        adapter.generate("Question", [{"citation_id": "C123", "excerpt": "untrusted content"}])
        == "Answer [C123]"
    )
    assert len(seen) == 1


def test_workspace_policy_consent_switch_budget_no_reindex(client, workspace, monkeypatch):
    item = upload(client, workspace)
    ready(client, workspace, item["document"]["id"])
    before = client.get(f"/api/workspaces/{workspace}/index-versions").json()
    conversation = chat(client, workspace)
    path = f"/api/workspaces/{workspace}/route-policy"
    policy = GenerationPolicy(
        provider="openai", model="manual", allow_paid=False, preset="cloud-optional"
    ).model_dump()
    assert client.put(path, json=policy).status_code == 200

    def call():
        return client.post(
            f"/api/chats/{conversation}/messages?workspace_id={workspace}", json={"content": "Aurora"}
        )

    assert call().status_code == 403
    client.patch(f"/api/workspaces/{workspace}", json={"cloud_opt_in": True})
    policy["consent_destination"] = "openai|https://api.openai.com/v1"
    client.put(path, json=policy)
    assert call().status_code == 403  # No paid permission.
    policy["allow_paid"], policy["max_calls_per_day"] = True, 1
    client.app.state.service.settings.paid_provider_allowlist = ["openai"]
    client.put(path, json=policy)
    monkeypatch.setattr(
        RemoteAdapter, "generate", lambda self, question, evidence: f"Grounded [{evidence[0]['citation_id']}]"
    )
    assert call().status_code == 200
    assert call().status_code == 429
    policy["provider"] = "anthropic"
    assert client.put(path, json=policy).status_code == 422  # Old destination consent cannot transfer.
    assert client.get(f"/api/workspaces/{workspace}/index-versions").json() == before
    with client.app.state.service.sessions() as session:
        usage = list(session.scalars(select(UsageEvent).where(UsageEvent.workspace_id == workspace)))
        assert len(usage) == 1 and usage[0].status == "ok"
    exported = client.get(f"/api/workspaces/{workspace}/settings-export").json()
    assert "api_key" not in json.dumps(exported)
    assert not exported["generation"]["allow_paid"] and exported["generation"]["consent_destination"] == ""
    assert client.post(f"/api/workspaces/{workspace}/settings-import", json=exported).status_code == 200
    assert not client.get("/api/workspaces").json()[0]["cloud_opt_in"]
    exported["api_key"] = "forbidden"
    assert client.post(f"/api/workspaces/{workspace}/settings-import", json=exported).status_code == 422


def test_ssrf_timeouts_and_redaction(monkeypatch):
    from nexus.config import Settings

    settings = Settings(_env_file=None, openai_api_key="super-secret")
    for bad in (
        "http://169.254.169.254",
        "https://127.0.0.1/v1",
        "https://user:pass@example.com/v1",
        "https://example.com/v1?key=secret",
    ):
        settings.compatible_base_url = bad
        with pytest.raises(ProviderError):
            destination(settings, "compatible")
    settings.ollama_base_url = "http://remote.example:11434"
    with pytest.raises(ProviderError):
        destination(settings, "ollama")
    real_client = httpx.Client

    def timeout(request):
        raise httpx.ReadTimeout("super-secret in unsafe transport exception")

    monkeypatch.setattr(
        "nexus.gateway.httpx.Client", lambda **kw: real_client(transport=httpx.MockTransport(timeout), **kw)
    )
    with pytest.raises(ProviderError) as error:
        RemoteAdapter(settings, GenerationPolicy(provider="openai", model="manual")).generate("question", [])
    assert error.value.status == 504 and "super-secret" not in str(error.value)
    monkeypatch.setattr(
        "nexus.gateway.httpx.Client",
        lambda **kw: real_client(
            transport=httpx.MockTransport(lambda r: httpx.Response(429, text="super-secret")), **kw
        ),
    )
    with pytest.raises(ProviderError) as error:
        RemoteAdapter(settings, GenerationPolicy(provider="openai", model="manual")).generate("question", [])
    assert error.value.status == 429 and "super-secret" not in str(error.value)


def test_feedback_comparison_diagnostics(client, workspace):
    item = upload(client, workspace)
    ready(client, workspace, item["document"]["id"])
    conversation = chat(client, workspace)
    answer = client.post(
        f"/api/chats/{conversation}/messages?workspace_id={workspace}", json={"content": "Aurora"}
    ).json()
    assert (
        client.post(
            f"/api/messages/{answer['id']}/feedback?workspace_id={workspace}",
            json={"rating": "wrong_citation", "comment": "Check this source"},
        ).status_code
        == 201
    )
    assert client.get(f"/api/workspaces/{workspace}/reviews").json()[0]["message_id"] == answer["id"]
    result = client.post(
        f"/api/workspaces/{workspace}/compare",
        json={
            "question": "Aurora",
            "policies": [
                GenerationPolicy().model_dump(),
                GenerationPolicy(provider="openai", model="unconfigured").model_dump(),
            ],
        },
    ).json()
    assert result["same_evidence_chunk_ids"]
    assert result["answers"][0]["citations"] and result["answers"][1]["unavailable"]
    metrics = client.get(f"/api/workspaces/{workspace}/diagnostics").json()
    assert metrics["request_sample_count"] and metrics["usage"]
    encoded = json.dumps(metrics)
    assert "question" not in encoded and "excerpt" not in encoded and "password" not in encoded
