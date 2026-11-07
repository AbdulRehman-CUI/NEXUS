import importlib.util
import time
from typing import Literal

import httpx
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import delete, select

from .auth import authorize, principal
from .contracts import IndexConfiguration, RetrievalSettings, SearchFilters
from .database import (
    Document,
    Feedback,
    IndexGeneration,
    Job,
    Message,
    ModelRegistry,
    Note,
    RequestEvent,
    RetrievalProfile,
    RoutePolicy,
    SyncRun,
    UsageEvent,
    Vault,
)
from .gateway import GenerationPolicy, destination, is_remote
from .providers import ProviderError
from .service import record

router = APIRouter(prefix="/api", tags=["Release controls"])


class BatchInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_ids: list[str] = Field(min_length=1, max_length=100)


@router.post("/workspaces/{workspace_id}/batch-reindex")
def batch_reindex(workspace_id: str, body: BatchInput, request: Request):
    svc = request.app.state.service
    ids = list(dict.fromkeys(body.document_ids))
    with svc.sessions() as session:
        for document_id in ids:
            svc.repo.get(session, Document, document_id, workspace_id)
    results = []
    for document_id in ids:
        try:
            job = svc.enqueue(workspace_id, document_id)
            results.append({"document_id": document_id, "accepted": True, "job_id": job["id"]})
        except HTTPException as error:
            results.append({"document_id": document_id, "accepted": False, "detail": error.detail})
    return {"results": results, "accepted": sum(r["accepted"] for r in results)}


@router.get("/workspaces/{workspace_id}/jobs")
def jobs(workspace_id: str, request: Request, offset: int = 0, limit: int = 50):
    if offset < 0 or not 1 <= limit <= 100:
        raise HTTPException(422, "Invalid job pagination.")
    svc = request.app.state.service
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        return [
            record(j)
            for j in session.scalars(
                select(Job)
                .where(Job.workspace_id == workspace_id)
                .order_by(Job.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
        ]


@router.post("/jobs/{job_id}/{action}")
def job_action(job_id: str, action: Literal["retry", "cancel"], request: Request, workspace_id: str):
    svc = request.app.state.service
    with svc.lock, svc.sessions.begin() as session:
        job = svc.repo.get(session, Job, job_id, workspace_id)
        document = svc.repo.get(session, Document, job.document_id, workspace_id)
        if action == "cancel":
            if job.kind != "index" or job.status != "queued":
                raise HTTPException(
                    409, "Only queued ingestion jobs can be cancelled; deletion cleanup must finish."
                )
            job.status, job.error = "cancelled", "Cancelled by user. Retry to index this document."
            document.status, document.error = "failed", job.error
        else:
            if job.status not in {"failed", "needs_ocr", "cancelled"} or job.attempts >= 3:
                raise HTTPException(
                    409, "Retry requires a failed/cancelled job with fewer than three attempts."
                )
            active = session.scalar(
                select(Job).where(Job.document_id == document.id, Job.status.in_(["queued", "processing"]))
            )
            if active:
                raise HTTPException(409, "Another job is already active for this document.")
            job.status, job.error = "queued", None
            document.status, document.error = ("deleting" if job.kind == "delete" else "queued"), None
        for note in session.scalars(
            select(Note).where(Note.document_id == document.id, Note.deleted.is_(False))
        ):
            note.status = "failed" if action == "cancel" else "pending"
        svc.wake.set()
        return record(job)


@router.post("/vaults/{vault_id}/cancel")
def cancel_sync(vault_id: str, request: Request, workspace_id: str):
    svc = request.app.state.service
    with svc.lock, svc.sessions.begin() as session:
        vault = svc.repo.get(session, Vault, vault_id, workspace_id)
        run = session.scalar(
            select(SyncRun).where(SyncRun.vault_id == vault_id, SyncRun.status.in_(["queued", "processing"]))
        )
        if run is None:
            raise HTTPException(409, "There is no queued/processing sync to cancel.")
        run.status = vault.status = "failed"
        run.error = vault.error = (
            "Sync cancelled. Partial completed notes remain current; retry or submit a replacement snapshot."
        )
        for note in session.scalars(
            select(Note).where(Note.vault_id == vault_id, Note.status == "pending", Note.deleted.is_(False))
        ):
            note.status = "failed"
            if note.document_id:
                doc = session.get(Document, note.document_id)
                if doc and doc.status == "queued":
                    doc.status, doc.error = "failed", "Sync cancelled."
                    for job in session.scalars(
                        select(Job).where(
                            Job.document_id == doc.id, Job.status == "queued", Job.kind == "index"
                        )
                    ):
                        job.status, job.error = "cancelled", "Sync cancelled."
        return {"cancelled": True, "run_id": run.id}


@router.get("/models")
def models(request: Request):
    svc = request.app.state.service
    with svc.sessions() as session:
        result = []
        for row in session.scalars(select(ModelRegistry).order_by(ModelRegistry.id)):
            item = {"id": row.id, **row.configuration, "reachability": "not_checked"}
            provider = item["provider"]
            if item["kind"] == "generation":
                key = getattr(svc.settings, f"{provider}_api_key", None)
                configured = provider in {"mock", "ollama"} or bool(key and key.get_secret_value())
                item.update(
                    configured=configured,
                    status="configured" if configured else "missing_credential",
                    destination=None,
                )
                if (
                    provider in {"openai", "anthropic", "google", "compatible"}
                    and provider not in svc.settings.paid_provider_allowlist
                ):
                    item["status"] = "disabled_by_operator"
                if provider != "compatible" or svc.settings.compatible_base_url:
                    try:
                        item["destination"] = destination(svc.settings, provider)
                    except ProviderError:
                        item["status"] = "invalid_destination"
            elif provider in {"sentence-transformers", "cross-encoder"}:
                item["status"] = (
                    "installed" if importlib.util.find_spec("sentence_transformers") else "not_installed"
                )
            else:
                item["status"] = "installed"
            result.append(item)
        return result


@router.get("/workspaces/{workspace_id}/route-policy", response_model=GenerationPolicy)
def get_policy(workspace_id: str, request: Request):
    svc = request.app.state.service
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        policy = svc.gateway.policy(session, workspace_id)
        return policy or GenerationPolicy(
            provider=svc.settings.generation_provider,
            model=svc.settings.generation_model,
            free_tier_confirmed=svc.settings.free_tier_confirmed,
        )


@router.put("/workspaces/{workspace_id}/route-policy", response_model=GenerationPolicy)
def save_policy(workspace_id: str, body: GenerationPolicy, request: Request):
    svc = request.app.state.service
    with svc.lock, svc.sessions.begin() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        # Configuring an unavailable adapter is allowed; sending remains gated at execution time.
        if body.consent_destination:
            expected = f"{body.provider}|{destination(svc.settings, body.provider)}"
            if body.consent_destination != expected or not is_remote(body.provider):
                raise HTTPException(
                    422, "Consent must name the exact selected remote provider and destination."
                )
        session.merge(RoutePolicy(workspace_id=workspace_id, configuration=body.model_dump()))
        return body


@router.post("/workspaces/{workspace_id}/provider-check")
def check_provider(workspace_id: str, request: Request):
    svc = request.app.state.service
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        policy = svc.gateway.policy(session, workspace_id) or GenerationPolicy()
    if policy.provider == "mock":
        return {
            "reachable": True,
            "model_available": True,
            "models": ["extractive-demo"],
            "note": "No network call.",
        }
    base = destination(svc.settings, policy.provider)
    headers = {}
    if policy.provider != "ollama":
        key = getattr(svc.settings, f"{policy.provider}_api_key").get_secret_value()
        if not key:
            raise ProviderError("Server credential is missing. No check was made.")
        headers = {"Authorization": f"Bearer {key}"}
    if policy.provider == "anthropic":
        headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
    if policy.provider == "google":
        headers = {"x-goog-api-key": key}
    path = "/api/tags" if policy.provider == "ollama" else "/models"
    try:
        with httpx.Client(
            timeout=min(15, policy.timeout_seconds), follow_redirects=False, trust_env=False
        ) as client:
            response = client.get(base + path, headers=headers)
        if not response.is_success:
            raise ProviderError(
                f"Provider model check returned HTTP {response.status_code}.",
                429 if response.status_code == 429 else 503,
            )
        if len(response.content) > 1_000_000:
            raise ValueError()
        data = response.json()
        items = data.get("data", data.get("models", []))
        names = [str(m.get("id", m.get("name", ""))).removeprefix("models/") for m in items][:500]
        return {
            "reachable": True,
            "model_available": policy.model in names,
            "models": names,
            "note": "No excerpts sent. Catalog reachability does not establish billing eligibility, quota or every model capability.",
        }
    except (httpx.HTTPError, ValueError, TypeError, AttributeError) as error:
        raise ProviderError(
            "Provider catalog could not be checked. No generation or fallback was attempted."
        ) from error


class FeedbackInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    rating: Literal["helpful", "not_helpful", "wrong_citation", "missing_evidence"]
    comment: str = Field("", max_length=1000)


@router.post("/messages/{message_id}/feedback", status_code=201)
def feedback(message_id: str, body: FeedbackInput, request: Request, workspace_id: str):
    svc = request.app.state.service
    with svc.sessions.begin() as session:
        message = svc.repo.get(session, Message, message_id, workspace_id)
        if message.role != "assistant":
            raise HTTPException(422, "Feedback must refer to an assistant answer.")
        user = principal.get()
        row = Feedback(
            workspace_id=workspace_id,
            message_id=message_id,
            user_id=user.id if user else None,
            **body.model_dump(),
        )
        session.add(row)
        session.flush()
        return record(row)


@router.get("/workspaces/{workspace_id}/reviews")
def reviews(workspace_id: str, request: Request):
    svc = request.app.state.service
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        return [
            {**record(row), "chat_id": message.chat_id}
            for row, message in session.execute(
                select(Feedback, Message)
                .join(Message, Message.id == Feedback.message_id)
                .where(Feedback.workspace_id == workspace_id)
                .order_by(Feedback.created_at.desc())
                .limit(100)
            )
        ]


class CompareInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=1, max_length=4000)
    filters: SearchFilters = Field(default_factory=SearchFilters)
    policies: list[GenerationPolicy] = Field(min_length=2, max_length=2)


@router.post("/workspaces/{workspace_id}/compare")
def compare(workspace_id: str, body: CompareInput, request: Request):
    svc = request.app.state.service
    with svc.lock, svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        results, _ = svc.rag.search(session, workspace_id, body.question, body.filters)
        evidence = svc.rag.evidence(results)
    answers = []
    for policy in body.policies:
        started = time.perf_counter()
        try:
            if not evidence:
                answer = "Insufficient evidence. No provider was called."
            else:
                answer = svc.gateway.invoke(workspace_id, policy, body.question, evidence)
            import re

            cited = (
                set(re.findall(r"\[(C[a-zA-Z0-9]+)\]", answer))
                if policy.provider != "mock"
                else set(re.findall(r"(?m)^\[(C[a-zA-Z0-9]+)\]\s*$", answer))
            )
            allowed = {e["citation_id"] for e in evidence}
            if cited - allowed:
                raise ProviderError("Comparison returned an unknown citation.", 502)
            with svc.sessions() as session:
                svc.repo.workspace(session, workspace_id)
                if any(not svc.citation_available(session, item) for item in evidence):
                    raise HTTPException(409, "Evidence changed during comparison. Retry.")
            if evidence and not cited:
                answer = "Insufficient cited evidence for a verified comparison answer."
            answers.append(
                {
                    "provider": policy.provider,
                    "model": policy.model,
                    "answer": answer,
                    "citations": [e for e in evidence if e["citation_id"] in cited],
                    "elapsed_ms": round((time.perf_counter() - started) * 1000, 1),
                    "estimated_output_tokens": len(answer.encode()) // 4,
                    "estimated_cost": None,
                    "time_to_first_token_ms": None,
                }
            )
        except (ProviderError, HTTPException) as error:
            answers.append(
                {
                    "provider": policy.provider,
                    "model": policy.model,
                    "unavailable": True,
                    "detail": str(error) if isinstance(error, ProviderError) else error.detail,
                }
            )
    return {
        "same_evidence_chunk_ids": [e["chunk_id"] for e in evidence],
        "answers": answers,
        "note": "Identical evidence; source validity is not claim entailment. Costs unknown, not billed totals. No automatic retries/fallback.",
    }


@router.get("/workspaces/{workspace_id}/diagnostics")
def diagnostics(workspace_id: str, request: Request):
    svc = request.app.state.service
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        events = list(
            session.scalars(
                select(RequestEvent)
                .where(RequestEvent.workspace_id == workspace_id)
                .order_by(RequestEvent.created_at.desc())
                .limit(1000)
            )
        )
        usage = list(
            session.scalars(
                select(UsageEvent)
                .where(UsageEvent.workspace_id == workspace_id)
                .order_by(UsageEvent.created_at.desc())
                .limit(500)
            )
        )
        latencies = sorted(e.elapsed_ms for e in events)
        errors = {}
        for event in events:
            if event.status >= 400:
                errors[str(event.status)] = errors.get(str(event.status), 0) + 1
        jobs = [
            record(j)
            for j in session.scalars(
                select(Job).where(Job.workspace_id == workspace_id).order_by(Job.created_at.desc()).limit(100)
            )
        ]
        builds = [
            record(j)
            for j in session.scalars(
                select(IndexGeneration).where(IndexGeneration.workspace_id == workspace_id)
            )
        ]
        syncs = [
            record(j)
            for j in session.scalars(
                select(SyncRun)
                .where(SyncRun.workspace_id == workspace_id)
                .order_by(SyncRun.created_at.desc())
                .limit(20)
            )
        ]
        memory = cpu = None
        # Process totals are administrator-only; workspace owners get scoped work metrics.
        user = principal.get()
        if svc.settings.profile == "local" or (user and user.admin):
            try:
                import psutil

                process = psutil.Process()
                memory = process.memory_info().rss
                cpu = sum(process.cpu_times()[:2])
            except ImportError:
                pass
        return {
            "request_sample_count": len(events),
            "p50_ms": latencies[len(latencies) // 2] if latencies else None,
            "p95_ms": latencies[min(len(latencies) - 1, int(len(latencies) * 0.95))] if latencies else None,
            "errors": errors,
            "queue_depth": sum(j["status"] in {"queued", "processing"} for j in jobs),
            "jobs": jobs,
            "index_generations": builds,
            "sync_runs": [{k: v for k, v in j.items() if k != "manifest"} for j in syncs],
            "usage": [record(e) for e in usage],
            "estimated_cost": None,
            "cost_note": "No price catalog configured; estimates are not billed costs. Token source is recorded per call.",
            "rss_bytes": memory,
            "cpu_seconds": cpu,
            "time_to_first_token_ms": None,
            "retention_days": svc.settings.telemetry_retention_days,
        }


@router.delete("/workspaces/{workspace_id}/diagnostics", status_code=204)
def clear_diagnostics(workspace_id: str, request: Request):
    svc = request.app.state.service
    with svc.sessions.begin() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        session.execute(delete(RequestEvent).where(RequestEvent.workspace_id == workspace_id))
        # Daily reservations are budget enforcement, not disposable analytics: retain today's usage.
        from datetime import datetime, timezone

        today = datetime.now(timezone.utc).date().isoformat()
        session.execute(
            delete(UsageEvent).where(UsageEvent.workspace_id == workspace_id, UsageEvent.created_at < today)
        )


class SettingsTransfer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    schema_version: Literal[1] = 1
    retrieval: RetrievalSettings
    generation: GenerationPolicy
    index_reference: IndexConfiguration


@router.get("/workspaces/{workspace_id}/settings-export", response_model=SettingsTransfer)
def export_settings(workspace_id: str, request: Request):
    svc = request.app.state.service
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        policy = svc.gateway.policy(session, workspace_id) or GenerationPolicy()
        policy = policy.model_copy(
            update={"consent_destination": "", "allow_paid": False, "free_tier_confirmed": False}
        )
        return SettingsTransfer(
            retrieval=svc.rag.profile(session, workspace_id),
            generation=policy,
            index_reference=svc.indexes.ensure(workspace_id).configuration,
        )


@router.post("/workspaces/{workspace_id}/settings-import")
def import_settings(workspace_id: str, body: SettingsTransfer, request: Request):
    svc = request.app.state.service
    with svc.lock, svc.sessions.begin() as session:
        workspace = svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        policy = body.generation.model_copy(
            update={"consent_destination": "", "allow_paid": False, "free_tier_confirmed": False}
        )
        workspace.cloud_opt_in = False
        session.merge(RetrievalProfile(workspace_id=workspace_id, configuration=body.retrieval.model_dump()))
        session.merge(RoutePolicy(workspace_id=workspace_id, configuration=policy.model_dump()))
        return {
            "imported": True,
            "note": "Cloud consent/paid permission cleared. Index reference is informational; use validated rebuild separately.",
        }
