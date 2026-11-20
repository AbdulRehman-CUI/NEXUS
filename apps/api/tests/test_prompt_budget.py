import json

import httpx
import pytest
from conftest import chat, ready, upload
from fastapi import HTTPException
from test_byok import byok as byok
from test_byok import enable, mock_http, save

from nexus.database import ProviderConfiguration
from nexus.prompt_budget import PromptBudget
from nexus.providers import SYSTEM_PROMPT

QUESTION = "What do you know about my ML syllabus"
MODEL = "gemini-2.5-flash-lite"


def select_google(client, *, window=8192, output=1000, advertised=None, streaming=False):
    config = save(
        client, "google", model=MODEL, streaming=streaming, context_window=window, max_output_tokens=output
    )
    if advertised:
        with client.app.state.service.sessions.begin() as session:
            session.get(ProviderConfiguration, config["id"]).models = [
                {"id": MODEL, "context_window": advertised, "max_output_tokens": 65536}
            ]
    return enable(client, config)


def add_source(client, workspace, name, passage):
    item = upload(client, workspace, name + ".txt", passage.encode("utf-8"), "text/plain")
    return ready(client, workspace, item["document"]["id"])["id"]


def google_fixture(monkeypatch):
    requests = []

    def respond(request):
        body = json.loads(request.content)
        system = body["systemInstruction"]["parts"][0]["text"]
        content = body["contents"][0]["parts"][0]["text"]
        grounded = json.loads(content)
        ids = [s["citation_id"] for s in grounded["evidence"]]
        requests.append((system, content, grounded, body["generationConfig"]["maxOutputTokens"]))
        reply = {
            "candidates": [
                {"content": {"parts": [{"text": " ".join(f"[{i}]" for i in ids)}]}, "finishReason": "STOP"}
            ]
        }
        if request.url.path.endswith(":streamGenerateContent"):
            return httpx.Response(200, text="data: " + json.dumps(reply) + "\n\n")
        return httpx.Response(200, json=reply)

    mock_http(monkeypatch, respond)
    return requests


def ask(client, workspace, chat_id, *, streaming=False, question=QUESTION, **fields):
    path = f"/api/chats/{chat_id}/messages" + ("/stream" if streaming else "")
    response = client.post(
        path, params={"workspace_id": workspace}, json={"content": question, "diagnostics": True, **fields}
    )
    if streaming:
        events = dict(event.split("\ndata: ", 1) for event in response.text.strip().split("\n\n"))
        assert "event: complete" in events, tuple(events)
        return json.loads(events["event: complete"])
    assert response.status_code == 200
    return response.json()


def verify_outbound(captured, answer, *, question, window, output, evidence_limit):
    system, content, grounded, reserved = captured
    sources = grounded["evidence"]
    byte_count = sum(len(s["excerpt"].encode()) for s in sources)
    assembled = len(system.encode()) + len(content.encode())
    assert system == SYSTEM_PROMPT and grounded["question"] == question
    assert reserved == output
    assert assembled + reserved + 256 <= window
    assert 0 < byte_count <= evidence_limit
    diagnostic = answer["diagnostics"]
    assert diagnostic["excerpt_bytes"] == byte_count
    assert len(diagnostic["final"]) == len(sources)
    assert [c["citation_id"] for c in answer["citations"]] == [s["citation_id"] for s in sources]
    assert [c["excerpt"] for c in answer["citations"]] == [s["excerpt"] for s in sources]
    budget = diagnostic["prompt_budget"]
    assert all(type(value) is int for value in budget.values())
    assert budget["source_limit_bytes"] == evidence_limit and budget["framing_tokens"] == 256
    assert budget["context_window_tokens"] == window and budget["reserved_output_tokens"] == output
    assert budget["prompt_bytes"] == assembled
    assert (
        budget["system_bytes"]
        + budget["question_bytes"]
        + budget["follow_up_bytes"]
        + budget["excerpt_bytes"]
        + budget["format_bytes"]
    ) == assembled


@pytest.mark.parametrize("streaming", [True, False])
def test_syllabus_fits_the_actual_google_request(byok, monkeypatch, streaming):
    workspace = select_google(byok, advertised=1048576, streaming=streaming)
    for topic in ["trees", "ridge", "bayes", "masks", "rates"]:
        passage = f"ML syllabus {topic}. " + (f'{topic} "é" \\ ' * 50).strip()
        add_source(byok, workspace, topic, passage)
    captured = google_fixture(monkeypatch)
    answer = ask(byok, workspace, chat(byok, workspace), streaming=streaming)
    assert len(captured) == 1
    verify_outbound(captured[0], answer, question=QUESTION, window=8192, output=1000, evidence_limit=4000)
    assert len(answer["citations"]) == 5
    for source in answer["citations"]:
        result = byok.get(source["source_url"])
        assert result.is_success
        span = next(s for s in result.json()["spans"] if s["id"] == source["source_span_id"])
        assert span["text"][source["start"] : source["end"]] == source["excerpt"]


@pytest.mark.parametrize("configured,advertised", [(4096, 2048), (32768, None)])
def test_ranked_sources_obey_model_and_saved_or_explicit_evidence_limits(
    byok, monkeypatch, configured, advertised
):
    workspace = select_google(byok, window=configured, output=384, advertised=advertised)
    path = f"/api/workspaces/{workspace}"
    # Equal-size passages make a ranked prefix the unique greedy result at either limit.
    for i, topic in enumerate(["atlas", "batch", "curve", "prior", "scale"]):
        add_source(byok, workspace, str(i), f"ML syllabus {topic}: " + ((topic + ' "雪" ') * 19).strip())
    assert byok.patch(path + "/retrieval-settings", json={"context_budget": 650}).is_success
    captured = google_fixture(monkeypatch)
    for options, limit in [({"mode": "keyword"}, 650), ({"mode": "keyword", "context_budget": 3000}, 3000)]:
        body = {"options": options, "filters": {"types": [".txt"]}}
        ranked = byok.post(path + "/search", json={"query": QUESTION, **body}).json()["results"]
        answer = ask(byok, workspace, chat(byok, workspace), **body)
        assert len(captured) == 1
        outbound = captured.pop()
        verify_outbound(
            outbound,
            answer,
            question=QUESTION,
            window=advertised or configured,
            output=384,
            evidence_limit=limit,
        )
        sent = [c["chunk_id"] for c in answer["citations"]]
        assert sent == [r["chunk_id"] for r in ranked][: len(sent)]
        if limit == 3000:
            if advertised:
                assert len(sent) < len(ranked)
            else:
                assert len(sent) == len(ranked) == 5
                assert answer["diagnostics"]["excerpt_bytes"] > 650
                assert all("source_url" in item for item in outbound[2]["evidence"])


def test_mandatory_input_no_fitting_source_and_short_request(byok, monkeypatch):
    # The catalog window is smaller than the saved setting. Keep the full output reservation.
    workspace = select_google(byok, window=8192, advertised=4096, output=2700)
    add_source(byok, workspace, "large", "ML syllabus " + "東京" * 130)
    captured = google_fixture(monkeypatch)
    identifier = chat(byok, workspace)
    answer = ask(byok, workspace, identifier)
    assert not captured and not answer["citations"]
    assert "fit" in answer["answer"].lower() and "evidence" in answer["answer"].lower()
    assert answer["diagnostics"]["prompt_budget"]["prompt_budget_skips"] > 0

    limited = ask(byok, workspace, identifier, options={"context_budget": 200})
    assert not captured and not limited["citations"] and "source" in limited["answer"]
    assert limited["diagnostics"]["prompt_budget"]["source_budget_skips"] > 0

    add_source(byok, workspace, "small", "ML syllabus: the project is due Friday.")
    answer = ask(byok, workspace, identifier)
    assert len(captured) == 1
    verify_outbound(captured.pop(), answer, question=QUESTION, window=4096, output=2700, evidence_limit=4000)
    impossible = byok.post(
        f"/api/chats/{identifier}/messages", params={"workspace_id": workspace}, json={"content": "雪" * 600}
    )
    assert impossible.status_code == 422 and not captured
    detail = impossible.json()["detail"].lower()
    assert "4096" in detail and "2700" in detail and "question" in detail


def test_long_follow_up_counts_only_the_supported_history(byok, monkeypatch):
    workspace = select_google(byok, window=8192, output=1200)
    earlier = "ML syllabus " + "é" * 1800
    add_source(byok, workspace, "short", "ML syllabus: study linear models.")
    captured = google_fixture(monkeypatch)
    identifier = chat(byok, workspace)
    ask(byok, workspace, identifier, question=earlier, options={"mode": "keyword"})
    captured.clear()
    question = "What about its prerequisites?"
    answer = ask(byok, workspace, identifier, question=question, options={"mode": "keyword"})
    assert len(captured) == 1
    expected = earlier[:1500] + " Follow-up: " + question
    verify_outbound(captured[0], answer, question=expected, window=8192, output=1200, evidence_limit=4000)
    assert answer["diagnostics"]["prompt_budget"]["follow_up_bytes"] == len(expected.encode()) - len(
        question.encode()
    )


def test_budget_skip_backfills_by_rank_and_ordinary_short_request_preserves_payload(byok, monkeypatch):
    workspace = select_google(byok, window=4096, advertised=2048, output=600)
    first = add_source(byok, workspace, "ML syllabus", "ML syllabus " * 10 + "雪" * 300)
    second = add_source(byok, workspace, "schedule", "ML sessions are on Friday.")
    options = {"mode": "keyword", "top_k": 1}
    ranked = byok.post(f"/api/workspaces/{workspace}/search", json={"query": QUESTION, "options": options})
    assert ranked.json()["results"][0]["document_id"] == first
    captured = google_fixture(monkeypatch)
    answer = ask(byok, workspace, chat(byok, workspace), options=options)
    verify_outbound(captured.pop(), answer, question=QUESTION, window=2048, output=600, evidence_limit=4000)
    assert [c["document_id"] for c in answer["citations"]] == [second]
    assert answer["diagnostics"]["prompt_budget"]["prompt_budget_skips"] == 1

    select_google(byok)
    answer = ask(
        byok,
        workspace,
        chat(byok, workspace),
        question="When are ML sessions?",
        filters={"document_ids": [second]},
    )
    outbound = captured.pop()
    verify_outbound(
        outbound, answer, question="When are ML sessions?", window=8192, output=1000, evidence_limit=4000
    )
    full_citation = {k: v for k, v in answer["citations"][0].items() if k != "available"}
    assert outbound[1] == json.dumps(
        {"question": "When are ML sessions?", "evidence": [full_citation]}, ensure_ascii=False
    )


def test_optional_locator_metadata_yields_to_a_complete_cited_passage_at_the_boundary():
    config = {"context_window": 2048, "max_output_tokens": 600, "context_budget_bytes": 4000}
    budget = PromptBudget(config, {})
    source = {"citation_id": "C1", "excerpt": "ML syllabus", "title": "雪" * 500}
    _, content = budget.checked_parts(QUESTION, [source])
    assert json.loads(content)["evidence"] == [{"citation_id": "C1", "excerpt": "ML syllabus"}]
    free = budget.input_limit - len(SYSTEM_PROMPT.encode()) - len(content.encode())
    source["excerpt"] += "x" * free
    assert budget.fits(QUESTION, [source])
    source["excerpt"] += "x"
    assert not budget.fits(QUESTION, [source])
    with pytest.raises(HTTPException, match="2048-token model window"):
        budget.checked_parts(QUESTION, [source])

    with pytest.raises(HTTPException, match="600 tokens exceeds the advertised maximum of 512"):
        PromptBudget(config, {"max_output_tokens": 512}).checked_parts(QUESTION, [])


@pytest.mark.parametrize("streaming", [False, True])
def test_provider_context_rejection_is_actionable_and_private(byok, monkeypatch, streaming):
    workspace = select_google(byok, streaming=streaming)
    add_source(byok, workspace, "short", "ML syllabus: study linear models.")
    identifier = chat(byok, workspace)
    calls = []

    def reject(request):
        calls.append(request.url.path)
        error = {"error": {"message": "The input token count exceeds the maximum. synthetic-private-marker"}}
        if streaming:
            return httpx.Response(200, text="data: " + json.dumps(error) + "\n\n")
        return httpx.Response(400, json=error)

    mock_http(monkeypatch, reject)
    path = f"/api/chats/{identifier}/messages" + ("/stream" if streaming else "")
    response = byok.post(path, params={"workspace_id": workspace}, json={"content": QUESTION})
    if streaming:
        assert "event: error" in response.text and "event: complete" not in response.text
        error = json.loads(response.text.split("event: error\ndata: ")[1])
    else:
        assert response.status_code == 422
        error = response.json()
    assert len(calls) == 1 and "synthetic-private-marker" not in response.text
    assert error["code"] == "context_length_exceeded" and "output limit" in error["detail"]
    assert not byok.get(f"/api/chats/{identifier}", params={"workspace_id": workspace}).json()["messages"]
