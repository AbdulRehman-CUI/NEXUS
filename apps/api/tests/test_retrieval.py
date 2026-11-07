import os

import pytest
from conftest import chat, ready, upload
from sqlalchemy import text

from nexus.retrieval import fuse, match_expression, reformulate


def search(client, workspace, query, mode="hybrid", filters=None, **options):
    response = client.post(
        f"/api/workspaces/{workspace}/search",
        json={
            "query": query,
            "options": {"mode": mode, **options},
            "filters": filters or {},
            "diagnostics": True,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_keyword_phrase_and_real_distinct_stages(client, workspace):
    for name, content in [
        ("exact.md", b"# Operations\nThe escalation code is QUARTZ-971. Exact phrase: amber protocol."),
        ("other.txt", b"General support and amber-colored objects are unrelated to the protocol."),
    ]:
        item = upload(client, workspace, name, content, "text/plain")
        ready(client, workspace, item["document"]["id"])
    keyword = search(client, workspace, '"amber protocol"', "keyword")
    assert keyword["results"][0]["title"] == "exact.md"
    assert (
        "lexical_0" in keyword["diagnostics"]["stages"] and "dense_0" not in keyword["diagnostics"]["stages"]
    )
    dense = search(client, workspace, "amber protocol", "semantic")
    assert "dense_0" in dense["diagnostics"]["stages"] and "lexical_0" not in dense["diagnostics"]["stages"]
    hybrid = search(client, workspace, "QUARTZ-971")
    assert {"dense_0", "lexical_0"} <= hybrid["diagnostics"]["stages"].keys()
    assert len({r["chunk_id"] for r in hybrid["results"]}) == len(hybrid["results"])
    assert "excerpt" not in str(hybrid["diagnostics"]["stages"])


def test_rrf_is_deterministic_and_deduplicates():
    a, b = [("b", 100), ("a", 90), ("a", 80)], [("a", 1), ("c", 0.5)]
    one = fuse([(a, 1), (b, 1)])
    assert one == fuse([(a, 1), (b, 1)])
    assert one[0][0] == "a" and len(one) == 3
    assert (
        match_expression('"alpha beta" OR x; DROP TABLE notes')
        == '"alpha beta" OR "OR" OR "x" OR "DROP" OR "TABLE" OR "notes"'
    )


def test_filters_applied_before_dense_and_lexical_and_fts_delete(client, workspace):
    a = upload(client, workspace)
    b = upload(client, workspace, "other.txt", b"Aurora launch owner is Mira.", "text/plain")
    for item in (a, b):
        ready(client, workspace, item["document"]["id"])
    for mode in ("semantic", "keyword", "hybrid"):
        result = search(
            client,
            workspace,
            "Aurora launch",
            mode,
            {"document_ids": [b["document"]["id"]], "types": [".txt"]},
        )
        assert result["results"] and all(r["document_id"] == b["document"]["id"] for r in result["results"])
    other = client.post("/api/workspaces", json={"name": "Other"}).json()["id"]
    assert search(client, other, "Aurora launch")["results"] == []
    assert (
        client.post(
            f"/api/workspaces/{other}/search",
            json={"query": "Aurora", "filters": {"document_ids": [a["document"]["id"]]}},
        ).status_code
        == 404
    )
    client.delete(f"/api/documents/{a['document']['id']}?workspace_id={workspace}")
    assert all(
        r["document_id"] != a["document"]["id"]
        for r in search(client, workspace, "Aurora", "keyword")["results"]
    )
    import time

    for _ in range(100):
        with client.app.state.service.sessions() as session:
            count = session.execute(
                text("SELECT count(*) FROM chunk_fts WHERE document_id=:id"), {"id": a["document"]["id"]}
            ).scalar()
        if count == 0:
            break
        time.sleep(0.02)
    assert count == 0


def test_followup_local_rewrite_profiles_and_reranker_fallback(client, workspace, monkeypatch):
    item = upload(client, workspace)
    ready(client, workspace, item["document"]["id"])
    conversation = chat(client, workspace)
    path = f"/api/chats/{conversation}/messages?workspace_id={workspace}"
    assert client.post(path, json={"content": "Tell me about Aurora launch"}).status_code == 200
    response = client.post(path, json={"content": "When is it?", "diagnostics": True}).json()
    assert "Aurora" in response["diagnostics"]["standalone_query"]
    assert response["diagnostics"]["additional_cloud_calls"] == 0
    assert reformulate("A fully specific question", "prior", True) == "A fully specific question"
    long_followup = "it " + "x" * 3997
    assert reformulate(long_followup, "prior context", True) == long_followup
    from nexus.retrieval import CrossEncoderReranker

    monkeypatch.setattr(CrossEncoderReranker, "rank", lambda *a: (_ for _ in ()).throw(ImportError()))
    result = search(client, workspace, "Aurora", reranker="cross-encoder", multi_query=True)
    assert result["results"] and result["diagnostics"]["warnings"]
    profile = client.patch(
        f"/api/workspaces/{workspace}/retrieval-settings", json={"mode": "keyword", "top_k": 1}
    ).json()
    assert profile["mode"] == "keyword" and profile["top_k"] == 1
    assert client.get(f"/api/workspaces/{workspace}/retrieval-settings").json() == profile


@pytest.mark.skipif(
    os.environ.get("NEXUS_TEST_SEMANTIC") != "1",
    reason="Real MiniLM optional: requires installed semantic runtime and cached model",
)
def test_real_semantic_paraphrase(tmp_path):
    from fastapi.testclient import TestClient

    from nexus.config import Settings
    from nexus.main import create_app

    with TestClient(
        create_app(Settings(_env_file=None, data_dir=tmp_path, embedding_provider="sentence-transformers"))
    ) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        item = upload(
            client,
            workspace,
            "policy.txt",
            b"Employees may take twenty days of annual leave each year.",
            "text/plain",
        )
        ready(client, workspace, item["document"]["id"])
        result = search(client, workspace, "How much vacation can staff use?", "semantic")
        assert result["results"][0]["document_id"] == item["document"]["id"]


@pytest.mark.skipif(
    os.environ.get("NEXUS_TEST_ONNX") != "1",
    reason="Opt-in real ONNX model test; basic tests never download weights",
)
def test_real_onnx_semantic_paraphrase(tmp_path):
    from fastapi.testclient import TestClient

    from nexus.config import Settings
    from nexus.main import create_app

    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="onnx", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        item = upload(
            client,
            workspace,
            "leave.txt",
            b"Employees may take twenty days of annual leave each year.",
            "text/plain",
        )
        client.app.state.service.process_one()
        ready(client, workspace, item["document"]["id"])
        result = search(client, workspace, "How much vacation can staff use?", "semantic")
        assert result["results"][0]["document_id"] == item["document"]["id"]
