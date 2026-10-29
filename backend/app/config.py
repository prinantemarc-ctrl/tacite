import os

from dotenv import load_dotenv

load_dotenv()

def _database_url() -> str:
    url = os.getenv("DATABASE_URL", "postgresql+psycopg://tacite:tacite@localhost:5432/tacite")
    if url.startswith("postgres://"):
        url = "postgresql+psycopg://" + url[len("postgres://"):]
    elif url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    if "render.com" in url and "sslmode=" not in url:
        url += "&sslmode=require" if "?" in url else "?sslmode=require"
    return url


DATABASE_URL = _database_url()
LLM_API_KEY = os.getenv("LLM_API_KEY", "")
LLM_BASE_URL = os.getenv("LLM_BASE_URL") or None

ARTIFACTS_DIR = os.getenv("ARTIFACTS_DIR", "/tmp/tacite-artifacts")
TACITE_TOKEN = os.getenv("TACITE_TOKEN", "").strip()

EMBEDDING_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_DIM = 384
