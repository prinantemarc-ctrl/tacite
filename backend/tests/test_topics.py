"""Clustering sémantique des sujets : même affaire, libellés différents."""

from fastapi.routing import APIRoute
import numpy as np

from app.main import app
from app.services.topics import (
    cluster_embeddings, _cluster_name, _family_name, _heat, brief_item, apply_briefs,
    search_agenda, lexical_overlap, blend_score, _public_agenda, MAX_THEMES, SIM_THRESHOLD,
)


def test_four_near_duplicates_make_one_cluster():
    rng = np.random.default_rng(0)
    a = np.zeros(32); a[0] = 1
    b = np.zeros(32); b[1] = 1
    near_a = np.stack([a + rng.normal(0, 0.03, 32) for _ in range(4)])
    near_b = np.stack([b + rng.normal(0, 0.03, 32) for _ in range(3)])
    labels = cluster_embeddings(np.vstack([near_a, near_b]), threshold=0.80)
    assert len(set(labels[:4])) == 1
    assert len(set(labels[4:])) == 1
    assert labels[0] != labels[4]


def test_identical_vectors_are_one_cluster():
    v = np.ones((5, 8))
    labels = cluster_embeddings(v)
    assert set(labels) == {0}


def test_orthogonal_stay_apart():
    x = np.eye(6)
    labels = cluster_embeddings(x, threshold=0.80)
    assert len(set(labels)) == 6


def test_cluster_name_picks_majority_and_keeps_aliases():
    extracted = [
        {"topics": [{"label": "Réforme des retraites"}]},
        {"topics": [{"label": "âge légal de départ"}]},
        {"topics": [{"label": "Réforme des retraites"}]},
        {"topics": [{"label": "pensions"}]},
    ]
    label, aliases = _cluster_name(extracted, ["un", "deux", "trois", "quatre"])
    assert label == "Réforme des retraites"
    assert "âge légal de départ" in aliases
    assert "pensions" in aliases


def test_junk_labels_ignored():
    extracted = [
        {"topics": [{"label": "Boilerplate"}]},
        {"topics": [{"label": "Non-political"}]},
    ]
    label, aliases = _cluster_name(extracted, ["Titre de repli", "autre"])
    assert label == "Titre de repli"
    assert aliases == []


def test_heat_buckets():
    assert _heat(8, 0)[0] == "new"
    assert _heat(9, 4)[0] == "up"
    assert _heat(5, 10)[0] == "down"
    assert _heat(10, 9)[0] == "stable"


def test_topics_route_exists():
    routes = [r for r in app.routes if isinstance(r, APIRoute) and r.path == "/api/map/topics"]
    assert routes, "GET /api/map/topics manquant"
    names = {p.name for p in routes[0].dependant.query_params}
    assert {"days", "country", "outlet_id", "journalist_id", "q"} <= names


def test_layout_groups_by_topic_with_core():
    from app.services.topics import layout_xyz
    rng = np.random.default_rng(1)
    a = np.zeros(24); a[0] = 1
    b = np.zeros(24); b[1] = 1
    emb = np.vstack([
        np.stack([a + rng.normal(0, 0.02, 24) for _ in range(6)]),
        np.stack([b + rng.normal(0, 0.02, 24) for _ in range(6)]),
    ])
    labels = np.array([0] * 6 + [1] * 6)
    xyz, centers, cent, _themes = layout_xyz(emb, labels, min_articles=2)
    intra0 = float(np.linalg.norm(xyz[:6] - xyz[:6].mean(0), axis=1).mean())
    intra1 = float(np.linalg.norm(xyz[6:] - xyz[6:].mean(0), axis=1).mean())
    inter = float(np.linalg.norm(xyz[:6].mean(0) - xyz[6:].mean(0)))
    assert inter > intra0 * 2
    assert inter > intra1 * 2
    assert set(centers) == {0, 1}
    assert float(cent[:6].mean()) > 0.7


def test_layout_hierarchy_keeps_subclusters_inside_family():
    from app.services.topics import layout_xyz
    rng = np.random.default_rng(2)
    bases = [np.zeros(24) for _ in range(4)]
    bases[0][0] = 1
    bases[1][0] = 0.92
    bases[1][1] = 0.39
    bases[2][2] = 1
    bases[3][2] = 0.92
    bases[3][3] = 0.39
    chunks = [np.stack([b + rng.normal(0, 0.02, 24) for _ in range(5)]) for b in bases]
    emb = np.vstack(chunks)
    labels = np.array([0] * 5 + [1] * 5 + [2] * 5 + [3] * 5)
    xyz, centers, _cent, tcenters = layout_xyz(
        emb, labels, min_articles=2, theme_of={0: 0, 1: 0, 2: 1, 3: 1},
    )
    c0, c1, c2, c3 = [xyz[i * 5:(i + 1) * 5].mean(0) for i in range(4)]
    d01 = float(np.linalg.norm(c0 - c1))
    d23 = float(np.linalg.norm(c2 - c3))
    d02 = float(np.linalg.norm(c0 - c2))
    assert d01 < d02 * 0.65
    assert d23 < d02 * 0.65
    assert set(tcenters) == {0, 1}
    assert set(centers) == {0, 1, 2, 3}


def test_mst_connects_all_nodes():
    from app.services.topics import _mst
    edges = _mst([0, 1, 2, 3], np.eye(4))
    assert len(edges) == 3
    nodes = {n for a, b, _ in edges for n in (a, b)}
    assert nodes == {0, 1, 2, 3}


def test_average_linkage_merges_related_centroids():
    a = np.zeros(16); a[0] = 1
    b = np.zeros(16); b[0] = 0.85; b[1] = 0.53
    c = np.zeros(16); c[2] = 1
    labels = cluster_embeddings(np.stack([a, b, c]), threshold=0.55, method="average")
    assert labels[0] == labels[1]
    assert labels[0] != labels[2]


def test_threshold_is_looser_than_dedup():
    # Dédup article = 0,95 ; affaire = 0,80 (liaison complète) + veto libellé/entités.
    assert SIM_THRESHOLD < 0.95
    assert SIM_THRESHOLD >= 0.75


def test_same_affair_label_canada_variants():
    from app.services.topics import same_affair_label
    assert same_affair_label("Canada-EU Relations", "EU-Kanada Relations")
    assert same_affair_label("Canada-EU Relations", "EU-Canada Trade Relations")
    assert same_affair_label("Canada-EU Relations", "Canada EU Relations")
    assert same_affair_label("Elections · Russian", "Russian · Elections")
    assert not same_affair_label("Canada-EU Relations", "Helicopter Crash")
    assert not same_affair_label("Electricity Price Increase", "Crisis in Ceuta")


def test_umbrella_ignores_minority_side_story():
    """Frappes de drones (volume) + une affaire élections : le nom ne dit pas « elections »."""
    stories = [
        {"label": "Ukrainian Drone Attack on Moscow", "aliases": [], "entities": [], "articles": 9},
        {"label": "Drone Strikes on Russian Infrastructure", "aliases": [], "entities": [], "articles": 8},
        {"label": "Cybersecurity and Election Interference", "aliases": [], "entities": [], "articles": 2},
    ]
    label, _ = _family_name(stories)
    blob = label.casefold()
    assert "drone" in blob or "moscow" in blob
    assert "election" not in blob


def test_merge_close_themes_joins_near_centroids():
    from app.services.topics import merge_close_themes
    # deux familles, centroïdes très proches (élections DE)
    a = np.zeros(8); a[0] = 1
    b = np.zeros(8); b[0] = 0.94; b[1] = 0.34
    c = np.zeros(8); c[2] = 1
    cents = np.stack([a, b, a, c])
    story_ids = [10, 11, 12, 13]
    theme_of = {10: 0, 11: 0, 12: 1, 13: 2}
    names = {10: "Landtagswahl", 11: "AfD Electoral Success", 12: "Political Landscape in Germany", 13: "Gold prices"}
    out = merge_close_themes(theme_of, story_ids, cents, names)
    assert out[10] == out[12]
    assert out[13] != out[10]


def test_merge_close_themes_joins_inverted_labels():
    from app.services.topics import merge_close_themes
    a = np.zeros(6); a[0] = 1
    b = np.zeros(6); b[0] = 0.96; b[1] = 0.28
    cents = np.stack([a, b])
    out = merge_close_themes(
        {1: 0, 2: 1}, [1, 2], cents,
        {1: "Elections in Russia", 2: "Russian Parliamentary Elections"},
    )
    assert out[1] == out[2]


def test_merge_close_themes_keeps_related_but_distinct():
    """Législatives russes vs frappes de drones : proches (~0,74) mais pas le même sujet."""
    from app.services.topics import merge_close_themes
    a = np.zeros(6); a[0] = 1
    b = np.zeros(6); b[0] = 0.74; b[1] = 0.67
    cents = np.stack([a, b])
    out = merge_close_themes(
        {1: 0, 2: 1}, [1, 2], cents,
        {1: "Elections in Russia", 2: "Ukrainian Drone Attack on Moscow"},
    )
    assert out[1] != out[2]


def test_merge_story_labels_joins_near_names():
    from app.services.topics import merge_story_labels
    rng = np.random.default_rng(3)
    a = np.zeros(16); a[0] = 1
    emb = np.vstack([
        np.stack([a + rng.normal(0, 0.03, 16) for _ in range(3)]),
        np.stack([a + rng.normal(0, 0.05, 16) for _ in range(3)]),
    ])
    labels = np.array([0, 0, 0, 1, 1, 1])
    rows = [(i, "t", "", 1, None, None, {"topics": [{"label": "Canada-EU Relations"}]}, None) for i in range(6)]
    out = merge_story_labels(labels, emb, rows, min_articles=2)
    assert len(set(out.tolist())) == 1


def test_split_keeps_same_affair_without_entities():
    """Retraites / âge légal : pas d'entités → on ne sépare pas."""
    from app.services.topics import split_incoherent_stories
    labels = np.array([0, 0, 0, 0])
    rows = [
        (0, "a", "", 1, None, None, {"topics": [{"label": "Réforme des retraites"}], "entities": {}}, None),
        (1, "b", "", 1, None, None, {"topics": [{"label": "âge légal de départ"}], "entities": {}}, None),
        (2, "c", "", 1, None, None, {"topics": [{"label": "pensions"}], "entities": {}}, None),
        (3, "d", "", 1, None, None, {"topics": [{"label": "Réforme des retraites"}], "entities": {}}, None),
    ]
    out = split_incoherent_stories(labels, rows, min_articles=2)
    assert len(set(out.tolist())) == 1


def test_split_ejects_disjoint_label_and_entities():
    """Bollo italien vs modèle social français : même embedding, identités opposées."""
    from app.services.topics import split_incoherent_stories
    labels = np.array([0, 0, 0, 0])
    rows = [
        (0, "bollo", "", 1, None, None, {
            "topics": [{"label": "Bollo Auto Policy"}],
            "entities": {"people": ["Giancarlo Giorgetti", "Giorgia Meloni"], "organizations": ["Regioni"]},
        }, None),
        (1, "giorgetti", "", 1, None, None, {
            "topics": [{"label": "Economic Policy and Energy Costs"}],
            "entities": {"people": ["Giancarlo Giorgetti"], "organizations": ["Unione europea"]},
        }, None),
        (2, "va", "", 1, None, None, {
            "topics": [{"label": "Contribution des entreprises au modèle social"}],
            "entities": {"people": ["Alexandre Bertolini"], "organizations": ["Medef"]},
        }, None),
        (3, "giornale", "", 1, None, None, {
            "topics": [{"label": "Islamic Terrorism and Mental Health"}],
            "entities": {"people": ["Mario Draghi"], "organizations": []},
        }, None),
    ]
    out = split_incoherent_stories(labels, rows, min_articles=2)
    assert out[0] == out[1]
    assert out[2] != out[0]
    assert out[3] != out[0]
    assert out[2] != out[3]


def test_family_name_single_story_keeps_label():
    stories = [{"label": "Réforme des retraites", "aliases": ["pensions"], "members": [], "entities": []}]
    label, aliases = _family_name(stories)
    assert label == "Réforme des retraites"
    assert "pensions" in aliases


def test_family_name_differs_from_child_stories():
    stories = [
        {
            "label": "Réforme des retraites",
            "aliases": ["âge légal de départ"],
            "members": [{"topic": "Réforme des retraites"}, {"topic": "âge légal de départ"}],
            "entities": [{"name": "Emmanuel Macron", "kind": "person", "n": 4}],
        },
        {
            "label": "pensions",
            "aliases": [],
            "members": [{"topic": "pensions"}, {"topic": "Réforme des retraites"}],
            "entities": [{"name": "Emmanuel Macron", "kind": "person", "n": 3}],
        },
    ]
    label, aliases = _family_name(stories)
    child = {s["label"].casefold() for s in stories}
    assert label.casefold() not in child
    blob = label.casefold()
    assert "retrait" in blob or "pension" in blob or "macron" in blob
    assert any("retrait" in a.casefold() or "pension" in a.casefold() for a in aliases)


def test_family_name_canada_eu_is_umbrella():
    stories = [
        {
            "label": "Canada-EU Relations",
            "aliases": [],
            "members": [{"topic": "Canada-EU Relations"}, {"topic": "EU-Kanada Relations"}],
            "entities": [],
        },
        {
            "label": "EU-Kanada Trade Relations",
            "aliases": ["Canada EU Trade"],
            "members": [{"topic": "EU-Kanada Trade Relations"}],
            "entities": [],
        },
    ]
    label, aliases = _family_name(stories)
    child = {s["label"].casefold() for s in stories}
    assert label.casefold() not in child
    blob = label.casefold()
    assert "canada" in blob or "kanada" in blob
    assert any("canada" in a.casefold() or "trade" in a.casefold() for a in aliases)


def test_brief_item_has_titles_not_counters():
    item = brief_item({
        "label": "CETA",
        "articles": 12,
        "outlets": 5,
        "entities": [{"name": "Justin Trudeau"}, {"name": "AFP"}, {"name": "Commission européenne"}],
        "lead": {"outlet": "Le Monde", "date": "2026-09-12T08:00:00", "title": "Ottawa et Bruxelles relancent le CETA"},
        "members": [
            {"title": "Le Canada durcit sa position sur le fromage", "outlet": "Le Figaro", "date": "2026-09-18"},
        ],
        "opinion": {"dominant_tone": "indignation", "dominant_tone_share": 0.6},
    }, "story", "s:1")
    assert item["id"] == "s:1"
    assert item["kind"] == "story"
    assert "articles" not in item
    assert "outlets" not in item
    assert "CETA" in (item["titles"][0]["title"] if item["titles"] else "")
    assert "Justin Trudeau" in item["actors"]
    assert "AFP" not in item["actors"]
    assert "indignation" in (item.get("press") or "")


def test_apply_briefs_writes_family_and_stories():
    themes = [{
        "id": 3, "label": "Retraites",
        "story_summaries": [{"id": 1, "label": "Réforme"}, {"id": 2, "label": "Pensions"}],
    }]
    clusters = [{"id": 1, "label": "Réforme"}, {"id": 2, "label": "Pensions"}]
    apply_briefs(themes, clusters, {
        "f:3": "Le gouvernement défend le recul de l'âge légal, face à une presse surtout indignée.",
        "s:1": "La réforme des retraites porte l'âge légal à 64 ans. Les titres suivent l'arbitrage de Matignon.",
        "s:2": "Le volet financement oppose cotisations et déficit, sans nouveau chiffre officiel.",
    })
    assert "âge légal" in themes[0]["brief"]
    assert "64 ans" in themes[0]["story_summaries"][0]["brief"]
    assert clusters[0]["brief"] == themes[0]["story_summaries"][0]["brief"]
    assert "financement" in clusters[1]["brief"]


def test_parse_brief_map_accepts_list_or_object():
    from app.services.llm import _parse_brief_map
    listed = _parse_brief_map({"briefs": [{"id": "s:1", "brief": "x" * 50}]})
    keyed = _parse_brief_map({"briefs": {"s:2": "y" * 50}})
    assert listed["s:1"].startswith("x")
    assert keyed["s:2"].startswith("y")
    assert _parse_brief_map({"briefs": [{"id": "s:3", "brief": "trop court"}]}) == {}


def _fake_theme(tid, label, vec, story_id=None, articles=10, aliases=None, entities=None):
    sid = story_id if story_id is not None else tid
    return {
        "id": tid, "label": label, "aliases": aliases or [], "articles": articles, "stories": 1,
        "story_ids": [sid],
        "story_summaries": [{
            "id": sid, "label": label, "articles": articles, "outlets": 3,
            "heat": "stable", "polarization": 0, "brief": "",
        }],
        "entities": entities or [], "brief": "", "members": [],
        "_vec": vec,
    }


def _fake_cluster(cid, label, vec, theme_id=None, articles=10, aliases=None):
    return {
        "id": cid, "theme_id": theme_id if theme_id is not None else cid,
        "label": label, "aliases": aliases or [], "articles": articles,
        "entities": [], "brief": "", "members": [], "_vec": vec,
    }


def test_lexical_overlap_substring_and_tokens():
    assert lexical_overlap("olympic", ["Olympic Bid in Berlin"]) == 1.0
    assert lexical_overlap("retraite pensions", ["Réforme des retraites", "âge légal"]) >= 0.5
    assert lexical_overlap("xyzzy", ["Unrelated topic"]) == 0.0


def test_blend_score_lifts_strong_lexical_match():
    assert blend_score(0.1, 1.0) >= 0.78
    assert blend_score(0.7, 0.0) == 0.7
    assert blend_score(0.2, 0.0) == 0.2


def test_search_ranks_by_cosine_then_lexical():
    dim = 8
    q = np.zeros(dim); q[0] = 1
    close = np.zeros(dim); close[0] = 0.95; close[1] = 0.05
    close = close / np.linalg.norm(close)
    far = np.zeros(dim); far[1] = 1
    neutral = np.zeros(dim); neutral[2] = 1
    data = {
        "themes": [
            _fake_theme(1, "Pension reform", close, aliases=["retraites"]),
            _fake_theme(2, "Olympic bid in Berlin", far),
        ],
        "clusters": [
            _fake_cluster(1, "Pension reform", close, aliases=["retraites"]),
            _fake_cluster(2, "Olympic bid in Berlin", far),
        ],
    }
    by_sense = search_agenda(data, "retirement age", query_vec=q)
    assert by_sense, "la réforme des retraites doit matcher sémantiquement"
    assert by_sense[0]["id"] == 1
    assert "_vec" not in by_sense[0]
    by_name = search_agenda(data, "olympic", query_vec=neutral)
    assert by_name and by_name[0]["id"] == 2
    assert by_name[0]["score"] >= 0.78
    assert "_label" not in by_name[0]
    # Une famille dont seul un alias fille matche reste derrière le libellé.
    data["themes"][0]["aliases"] = ["Olympic opening ceremony"]
    data["clusters"][0]["aliases"] = ["Olympic opening ceremony"]
    ranked = search_agenda(data, "olympic", query_vec=neutral)
    assert ranked[0]["id"] == 2


def test_search_reaches_families_beyond_the_map_cap():
    dim = 4
    q = np.zeros(dim); q[0] = 1
    noise = np.zeros(dim); noise[1] = 1
    themes = [_fake_theme(i, f"Other {i}", noise, articles=80 - i) for i in range(MAX_THEMES)]
    hit_vec = np.zeros(dim); hit_vec[0] = 1
    themes.append(_fake_theme(99, "AfD electoral success", hit_vec, articles=4, aliases=["Alternative für Deutschland"]))
    data = {
        "themes": themes,
        "clusters": [_fake_cluster(t["id"], t["label"], t["_vec"], articles=t["articles"]) for t in themes],
    }
    hits = search_agenda(data, "AfD", query_vec=q)
    assert hits and hits[0]["id"] == 99


def test_public_agenda_strips_vectors_and_caps_themes():
    themes = [_fake_theme(i, f"T{i}", np.ones(3), articles=20 - i) for i in range(20)]
    out = _public_agenda({"themes": themes, "clusters": [_fake_cluster(0, "c", np.ones(3))], "n_themes_all": 20})
    assert len(out["themes"]) == MAX_THEMES
    assert out["n_themes"] == MAX_THEMES
    assert out["n_themes_all"] == 20
    assert all("_vec" not in t for t in out["themes"])
    assert all("_vec" not in c for c in out["clusters"])

