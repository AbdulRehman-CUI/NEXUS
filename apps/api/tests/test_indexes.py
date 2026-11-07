from conftest import chat, ready, upload
from fastapi.testclient import TestClient
from sqlalchemy import select
from test_retrieval import search

from nexus.config import Settings
from nexus.database import IndexGeneration
from nexus.main import create_app
from nexus.providers import HashEmbeddingProvider


def drain(client, count=30):
    for _ in range(count):
        if not client.app.state.service.process_one():
            return
    raise AssertionError("Worker did not drain")


def test_rollback_manifest_tracks_vault_revision_cleanup(tmp_path):
    from test_vaults import import_zip

    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        imported = import_zip(
            client, workspace, {"a.md": "# A\nFirst source.", "b.md": "# B\nSecond source."}
        )
        drain(client)
        original = client.get(f"/api/workspaces/{workspace}/index-versions").json()[0]
        import_zip(client, workspace, {"b.md": "# B\nChanged second source."}, imported["vault"]["id"])
        drain(client)
        client.post(f"/api/workspaces/{workspace}/indexes/rebuild", json={"embedding_dimension": 64})
        drain(client)
        response = client.post(f"/api/index-versions/{original['id']}/activate?workspace_id={workspace}")
        assert response.status_code == 200, response.text
        assert response.json()["active"]


def test_index_rebuild_keeps_old_available_activates_and_rolls_back(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        item = upload(client, workspace)
        drain(client)
        ready(client, workspace, item["document"]["id"])
        original = client.get(f"/api/workspaces/{workspace}/index-versions").json()[0]
        conversation = chat(client, workspace)
        answer = client.post(
            f"/api/chats/{conversation}/messages?workspace_id={workspace}", json={"content": "Aurora"}
        ).json()
        response = client.post(
            f"/api/workspaces/{workspace}/indexes/rebuild", json={"embedding_dimension": 64}
        )
        assert response.status_code == 202, response.text
        replacement = response.json()
        assert replacement["namespace"] != original["namespace"]
        assert search(client, workspace, "Aurora")["diagnostics"]["index_id"] == original["id"]
        drain(client)
        result = search(client, workspace, "Aurora")
        assert result["results"] and result["diagnostics"]["index_id"] == replacement["id"]
        generation = client.app.state.service.indexes.ensure(workspace)
        _, active_index = client.app.state.service.indexes.adapters_for(generation)
        assert client.get("/health").json()["indexed_chunks"] == active_index.collection.count() > 0
        assert client.get(answer["citations"][0]["source_url"]).status_code == 200
        rollback = client.post(f"/api/index-versions/{original['id']}/activate?workspace_id={workspace}")
        assert rollback.status_code == 200 and rollback.json()["active"]
        assert search(client, workspace, "Aurora")["diagnostics"]["index_id"] == original["id"]
        index = client.app.state.service.index
        try:
            index.upsert([{"id": "bad", "text": "bad", "metadata": {}}], [[0.0] * 8])
        except ValueError as error:
            assert "dimension" in str(error)
        else:
            raise AssertionError("Dimension mismatch was accepted")


def test_interrupted_rebuild_checkpoint_and_failure_preserve_active(tmp_path, monkeypatch):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        upload(client, workspace)
        drain(client)
        generation = client.post(
            f"/api/workspaces/{workspace}/indexes/rebuild", json={"embedding_dimension": 32}
        ).json()
        assert client.app.state.service.process_one()
        with client.app.state.service.sessions() as session:
            assert session.get(IndexGeneration, generation["id"]).checkpoint
    with TestClient(create_app(settings)) as client:
        drain(client)
        assert search(client, workspace, "Aurora")["diagnostics"]["index_id"] == generation["id"]
        failed = client.post(
            f"/api/workspaces/{workspace}/indexes/rebuild", json={"embedding_dimension": 16}
        ).json()
        original_embed = HashEmbeddingProvider.embed

        def invalid(self, texts):
            return [[0.0] * 8 for _ in texts] if self.dimension == 16 else original_embed(self, texts)

        monkeypatch.setattr(HashEmbeddingProvider, "embed", invalid)
        assert client.app.state.service.process_one()
        with client.app.state.service.sessions() as session:
            assert session.get(IndexGeneration, failed["id"]).status == "failed"
            active = session.scalar(
                select(IndexGeneration).where(
                    IndexGeneration.workspace_id == workspace, IndexGeneration.active.is_(True)
                )
            )
            assert active.id == generation["id"]
        assert search(client, workspace, "Aurora")["results"]
        assert (
            client.post(f"/api/index-versions/{failed['id']}/activate?workspace_id={workspace}").status_code
            == 409
        )
