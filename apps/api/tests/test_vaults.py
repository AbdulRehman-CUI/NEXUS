import io
import stat
import time
import zipfile

import pytest
from conftest import chat
from sqlalchemy import select
from test_retrieval import search

from nexus.database import Note, SyncRun
from nexus.local_agent import folder_snapshot
from nexus.vaults import parse_markdown, read_vault_zip, safe_relative


def zip_bytes(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", zipfile.ZIP_STORED) as archive:
        for path, content in files.items():
            archive.writestr(path, content)
    return output.getvalue()


def import_zip(client, workspace, files, vault_id=None, source_kind="snapshot"):
    path = (
        f"/api/vaults/{vault_id}/sync?workspace_id={workspace}"
        if vault_id
        else f"/api/workspaces/{workspace}/vaults/import?name=Research&source_kind={source_kind}"
    )
    response = client.post(path, files={"file": ("vault.zip", zip_bytes(files), "application/zip")})
    assert response.status_code == 202, response.text
    return response.json()


def synced(client, workspace, vault_id):
    for _ in range(300):
        status = client.get(f"/api/vaults/{vault_id}/sync-status?workspace_id={workspace}").json()
        if status["vault"]["status"] in {"ready", "failed"}:
            assert status["vault"]["status"] == "ready", status
            return status
        time.sleep(0.03)
    raise AssertionError("Vault sync timeout")


FILES = {
    "Projects/Aurora.md": "---\ntags: [launch, work]\naliases: [Aurora project]\n---\n# Aurora\nAurora launch is in November. [[../People/Mira|Owner]] [[Missing note]] #planning\n[[../People/Mira#Role]]",
    "People/Mira.md": "# Mira\n## Role\nMira owns the Aurora launch. [[../Projects/Aurora]]",
    "One/Duplicate.md": "# Duplicate\nFirst duplicate note.",
    "Two/Duplicate.md": "# Duplicate\nSecond duplicate note.",
    "Index.md": "# Index\n[[Duplicate]] ![[image.png]] [bad](javascript:alert) [safe](https://example.com)",
    ".obsidian/plugins/evil.js": "do not execute",
}


def test_parse_frontmatter_links_and_adversarial_data():
    parsed = parse_markdown(FILES["Projects/Aurora.md"])
    assert parsed["tags"] == ["launch", "planning", "work"]
    assert parsed["links"][0]["label"] == "Owner"
    assert parsed["links"][2]["anchor"] == "Role"
    assert "tags:" not in parsed["body"]
    with pytest.raises(ValueError):
        parse_markdown("---\ntags: &a [*a]\n---\nunsafe")
    with pytest.raises(ValueError):
        parse_markdown("---\nx: !!python/object/apply:os.system ['bad']\n---\nunsafe")


@pytest.mark.parametrize(
    "path",
    [
        "../evil.md",
        "/evil.md",
        "C:/evil.md",
        "\\\\server\\evil.md",
        "a/../evil.md",
        "NUL.md",
        "a/COM1.txt",
        "a./note.md",
    ],
)
def test_reject_unsafe_vault_paths(path):
    with pytest.raises(ValueError):
        safe_relative(path)


def test_zip_safety_limits_symlink_and_collisions(client, workspace):
    for files in ({"../escape.md": "bad"}, {"Note.md": "a", "note.md": "b"}):
        response = client.post(
            f"/api/workspaces/{workspace}/vaults/import",
            files={"file": ("vault.zip", zip_bytes(files), "application/zip")},
        )
        assert response.status_code == 415
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as archive:
        link = zipfile.ZipInfo("link.md")
        link.create_system = 3
        link.external_attr = (stat.S_IFLNK | 0o777) << 16
        archive.writestr(link, "../../outside")
    with pytest.raises(ValueError):
        read_vault_zip(output.getvalue(), client.app.state.service.settings)
    settings = client.app.state.service.settings.model_copy(update={"max_vault_files": 1})
    with pytest.raises(ValueError):
        read_vault_zip(zip_bytes({"a.md": "a", "b.md": "b"}), settings)
    bomb = io.BytesIO()
    with zipfile.ZipFile(bomb, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("bomb.md", "a" * 100000)
    with pytest.raises(ValueError, match="ratio"):
        read_vault_zip(bomb.getvalue(), client.app.state.service.settings)


def test_vault_import_links_graph_filters_and_citations(client, workspace):
    imported = import_zip(client, workspace, FILES)
    vault_id = imported["vault"]["id"]
    synced(client, workspace, vault_id)
    listing = client.get(f"/api/vaults/{vault_id}/notes?workspace_id={workspace}").json()
    assert listing["total"] == 5
    links = client.get(f"/api/vaults/{vault_id}/links?workspace_id={workspace}").json()["links"]
    assert {"resolved", "unresolved", "ambiguous", "blocked", "external"} <= {e["status"] for e in links}
    owner = next(n for n in listing["notes"] if n["path"] == "People/Mira.md")
    detail = client.get(f"/api/notes/{owner['id']}?workspace_id={workspace}").json()
    assert detail["backlinks"] and detail["outlinks"]
    graph = client.get(f"/api/workspaces/{workspace}/graph?vault_id={vault_id}").json()
    assert graph["shown_notes"] == 5 and any(e["type"] == "tag" for e in graph["edges"])
    assert all(e["provenance"] == "authored" for e in graph["edges"])
    result = search(
        client,
        workspace,
        "Aurora launch",
        "hybrid",
        {"vault_id": vault_id, "tags": ["launch"], "path_prefix": "Projects/"},
    )
    assert result["results"] and all(r["path"] == "Projects/Aurora.md" for r in result["results"])
    conversation = chat(client, workspace)
    answer = client.post(
        f"/api/chats/{conversation}/messages?workspace_id={workspace}",
        json={"content": "Aurora launch?", "filters": {"vault_id": vault_id}},
    ).json()
    assert answer["citations"] and all(c["note_id"] for c in answer["citations"])
    source = client.get(answer["citations"][0]["source_url"])
    assert source.status_code == 200
    assert source.json()["document"]["title"] == answer["citations"][0]["path"]
    other = client.post("/api/workspaces", json={"name": "Private"}).json()["id"]
    assert client.get(f"/api/workspaces/{other}/graph?vault_id={vault_id}").status_code == 404
    for path in (
        f"/api/vaults/{vault_id}/notes",
        f"/api/vaults/{vault_id}/links",
        f"/api/notes/{owner['id']}",
    ):
        assert client.get(path, params={"workspace_id": other}).status_code == 404


def test_sync_modify_rename_delete_idempotence_and_stale_sources(client, workspace):
    files = {
        "A.md": "# Aurora\nAurora launch code OLD-CODE. [[B]]",
        "B.md": "# B\nAurora support owner is Mira.",
    }
    vault_id = import_zip(client, workspace, files)["vault"]["id"]
    first = synced(client, workspace, vault_id)
    notes = client.get(f"/api/vaults/{vault_id}/notes?workspace_id={workspace}").json()["notes"]
    original_b = next(n for n in notes if n["path"] == "B.md")
    conversation = chat(client, workspace)
    answer = client.post(
        f"/api/chats/{conversation}/messages?workspace_id={workspace}",
        json={"content": '"OLD-CODE"', "options": {"mode": "keyword"}},
    ).json()
    old_url = answer["citations"][0]["source_url"]
    updated = {"A.md": "# Aurora\nAurora launch code NEW-CODE. [[Renamed]]", "Renamed.md": files["B.md"]}
    update = import_zip(client, workspace, updated, vault_id)
    synced(client, workspace, vault_id)
    assert update["run"]["counts"]["updated"] == 1 and update["run"]["counts"]["renamed"] == 1
    current = client.get(f"/api/vaults/{vault_id}/notes?workspace_id={workspace}").json()["notes"]
    renamed = next(n for n in current if n["path"] == "Renamed.md")
    assert renamed["id"] == original_b["id"]
    assert search(client, workspace, '"NEW-CODE"', "keyword", {"vault_id": vault_id})["results"]
    assert search(client, workspace, '"OLD-CODE"', "keyword", {"vault_id": vault_id})["results"] == []
    assert client.get(old_url).status_code in {404, 410}
    historical = client.get(f"/api/chats/{conversation}?workspace_id={workspace}").json()["messages"][1][
        "citations"
    ]
    assert historical and all(not c["available"] for c in historical)
    repeated = import_zip(client, workspace, updated, vault_id)
    assert repeated["run"]["id"] == update["run"]["id"]
    assert repeated["run"]["id"] != first["run"]["id"]
    import_zip(client, workspace, {}, vault_id)
    assert search(client, workspace, "Aurora", "keyword", {"vault_id": vault_id})["results"] == []
    synced(client, workspace, vault_id)
    graph = client.get(f"/api/workspaces/{workspace}/graph?vault_id={vault_id}").json()
    assert graph["nodes"] == [] and graph["edges"] == []


def test_interrupted_sync_replays_manifest_and_duplicate_contents_keep_distinct_notes(tmp_path):
    from fastapi.testclient import TestClient

    from nexus.config import Settings
    from nexus.main import create_app

    settings = Settings(_env_file=None, data_dir=tmp_path, embedding_provider="hash", worker_enabled=False)
    with TestClient(create_app(settings)) as client:
        workspace = client.get("/api/workspaces").json()[0]["id"]
        imported = import_zip(
            client, workspace, {"one.md": "# Same\nIdentical note.", "two.md": "# Same\nIdentical note."}
        )
        client.app.state.service.process_one()
        with client.app.state.service.sessions.begin() as session:
            session.get(SyncRun, imported["run"]["id"]).status = "processing"
    with TestClient(create_app(settings)) as client:
        for _ in range(15):
            client.app.state.service.process_one()
        status = synced(client, workspace, imported["vault"]["id"])
        assert status["run"]["status"] == "ready"
        with client.app.state.service.sessions() as session:
            notes = list(session.scalars(select(Note).where(Note.vault_id == imported["vault"]["id"])))
            assert (
                len(notes) == 2
                and notes[0].id != notes[1].id
                and notes[0].document_id == notes[1].document_id
            )


def test_folder_agent_real_create_modify_delete_and_root_safety(client, workspace, tmp_path):
    root = tmp_path / "approved"
    root.mkdir()
    path = root / "note.md"
    path.write_text("# Agent\nInitial manifest.", encoding="utf-8")
    settings = client.app.state.service.settings
    archive, first = folder_snapshot(root, settings)
    response = client.post(
        f"/api/workspaces/{workspace}/vaults/import?source_kind=agent",
        files={"file": ("vault.zip", archive, "application/zip")},
    )
    vault_id = response.json()["vault"]["id"]
    synced(client, workspace, vault_id)
    path.write_text("# Agent\nChanged manifest with NEWTERM.", encoding="utf-8")
    archive, second = folder_snapshot(root, settings)
    assert first != second
    client.post(
        f"/api/vaults/{vault_id}/sync?workspace_id={workspace}",
        files={"file": ("vault.zip", archive, "application/zip")},
    )
    synced(client, workspace, vault_id)
    assert search(client, workspace, "NEWTERM", "keyword", {"vault_id": vault_id})["results"]
    path.unlink()
    archive, third = folder_snapshot(root, settings)
    assert third != second
    client.post(
        f"/api/vaults/{vault_id}/sync?workspace_id={workspace}",
        files={"file": ("vault.zip", archive, "application/zip")},
    )
    synced(client, workspace, vault_id)
    assert search(client, workspace, "NEWTERM", "keyword", {"vault_id": vault_id})["results"] == []
    assert (
        client.post(f"/api/vaults/{vault_id}/sync?workspace_id={workspace}").json()["vault"]["status"]
        == "waiting_agent"
    )
    try:
        (root / "outside.md").symlink_to(tmp_path / "outside.md")
    except OSError:
        return  # Windows may prohibit creating symlinks; ZIP symlink rejection is always tested.
    with pytest.raises(ValueError, match="symlink"):
        folder_snapshot(root, settings)
