from fastapi.testclient import TestClient
from sqlalchemy import select
from test_indexes import drain
from test_retrieval import search
from test_vaults import import_zip

from nexus.config import Settings
from nexus.database import Note
from nexus.main import create_app


def test_older_reindex_cannot_restore_revoked_note_revision(tmp_path):
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        first = import_zip(client, workspace, {"note.md": "# Version\nOLDTERM source."})
        vault_id = first["vault"]["id"]
        drain(client)
        with client.app.state.service.sessions() as session:
            note = session.scalar(select(Note).where(Note.vault_id == vault_id))
            document_id, note_id = note.document_id, note.id
        client.post(f"/api/documents/{document_id}/reindex?workspace_id={workspace}")
        import_zip(client, workspace, {"note.md": "# Version\nNEWTERM source."}, vault_id)
        # The older job runs before the newer manifest application step.
        assert client.app.state.service.process_one()
        with client.app.state.service.sessions() as session:
            assert session.get(Note, note_id).status == "pending"
        assert search(client, workspace, "OLDTERM", "keyword", {"vault_id": vault_id})["results"] == []
        drain(client)
        assert search(client, workspace, "NEWTERM", "keyword", {"vault_id": vault_id})["results"]


def test_failed_shared_note_content_sync_can_retry_without_hanging(tmp_path, monkeypatch):
    from nexus.providers import HashEmbeddingProvider

    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False)
    original = HashEmbeddingProvider.embed
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        imported = import_zip(
            client, workspace, {"a.md": "# Shared\nSame bytes.", "b.md": "# Shared\nSame bytes."}
        )
        monkeypatch.setattr(
            HashEmbeddingProvider, "embed", lambda *a: (_ for _ in ()).throw(RuntimeError("fixture failure"))
        )
        drain(client)
        vault_id = imported["vault"]["id"]
        status = client.get(f"/api/vaults/{vault_id}/sync-status?workspace_id={workspace}").json()
        assert status["vault"]["status"] == "failed"
        monkeypatch.setattr(HashEmbeddingProvider, "embed", original)
        assert client.post(f"/api/vaults/{vault_id}/retry?workspace_id={workspace}").status_code == 202
        drain(client)
        assert (
            client.get(f"/api/vaults/{vault_id}/sync-status?workspace_id={workspace}").json()["vault"][
                "status"
            ]
            == "ready"
        )
