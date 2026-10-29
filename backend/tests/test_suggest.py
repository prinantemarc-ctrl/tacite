"""Suggest : 403 → robot_blocked, timeout → unreachable."""

from unittest.mock import MagicMock, patch

import httpx

from app.services.suggest import fetch_diag, _verify


class _Resp:
    def __init__(self, status, text="<html></html>", headers=None, url="https://example.com"):
        self.status_code = status
        self.text = text
        self.headers = headers or {"content-type": "text/html"}
        self.url = url


def _client(resp=None, exc=None):
    inst = MagicMock()
    inst.__enter__.return_value = inst
    inst.__exit__.return_value = False
    if exc:
        inst.get.side_effect = exc
    else:
        inst.get.return_value = resp
    return inst


@patch("app.services.suggest.httpx.Client")
def test_fetch_diag_403_robot(mock_cls):
    mock_cls.return_value = _client(_Resp(403))
    html, err, reason = fetch_diag("https://example.com")
    assert html is None
    assert err == "robot"
    assert "403" in (reason or "")


@patch("app.services.suggest.httpx.Client")
def test_fetch_diag_timeout(mock_cls):
    mock_cls.return_value = _client(exc=httpx.TimeoutException("slow"))
    html, err, reason = fetch_diag("https://example.com")
    assert html is None
    assert err == "timeout"


@patch("app.services.suggest._feed_works", return_value=False)
@patch("app.services.suggest.fetch_diag")
def test_verify_403_robot_blocked(mock_fetch, _feeds):
    mock_fetch.return_value = (None, "robot", "le site existe mais bloque les robots (HTTP 403)")
    out = _verify({"name": "Le Quotidien", "website_url": "https://lequotidien.test"}, set(), set())
    assert out["status"] == "robot_blocked"


@patch("app.services.suggest._feed_works", return_value=False)
@patch("app.services.suggest.fetch_diag")
def test_verify_timeout_unreachable(mock_fetch, _feeds):
    mock_fetch.return_value = (None, "timeout", "pas de réponse en 12 s")
    out = _verify({"name": "Le Quotidien", "website_url": "https://lequotidien.test"}, set(), set())
    assert out["status"] == "unreachable"
