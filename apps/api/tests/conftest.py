import time

import pymupdf
import pytest
from fastapi.testclient import TestClient

from nexus.config import Settings
from nexus.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        _env_file=None,
        data_dir=tmp_path,
        embedding_provider="hash",
        worker_enabled=True,
        rate_limit_per_minute=10000,
    )
    with TestClient(create_app(settings)) as client:
        yield client


@pytest.fixture
def workspace(client):
    return client.get("/api/workspaces").json()[0]["id"]


def pdf_bytes(*pages):
    pdf = pymupdf.open()
    for text in pages:
        page = pdf.new_page()
        if text:
            page.insert_text((72, 72), text)
    content = pdf.tobytes()
    pdf.close()
    return content


def upload(
    client,
    workspace,
    name="aurora.md",
    content=b"# Aurora launch\nAurora launch is on 14 November 2026.",
    mime="text/markdown",
):
    response = client.post(f"/api/workspaces/{workspace}/documents", files={"file": (name, content, mime)})
    assert response.status_code == 202, response.text
    return response.json()


def ready(client, workspace, document_id, expected="ready"):
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        response = client.get(f"/api/documents/{document_id}", params={"workspace_id": workspace})
        assert response.status_code == 200, response.text
        result = response.json()
        if result["status"] in {"ready", "failed", "needs_ocr"}:
            assert result["status"] == expected, result
            return result
        time.sleep(0.05)
    raise AssertionError("Ingestion did not finish within 30 seconds")


def chat(client, workspace):
    return client.post(f"/api/workspaces/{workspace}/chats").json()["id"]
