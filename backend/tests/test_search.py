"""Contrat recherche articles (body JSON) + outils SQL durcis."""

from fastapi.routing import APIRoute

from app.main import app
from app.schemas import ArticleSearchIn
from app.services.agent_tools import sql_query


def test_article_search_in_body():
    m = ArticleSearchIn(query="climat", limit=10, days=30, analyzed_only=True)
    assert m.query == "climat"
    assert m.limit == 10


def test_search_route_accepts_json_body():
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/articles/search"]
    assert routes, "POST /api/articles/search manquant"
    r = routes[0]
    assert "POST" in r.methods
    fields = {p.name for p in r.dependant.body_params}
    assert "data" in fields or any(p.type_annotation is ArticleSearchIn for p in r.dependant.body_params)


def test_sql_query_blocks_pg_sleep():
    out = sql_query(None, {"sql": "SELECT pg_sleep(10)"}, {})
    assert "error" in out


def test_sql_query_blocks_settings():
    out = sql_query(None, {"sql": "SELECT value FROM settings"}, {})
    assert "error" in out
    assert "settings" in out["error"].lower()


def test_sql_query_blocks_catalog():
    out = sql_query(None, {"sql": "SELECT * FROM pg_catalog.pg_tables"}, {})
    assert "error" in out
