"""Authenticated, user-private configuration APIs and provisional SSE delivery."""

import asyncio
import json
import queue
import threading
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict
from sqlalchemy import func, select

from .auth import principal, required_role
from .byok import ConfigurationInput, owner_id
from .contracts import ChatInput
from .database import Chat, ProviderConfiguration, ProviderSelection, ProviderUsage, now, uid
from .provider_transport import PROVIDERS, ProviderFailure, ProviderTransport, base_url
from .providers import ProviderError
from .service import record

router = APIRouter(prefix="/api", tags=["Private model configurations"])


def service(request):
    svc = request.app.state.service
    if svc.settings.profile == "server" and svc.settings.secure_cookies and request.url.scheme != "https":
        raise HTTPException(
            403, "BYOK requires HTTPS in the server profile. Configure TLS and trusted proxy headers."
        )
    owner_id(svc.settings)
    return svc


@router.get("/me/provider-configurations")
def configurations(request: Request, response: Response):
    svc = service(request)
    response.headers["Cache-Control"] = "no-store"
    owner = owner_id(svc.settings)
    with svc.sessions() as session:
        rows = session.scalars(
            select(ProviderConfiguration)
            .where(ProviderConfiguration.owner == owner, ProviderConfiguration.deleted.is_(False))
            .order_by(ProviderConfiguration.created_at)
        )
        return {
            "default_unavailable": bool(
                session.scalar(
                    select(ProviderConfiguration.id).where(
                        ProviderConfiguration.owner == owner,
                        ProviderConfiguration.is_default.is_(True),
                        ProviderConfiguration.deleted.is_(True),
                    )
                )
            ),
            "configurations": [svc.byok.public(row) for row in rows],
            "providers": PROVIDERS,
            "credential_storage": {
                "enabled": svc.byok.vault.enabled,
                "message": "AES-256-GCM; master key stored outside the database."
                if svc.byok.vault.enabled
                else "Cloud credential storage is disabled until the operator configures a secure master key. Local Ollama remains available.",
            },
        }


@router.post("/me/provider-configurations", status_code=201)
def create_configuration(body: ConfigurationInput, request: Request):
    return service(request).byok.save(body)


class PreviewInput(ConfigurationInput):
    configuration_id: str | None = None


@router.post("/me/provider-configurations/preview")
def preview_configuration(body: PreviewInput, request: Request):
    svc = service(request)
    target = base_url(svc.settings, body.provider, body.base_url)
    key = body.api_key.get_secret_value() if body.api_key else ""
    if body.configuration_id:
        with svc.sessions() as session:
            row = svc.byok.get(session, body.configuration_id)
            if row.configuration["provider"] != body.provider or row.configuration["destination"] != target:
                raise HTTPException(
                    409, "A saved credential cannot be tested at another provider or endpoint."
                )
            if not key and body.provider != "ollama":
                key = svc.byok.vault.decrypt(row)
    adapter = ProviderTransport(svc.settings, body.model_dump(exclude={"api_key", "configuration_id"}), key)
    try:
        models, connection = adapter.check()
        return {"models": models, "connection": connection}
    except ProviderFailure as error:
        return {"models": [], "connection": {"status": error.code, "message": str(error)}}


@router.put("/me/provider-configurations/{identifier}")
def update_configuration(identifier: str, body: ConfigurationInput, request: Request):
    return service(request).byok.save(body, identifier)


@router.delete("/me/provider-configurations/{identifier}", status_code=204)
def delete_configuration(identifier: str, request: Request):
    svc = service(request)
    with svc.lock, svc.sessions.begin() as session:
        row = svc.byok.get(session, identifier)
        # A tombstone keeps selected/default routes blocked instead of silently falling back.
        row.deleted, row.encrypted_key, row.models, row.connection = True, None, [], {}
        row.revision = uid()


@router.delete("/me/provider-configurations/{identifier}/credential", status_code=204)
def delete_credential(identifier: str, request: Request):
    svc = service(request)
    with svc.lock, svc.sessions.begin() as session:
        row = svc.byok.get(session, identifier)
        row.encrypted_key, row.models, row.revision = None, [], uid()
        row.updated_at = now()
        row.connection = {
            "status": "not_configured",
            "message": "Stored credential removed. Revoke it at the provider if necessary.",
        }


@router.post("/me/provider-configurations/{identifier}/default")
def make_default(identifier: str, request: Request):
    svc = service(request)
    with svc.lock, svc.sessions.begin() as session:
        row = svc.byok.get(session, identifier)
        for other in session.scalars(
            select(ProviderConfiguration).where(ProviderConfiguration.owner == row.owner)
        ):
            other.is_default = other.id == row.id
        return {"default_id": row.id}


@router.delete("/me/provider-default", status_code=204)
def clear_default(request: Request):
    svc = service(request)
    with svc.lock, svc.sessions.begin() as session:
        for row in session.scalars(
            select(ProviderConfiguration).where(ProviderConfiguration.owner == owner_id(svc.settings))
        ):
            row.is_default = False


def provider_action(identifier, request, check):
    svc = service(request)
    with svc.sessions() as session:
        row = svc.byok.get(session, identifier)
        revision = row.revision
        adapter = svc.byok.transport(row)
    try:
        models, status = adapter.check() if check else (adapter.models(), None)
    except ProviderFailure as error:
        if not check:
            raise
        models, status = None, {"status": error.code, "message": str(error), "scope": "metadata_only"}
    with svc.lock, svc.sessions.begin() as session:
        row = svc.byok.get(session, identifier)
        if row.revision != revision:
            raise HTTPException(
                409, "Configuration changed during the check. Test the current settings again."
            )
        if models is not None:
            row.models = models
        if check:
            row.connection = {**status, "checked_at": now()}
            return row.connection
        return {
            "models": row.models,
            "fetched_at": now(),
            "limit": 1500,
            "note": "Provider metadata may be incomplete; manual identifiers remain available.",
        }


@router.post("/me/provider-configurations/{identifier}/test")
def test_configuration(identifier: str, request: Request):
    return provider_action(identifier, request, True)


@router.post("/me/provider-configurations/{identifier}/models")
def refresh_models(identifier: str, request: Request):
    return provider_action(identifier, request, False)


@router.get("/me/provider-configurations/{identifier}/models")
def cached_models(identifier: str, request: Request):
    svc = service(request)
    with svc.sessions() as session:
        return {"models": svc.byok.get(session, identifier).models}


class SelectionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    configuration_id: str | None = None
    use_default: bool = False


@router.get("/workspaces/{workspace_id}/ai-selection")
def selection(workspace_id: str, request: Request):
    svc, owner = service(request), owner_id(request.app.state.service.settings)
    with svc.sessions() as session:
        workspace = svc.repo.workspace(session, workspace_id)
        row = svc.byok.resolve(session, workspace_id, allow_removed=True)
        chosen = session.get(ProviderSelection, (owner, workspace_id))
        configs = session.scalars(
            select(ProviderConfiguration)
            .where(ProviderConfiguration.owner == owner, ProviderConfiguration.deleted.is_(False))
            .order_by(ProviderConfiguration.created_at)
        )
        return {
            "active": svc.byok.public(row) if row and not row.deleted else None,
            "unavailable": bool(row and row.deleted),
            "selection": chosen.configuration_id if chosen else "default",
            "workspace_cloud_allowed": workspace.cloud_opt_in,
            "configurations": [
                {
                    "id": r.id,
                    "name": r.configuration["name"],
                    "provider": r.configuration["provider"],
                    "model": r.configuration["model"],
                    "is_default": r.is_default,
                }
                for r in configs
            ],
        }


@router.put("/workspaces/{workspace_id}/ai-selection")
def select_model(workspace_id: str, body: SelectionInput, request: Request):
    svc = service(request)
    owner = owner_id(svc.settings)
    with svc.lock, svc.sessions.begin() as session:
        svc.repo.workspace(session, workspace_id)
        if body.configuration_id:
            svc.byok.validate(session, workspace_id, svc.byok.get(session, body.configuration_id))
        current = session.get(ProviderSelection, (owner, workspace_id))
        if body.use_default:
            if current:
                session.delete(current)
        elif current:
            current.configuration_id = body.configuration_id
        else:
            session.add(
                ProviderSelection(
                    owner=owner, workspace_id=workspace_id, configuration_id=body.configuration_id
                )
            )
    return {"saved": True}


@router.get("/me/provider-usage")
def usage(request: Request):
    svc, owner = service(request), owner_id(request.app.state.service.settings)
    month = datetime.now(timezone.utc).strftime("%Y-%m-01")
    with svc.sessions() as session:
        rows = session.scalars(
            select(ProviderUsage)
            .where(ProviderUsage.owner == owner)
            .order_by(ProviderUsage.created_at.desc())
            .limit(100)
        )
        events = [record(row) for row in rows]
        configs = list(
            session.scalars(
                select(ProviderConfiguration).where(
                    ProviderConfiguration.owner == owner, ProviderConfiguration.deleted.is_(False)
                )
            )
        )
        summaries = []
        for row in configs:
            total, unknown = session.execute(
                select(
                    func.coalesce(func.sum(ProviderUsage.cost_usd), 0),
                    func.sum(ProviderUsage.cost_usd.is_(None)),
                ).where(
                    ProviderUsage.owner == owner,
                    ProviderUsage.configuration_id == row.id,
                    ProviderUsage.created_at >= month,
                )
            ).one()
            threshold = row.configuration.get("spending_warning_usd")
            summaries.append(
                {
                    "configuration_id": row.id,
                    "month": month,
                    "known_cost_usd": total,
                    "unknown_cost_requests": int(unknown or 0),
                    "warning_usd": threshold,
                    "warning_reached": threshold is not None and total >= threshold,
                }
            )
        return {
            "events": events,
            "summaries": summaries,
            "note": "Only provider-reported tokens are recorded. Costs are labeled reported or estimated. Unknown usage/cost remains unknown. Local warnings and request limits do not enforce provider billing.",
        }


@router.post("/chats/{chat_id}/messages/stream")
async def stream_message(chat_id: str, body: ChatInput, request: Request, workspace_id: str):
    svc = request.app.state.service
    # Authenticate and authorize before sending SSE headers. A worker retains this exact identity.
    actor, role = principal.get(), required_role.get()
    with svc.sessions() as session:
        svc.repo.get(session, Chat, chat_id, workspace_id)
        svc.gateway.generator(session, workspace_id)
    if not svc.stream_slots.acquire(blocking=False):
        raise HTTPException(503, "All response streams are busy. Retry shortly.")
    cancelled, events = threading.Event(), queue.Queue(maxsize=64)

    def publish(event, data):
        while not cancelled.is_set():
            try:
                events.put((event, data), timeout=0.1)
                return
            except queue.Full:
                pass
        from .provider_transport import GenerationCancelled

        raise GenerationCancelled()

    def work():
        token, role_token = principal.set(actor), required_role.set(role)
        try:
            answer = svc.answer(
                workspace_id,
                chat_id,
                body.content.strip(),
                body.filters,
                body.options,
                body.diagnostics,
                lambda text: publish("delta", {"text": text, "provisional": True}),
                cancelled,
            )
            publish("complete", answer)
        except (HTTPException, ProviderError) as error:
            if not cancelled.is_set():
                publish(
                    "error",
                    {
                        "detail": error.detail if isinstance(error, HTTPException) else str(error),
                        "code": getattr(error, "code", "request_failed"),
                    },
                )
        except Exception:
            if not cancelled.is_set():
                publish(
                    "error",
                    {"detail": "Response failed. No unverified answer was saved.", "code": "request_failed"},
                )
        finally:
            principal.reset(token)
            required_role.reset(role_token)
            svc.stream_slots.release()

    async def deliver():
        task = asyncio.create_task(asyncio.to_thread(work))
        try:
            yield 'event: status\ndata: {"stage":"retrieving","message":"Retrieving and grounding your answer"}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event, data = events.get_nowait()
                except queue.Empty:
                    if task.done():
                        break
                    await asyncio.sleep(0.04)
                    continue
                yield f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"
                if event in {"complete", "error"}:
                    break
        finally:
            cancelled.set()
            # The HTTPX read deadline bounds a provider that stops emitting after disconnect.
            task.add_done_callback(
                lambda finished: finished.exception() if not finished.cancelled() else None
            )

    return StreamingResponse(
        deliver(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
