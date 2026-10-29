"""Compte courant et isolation des lignes.

Chaque table métier a une colonne user_id. L'application se connecte en superutilisateur,
puis chaque transaction prend le rôle tacite_app, soumis aux politiques de ligne :
sans compte courant, une requête ne voit rien. Le rôle propriétaire ne sert qu'aux
migrations.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from contextvars import ContextVar, Token

from sqlalchemy import Column, ForeignKey, Integer, event, text
from sqlalchemy.orm import Session, declared_attr

log = logging.getLogger("tacite.tenant")

ROLE = "tacite_app"

_user_id: ContextVar[int | None] = ContextVar("tacite_user_id", default=None)
_bypass: ContextVar[bool] = ContextVar("tacite_tenant_bypass", default=False)
_as_owner: ContextVar[bool] = ContextVar("tacite_as_owner", default=False)
_read_only: ContextVar[bool] = ContextVar("tacite_read_only", default=False)

_installed = False


class HasTenant:
    """Mixin : la ligne appartient à un compte. user_id est posé au flush."""

    @declared_attr
    def user_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=True)


def current_user_id() -> int | None:
    return _user_id.get()


def set_current_user(user_id: int | None) -> Token:
    return _user_id.set(user_id)


def reset_current_user(token: Token) -> None:
    _user_id.reset(token)


def bypass_tenant(on: bool = True) -> Token:
    return _bypass.set(on)


def reset_bypass(token: Token) -> None:
    _bypass.reset(token)


@contextmanager
def as_owner():
    """Migrations : rester superutilisateur, les politiques de ligne ne s'appliquent pas."""
    token = _as_owner.set(True)
    try:
        yield
    finally:
        _as_owner.reset(token)


@contextmanager
def read_only_tx():
    """La transaction qui suit refuse les écritures (requêtes SQL libres)."""
    token = _read_only.set(True)
    try:
        yield
    finally:
        _read_only.reset(token)


def stamp_new(session: Session, flush_context, instances) -> None:  # noqa: ARG001
    uid = _user_id.get()
    if uid is None:
        return
    for obj in session.new:
        if isinstance(obj, HasTenant) and obj.user_id is None:
            obj.user_id = uid


def _set_guc(conn, key: str, value: str) -> None:
    result = conn.exec_driver_sql("SELECT set_config(%s, %s, true)", (key, value))
    result.close()


def _apply_role(conn) -> None:
    if _as_owner.get():
        return
    # SET TRANSACTION doit être le premier ordre de la transaction.
    if _read_only.get():
        conn.exec_driver_sql("SET TRANSACTION READ ONLY")
    conn.exec_driver_sql(f"SET LOCAL ROLE {ROLE}")
    if _bypass.get():
        _set_guc(conn, "app.bypass", "on")
        _set_guc(conn, "app.user_id", "")
        return
    _set_guc(conn, "app.bypass", "off")
    uid = _user_id.get()
    # uid vient de la table users, jamais de la requête.
    _set_guc(conn, "app.user_id", str(int(uid)) if uid is not None else "")


def install(engine) -> None:
    global _installed
    if _installed:
        return
    _installed = True
    event.listen(Session, "before_flush", stamp_new)
    event.listen(engine, "begin", _apply_role)


def migrate(engine) -> None:
    """Colonnes user_id, index d'unicité par compte, rôle applicatif et politiques de ligne."""
    from . import models

    tables = [cls.__tablename__ for cls in models.TENANT_MODELS]
    with engine.begin() as conn:
        if _already_migrated(conn):
            return
        conn.execute(text("SET lock_timeout = '20s'"))
        conn.execute(text(
            f"""
            DO $$ BEGIN
              CREATE ROLE {ROLE} NOLOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB NOCREATEROLE;
            EXCEPTION WHEN duplicate_object THEN NULL;
            END $$;
            """
        ))
        # Sur Render le rôle de connexion n'est pas superuser : il doit être
        # membre de tacite_app pour pouvoir SET LOCAL ROLE.
        conn.execute(text(f"GRANT {ROLE} TO CURRENT_USER"))
        for table in tables:
            conn.execute(text(
                f'ALTER TABLE "{table}" ADD COLUMN IF NOT EXISTS user_id INTEGER '
                f'REFERENCES users(id) ON DELETE CASCADE'
            ))
            conn.execute(text(
                f'CREATE INDEX IF NOT EXISTS "ix_{table}_user_id" ON "{table}" (user_id)'
            ))

        pkey_len = conn.execute(text(
            "SELECT array_length(conkey, 1) FROM pg_constraint WHERE conname = 'settings_pkey'"
        )).scalar()
        if pkey_len == 1:
            conn.execute(text("ALTER TABLE settings DROP CONSTRAINT settings_pkey"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS settings_user_key ON settings (user_id, key)"
        ))

        conn.execute(text("ALTER TABLE articles DROP CONSTRAINT IF EXISTS articles_url_key"))
        conn.execute(text("DROP INDEX IF EXISTS articles_url_key"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS articles_user_url_key ON articles (user_id, url)"
        ))

        conn.execute(text("ALTER TABLE outlets DROP CONSTRAINT IF EXISTS outlets_name_key"))
        conn.execute(text("ALTER TABLE outlets DROP CONSTRAINT IF EXISTS outlets_name_country_key"))
        conn.execute(text("DROP INDEX IF EXISTS outlets_name_country_key"))
        conn.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS outlets_user_name_country_key "
            "ON outlets (user_id, name, country)"
        ))

        for table in tables:
            conn.execute(text(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY'))
            conn.execute(text(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY'))
            conn.execute(text(f'DROP POLICY IF EXISTS tenant_all ON "{table}"'))
            conn.execute(text(
                f"""
                CREATE POLICY tenant_all ON "{table}"
                FOR ALL
                USING (
                  current_setting('app.bypass', true) = 'on'
                  OR user_id = NULLIF(current_setting('app.user_id', true), '')::int
                )
                WITH CHECK (
                  current_setting('app.bypass', true) = 'on'
                  OR user_id = NULLIF(current_setting('app.user_id', true), '')::int
                )
                """
            ))

        conn.execute(text(f"GRANT USAGE ON SCHEMA public TO {ROLE}"))
        conn.execute(text(
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO {ROLE}"
        ))
        conn.execute(text(
            f"GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO {ROLE}"
        ))
        conn.execute(text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO {ROLE}"
        ))
        conn.execute(text(
            f"ALTER DEFAULT PRIVILEGES IN SCHEMA public "
            f"GRANT USAGE, SELECT ON SEQUENCES TO {ROLE}"
        ))
        log.info("Isolation par compte en place (%d tables)", len(tables))


def _already_migrated(conn) -> bool:
    role = conn.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": ROLE}).first()
    column = conn.execute(text(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_schema = 'public' AND table_name = 'articles' AND column_name = 'user_id'"
    )).first()
    policy = conn.execute(text(
        "SELECT 1 FROM pg_policies WHERE schemaname = 'public' AND tablename = 'articles' AND policyname = 'tenant_all'"
    )).first()
    return bool(role and column and policy)
