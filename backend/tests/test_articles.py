"""Filtre pays sur la liste d'articles."""

from fastapi.routing import APIRoute

from app.main import app


def _articles_route():
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/articles" and "GET" in r.methods]
    assert routes, "GET /api/articles manquant"
    return routes[0]


def test_list_articles_accepts_country():
    names = {p.name for p in _articles_route().dependant.query_params}
    assert "country" in names
    assert "outlet_id" in names


def test_outlet_has_articles_endpoint():
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/outlets/{outlet_id}/articles"]
    assert routes, "GET /api/outlets/{id}/articles manquant"
