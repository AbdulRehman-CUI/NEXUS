"""Opaque expiring sessions and a shared workspace authorization boundary."""

import hashlib
import hmac
import re
import secrets
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from fastapi import APIRouter, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select

from .database import AuthSession, GuestSession, Membership, User, Workspace

COOKIE = "nexus_session"
GUEST_COOKIE = "__Host-nexus_guest"


@dataclass(frozen=True)
class Principal:
    id: str
    admin: bool = False
    guest: bool = False


principal: ContextVar[Principal | None] = ContextVar("principal", default=None)
internal: ContextVar[bool] = ContextVar("internal", default=False)
required_role: ContextVar[str] = ContextVar("required_role", default="viewer")
LEVEL = {"viewer": 0, "editor": 1, "owner": 2}


@contextmanager
def system_scope():
    token = internal.set(True)
    try:
        yield
    finally:
        internal.reset(token)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def csrf_token(token):
    return hashlib.sha256(("nexus-csrf:" + token).encode()).hexdigest()


def hash_password(password):
    if not 12 <= len(password) <= 256:
        raise ValueError("Use a password of 12–256 characters.")
    salt = secrets.token_hex(16)
    digest = hashlib.scrypt(
        password.encode(), salt=bytes.fromhex(salt), n=131072, r=8, p=1, maxmem=256 * 1024 * 1024
    )
    return f"scrypt-v1${salt}${digest.hex()}"


def verify_password(password, encoded):
    try:
        version, salt, expected = encoded.split("$")
        if version != "scrypt-v1" or len(password) > 256:
            return False
        digest = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), n=131072, r=8, p=1, maxmem=256 * 1024 * 1024
        )
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def authorize(settings, session, workspace_id, role=None):
    if settings.profile == "local" or internal.get():
        return
    user = principal.get()
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    if user.guest:
        if user.id != workspace_id:
            raise HTTPException(404, "Workspace not found")
        return
    membership = session.get(Membership, (workspace_id, user.id))
    if membership is None:
        raise HTTPException(404, "Workspace not found")
    if LEVEL.get(membership.role, -1) < LEVEL[role or required_role.get()]:
        raise HTTPException(403, "Your workspace role does not allow this operation.")


def require_admin(settings):
    if settings.profile == "server" and not (principal.get() and principal.get().admin):
        raise HTTPException(403, "Server administrator access is required.")


def add_user(session, username, password, admin=False):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_.-]{2,63}", username):
        raise ValueError("Username must be 3–64 lowercase letters, digits, dot, underscore or dash.")
    if session.scalar(select(User).where(User.username == username)):
        raise ValueError("Username already exists.")
    user = User(username=username, password_hash=hash_password(password), admin=admin)
    session.add(user)
    session.flush()
    return user


class LoginInput(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=1, max_length=256)


router = APIRouter(prefix="/api/auth", tags=["Identity"])


class SetupInput(LoginInput):
    token: str = Field(min_length=32, max_length=128)
    password: str = Field(min_length=12, max_length=256)


@router.get("/setup")
def setup_status(request: Request):
    svc = request.app.state.service
    with svc.sessions() as session:
        return {
            "available": not svc.settings.guest_access
            and bool(svc.settings.setup_token_hash.get_secret_value())
            and session.scalar(select(User.id).limit(1)) is None
        }


@router.post("/setup", status_code=201)
def setup_owner(body: SetupInput, request: Request):
    svc = request.app.state.service
    expected = svc.settings.setup_token_hash.get_secret_value()
    if (
        svc.settings.profile != "server"
        or svc.settings.guest_access
        or not expected
        or not hmac.compare_digest(token_hash(body.token), expected)
    ):
        raise HTTPException(403, "Invalid setup token.")
    with svc.lock, svc.sessions.begin() as session:
        if session.scalar(select(User.id).limit(1)) is not None:
            raise HTTPException(409, "Setup is complete. Sign in with your existing account.")
        try:
            add_user(session, body.username.lower(), body.password, admin=True)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None
    return {"created": True}


@router.get("/me")
def me(request: Request):
    service = request.app.state.service
    user = principal.get()
    if service.settings.profile == "local":
        return {"profile": "local", "user": None, "csrf": None}
    if user is None:
        raise HTTPException(401, "Sign in to continue.")
    if user.guest:
        return {
            "profile": "server",
            "guest": True,
            "user": None,
            "csrf": csrf_token(request.cookies[GUEST_COOKIE]),
        }
    with service.sessions() as session:
        record = session.get(User, user.id)
        return {
            "profile": "server",
            "user": {"id": user.id, "username": record.username, "admin": user.admin},
            "csrf": csrf_token(request.cookies[COOKIE]),
        }


class GuestInput(BaseModel):
    nonce: str = Field(pattern=r"^[a-f0-9]{64}$", min_length=64, max_length=64)


@router.post("/guest")
def guest_session(body: GuestInput, request: Request, response: Response):
    svc = request.app.state.service
    settings = svc.settings
    if not settings.guest_access:
        return JSONResponse(
            {"code": "guest_access_disabled", "detail": "Guest access is unavailable on this server."},
            status_code=404,
        )
    if request.url.scheme != "https" or request.headers.get("origin") not in settings.cors_origins:
        raise HTTPException(403, "Guest initialization requires HTTPS and an allowed application origin.")
    if principal.get():
        return me(request)

    # A browser retries with the same random nonce if a response is lost. Only the
    # server can derive the bearer cookie. Concurrent instances contend on one SQL row.
    secret = settings.guest_session_secret.get_secret_value().encode()
    token = hmac.digest(secret, b"nexus-guest-cookie:" + body.nonce.encode(), "sha256").hex()
    workspace_id = hmac.digest(secret, b"nexus-guest-workspace:" + body.nonce.encode(), "sha256").hex()
    digest = token_hash(token)
    now = int(time.time())
    with svc.sessions.begin() as session:
        if session.bind.dialect.name == "postgresql":
            from sqlalchemy.dialects.postgresql import insert
        else:
            from sqlalchemy.dialects.sqlite import insert
        # Keep expired rows so replaying an old nonce cannot revive an expired workspace.
        session.execute(
            insert(Workspace)
            .values(id=workspace_id, name="Personal workspace")
            .on_conflict_do_nothing(index_elements=[Workspace.id])
        )
        session.execute(
            insert(GuestSession)
            .values(
                token_hash=digest,
                workspace_id=workspace_id,
                expires_at=now + settings.guest_session_hours * 3600,
            )
            .on_conflict_do_nothing(index_elements=[GuestSession.token_hash])
        )
        expires_at = session.get(GuestSession, digest).expires_at
        if expires_at <= now:
            raise HTTPException(409, "This guest session expired. Start a new session.")
    response.set_cookie(
        GUEST_COOKIE, token, max_age=expires_at - now, httponly=True, secure=True, samesite="strict", path="/"
    )
    return {"profile": "server", "guest": True, "user": None, "csrf": csrf_token(token)}


@router.post("/login")
def login(body: LoginInput, request: Request, response: Response):
    svc = request.app.state.service
    if svc.settings.profile != "server":
        raise HTTPException(409, "The local profile does not use accounts.")
    with svc.sessions.begin() as session:
        user = session.scalar(select(User).where(User.username == body.username.lower()))
        # Perform the same expensive KDF when the username is absent, reducing timing disclosure.
        valid = (
            verify_password(body.password, user.password_hash)
            if user
            else verify_password(body.password, request.app.state.dummy_password)
        )
        if not user or user.disabled or not valid:
            raise HTTPException(401, "Invalid username or password.")
        old = request.cookies.get(COOKIE)
        if old:
            session.execute(delete(AuthSession).where(AuthSession.token_hash == token_hash(old)))
        session.execute(delete(AuthSession).where(AuthSession.expires_at < int(time.time())))
        token = secrets.token_urlsafe(32)
        session.add(
            AuthSession(
                token_hash=token_hash(token),
                user_id=user.id,
                expires_at=int(time.time()) + svc.settings.session_hours * 3600,
            )
        )
        response.set_cookie(
            COOKIE,
            token,
            max_age=svc.settings.session_hours * 3600,
            httponly=True,
            secure=svc.settings.secure_cookies,
            samesite="strict",
            path="/",
        )
        return {
            "profile": "server",
            "user": {"id": user.id, "username": user.username, "admin": user.admin},
            "csrf": csrf_token(token),
        }


@router.post("/logout", status_code=204)
def logout(request: Request, response: Response):
    svc = request.app.state.service
    with svc.sessions.begin() as session:
        session.execute(
            delete(AuthSession).where(AuthSession.token_hash == token_hash(request.cookies.get(COOKIE, "")))
        )
    response.delete_cookie(
        COOKIE, path="/", secure=svc.settings.secure_cookies, httponly=True, samesite="strict"
    )


class MemberInput(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    role: str = Field(pattern="^(owner|editor|viewer)$")


members_router = APIRouter(prefix="/api/workspaces", tags=["Memberships"])


@members_router.get("/{workspace_id}/members")
def members(workspace_id: str, request: Request):
    svc = request.app.state.service
    with svc.sessions() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        return [
            {"user_id": u.id, "username": u.username, "role": m.role}
            for m, u in session.execute(
                select(Membership, User)
                .join(User, User.id == Membership.user_id)
                .where(Membership.workspace_id == workspace_id)
            )
        ]


@members_router.put("/{workspace_id}/members")
def put_member(workspace_id: str, body: MemberInput, request: Request):
    svc = request.app.state.service
    with svc.lock, svc.sessions.begin() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        user = session.scalar(select(User).where(User.username == body.username))
        if user is None or user.disabled:
            raise HTTPException(404, "Ask an administrator to create this account first.")
        current = session.get(Membership, (workspace_id, user.id))
        if current and current.role == "owner" and body.role != "owner":
            owners = list(
                session.scalars(
                    select(Membership).where(
                        Membership.workspace_id == workspace_id, Membership.role == "owner"
                    )
                )
            )
            if len(owners) <= 1:
                raise HTTPException(409, "Keep at least one workspace owner.")
        session.merge(Membership(workspace_id=workspace_id, user_id=user.id, role=body.role))
        return {"user_id": user.id, "role": body.role}


@members_router.delete("/{workspace_id}/members/{user_id}", status_code=204)
def remove_member(workspace_id: str, user_id: str, request: Request):
    svc = request.app.state.service
    with svc.lock, svc.sessions.begin() as session:
        svc.repo.workspace(session, workspace_id)
        authorize(svc.settings, session, workspace_id, "owner")
        member = session.get(Membership, (workspace_id, user_id))
        if member and member.role == "owner":
            owners = list(
                session.scalars(
                    select(Membership).where(
                        Membership.workspace_id == workspace_id, Membership.role == "owner"
                    )
                )
            )
            if len(owners) <= 1:
                raise HTTPException(409, "Keep at least one workspace owner.")
        if member:
            session.delete(member)
