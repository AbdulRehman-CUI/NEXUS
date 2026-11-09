import os
from contextlib import ExitStack, asynccontextmanager
from pathlib import Path
from typing import Literal

import httpx
from alembic import command
from alembic.config import Config
from fastapi import FastAPI, HTTPException, Query, UploadFile
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from sqlalchemy import func, select, text
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import Settings
from .contracts import ChatInput
from .database import Chat, Chunk, Citation, Document, IndexGeneration, Job, Note, Span, Workspace, database
from .middleware import UploadLimitMiddleware
from .providers import ProviderError
from .service import Service, record
from .storage import FileStorage


class NameInput(BaseModel):
    name: str = Field(min_length=1, max_length=100, pattern=r".*\S.*")


class WorkspaceInput(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=100)
    cloud_opt_in: bool | None = None


class TitleInput(BaseModel):
    title: str = Field(min_length=1, max_length=100)


class QuestionInput(BaseModel):
    content: str = Field(min_length=1, max_length=4000, pattern=r".*\S.*")


class ProviderInput(BaseModel):
    generation_provider: Literal["mock", "groq"]
    generation_model: str = Field(min_length=1, max_length=150, pattern=r"^[\w./:-]+$")
    free_tier_confirmed: bool


def create_app(settings: Settings | None = None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        from .lease import DataLease
        from .logging_setup import configure_logging

        configure_logging()

        settings.data_dir = settings.data_dir.resolve()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        database_url = settings.database_url.get_secret_value()
        with ExitStack() as cleanup:
            if not database_url:
                cleanup.enter_context(DataLease(settings.data_dir))
            if (settings.data_dir / ".restoring").exists():
                raise RuntimeError(
                    "Incomplete restore directory. Restore a verified backup into a new directory."
                )
            safe_config = FileStorage(settings.data_dir)
            saved = safe_config.path("provider.json")
            if not database_url and saved.exists():
                config = ProviderInput.model_validate_json(saved.read_text("utf-8"))
                for key, value in config.model_dump().items():
                    setattr(settings, key, value)
            engine, sessions = database(settings.data_dir / "nexus.sqlite3", database_url)
            cleanup.callback(engine.dispose)
            config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
            with engine.begin() as connection:
                if database_url:
                    connection.execute(text("SELECT pg_advisory_xact_lock(834102, 1)"))
                config.attributes["connection"] = connection
                command.upgrade(config, "head")
            service = Service(settings, sessions)
            cleanup.callback(service.close)
            app.state.service = service
            app.state.engine = engine
            if settings.profile == "server":
                from .auth import hash_password

                app.state.dummy_password = hash_password(os.urandom(24).hex())
            service.start()
            yield

    app = FastAPI(title="NEXUS API", version="0.3.0-rc.1", lifespan=lifespan)
    app.add_middleware(UploadLimitMiddleware, max_bytes=settings.max_upload_mb * 1024 * 1024 + 65536)
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.allowed_hosts)
    from .http_boundary import install_boundary

    install_boundary(app, settings)
    # CORS must wrap admission errors as well as successful route responses.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PATCH", "PUT", "DELETE"],
        allow_headers=["Content-Type", "X-CSRF-Token"],
        expose_headers=["X-Request-ID"],
    )

    @app.exception_handler(ProviderError)
    async def provider_error(_, error):
        return JSONResponse(
            {"detail": str(error), "code": getattr(error, "code", "provider_error")},
            status_code=error.status,
            headers={"Retry-After": "60"} if error.status == 429 else None,
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, error):
        if request.url.path in {"/api/auth/guest", "/api/auth/login"}:
            return JSONResponse({"detail": "Invalid session request."}, status_code=422)
        if request.url.path.startswith("/api/me/provider-configurations") or request.url.path.endswith(
            "/ai-selection/configuration"
        ):
            # Pydantic's default error response includes the rejected input value.
            return JSONResponse(
                {
                    "detail": "Invalid provider configuration. Check field lengths, model ID, and generation limits."
                },
                status_code=422,
            )
        return await request_validation_exception_handler(request, error)

    def svc() -> Service:
        return app.state.service

    @app.get("/health")
    def health():
        from .auth import principal

        actor = principal.get()
        restricted_health = settings.profile == "server" and (actor is None or actor.guest)
        service = svc()
        with service.lock, service.sessions() as session:
            sql = session.execute(text("SELECT 1")).scalar() == 1
            service.index.count()
            count = session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(
                    select(IndexGeneration.id)
                    .where(
                        IndexGeneration.active.is_(True),
                        IndexGeneration.workspace_id == Chunk.workspace_id,
                        IndexGeneration.fingerprint == Chunk.fingerprint,
                    )
                    .exists()
                )
            )
            loaded = settings.embedding_provider == "hash" or any(
                getattr(embedding, "model", None) is not None
                for embedding, _ in service.indexes.adapters.values()
            )
        if restricted_health:
            return {"status": "ok"}
        return {
            "status": "ok",
            "sqlite": sql,
            "vectors": True,
            "indexed_chunks": count,
            "files": bool(settings.database_url.get_secret_value()) or os.access(service.files.root, os.W_OK),
            "worker": bool(service.thread and service.thread.is_alive()),
            "embedding_provider": settings.embedding_provider,
            "embedding_loaded": loaded,
        }

    @app.get("/api/workspaces")
    def workspaces():
        from .auth import principal
        from .database import Membership

        with svc().sessions() as session:
            query = select(Workspace).order_by(Workspace.created_at)
            if settings.profile == "server":
                actor = principal.get()
                query = (
                    query.where(Workspace.id == actor.id)
                    if actor.guest
                    else query.join(Membership).where(Membership.user_id == actor.id)
                )
            return [record(w) for w in session.scalars(query)]

    @app.post("/api/workspaces", status_code=201)
    def create_workspace(body: NameInput):
        from .auth import principal
        from .database import Membership

        actor = principal.get()
        if actor and actor.guest:
            raise HTTPException(403, "A guest session has one private workspace.")
        with svc().sessions.begin() as session:
            workspace = Workspace(name=body.name.strip())
            session.add(workspace)
            session.flush()
            if settings.profile == "server":
                session.add(Membership(workspace_id=workspace.id, user_id=principal.get().id, role="owner"))
            return record(workspace)

    @app.patch("/api/workspaces/{workspace_id}")
    def update_workspace(workspace_id: str, body: WorkspaceInput):
        with svc().lock, svc().sessions.begin() as session:
            workspace = svc().repo.workspace(session, workspace_id)
            for key, value in body.model_dump(exclude_none=True).items():
                if key == "name" and not value.strip():
                    raise HTTPException(422, "Workspace name cannot be blank")
                setattr(workspace, key, value)
            return record(workspace)

    @app.get("/api/workspaces/{workspace_id}/documents")
    def documents(workspace_id: str):
        with svc().sessions() as session:
            svc().repo.workspace(session, workspace_id)
            return [
                {
                    **record(d),
                    "needs_reindex": d.status == "ready"
                    and d.fingerprint != svc().indexes.ensure(workspace_id).fingerprint,
                }
                for d in session.scalars(
                    select(Document)
                    .where(Document.workspace_id == workspace_id)
                    .order_by(Document.created_at.desc())
                )
            ]

    @app.post("/api/workspaces/{workspace_id}/documents", status_code=202)
    async def upload(workspace_id: str, file: UploadFile):
        from starlette.concurrency import run_in_threadpool

        limit = settings.max_upload_mb * 1024 * 1024
        content = await file.read(limit + 1)
        await file.close()
        if len(content) > limit:
            raise HTTPException(413, f"File exceeds {settings.max_upload_mb} MB. Split it and retry.")
        return await run_in_threadpool(
            svc().upload, workspace_id, file.filename or "", file.content_type or "", content
        )

    @app.get("/api/documents/{document_id}")
    def document_detail(document_id: str, workspace_id: str = Query(...)):
        with svc().sessions() as session:
            document = svc().repo.get(session, Document, document_id, workspace_id)
            count = session.scalar(
                select(func.count())
                .select_from(Chunk)
                .where(Chunk.document_id == document_id, Chunk.workspace_id == workspace_id)
            )
            jobs = session.scalars(
                select(Job)
                .where(Job.document_id == document_id, Job.workspace_id == workspace_id)
                .order_by(Job.created_at.desc())
            )
            return {
                **record(document),
                "chunk_count": count,
                "jobs": [record(j) for j in jobs],
                "needs_reindex": document.fingerprint != svc().indexes.ensure(workspace_id).fingerprint,
            }

    @app.post("/api/documents/{document_id}/reindex", status_code=202)
    def reindex(document_id: str, workspace_id: str = Query(...)):
        return svc().enqueue(workspace_id, document_id)

    @app.delete("/api/documents/{document_id}", status_code=202)
    def delete_document(document_id: str, workspace_id: str = Query(...)):
        return svc().enqueue(workspace_id, document_id, "delete")

    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str, workspace_id: str = Query(...)):
        with svc().sessions() as session:
            return record(svc().repo.get(session, Job, job_id, workspace_id))

    @app.get("/api/documents/{document_id}/source")
    def source(
        document_id: str,
        workspace_id: str = Query(...),
        citation_id: str | None = None,
        page: int | None = Query(None, ge=1),
        heading: str | None = None,
        note_id: str | None = None,
        chunk_id: str | None = None,
    ):
        with svc().lock, svc().sessions() as session:
            document = svc().repo.get(session, Document, document_id, workspace_id)
            if document.status == "deleting":
                raise HTTPException(409, "Document is awaiting deletion")
            citation = None
            query = (
                select(Span)
                .where(
                    Span.document_id == document_id,
                    Span.workspace_id == workspace_id,
                    Span.version_id == document.version_id,
                )
                .order_by(Span.ordinal)
            )
            if citation_id:
                stored = svc().repo.get(session, Citation, citation_id, workspace_id)
                if stored.document_id != document_id:
                    raise HTTPException(404, "Citation does not belong to this document")
                citation = stored.payload
                if not svc().citation_available(session, citation):
                    raise HTTPException(
                        410, "This historical source is unavailable after a note revision or deletion."
                    )
                if note_id and note_id != citation.get("note_id"):
                    raise HTTPException(404, "Citation does not belong to this note")
                note_id = citation.get("note_id") or note_id
                chunk = svc().repo.get(session, Chunk, stored.chunk_id, workspace_id)
                query = query.where(Span.id == chunk.span_id)
            elif chunk_id:
                chunk = svc().repo.get(session, Chunk, chunk_id, workspace_id)
                if chunk.document_id != document_id or chunk.version_id != document.version_id:
                    raise HTTPException(404, "Chunk does not belong to this document version")
                query = query.where(Span.id == chunk.span_id)
            elif page:
                query = query.where(Span.page == page)
            elif heading:
                query = query.where(Span.heading == heading)
            spans = [record(s) for s in session.scalars(query)]
            note = svc().repo.get(session, Note, note_id, workspace_id) if note_id else None
            if note and (
                note.deleted
                or note.document_id != document_id
                or note.status != "ready"
                or note.content_hash != document.content_hash
            ):
                raise HTTPException(
                    410, "This note revision is unavailable. Open the current note from the vault."
                )
            if not spans:
                raise HTTPException(
                    404, "No indexed source at this locator. Wait for indexing or reindex the document."
                )
            return {
                "document": {
                    **record(document),
                    **({"title": note.path, "note_id": note.id, "vault_id": note.vault_id} if note else {}),
                },
                "spans": spans,
                "citation": citation,
                "file_url": f"/api/documents/{document_id}/file?workspace_id={workspace_id}",
            }

    @app.get("/api/documents/{document_id}/file")
    def original(document_id: str, workspace_id: str = Query(...)):
        with svc().lock, svc().sessions() as session:
            document = svc().repo.get(session, Document, document_id, workspace_id)
            if document.status == "deleting":
                raise HTTPException(409, "Document is awaiting deletion")
            media_type = {
                ".pdf": "application/pdf",
                ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            }.get(document.extension, "text/plain")
            disposition = "inline" if document.extension == ".pdf" else "attachment"
            if settings.database_url.get_secret_value():
                from urllib.parse import quote

                try:
                    content = svc().files.read(document.storage_key, session=session)
                except FileNotFoundError:
                    raise HTTPException(404, "Original file is unavailable") from None
                return Response(
                    content,
                    media_type=media_type,
                    headers={
                        "Content-Disposition": f"{disposition}; filename*=UTF-8''{quote(document.title, safe='')}"
                    },
                )
            path = svc().files.path(document.storage_key)
            if not path.is_file():
                raise HTTPException(404, "Original file is unavailable")
            return FileResponse(
                path,
                media_type=media_type,
                filename=document.title,
                content_disposition_type=disposition,
            )

    @app.get("/api/workspaces/{workspace_id}/chats")
    def chats(workspace_id: str):
        with svc().sessions() as session:
            svc().repo.workspace(session, workspace_id)
            return [
                record(c)
                for c in session.scalars(
                    select(Chat).where(Chat.workspace_id == workspace_id).order_by(Chat.created_at.desc())
                )
            ]

    @app.post("/api/workspaces/{workspace_id}/chats", status_code=201)
    def create_chat(workspace_id: str):
        with svc().sessions.begin() as session:
            svc().repo.workspace(session, workspace_id)
            chat = Chat(workspace_id=workspace_id)
            session.add(chat)
            session.flush()
            return record(chat)

    @app.get("/api/chats/{chat_id}")
    def chat_detail(chat_id: str, workspace_id: str = Query(...)):
        with svc().sessions() as session:
            chat = svc().repo.get(session, Chat, chat_id, workspace_id)
            return {**record(chat), "messages": svc().messages(session, chat)}

    @app.patch("/api/chats/{chat_id}")
    def rename_chat(chat_id: str, body: TitleInput, workspace_id: str = Query(...)):
        with svc().lock, svc().sessions.begin() as session:
            chat = svc().repo.get(session, Chat, chat_id, workspace_id)
            if not body.title.strip():
                raise HTTPException(422, "Title cannot be blank")
            chat.title = body.title.strip()
            return record(chat)

    @app.delete("/api/chats/{chat_id}", status_code=204)
    def delete_chat(chat_id: str, workspace_id: str = Query(...)):
        with svc().lock, svc().sessions.begin() as session:
            session.delete(svc().repo.get(session, Chat, chat_id, workspace_id))

    @app.post("/api/chats/{chat_id}/messages")
    def send_message(chat_id: str, body: ChatInput, workspace_id: str = Query(...)):
        return svc().answer(
            workspace_id, chat_id, body.content.strip(), body.filters, body.options, body.diagnostics
        )

    def public_settings():
        return {
            "generation_provider": settings.generation_provider,
            "generation_model": settings.generation_model,
            "free_tier_confirmed": settings.free_tier_confirmed,
            "groq_key_configured": bool(settings.groq_api_key.get_secret_value()),
            "embedding_provider": settings.embedding_provider,
            "embedding_model": settings.embedding_model,
            "index_fingerprint": svc().index.fingerprint,
            "max_upload_mb": settings.max_upload_mb,
            "disclosure": "Cloud models receive your question and retrieved document excerpts. Opt in per workspace before use.",
            "security": "Authenticated server profile with workspace membership."
            if settings.profile == "server"
            else "Local single-user profile. Non-loopback clients are refused.",
        }

    @app.get("/api/settings/public")
    def get_settings():
        return public_settings()

    @app.patch("/api/settings/public")
    def update_settings(body: ProviderInput):
        if settings.database_url.get_secret_value():
            raise HTTPException(409, "Configure hosted server defaults through environment variables.")
        with svc().lock:
            FileStorage(settings.data_dir).write("provider.json", body.model_dump_json().encode())
            for key, value in body.model_dump().items():
                setattr(settings, key, value)
        return public_settings()

    @app.get("/api/providers")
    def providers():
        key = bool(settings.groq_api_key.get_secret_value())
        return [
            {
                "id": "mock",
                "name": "Offline demo",
                "available": True,
                "remote": False,
                "detail": "Deterministic passage extraction. No generative model or API key.",
            },
            {
                "id": "groq",
                "name": "Groq Free Plan",
                "available": key and settings.free_tier_confirmed,
                "remote": True,
                "detail": "Requires server key, eligible free account/model, and workspace opt-in.",
            },
        ]

    @app.post("/api/providers/groq/check")
    def check_provider():
        if not settings.groq_api_key.get_secret_value():
            raise ProviderError("Groq API key is missing.")
        if not settings.free_tier_confirmed:
            raise ProviderError("Confirm free-tier eligibility before checking the provider.")
        try:
            response = httpx.get(
                "https://api.groq.com/openai/v1/models",
                headers={"Authorization": f"Bearer {settings.groq_api_key.get_secret_value()}"},
                timeout=15,
                follow_redirects=False,
                trust_env=False,
            )
            if not response.is_success:
                raise ProviderError(f"Groq model check returned HTTP {response.status_code}.")
            models = [m["id"] for m in response.json()["data"]]
            return {
                "reachable": True,
                "model_available": settings.generation_model in models,
                "models": models,
                "note": "Model availability does not verify your billing tier or remaining quota.",
            }
        except (httpx.HTTPError, ValueError, KeyError, TypeError) as error:
            raise ProviderError("Unable to check Groq. Verify network and server configuration.") from error

    from .auth import members_router
    from .auth import router as auth_router
    from .routes_byok import router as byok_router
    from .routes_phase2 import router
    from .routes_release import router as release_router

    app.include_router(router)
    app.include_router(auth_router)
    app.include_router(members_router)
    app.include_router(release_router)
    app.include_router(byok_router)
    return app


app = create_app()
