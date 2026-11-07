"""Offline citation formatting/source validity and controlled abstention; no external judge."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from fastapi.testclient import TestClient
from nexus.config import Settings
from nexus.main import create_app


def main():
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="artifacts/grounding-evaluation")
    parser.add_argument("--output", default="artifacts/grounding-evaluation.json")
    args = parser.parse_args()
    settings = Settings(
        _env_file=None,
        data_dir=Path(args.data),
        embedding_provider="hash",
        worker_enabled=False,
        rate_limit_per_minute=10000,
    )
    with TestClient(create_app(settings)) as client:
        workspace = client.post(
            "/api/workspaces", json={"name": "Synthetic grounding review"}
        ).json()["id"]
        chat = client.post(f"/api/workspaces/{workspace}/chats").json()["id"]
        path = f"/api/chats/{chat}/messages?workspace_id={workspace}"
        empty = client.post(path, json={"content": "When is Aurora?"}).json()
        assert not empty["citations"] and "enough evidence" in empty["answer"]
        fixture = Path("examples/aurora-notes.md").read_bytes()
        client.post(
            f"/api/workspaces/{workspace}/documents",
            files={"file": ("aurora.md", fixture, "text/markdown")},
        ).raise_for_status()
        assert client.app.state.service.process_one()
        answer = client.post(
            path, json={"content": "Aurora launch", "diagnostics": True}
        ).json()
        assert answer["citations"]
        valid = 0
        for citation in answer["citations"]:
            source = client.get(citation["source_url"])
            source.raise_for_status()
            assert any(
                citation["excerpt"] in span["text"] for span in source.json()["spans"]
            )
            valid += 1
        unsupported = client.post(
            path,
            json={
                "content": "ZXQWUNSUPPORTEDNONCE991",
                "options": {"mode": "keyword", "rewrite": False},
            },
        ).json()
        assert (
            not unsupported["citations"] and "enough evidence" in unsupported["answer"]
        )
        result = {
            "dataset_version": "release-v2",
            "known_answer_cases": 1,
            "citation_ids_checked": valid,
            "citation_id_validity": 1.0,
            "citation_coverage": answer["diagnostics"]["citation_coverage"],
            "controlled_abstention_cases": 2,
            "controlled_abstention_passed": 2,
            "provider": "mock",
            "external_evaluator_calls": 0,
            "limitations": "Controlled no-hit/empty cases only. Unsupported natural-language questions may retrieve irrelevant passages. Mock formatting/source validity does not establish real LLM factual accuracy or entailment.",
        }
        Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
