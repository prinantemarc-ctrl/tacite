from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import DATABASE_URL


class Base(DeclarativeBase):
    pass


engine = create_engine(DATABASE_URL, pool_pre_ping=True)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    """Create pgvector extension and all tables. Safe to call concurrently."""
    from . import models  # noqa: F401  (register models)
    from .tenant import as_owner, migrate

    with as_owner():
        _init_db_as_owner()
        migrate(engine)


def _init_db_as_owner():
    try:
        with engine.connect() as conn:
            conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
            conn.commit()
    except Exception:
        pass
    try:
        Base.metadata.create_all(bind=engine)
    except Exception:
        # Another process may be creating tables at the same time.
        pass
    # Mini-migrations : create_all ne modifie pas les tables existantes.
    for stmt in (
        "ALTER TABLE articles ADD COLUMN IF NOT EXISTS text_coverage VARCHAR",
        "ALTER TABLE outlets ADD COLUMN IF NOT EXISTS collect_enabled INTEGER DEFAULT 1",
        "ALTER TABLE journalists ADD COLUMN IF NOT EXISTS beat VARCHAR",
        "ALTER TABLE outlet_profiles ADD COLUMN IF NOT EXISTS axis_n JSONB DEFAULT '{}'::jsonb",
        """UPDATE journalists SET beat = substring(bio from '\\[([^\\]]+)\\]')
           WHERE beat IS NULL AND bio LIKE '[%]%'""",
        "ALTER TABLE outlets DROP CONSTRAINT IF EXISTS outlets_name_key",
        "CREATE INDEX IF NOT EXISTS ix_articles_outlet_id ON articles (outlet_id)",
        "CREATE INDEX IF NOT EXISTS ix_journalists_outlet_id ON journalists (outlet_id)",
        """CREATE INDEX IF NOT EXISTS articles_embedding_hnsw
           ON articles USING hnsw (embedding vector_cosine_ops)""",
    ):
        try:
            with engine.connect() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '2s'"))
                conn.execute(text(stmt))
                conn.commit()
        except Exception:
            pass
    _ensure_prepared_view_rls()


def _ensure_prepared_view_rls():
    """migrate() s'arrête dès que l'isolation existe : une table nouvelle doit être accordée ici."""
    from .tenant import ROLE

    for stmt in (
        f"GRANT SELECT, INSERT, UPDATE, DELETE ON prepared_views TO {ROLE}",
        f"GRANT USAGE, SELECT ON SEQUENCE prepared_views_id_seq TO {ROLE}",
        "ALTER TABLE prepared_views ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE prepared_views FORCE ROW LEVEL SECURITY",
        "DROP POLICY IF EXISTS tenant_all ON prepared_views",
        """
        CREATE POLICY tenant_all ON prepared_views
        FOR ALL
        USING (
          current_setting('app.bypass', true) = 'on'
          OR user_id = NULLIF(current_setting('app.user_id', true), '')::int
        )
        WITH CHECK (
          current_setting('app.bypass', true) = 'on'
          OR user_id = NULLIF(current_setting('app.user_id', true), '')::int
        )
        """,
    ):
        try:
            with engine.connect() as conn:
                conn.execute(text("SET LOCAL lock_timeout = '2s'"))
                conn.execute(text(stmt))
                conn.commit()
        except Exception:
            pass


from . import tenant as _tenant  # noqa: E402

_tenant.install(engine)
