import io
import zipfile

import pytest
from conftest import chat, upload
from fastapi.testclient import TestClient

from nexus.backup import backup, restore
from nexus.config import Settings
from nexus.extraction import bounded_extract, extract
from nexus.lease import DataLease
from nexus.main import create_app


def docx_bytes(xml=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        archive.writestr(
            "word/document.xml",
            xml
            or """<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>DOCX policy</w:t></w:r></w:p><w:p><w:r><w:t>Annual leave is twenty days.</w:t></w:r></w:p><w:tbl><w:tr><w:tc><w:p><w:r><w:t>Team</w:t></w:r></w:p></w:tc><w:tc><w:p><w:r><w:t>Aurora</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>""",
        )
    return buffer.getvalue()


def test_docx_and_bounded_parser(tmp_path, monkeypatch):
    path = tmp_path / "policy.docx"
    path.write_bytes(docx_bytes())
    result = extract(path, ".docx", 10000, 10)
    assert result[0].heading == "DOCX policy" and "Team | Aurora" in result[0].text
    settings = Settings(_env_file=None, embedding_provider="hash", data_dir=tmp_path)
    assert bounded_extract(path, ".docx", settings) == result
    path.write_bytes(docx_bytes('<!DOCTYPE foo [<!ENTITY x "unsafe">]><document/>'))
    with pytest.raises(ValueError, match="XML"):
        bounded_extract(path, ".docx", settings)
    import subprocess

    monkeypatch.setattr(
        subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(subprocess.TimeoutExpired("parser", 1))
    )
    with pytest.raises(ValueError, match="time limit"):
        bounded_extract(path, ".docx", settings)


def test_backup_restore_full_fixture_and_tampering(tmp_path):
    from test_indexes import drain
    from test_vaults import import_zip

    from nexus.database import GuestSession

    source = tmp_path / "original"
    settings = Settings(_env_file=None, data_dir=source, embedding_provider="hash", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        with client.app.state.service.sessions.begin() as session:
            session.add(
                GuestSession(token_hash="guest-backup-fixture", workspace_id=workspace, expires_at=2147483647)
            )
        upload(client, workspace)
        imported = import_zip(client, workspace, {"a.md": "# A\n[[b]] #tag", "b.md": "# B\nRestore proof."})
        drain(client)
        conversation = chat(client, workspace)
        answer = client.post(
            f"/api/chats/{conversation}/messages?workspace_id={workspace}", json={"content": "Aurora"}
        ).json()
        citation = answer["citations"][0]["source_url"]
        with pytest.raises(RuntimeError, match="in use"):
            backup(source, tmp_path / "live.zip")
    archive = tmp_path / "backup.zip"
    assert backup(source, archive)["database_revision"] == "0006"
    target = tmp_path / "restored"
    assert restore(archive, target)["sessions_revoked"]
    with TestClient(create_app(settings.model_copy(update={"data_dir": target}))) as client:
        with client.app.state.service.sessions() as session:
            assert session.get(GuestSession, "guest-backup-fixture").expires_at == 0
        assert client.get(citation).status_code == 200
        assert client.get(f"/api/chats/{conversation}?workspace_id={workspace}").json()["messages"]
        assert client.post(
            f"/api/workspaces/{workspace}/search", json={"query": "Aurora", "options": {"mode": "keyword"}}
        ).json()["results"]
        assert client.post(
            f"/api/workspaces/{workspace}/search", json={"query": "Aurora", "options": {"mode": "semantic"}}
        ).json()["results"]
        assert client.get(f"/api/workspaces/{workspace}/graph").json()["shown_notes"] == 2
        assert (
            client.get(f"/api/vaults/{imported['vault']['id']}/sync-status?workspace_id={workspace}").json()[
                "vault"
            ]["status"]
            == "ready"
        )
    with pytest.raises(ValueError, match="never overwritten"):
        restore(archive, target)
    tampered = tmp_path / "tampered.zip"
    with zipfile.ZipFile(archive) as original, zipfile.ZipFile(tampered, "w") as changed:
        for name in original.namelist():
            changed.writestr(name, original.read(name) + (b"bad" if name == "nexus.sqlite3" else b""))
    with pytest.raises(ValueError, match="checksum"):
        restore(tampered, tmp_path / "bad")
    assert not (tmp_path / "bad").exists()


def test_job_cancel_retry_sync_cancel_and_missing_index(tmp_path):
    from test_indexes import drain
    from test_vaults import import_zip

    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        item = upload(client, workspace)
        job_id = item["job_id"]
        path = f"/api/jobs/{job_id}"
        assert client.post(path + f"/cancel?workspace_id={workspace}").status_code == 200
        assert not client.app.state.service.process_one()
        assert client.post(path + f"/retry?workspace_id={workspace}").status_code == 200
        drain(client)
        assert client.post(path + f"/cancel?workspace_id={workspace}").status_code == 409
        imported = import_zip(client, workspace, {"a.md": "# A\nSync cancellation"})
        vault = imported["vault"]["id"]
        assert client.post(f"/api/vaults/{vault}/cancel?workspace_id={workspace}").json()["cancelled"]
        assert (
            client.get(f"/api/vaults/{vault}/sync-status?workspace_id={workspace}").json()["run"]["status"]
            == "failed"
        )
        active = client.app.state.service.indexes.ensure(workspace)
        _, index = client.app.state.service.indexes.adapters_for(active)
        index.collection.delete(where={"workspace_id": workspace})
    with TestClient(create_app(settings)) as client:
        result = client.post(f"/api/workspaces/{workspace}/search", json={"query": "Aurora"})
        assert result.status_code == 503 and "integrity" in result.json()["detail"]
        client.post(f"/api/workspaces/{workspace}/indexes/rebuild", json={})
        drain(client)
        assert client.post(f"/api/workspaces/{workspace}/search", json={"query": "Aurora"}).json()["results"]


def test_lease_and_incomplete_restore(tmp_path):
    with DataLease(tmp_path):
        with pytest.raises(RuntimeError):
            with DataLease(tmp_path):
                pass
    (tmp_path / ".restoring").write_text("not complete")
    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash")
    with pytest.raises(RuntimeError, match="Incomplete restore"):
        with TestClient(create_app(settings)):
            pass
    # Startup failures release the lease too.
    with DataLease(tmp_path):
        pass


def test_first_index_creation_is_serialized(client):
    from concurrent.futures import ThreadPoolExecutor

    workspace = client.post("/api/workspaces", json={"name": "Concurrent index"}).json()["id"]
    with ThreadPoolExecutor(max_workers=4) as pool:
        ids = list(pool.map(lambda _: client.app.state.service.indexes.ensure(workspace).id, range(8)))
    assert len(set(ids)) == 1
