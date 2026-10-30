"""Les pages lisent un instantané. Sans lui, elles répondent tout de suite."""

import numpy as np

from app.services.cartography import landscape
from app.services.prepared import agenda_key, jsonable, landscape_key
from app.services.topics import agenda, invalidate


def _agenda_blob():
    theme = {
        "id": 1, "label": "Election · Germany", "stories": 1, "articles": 4,
        "aliases": [], "story_summaries": [], "story_ids": [1], "entities": [],
        "_vec": [1.0, 0.0],
    }
    return {
        "since": "2026-01-01", "until": "2026-01-08", "days": 7,
        "threshold": 0.8, "theme_threshold": 0.55,
        "n_articles": 4, "n_clustered": 4, "n_singletons": 0,
        "n_themes": 1, "n_themes_all": 1, "explained_variance": [0.5, 0.2],
        "clusters": [{"id": 1, "label": "Election · Berlin", "articles": 4, "outlets": 2, "_vec": [1.0, 0.0]}],
        "points": [], "themes": [theme], "edges": [],
        "filters": {"country": None, "outlet_id": None, "journalist_id": None},
    }


def test_jsonable_turns_centroids_into_lists():
    out = jsonable({"v": np.array([0.123456789, 1.0]), "n": np.int64(3)})
    assert out["v"] == [0.12346, 1.0]
    assert out["n"] == 3


def test_snapshot_keys():
    assert agenda_key(7, None) == "agenda:7:_:700"
    assert agenda_key(1, "fr") == "agenda:1:FR:400"
    assert landscape_key(8, "DE") == "landscape:8:5:DE"


def test_agenda_reads_snapshot_without_clustering(monkeypatch):
    monkeypatch.setattr("app.services.prepared.load", lambda db, key: _agenda_blob())
    monkeypatch.setattr("app.services.topics._agenda", lambda *a, **k: (_ for _ in ()).throw(AssertionError("clustered")))
    out = agenda(None, days=7, briefs=True, cap=500)
    assert out.get("preparing") is not True
    assert out["themes"][0]["label"] == "Election · Germany"
    assert "_vec" not in out["themes"][0]
    assert "_vec" not in out["clusters"][0]


def test_missing_snapshot_returns_immediately(monkeypatch):
    seen = {}

    def fake_load(db, key):
        seen["key"] = key
        return None

    monkeypatch.setattr("app.services.prepared.load", fake_load)
    monkeypatch.setattr("app.services.topics._agenda", lambda *a, **k: (_ for _ in ()).throw(AssertionError("clustered")))
    out = agenda(None, days=7, country="fr")
    assert seen["key"] == "agenda:7:FR:700"
    assert out["preparing"] is True
    assert out["themes"] == []
    assert out["filters"]["country"] == "FR"


def test_search_uses_stored_vectors(monkeypatch):
    blob = _agenda_blob()
    blob["themes"].append({
        "id": 2, "label": "Ukrainian drones", "stories": 1, "articles": 3,
        "aliases": [], "story_summaries": [], "story_ids": [2], "entities": [],
        "_vec": [0.0, 1.0],
    })
    monkeypatch.setattr("app.services.prepared.load", lambda db, key: blob)
    monkeypatch.setattr("app.services.embeddings.embed_text", lambda q: np.array([1.0, 0.0]))
    out = agenda(None, days=7, q="election")
    labels = [t["label"] for t in out["search"]["themes"]]
    assert labels[0] == "Election · Germany"
    assert "_vec" not in out["search"]["themes"][0]


def test_outlet_filter_still_computes_live(monkeypatch):
    called = {}

    def fake_agenda(*args, **kwargs):
        called["cap"] = args[7]
        return {
            "themes": [], "clusters": [], "n_themes_all": 0,
            "since": "2026-01-01", "until": "2026-01-08", "days": 7,
            "threshold": 0.8, "theme_threshold": 0.55,
            "n_articles": 0, "n_clustered": 0, "n_singletons": 0,
            "explained_variance": [], "points": [], "edges": [], "filters": {},
        }

    monkeypatch.setattr("app.services.topics._agenda", fake_agenda)
    monkeypatch.setattr("app.services.prepared.load", lambda *a, **k: (_ for _ in ()).throw(AssertionError("snapshot")))
    invalidate()
    agenda(None, days=7, outlet_id=3)
    assert called["cap"] == 400


def test_landscape_missing_does_not_compute(monkeypatch):
    seen = {}

    def fake_load(db, key):
        seen["key"] = key
        return None

    monkeypatch.setattr("app.services.prepared.load", fake_load)
    monkeypatch.setattr("app.services.cartography._landscape", lambda *a, **k: (_ for _ in ()).throw(AssertionError("computed")))
    out = landscape(None, weeks=8, country="de")
    assert seen["key"] == "landscape:8:5:DE"
    assert out["preparing"] is True
    assert out["outlets"] == []
