"""Comptes, sessions, et rattachement des données déjà présentes."""

from __future__ import annotations

import hashlib
import os
import re
import secrets
from datetime import datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from .database import SessionLocal, get_db
from .i18n import msg
from .models import TENANT_MODELS, AuthSession, User
from .seed import seed_user
from .tenant import (
    bypass_tenant,
    current_user_id,
    reset_bypass,
    reset_current_user,
    set_current_user,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

PUBLIC_PATHS = {"/api/health", "/health", "/api/auth/login", "/api/auth/register"}
SESSION_DAYS = 30
_USERNAME = re.compile(r"[\w][\w .'\-]{1,38}[\w]", re.UNICODE)
_dummy_hash: str | None = None


class Credentials(BaseModel):
    username: str
    password: str


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, salt_hex, dk_hex = stored.split("$", 2)
        if scheme != "scrypt":
            return False
        dk = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1, dklen=32)
        return secrets.compare_digest(dk, bytes.fromhex(dk_hex))
    except (ValueError, TypeError):
        return False


def _dummy() -> str:
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("tacite-dummy-password")
    return _dummy_hash


def normalize_username(raw: str) -> str:
    name = " ".join((raw or "").strip().split())
    if not _USERNAME.fullmatch(name):
        raise ValueError(name)
    return name.casefold()


def _public_user(user: User) -> dict:
    return {"id": user.id, "username": user.username}


def _new_session(db: Session, user_id: int) -> AuthSession:
    row = AuthSession(
        token=secrets.token_urlsafe(32),
        user_id=user_id,
        expires_at=datetime.utcnow() + timedelta(days=SESSION_DAYS),
    )
    db.add(row)
    return row


def claim_orphans(db: Session, user_id: int) -> None:
    """Donne au premier compte les lignes enregistrées avant les comptes."""
    for cls in TENANT_MODELS:
        db.query(cls).filter(cls.user_id.is_(None)).update(
            {cls.user_id: user_id}, synchronize_session=False,
        )


def open_account(db: Session, username: str, password: str) -> tuple[User, str]:
    """Crée le compte. Le premier récupère les données déjà en base, puis le catalogue s'il est vide."""
    name = normalize_username(username)
    if len(password) < 5 or len(password) > 200:
        raise ValueError("password")
    bypass = bypass_tenant(True)
    try:
        db.execute(text("SELECT pg_advisory_xact_lock(864213)"))
        if db.query(User).filter(User.username == name).first():
            raise HTTPException(409, msg("ce nom d'utilisateur est pris", "this username is taken"))
        first = db.query(User).count() == 0
        user = User(username=name, password_hash=hash_password(password))
        db.add(user)
        db.flush()
        if first:
            claim_orphans(db, user.id)
        db.commit()
        uid = user.id
    finally:
        reset_bypass(bypass)

    token_ctx = set_current_user(uid)
    bypass = bypass_tenant(True)
    try:
        seed_user(db)
        session = _new_session(db, uid)
        db.commit()
        raw = session.token
    finally:
        reset_bypass(bypass)
        reset_current_user(token_ctx)
    db.refresh(user)
    return user, raw


def resolve_token(raw: str) -> int | None:
    if not raw:
        return None
    db = SessionLocal()
    try:
        row = db.get(AuthSession, raw)
        if row is None:
            return None
        if row.expires_at < datetime.utcnow():
            db.delete(row)
            db.commit()
            return None
        return row.user_id
    finally:
        db.close()


def bootstrap_owner() -> None:
    """Compte initial optionnel (TACITE_BOOTSTRAP_USER / TACITE_BOOTSTRAP_PASSWORD)."""
    username = os.getenv("TACITE_BOOTSTRAP_USER", "").strip()
    password = os.getenv("TACITE_BOOTSTRAP_PASSWORD", "")
    if not username or not password:
        return
    db = SessionLocal()
    try:
        if db.query(User).first():
            return
        open_account(db, username, password)
    finally:
        db.close()


class AuthMiddleware:
    """Pose le compte courant à partir du jeton Bearer. Les chemins publics passent."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path") or ""
        if scope.get("method") == "OPTIONS" or not _needs_auth(path):
            await self.app(scope, receive, send)
            return
        uid = resolve_token(_bearer(scope))
        if uid is None:
            await JSONResponse({"detail": msg("non autorisé", "unauthorized")}, status_code=401)(scope, receive, send)
            return
        token = set_current_user(uid)
        # Une seule base : le compte identifie la personne, il ne filtre pas les données.
        bypass = bypass_tenant(True)
        try:
            await self.app(scope, receive, send)
        finally:
            reset_bypass(bypass)
            reset_current_user(token)


def _needs_auth(path: str) -> bool:
    if path in PUBLIC_PATHS:
        return False
    return path == "/mcp" or path.startswith("/mcp/") or path.startswith("/api/")


def _bearer(scope) -> str:
    for key, value in scope.get("headers") or []:
        if key.lower() == b"authorization":
            text_value = value.decode("latin1")
            if text_value.lower().startswith("bearer "):
                return text_value[7:].strip()
    return ""


@router.post("/register")
def register(body: Credentials, db: Session = Depends(get_db)):
    try:
        user, token = open_account(db, body.username, body.password)
    except ValueError:
        raise HTTPException(400, msg(
            "nom d'utilisateur (3 à 40 caractères) et mot de passe (5 caractères minimum) requis",
            "username (3 to 40 characters) and password (5 characters minimum) required",
        ))
    return {"token": token, "user": _public_user(user)}


@router.post("/login")
def login(body: Credentials, db: Session = Depends(get_db)):
    try:
        name = normalize_username(body.username)
    except ValueError:
        verify_password(body.password or "x", _dummy())
        raise HTTPException(401, msg("identifiants incorrects", "incorrect credentials"))
    user = db.query(User).filter(User.username == name).first()
    if user is None or not verify_password(body.password, user.password_hash):
        if user is None:
            verify_password(body.password or "x", _dummy())
        raise HTTPException(401, msg("identifiants incorrects", "incorrect credentials"))
    ctx = set_current_user(user.id)
    try:
        session = _new_session(db, user.id)
        db.commit()
        return {"token": session.token, "user": _public_user(user)}
    finally:
        reset_current_user(ctx)


@router.get("/me")
def me(db: Session = Depends(get_db)):
    uid = current_user_id()
    user = db.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(401, msg("non autorisé", "unauthorized"))
    return _public_user(user)


@router.post("/logout")
def logout(request: Request, db: Session = Depends(get_db)):
    uid = current_user_id()
    if uid is None:
        raise HTTPException(401, msg("non autorisé", "unauthorized"))
    auth = request.headers.get("authorization") or ""
    raw = auth[7:].strip() if auth.lower().startswith("bearer ") else ""
    if raw:
        row = db.get(AuthSession, raw)
        if row is not None and row.user_id == uid:
            db.delete(row)
            db.commit()
    return {"ok": True}
