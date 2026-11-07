from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, UploadFile
from sqlalchemy import func, or_, select
from starlette.concurrency import run_in_threadpool

from .contracts import (
    GraphOutput,
    IndexConfiguration,
    IndexOutput,
    LinksOutput,
    NoteDetailOutput,
    NotesOutput,
    RetrievalSettings,
    SearchInput,
    SearchOutput,
    SyncOutput,
    VaultOutput,
)
from .database import IndexGeneration, Note, NoteLink, NoteTag, RetrievalProfile, SyncRun, Vault, now
from .service import record

router = APIRouter(prefix="/api", tags=["Phase 2 knowledge"])


def service(request):
    return request.app.state.service


def note_record(note):
    return {
        **record(note),
        "source_url": f"/api/documents/{note.document_id}/source?"
        + urlencode({"workspace_id": note.workspace_id, "note_id": note.id})
        if note.document_id and note.status == "ready" and not note.deleted
        else None,
    }


def vault_record(session, vault):
    count = session.scalar(
        select(func.count())
        .select_from(Note)
        .where(Note.vault_id == vault.id, Note.workspace_id == vault.workspace_id, Note.deleted.is_(False))
    )
    unresolved = session.scalar(
        select(func.count())
        .select_from(NoteLink)
        .where(
            NoteLink.vault_id == vault.id,
            NoteLink.workspace_id == vault.workspace_id,
            NoteLink.status.in_(["ambiguous", "unresolved", "missing_anchor", "blocked"]),
        )
    )
    return {**record(vault), "note_count": count, "unresolved_count": unresolved}


async def archive_bytes(file, svc):
    if (
        not file.filename
        or not file.filename.lower().endswith(".zip")
        or file.content_type
        not in {"application/zip", "application/x-zip-compressed", "application/octet-stream"}
    ):
        await file.close()
        raise HTTPException(415, "Choose an unencrypted regular-file ZIP containing Markdown notes.")
    content = await file.read(svc.settings.max_upload_mb * 1024 * 1024 + 1)
    await file.close()
    if len(content) > svc.settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(413, "Vault ZIP exceeds the configured upload limit.")
    return content


@router.post("/workspaces/{workspace_id}/search", response_model=SearchOutput)
def search(workspace_id: str, body: SearchInput, request: Request):
    svc = service(request)
    with svc.lock, svc.sessions() as session:
        results, diagnostics = svc.rag.search(session, workspace_id, body.query, body.filters, body.options)
        return {"results": results, "diagnostics": diagnostics if body.diagnostics else None}


@router.get("/workspaces/{workspace_id}/retrieval-settings", response_model=RetrievalSettings)
def retrieval_settings(workspace_id: str, request: Request):
    svc = service(request)
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        return svc.rag.profile(session, workspace_id)


@router.patch("/workspaces/{workspace_id}/retrieval-settings", response_model=RetrievalSettings)
def update_retrieval(workspace_id: str, body: RetrievalSettings, request: Request):
    svc = service(request)
    with svc.lock, svc.sessions.begin() as session:
        svc.repo.workspace(session, workspace_id)
        current = svc.rag.profile(session, workspace_id).model_dump()
        updated = RetrievalSettings.model_validate({**current, **body.model_dump(exclude_unset=True)})
        session.merge(RetrievalProfile(workspace_id=workspace_id, configuration=updated.model_dump()))
        return updated


@router.post("/workspaces/{workspace_id}/vaults/import", status_code=202, response_model=SyncOutput)
async def import_vault(
    workspace_id: str,
    file: UploadFile,
    request: Request,
    name: str = Query("Imported vault", min_length=1, max_length=100),
    source_kind: Literal["snapshot", "agent"] = "snapshot",
):
    svc = service(request)
    content = await archive_bytes(file, svc)
    vault, run = await run_in_threadpool(svc.vaults.prepare, workspace_id, content, name, None, source_kind)
    return {"vault": record(vault), "run": record(run)}


@router.get("/workspaces/{workspace_id}/vaults", response_model=list[VaultOutput])
def vaults(workspace_id: str, request: Request):
    svc = service(request)
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        return [
            vault_record(session, vault)
            for vault in session.scalars(
                select(Vault).where(Vault.workspace_id == workspace_id).order_by(Vault.created_at)
            )
        ]


@router.get("/vaults/{vault_id}/notes", response_model=NotesOutput)
def notes(
    vault_id: str,
    request: Request,
    workspace_id: str = Query(...),
    q: str = Query("", max_length=200),
    tag: str | None = Query(None, max_length=100),
    prefix: str = Query("", max_length=512),
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=300),
):
    svc = service(request)
    with svc.sessions() as session:
        svc.repo.get(session, Vault, vault_id, workspace_id)
        query = select(Note).where(
            Note.workspace_id == workspace_id, Note.vault_id == vault_id, Note.deleted.is_(False)
        )
        if q:
            query = query.where(Note.path.icontains(q, autoescape=True))
        if prefix:
            query = query.where(Note.path.startswith(prefix, autoescape=True))
        if tag:
            query = query.where(
                select(NoteTag.note_id)
                .where(NoteTag.note_id == Note.id, NoteTag.workspace_id == workspace_id, NoteTag.tag == tag)
                .exists()
            )
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        return {
            "notes": [
                note_record(note)
                for note in session.scalars(query.order_by(Note.path).offset(offset).limit(limit))
            ],
            "total": total,
        }


@router.get("/notes/{note_id}", response_model=NoteDetailOutput)
def note_detail(note_id: str, request: Request, workspace_id: str = Query(...)):
    svc = service(request)
    with svc.sessions() as session:
        note = svc.repo.get(session, Note, note_id, workspace_id)
        if note.deleted:
            raise HTTPException(410, "This note was deleted from its vault.")
        links = list(
            session.scalars(
                select(NoteLink).where(
                    NoteLink.workspace_id == workspace_id,
                    or_(NoteLink.source_id == note_id, NoteLink.target_id == note_id),
                )
            )
        )
        return {
            "note": note_record(note),
            "outlinks": [record(link) for link in links if link.source_id == note_id],
            "backlinks": [record(link) for link in links if link.target_id == note_id],
        }


@router.get("/vaults/{vault_id}/links", response_model=LinksOutput)
def links(
    vault_id: str,
    request: Request,
    workspace_id: str = Query(...),
    status: Literal["resolved", "unresolved", "ambiguous", "blocked", "missing_anchor", "external"]
    | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=300),
):
    svc = service(request)
    with svc.sessions() as session:
        svc.repo.get(session, Vault, vault_id, workspace_id)
        query = select(NoteLink).where(NoteLink.workspace_id == workspace_id, NoteLink.vault_id == vault_id)
        if status:
            query = query.where(NoteLink.status == status)
        total = session.scalar(select(func.count()).select_from(query.subquery()))
        return {
            "links": [
                record(link)
                for link in session.scalars(
                    query.order_by(NoteLink.source_id, NoteLink.id).offset(offset).limit(limit)
                )
            ],
            "total": total,
        }


@router.get("/vaults/{vault_id}/sync-status", response_model=SyncOutput)
def sync_status(vault_id: str, request: Request, workspace_id: str = Query(...)):
    svc = service(request)
    with svc.sessions() as session:
        vault = svc.repo.get(session, Vault, vault_id, workspace_id)
        run = session.scalar(
            select(SyncRun)
            .where(SyncRun.vault_id == vault_id, SyncRun.workspace_id == workspace_id)
            .order_by(SyncRun.created_at.desc())
        )
        return {"vault": vault_record(session, vault), "run": record(run) if run else None}


@router.post("/vaults/{vault_id}/sync", status_code=202, response_model=SyncOutput)
async def sync(
    vault_id: str, request: Request, workspace_id: str = Query(...), file: UploadFile | None = None
):
    svc = service(request)
    with svc.lock, svc.sessions.begin() as session:
        vault = svc.repo.get(session, Vault, vault_id, workspace_id)
        if file is None:
            if vault.source_kind != "agent":
                raise HTTPException(
                    409, "This is a ZIP snapshot. Select an updated ZIP to sync; it is not a live folder."
                )
            vault.scan_requested_at = now()
            vault.status = "waiting_agent"
            return {"vault": record(vault), "run": None}
    content = await archive_bytes(file, svc)
    vault, run = await run_in_threadpool(svc.vaults.prepare, workspace_id, content, None, vault_id)
    return {"vault": record(vault), "run": record(run)}


@router.post("/vaults/{vault_id}/retry", status_code=202, response_model=SyncOutput)
def retry_sync(vault_id: str, request: Request, workspace_id: str = Query(...)):
    vault, run = service(request).vaults.retry(workspace_id, vault_id)
    return {"vault": record(vault), "run": record(run)}


@router.get("/workspaces/{workspace_id}/graph", response_model=GraphOutput)
def graph(
    workspace_id: str,
    request: Request,
    vault_id: str | None = None,
    tag: str | None = Query(None, max_length=100),
    kind: Literal["wikilink", "markdown", "embed", "tag"] | None = None,
    q: str = Query("", max_length=200),
    limit: int = Query(150, ge=1, le=300),
):
    svc = service(request)
    with svc.sessions() as session:
        return svc.vaults.graph(session, workspace_id, vault_id, tag, kind, q, limit)


@router.get("/workspaces/{workspace_id}/index-versions", response_model=list[IndexOutput])
def indexes(workspace_id: str, request: Request):
    svc = service(request)
    with svc.lock:
        svc.indexes.ensure(workspace_id)
        with svc.sessions() as session:
            return [
                record(generation)
                for generation in session.scalars(
                    select(IndexGeneration)
                    .where(IndexGeneration.workspace_id == workspace_id)
                    .order_by(IndexGeneration.created_at.desc())
                )
            ]


@router.post("/workspaces/{workspace_id}/indexes/rebuild", status_code=202, response_model=IndexOutput)
def rebuild(workspace_id: str, body: IndexConfiguration, request: Request):
    svc = service(request)
    current = svc.indexes.ensure(workspace_id).configuration
    config = IndexConfiguration.model_validate({**current, **body.model_dump(exclude_unset=True)})
    return record(svc.indexes.rebuild(workspace_id, config))


@router.post("/index-versions/{generation_id}/{action}", response_model=IndexOutput)
def index_action(
    generation_id: str,
    action: Literal["retry", "activate", "cancel"],
    request: Request,
    workspace_id: str = Query(...),
):
    return record(service(request).indexes.action(workspace_id, generation_id, action))
