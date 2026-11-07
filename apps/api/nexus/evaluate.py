"""Repeatable no-cloud retrieval benchmark over checked-in non-sensitive sources."""

import argparse
import hashlib
import io
import json
import platform
import time
import zipfile
from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import select

from .config import Settings
from .database import Document, Note, Span
from .main import create_app


def source_key(path, page, heading, content):
    identity = json.dumps(
        {"path": path, "page": page, "heading": heading, "text": content}, ensure_ascii=False, sort_keys=True
    )
    return hashlib.sha256(identity.encode()).hexdigest()


def metrics(relevant, retrieved):
    relevant = set(relevant)
    if not relevant:
        return None, None
    unique = list(dict.fromkeys(retrieved))
    recall = len(relevant & set(unique)) / len(relevant)
    reciprocal = next((1 / position for position, key in enumerate(unique, 1) if key in relevant), 0)
    return recall, reciprocal


def evaluate(data_dir, provider="hash", top_k=3):
    root = Path(__file__).resolve().parents[3] / "examples" / "evaluation"
    labels = json.loads((root / "questions.json").read_text("utf-8"))
    started = time.perf_counter()
    settings = Settings(
        _env_file=None,
        data_dir=Path(data_dir),
        embedding_provider=provider,
        generation_provider="mock",
        worker_enabled=False,
        rate_limit_per_minute=10000,
    )
    archive = io.BytesIO()
    with zipfile.ZipFile(archive, "w", zipfile.ZIP_STORED) as output:
        for file in sorted((root / "vault").rglob("*.md")):
            output.writestr(file.relative_to(root / "vault").as_posix(), file.read_bytes())
    with TestClient(create_app(settings)) as client:
        spaces = client.get("/api/workspaces").json()
        workspace = next((w for w in spaces if w["name"] == "Retrieval evaluation"), None)
        if workspace is None:
            response = client.post("/api/workspaces", json={"name": "Retrieval evaluation"})
            response.raise_for_status()
            workspace = response.json()
        workspace_id = workspace["id"]
        vaults = client.get(f"/api/workspaces/{workspace_id}/vaults").json()
        existing = next((v for v in vaults if v["name"] == "Evaluation corpus"), None)
        route = (
            f"/api/vaults/{existing['id']}/sync?workspace_id={workspace_id}"
            if existing
            else f"/api/workspaces/{workspace_id}/vaults/import?name=Evaluation%20corpus"
        )
        response = client.post(
            route, files={"file": ("evaluation.zip", archive.getvalue(), "application/zip")}
        )
        response.raise_for_status()
        for pdf in sorted(root.glob("*.pdf")):
            response = client.post(
                f"/api/workspaces/{workspace_id}/documents",
                files={"file": (pdf.name, pdf.read_bytes(), "application/pdf")},
            )
            response.raise_for_status()
        for _ in range(2000):
            if not client.app.state.service.process_one():
                break
        else:
            raise RuntimeError("Evaluation worker did not drain")
        documents = client.get(f"/api/workspaces/{workspace_id}/documents").json()
        if any(d["status"] != "ready" for d in documents):
            raise RuntimeError("Evaluation corpus failed to index. Check the selected embedding runtime.")
        mapping, actual_sources = {}, []
        with client.app.state.service.sessions() as session:
            for span, document in session.execute(
                select(Span, Document)
                .join(Document, Document.id == Span.document_id)
                .where(Span.workspace_id == workspace_id)
            ):
                note = session.scalar(
                    select(Note).where(
                        Note.document_id == document.id,
                        Note.workspace_id == workspace_id,
                        Note.deleted.is_(False),
                    )
                )
                path = note.path if note else document.title
                key = source_key(path, span.page, span.heading, span.text)
                mapping[span.id] = key
                actual_sources.append(
                    {
                        "source_id": key,
                        "source_span_id": span.id,
                        "document_id": document.id,
                        "document_version_id": document.version_id,
                        "path": path,
                        "page": span.page,
                        "heading": span.heading,
                    }
                )
        expected = {key for case in labels["questions"] for key in case["relevant_source_ids"]}
        if not expected <= set(mapping.values()):
            raise RuntimeError(
                "Evaluation labels no longer match the normalized corpus; review labels rather than silently changing relevance."
            )
        results = {}
        for mode in ("semantic", "keyword", "hybrid"):
            cases, recalls, reciprocal_ranks, unsupported_hits = [], [], [], 0
            mode_started = time.perf_counter()
            for case in labels["questions"]:
                response = client.post(
                    f"/api/workspaces/{workspace_id}/search",
                    json={
                        "query": case["query"],
                        "options": {"mode": mode, "top_k": top_k, "max_per_document": 3, "rewrite": False},
                        "diagnostics": True,
                    },
                )
                response.raise_for_status()
                answer = response.json()
                retrieved = [mapping[item["source_span_id"]] for item in answer["results"]]
                recall, reciprocal = metrics(case["relevant_source_ids"], retrieved)
                if recall is not None:
                    recalls.append(recall)
                    reciprocal_ranks.append(reciprocal)
                else:
                    unsupported_hits += bool(retrieved)
                for item in answer["results"]:
                    source = client.get(item["source_url"])
                    source.raise_for_status()
                    assert item["excerpt"] in source.json()["spans"][0]["text"]
                cases.append(
                    {
                        "id": case["id"],
                        "relevant_source_ids": case["relevant_source_ids"],
                        "retrieved_source_ids": retrieved,
                        "retrieved_chunk_ids": [r["chunk_id"] for r in answer["results"]],
                        "recall_at_k": recall,
                        "reciprocal_rank": reciprocal,
                    }
                )
            results[mode] = {
                "recall_at_k": sum(recalls) / len(recalls),
                "mrr": sum(reciprocal_ranks) / len(reciprocal_ranks),
                "answerable_cases": len(recalls),
                "unsupported_cases_with_hits": unsupported_hits,
                "elapsed_ms": round((time.perf_counter() - mode_started) * 1000, 2),
                "cases": cases,
            }
        return {
            "corpus_version": labels["version"],
            "provider": provider,
            "model": settings.embedding_model if provider != "hash" else "sha256-token-hash-384",
            "semantic_quality_claim": provider != "hash",
            "k": top_k,
            "question_count": len(labels["questions"]),
            "hardware": {
                "platform": platform.platform(),
                "machine": platform.machine(),
                "processor": platform.processor(),
                "python": platform.python_version(),
            },
            "elapsed_seconds": round(time.perf_counter() - started, 3),
            "results": results,
            "source_mapping": actual_sources,
            "limitations": [
                "Small synthetic corpus, no live generation or cloud calls.",
                "Hash embeddings test dense plumbing, not semantic paraphrase quality."
                if provider == "hash"
                else "Results apply only to this pinned model/corpus.",
                "Source IDs validate provenance; they do not validate answer entailment.",
            ],
        }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default="artifacts/evaluation-data")
    parser.add_argument("--output", default="artifacts/retrieval-evaluation.json")
    parser.add_argument(
        "--embedding-provider", choices=["hash", "onnx", "sentence-transformers"], default="onnx"
    )
    parser.add_argument("--top-k", type=int, default=3, choices=range(1, 21))
    args = parser.parse_args()
    result = evaluate(args.data_dir, args.embedding_provider, args.top_k)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    for mode, values in result["results"].items():
        print(f"{mode}: Recall@{args.top_k}={values['recall_at_k']:.4f} MRR={values['mrr']:.4f}")
    print(
        f"{result['question_count']} cases; provider={result['provider']}; {result['elapsed_seconds']}s; details: {output}"
    )


if __name__ == "__main__":
    main()
