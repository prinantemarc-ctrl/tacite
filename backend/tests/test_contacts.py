from fastapi.routing import APIRoute

from app.main import app
from app.services.contacts import journalist_has_contact, REACHABLE_KINDS


def test_email_counts_as_contact():
    assert journalist_has_contact(["email"]) is True
    assert journalist_has_contact(["x", "author_page"]) is True


def test_guess_still_counts():
    """Une adresse déduite est un contact : oui / non ne distingue pas la confiance."""
    assert journalist_has_contact(["email"]) is True


def test_author_page_alone_is_not_contact():
    assert journalist_has_contact(["author_page"]) is False
    assert journalist_has_contact(["wikipedia"]) is False
    assert journalist_has_contact([]) is False
    assert journalist_has_contact(None) is False


def test_reachable_excludes_traces():
    assert "email" in REACHABLE_KINDS
    assert "author_page" not in REACHABLE_KINDS
    assert "wikipedia" not in REACHABLE_KINDS


def test_list_journalists_route():
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/journalists" and "GET" in r.methods]
    assert routes, "GET /api/journalists manquant"
