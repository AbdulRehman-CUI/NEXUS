from fastapi.testclient import TestClient

from nexus.config import Settings
from nexus.main import create_app
from nexus.storage import validate_upload


def test_windows_browser_paths_are_normalized_without_storage_escape(tmp_path):
    import pytest

    with pytest.raises(ValueError):
        validate_upload("C:\\escape.txt", "text/plain", b"hello")
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        response = client.post(
            f"/api/workspaces/{workspace}/documents",
            files={"file": ("C:\\escape.txt", b"hello", "text/plain")},
        )
        # The multipart parser strips IE-style drive paths before endpoint validation.
        assert response.status_code == 202
        document = response.json()["document"]
        assert document["title"] == "escape.txt"
        assert client.app.state.service.files.path(document["storage_key"]).is_relative_to(tmp_path)


def test_multipart_body_limit_before_spooling(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", max_upload_mb=1)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        response = client.post(
            f"/api/workspaces/{workspace}/documents",
            files={"file": ("too-large.txt", b"a" * (1024 * 1024 + 100000), "text/plain")},
        )
        assert response.status_code == 413, response.text
        assert client.get(f"/api/workspaces/{workspace}/documents").json() == []


def test_job_queue_is_bounded_and_duplicate_does_not_consume_capacity(tmp_path):
    settings = Settings(
        _env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False, max_queued_jobs=1
    )
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        path = f"/api/workspaces/{workspace}/documents"
        one = client.post(path, files={"file": ("one.txt", b"one", "text/plain")})
        assert one.status_code == 202
        duplicate = client.post(path, files={"file": ("renamed.txt", b"one", "text/plain")})
        assert duplicate.status_code == 202 and duplicate.json()["duplicate"]
        assert client.post(path, files={"file": ("two.txt", b"two", "text/plain")}).status_code == 429
