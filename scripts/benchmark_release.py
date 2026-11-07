"""Synthetic CPU feasibility measurement, not a load/capacity certification."""

import argparse
import gc
import json
import platform
import statistics
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "apps/api"))
from fastapi.testclient import TestClient
from nexus.config import Settings
from nexus.main import create_app


def memory():
    try:
        import psutil

        return psutil.Process().memory_info().rss
    except ImportError:
        return None


def run(args):
    root = Path(args.data)
    if (root / "nexus.sqlite3").exists():
        raise ValueError("Use a fresh dedicated benchmark data directory.")
    settings = Settings(
        _env_file=None,
        data_dir=root,
        embedding_provider=args.embedding_provider,
        worker_enabled=False,
        isolated_extraction=not args.in_process,
        rate_limit_per_minute=10000,
    )
    baseline_memory = memory()
    started = time.perf_counter()
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        upload_start = time.perf_counter()
        for index in range(args.documents):
            content = (
                f"# Synthetic record {index}\nRecord PHASE3CODE{index:04d}. Aurora recovery owner is Mira. "
                + (
                    "Annual leave allowance is twenty days per employee. Evidence remains scoped to the current record. "
                    * 12
                )
            )
            response = client.post(
                f"/api/workspaces/{workspace}/documents",
                files={
                    "file": (
                        f"record-{index:04d}.md",
                        content.encode(),
                        "text/markdown",
                    )
                },
            )
            response.raise_for_status()
            # Drain each bounded job; don't exceed the configured queue ceiling.
            assert client.app.state.service.process_one()
        elapsed = time.perf_counter() - upload_start
        docs = client.get(f"/api/workspaces/{workspace}/documents").json()
        assert len(docs) == args.documents and all(
            d["status"] == "ready" for d in docs
        ), docs
        ingestion_memory = memory()
    gc.collect()
    with TestClient(create_app(settings)) as client:
        latencies = {}
        for mode in ("semantic", "keyword", "hybrid"):
            values = []
            for _ in range(11):
                stamp = time.perf_counter()
                response = client.post(
                    f"/api/workspaces/{workspace}/search",
                    json={
                        "query": "PHASE3CODE0007 recovery allowance",
                        "options": {"mode": mode, "top_k": 3},
                        "diagnostics": True,
                    },
                )
                response.raise_for_status()
                assert response.json()["results"]
                values.append((time.perf_counter() - stamp) * 1000)
            latencies[mode] = {
                "first_query_ms": round(values[0], 2),
                "warm_median_ms": round(statistics.median(values[1:]), 2),
                "warm_p95_ms": round(max(values[1:]), 2),
                "repetitions": 10,
            }
        conversation = client.post(f"/api/workspaces/{workspace}/chats").json()["id"]
        stamp = time.perf_counter()
        answer = client.post(
            f"/api/chats/{conversation}/messages?workspace_id={workspace}",
            json={"content": "PHASE3CODE0007 recovery allowance"},
        )
        answer.raise_for_status()
        chat_ms = (time.perf_counter() - stamp) * 1000
        assert answer.json()["citations"]
        health = client.get("/health").json()
        final_memory = memory()
    result = {
        "environment": {
            "platform": platform.platform(),
            "processor": platform.processor(),
            "python": platform.python_version(),
        },
        "documents": args.documents,
        "embedding_provider": args.embedding_provider,
        "isolated_extraction": not args.in_process,
        "ingestion_seconds": round(elapsed, 3),
        "documents_per_second": round(args.documents / elapsed, 3),
        "active_chunks": health["indexed_chunks"],
        "data_bytes_excluding_model_cache": sum(
            p.stat().st_size
            for p in root.rglob("*")
            if p.is_file() and "models" not in p.relative_to(root).parts
        ),
        "rss_bytes": {
            "before": baseline_memory,
            "after_ingestion": ingestion_memory,
            "after_warm_queries": final_memory,
        },
        "retrieval": latencies,
        "mock_chat_total_ms": round(chat_ms, 2),
        "time_to_first_token_ms": None,
        "total_seconds": round(time.perf_counter() - started, 3),
        "limitations": "One sequential synthetic run; query first observation follows restart, semantic includes model load; warm p95 is maximum of ten observations. Not a throughput/memory capacity guarantee, no live model generation.",
    }
    Path(args.output).write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="artifacts/benchmark-release")
    parser.add_argument("--output", default="artifacts/benchmark-release.json")
    parser.add_argument(
        "--embedding-provider", choices=["hash", "onnx"], default="onnx"
    )
    parser.add_argument("--documents", type=int, default=100)
    parser.add_argument(
        "--in-process",
        action="store_true",
        help="Explicit comparison only; server default uses disposable extraction.",
    )
    args = parser.parse_args()
    if not 10 <= args.documents <= 1000:
        parser.error("Use 10–1000 synthetic documents.")
    run(args)
