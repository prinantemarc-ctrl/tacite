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


from . import tenant as _tenant  # noqa: E402

_tenant.install(engine)
