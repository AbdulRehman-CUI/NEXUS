import asyncio
import hmac
import ipaddress
import logging
import re
import sqlite3
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse

from .auth import COOKIE, Principal, csrf_token, principal, required_role, token_hash
from .database import AuthSession, User, uid
from .database import now as utc_now

logger = logging.getLogger("nexus.requests")


def install_boundary(app, settings):
    buckets = {}
    slots = asyncio.Semaphore(8)

    def store_metric(request_id, user_id, workspace_id, route, method, status, elapsed):
        # Diagnostics must not stall the event loop or compete for a long writer lock on a full disk.
        try:
            with sqlite3.connect(settings.data_dir / "nexus.sqlite3", timeout=0.05) as connection:
                connection.execute(
                    "INSERT INTO request_events (id,user_id,workspace_id,route,method,status,elapsed_ms,created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (request_id, user_id, workspace_id, route, method, status, elapsed, utc_now()),
                )
                cutoff = (
                    datetime.now(timezone.utc) - timedelta(days=settings.telemetry_retention_days)
                ).isoformat()
                connection.execute("DELETE FROM request_events WHERE created_at < ?", (cutoff,))
                connection.execute("DELETE FROM usage_events WHERE created_at < ?", (cutoff,))
        except sqlite3.Error:
            logger.warning("request_metric_write_failed request_id=%s", request_id)

    @app.middleware("http")
    async def boundary(request: Request, call_next):
        started, request_id = time.perf_counter(), uid()
        user_token = role_token = None
        scope = None
        try:
            peer = request.client.host if request.client else ""
            if settings.profile == "local" and peer != "testclient":
                try:
                    loopback = ipaddress.ip_address(peer).is_loopback
                except ValueError:
                    loopback = False
                if not loopback:
                    raise HTTPException(
                        403,
                        "Local mode only accepts loopback connections. Use the authenticated server profile.",
                    )
            origin = request.headers.get("origin")
            mutation = request.method not in {"GET", "HEAD", "OPTIONS"}
            if mutation and origin and origin not in settings.cors_origins:
                raise HTTPException(403, "Origin not allowed")
            if request.method == "OPTIONS":
                return await call_next(request)
            now = time.monotonic()
            login = request.url.path == "/api/auth/login"
            key = (peer, "login" if login else "all")
            if len(buckets) > 5000:
                buckets.clear()  # One process; reverse-proxy network limits remain necessary for server deployments.
            queue = buckets.setdefault(key, deque())
            while queue and queue[0] < now - 60:
                queue.popleft()
            if len(queue) >= (settings.login_limit_per_minute if login else settings.rate_limit_per_minute):
                raise HTTPException(
                    429,
                    "Local request limit reached. Wait one minute and retry.",
                    headers={"Retry-After": "60"},
                )
            queue.append(now)
            user = None
            if settings.profile == "server":
                cookie = request.cookies.get(COOKIE, "")
                with app.state.service.sessions() as session:
                    auth = session.get(AuthSession, token_hash(cookie)) if cookie else None
                    account = (
                        session.get(User, auth.user_id)
                        if auth and auth.expires_at > int(time.time())
                        else None
                    )
                    if account and not account.disabled:
                        user = Principal(account.id, account.admin)
                public = request.url.path in {"/health", "/api/auth/login"}
                if user is None and not public:
                    raise HTTPException(401, "Sign in to continue.")
                if mutation and user and not login:
                    if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), csrf_token(cookie)):
                        raise HTTPException(403, "CSRF token missing or invalid. Reload and retry.")
                if (
                    mutation
                    and request.url.path in {"/api/settings/public", "/api/providers/groq/check"}
                    and not (user and user.admin)
                ):
                    raise HTTPException(403, "Server administrator access is required.")
            user_token = principal.set(user)
            role = "editor" if mutation else "viewer"
            if request.url.path.endswith(("/search", "/compare")):
                role = "viewer"
            if mutation and (
                request.url.path.endswith(("/route-policy", "/retrieval-settings"))
                or "/index" in request.url.path
                or "/members" in request.url.path
                or re.fullmatch(r"/api/workspaces/[^/]+", request.url.path)
            ):
                role = "owner"
            role_token = required_role.set(role)
            match = re.match(r"^/api/workspaces/([^/]+)(?:/|$)", request.url.path)
            scope = match[1] if match else request.query_params.get("workspace_id")
            if scope:
                with app.state.service.sessions() as session:
                    app.state.service.repo.workspace(session, scope)
            try:
                await asyncio.wait_for(slots.acquire(), timeout=2)
            except TimeoutError:
                raise HTTPException(503, "Server is busy. Retry shortly.") from None
            try:
                response = await call_next(request)
            finally:
                slots.release()
        except HTTPException as error:
            response = JSONResponse({"detail": error.detail}, error.status_code, headers=error.headers)
        except Exception as error:
            logger.error("request_failed request_id=%s error_type=%s", request_id, type(error).__name__)
            response = JSONResponse(
                {"detail": "Request failed. Use the request ID when checking server diagnostics."}, 500
            )
        finally:
            if role_token is not None:
                required_role.reset(role_token)
            if user_token is not None:
                principal.reset(user_token)
        response.headers.update(
            {
                "X-Request-ID": request_id,
                "X-Content-Type-Options": "nosniff",
                "Cache-Control": "no-store",
                "Referrer-Policy": "no-referrer",
                "X-Frame-Options": "SAMEORIGIN",
                "Content-Security-Policy": "default-src 'none'; frame-ancestors 'self'; sandbox allow-same-origin allow-scripts",
            }
        )
        if response.headers.get("content-type", "").startswith("application/pdf"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; frame-ancestors 'self' " + " ".join(settings.cors_origins)
            )
            del response.headers["X-Frame-Options"]
        if request.url.path in {"/docs", "/redoc"}:
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; img-src 'self' https://fastapi.tiangolo.com data:; frame-ancestors 'self'"
            )
        if settings.profile == "server" and settings.secure_cookies:
            response.headers["Strict-Transport-Security"] = "max-age=31536000"
        elapsed = int((time.perf_counter() - started) * 1000)
        route = request.scope.get("route")
        route_name = getattr(route, "path", "unmatched")
        # Store only templates/status/timings/opaque IDs, never URLs, query strings, bodies or exception text.
        if route_name != "/health":
            await asyncio.to_thread(
                store_metric,
                request_id,
                user.id if user_token is not None and user else None,
                scope,
                route_name,
                request.method,
                response.status_code,
                elapsed,
            )
        logger.info(
            "request_completed request_id=%s route=%s method=%s status=%s elapsed_ms=%s",
            request_id,
            route_name,
            request.method,
            response.status_code,
            elapsed,
        )
        return response
