"""Cartographie — projections, réseaux, agrégats géographiques et analyses structurelles.

Tout est calculé à partir des données déjà en base (framing 12 axes des articles,
citations, embeddings, entités). Les vues des pages sont des instantanés : le worker
les recalcule, la requête HTTP ne fait que les lire.
"""

from __future__ import annotations

import logging
import math
import re
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import TONE_VALENCE, axes_for_country
from ..i18n import axis_labels, axis_poles_map, get_locale
from ..kits import STRUCTURAL_IDS, framing_value
from ..models import Article, Citation, Journalist, Outlet
from .. import geo

log = logging.getLogger("tacite.cartography")

CACHE_TTL = 600
_cache: dict[str, tuple[float, object]] = {}


def _cached(key: str, fn):
    from ..tenant import current_user_id
    key = f"{current_user_id()}:{get_locale()}:{key}"
    now = time.time()
    hit = _cache.get(key)
    if hit and now - hit[0] < CACHE_TTL:
        return hit[1]
    val = fn()
    _cache[key] = (now, val)
    return val


def invalidate():
    _cache.clear()


# ───────────────────────────────────────────────────────────── helpers


def _axes_for_view(country: str | None, db=None) -> list[str]:
    if country:
        return axes_for_country(country, db)
    return list(STRUCTURAL_IDS)


def _framing_vec(data: dict | None, axes: list[str]) -> np.ndarray | None:
    fr = (data or {}).get("framing") or {}
    if not fr:
        return None
    vals = [framing_value(fr, a) for a in axes]
    if not any(vals):
        return None
    return np.array(vals)


def _mean_nonzero(vectors: list[np.ndarray], n_axes: int) -> np.ndarray:
    """Per-axis mean of non-zero values — same rule as profiles._real_classification."""
    if not vectors:
        return np.zeros(n_axes)
    m = np.stack(vectors)
    nz = (m != 0)
    counts = nz.sum(axis=0)
    sums = (m * nz).sum(axis=0)
    with np.errstate(invalid="ignore", divide="ignore"):
        out = np.where(counts > 0, sums / np.maximum(counts, 1), 0.0)
    return out


def _axis_n(vectors: list[np.ndarray], axes: list[str]) -> dict:
    if not vectors:
        return {a: 0 for a in axes}
    counts = (np.stack(vectors) != 0).sum(axis=0)
    return {a: int(counts[i]) for i, a in enumerate(axes)}


def _vec_to_dict(v: np.ndarray, axes: list[str]) -> dict:
    return {a: round(float(v[i]), 3) for i, a in enumerate(axes)}


def _confidence(n: int) -> str:
    return "high" if n >= 30 else "medium" if n >= 10 else "low"


def _pca(matrix: np.ndarray, n_components: int = 2, axes: list[str] | None = None):
    """PCA via SVD. Returns (transform_fn, components, explained_variance_ratio)."""
    mean = matrix.mean(axis=0)
    centered = matrix - mean
    if centered.shape[0] < 2:
        comps = np.eye(matrix.shape[1])[:n_components]
        return (lambda m: (m - mean) @ comps.T), comps, [0.0] * n_components
    u, s, vt = np.linalg.svd(centered, full_matrices=False)
    comps = vt[:n_components]
    var = (s ** 2) / max((s ** 2).sum(), 1e-9)
    # Orientation stable : premier axe orienté vers "société progressiste" positif
    names = axes or []
    soc = names.index("society") if "society" in names and comps.shape[1] == len(names) else None
    if soc is not None and comps[0][soc] < 0:
        comps[0] = -comps[0]
    return (lambda m: (m - mean) @ comps.T), comps, [round(float(x), 3) for x in var[:n_components]]


def _kmeans(x: np.ndarray, k: int, seed: int = 7, iters: int = 50) -> np.ndarray:
    rng = np.random.default_rng(seed)
    # k-means++ init
    centers = [x[rng.integers(len(x))]]
    for _ in range(1, k):
        d2 = np.min([((x - c) ** 2).sum(axis=1) for c in centers], axis=0)
        probs = d2 / d2.sum() if d2.sum() > 0 else np.full(len(x), 1 / len(x))
        centers.append(x[rng.choice(len(x), p=probs)])
    centers = np.stack(centers)
    labels = np.zeros(len(x), dtype=int)
    for _ in range(iters):
        dist = ((x[:, None, :] - centers[None, :, :]) ** 2).sum(axis=2)
        new = dist.argmin(axis=1)
        if np.array_equal(new, labels) and _ > 0:
            break
        labels = new
        for j in range(k):
            if (labels == j).any():
                centers[j] = x[labels == j].mean(axis=0)
    return labels


def _silhouette(x: np.ndarray, labels: np.ndarray) -> float:
    n = len(x)
    if n < 3 or len(set(labels)) < 2:
        return -1
    d = np.sqrt(((x[:, None, :] - x[None, :, :]) ** 2).sum(axis=2))
    s = []
    for i in range(n):
        own = labels == labels[i]
        a = d[i][own & (np.arange(n) != i)].mean() if own.sum() > 1 else 0
        b = min(d[i][labels == l].mean() for l in set(labels) if l != labels[i])
        s.append((b - a) / max(a, b, 1e-9))
    return float(np.mean(s))


def _cluster_label(centroid: np.ndarray, axes: list[str], reference: np.ndarray | None = None) -> str:
    """Nomme un bloc par les deux axes où il s'écarte le plus de la moyenne du paysage
    (et non par ses valeurs absolues : sinon tous les blocs portent le même nom)."""
    diff = centroid - (reference if reference is not None else 0)
    order = np.argsort(-np.abs(diff))
    parts = []
    poles = axis_poles_map()
    for i in order[:2]:
        if abs(diff[i]) < 0.05:
            continue
        ax = axes[i] if i < len(axes) else None
        if not ax or ax not in poles:
            continue
        neg, pos = poles[ax]
        parts.append(("plus " if reference is not None else "") + (pos if diff[i] > 0 else neg))
    return " · ".join(parts).capitalize() if parts else "Centre du paysage"


def _norm_topic(label: str) -> str:
    s = re.sub(r"[^\w\s]", " ", (label or "").lower())
    s = re.sub(r"\b(le|la|les|de|des|du|d|l|et|en|the|of|and|a|an|to|in|el|los|las|der|die|das|und)\b", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _outlet_index(db: Session) -> dict[int, Outlet]:
    return {o.id: o for o in db.query(Outlet).all()}


# ───────────────────────────────────────────────────────────── landscape


def landscape(db: Session, weeks: int = 8, min_articles: int = 5, country: str | None = None, cap: int | None = None) -> dict:
    country = (country or "").upper() or None
    weeks = int(weeks or 8)
    if int(min_articles or 5) == 5 and weeks in (4, 8, 12, 26) and cap is None:
        from . import prepared
        hit = prepared.load(db, prepared.landscape_key(weeks, country))
        if hit is not None:
            return hit
        return prepared.empty_landscape(weeks, country)
    return _cached(f"landscape:{weeks}:{min_articles}:{country}:{cap}", lambda: _landscape(db, weeks, min_articles, country, cap))


def _landscape(db: Session, weeks: int, min_articles: int, country: str | None = None, cap: int | None = None) -> dict:
    since = datetime.utcnow() - timedelta(weeks=weeks)
    axes = _axes_for_view(country, db)
    n_ax = len(axes)
    outlets = _outlet_index(db)
    if country:
        outlets = {i: o for i, o in outlets.items() if (o.country or "").upper() == country}
    q = (
        db.query(Article.outlet_id, Article.journalist_id, Article.extracted_data)
        .filter(Article.analysis_status == "analyzed", Article.published_at >= since)
    )
    if cap:
        q = q.order_by(Article.published_at.desc()).limit(int(cap))
    rows = q.all()
    by_outlet: dict[int, list[np.ndarray]] = defaultdict(list)
    by_journalist: dict[int, list[np.ndarray]] = defaultdict(list)
    for oid, jid, data in rows:
        if oid not in outlets:
            continue
        v = _framing_vec(data, axes)
        if v is None:
            continue
        by_outlet[oid].append(v)
        if jid:
            by_journalist[jid].append(v)

    real: dict[int, np.ndarray] = {}
    official: dict[int, np.ndarray] = {}
    for oid, o in outlets.items():
        off = o.official_classification or {}
        official[oid] = np.array([framing_value(off, a) for a in axes])
        real[oid] = _mean_nonzero(by_outlet.get(oid, []), n_ax) if by_outlet.get(oid) else official[oid].copy()

    ids = list(outlets.keys())
    if not ids:
        return {"outlets": [], "journalists": [], "clusters": [], "axes": [], "explained_variance": [], "kit_axes": axes, "country": country}

    # ACP ajustée sur les positions réelles documentées (les positions déclarées sont
    # seulement projetées : elles sont bien plus dispersées et écraseraient le paysage mesuré).
    solid = [i for i in ids if len(by_outlet.get(i, [])) >= min_articles]
    fit_ids = solid if len(solid) >= 3 else ids
    fit_matrix = np.stack([real[i] for i in fit_ids])
    transform, comps, var = _pca(fit_matrix, axes=axes)
    global_mean = fit_matrix.mean(axis=0)

    labels: dict[int, int] = {}
    clusters = []
    if len(solid) >= 4:
        x = np.stack([real[i] for i in solid])
        best_k, best_s, best_lab = 2, -2, None
        for k in range(2, min(6, len(solid) // 2) + 1):
            lab = _kmeans(x, k)
            s = _silhouette(x, lab)
            if s > best_s:
                best_k, best_s, best_lab = k, s, lab
        # Un découpage faible (silhouette < 0,3) ou un bloc fourre-tout (> 60 % des médias)
        # n'apprend rien au lecteur : on ne l'affiche pas.
        if best_lab is not None and (best_s < 0.3 or max(np.bincount(best_lab)) > 0.6 * len(solid)):
            best_lab = None
        if best_lab is not None:
            for i, l in zip(solid, best_lab):
                labels[i] = int(l)
            for c in range(best_k):
                members = [i for i in solid if labels[i] == c]
                cen = np.stack([real[i] for i in members]).mean(axis=0)
                xy = transform(cen[None, :])[0]
                clusters.append({
                    "id": c, "label": _cluster_label(cen, axes, global_mean), "size": len(members),
                    "members": members, "centroid": _vec_to_dict(cen, axes),
                    "x": round(float(xy[0]), 3), "y": round(float(xy[1]), 3),
                    "silhouette": round(best_s, 3),
                })

    out_points = []
    for i in ids:
        o = outlets[i]
        xr, yr = transform(real[i][None, :])[0]
        xo, yo = transform(official[i][None, :])[0]
        n = len(by_outlet.get(i, []))
        usable = axes_for_country(o.country, db)
        idx = [axes.index(a) for a in usable if a in axes]
        gap_vec = real[i][idx] - official[i][idx] if idx else np.array([0.0])
        out_points.append({
            "id": i, "name": o.name, "country": o.country, "language": o.language,
            "influence": round(o.influence_score or 0, 1), "n_articles": n, "confidence": _confidence(n),
            "x": round(float(xr), 3), "y": round(float(yr), 3),
            "x_official": round(float(xo), 3), "y_official": round(float(yo), 3),
            "gap": round(float(np.linalg.norm(gap_vec) / math.sqrt(max(len(idx), 1))), 3),
            "cluster": labels.get(i), "real": _vec_to_dict(real[i], axes), "official": _vec_to_dict(official[i], axes),
            "axis_n": _axis_n(by_outlet.get(i, []), axes),
        })

    j_points = []
    if by_journalist:
        jids = [j for j, vs in by_journalist.items() if len(vs) >= min_articles]
        if jids:
            js = {j.id: j for j in db.query(Journalist).filter(Journalist.id.in_(jids)).all()}
            for jid in jids:
                j = js.get(jid)
                if not j:
                    continue
                v = _mean_nonzero(by_journalist[jid], n_ax)
                x, y = transform(v[None, :])[0]
                dev = float(np.linalg.norm(v - real.get(j.outlet_id, v)) / math.sqrt(n_ax))
                j_points.append({
                    "id": jid, "name": j.name, "outlet_id": j.outlet_id, "outlet_name": outlets.get(j.outlet_id).name if outlets.get(j.outlet_id) else "",
                    "n_articles": len(by_journalist[jid]), "accessibility": round(j.accessibility_score or 0),
                    "x": round(float(x), 3), "y": round(float(y), 3), "deviation": round(dev, 3),
                    "real": _vec_to_dict(v, axes),
                })

    axis_meta = [{"axis": a, "label": axis_labels().get(a, a), "poles": axis_poles_map().get(a, ("−", "+")),
             "dx": round(float(comps[0][i]), 3), "dy": round(float(comps[1][i]), 3)} for i, a in enumerate(axes)]
    return {
        "since": since.date().isoformat(), "weeks": weeks, "explained_variance": var,
        "axes": axis_meta, "outlets": out_points, "journalists": j_points, "clusters": clusters,
        "country": country, "kit_axes": axes,
    }


# ───────────────────────────────────────────────────────────── dissidents


def dissidents(db: Session, weeks: int = 8, min_articles: int = 5, limit: int = 40, cap: int | None = None) -> list[dict]:
    if int(weeks or 8) == 8 and int(min_articles or 5) == 5 and cap is None and 1 <= int(limit or 40) <= 40:
        from . import prepared
        hit = prepared.load(db, prepared.dissidents_key())
        if hit is None:
            return []
        return list(hit)[: int(limit or 40)]
    return _dissidents(db, int(weeks or 8), int(min_articles or 5), int(limit or 40), cap)


def _dissidents(db: Session, weeks: int, min_articles: int, limit: int, cap: int | None) -> list[dict]:
    return dissidents_from(db, _landscape(db, weeks, min_articles, None, cap), weeks, limit)


def dissidents_from(db: Session, data: dict, weeks: int, limit: int) -> list[dict]:
    outlets = {o["id"]: o for o in data["outlets"]}
    rows = []
    for j in data["journalists"]:
        o = outlets.get(j["outlet_id"])
        if not o:
            continue
        # axe de divergence dominant
        # recalcul léger : on n'a pas le vecteur du journaliste ici → on l'approxime par la position projetée
        rows.append({**j, "outlet_confidence": o["confidence"], "outlet_influence": o["influence"]})
    rows.sort(key=lambda r: -r["deviation"])
    # Enrichit les N premiers avec l'axe dominant (requête ciblée)
    top = rows[:limit]
    if top:
        since = datetime.utcnow() - timedelta(weeks=weeks)
        jids = [r["id"] for r in top]
        arts = db.query(Article.journalist_id, Article.extracted_data).filter(
            Article.journalist_id.in_(jids), Article.analysis_status == "analyzed", Article.published_at >= since
        ).all()
        axes = list((outlets[top[0]["outlet_id"]].get("real") or {}).keys()) or list(STRUCTURAL_IDS)
        n_ax = len(axes)
        vecs: dict[int, list[np.ndarray]] = defaultdict(list)
        for jid, d in arts:
            v = _framing_vec(d, axes)
            if v is not None:
                vecs[jid].append(v)
        poles = axis_poles_map()
        labels = axis_labels()
        for r in top:
            v = _mean_nonzero(vecs.get(r["id"], []), n_ax)
            o = outlets[r["outlet_id"]]
            ov = np.array([float((o.get("real") or {}).get(a, 0) or 0) for a in axes])
            diff = v - ov
            i = int(np.argmax(np.abs(diff))) if len(diff) else 0
            ax = axes[i] if i < len(axes) else (axes[0] if axes else "economy")
            neg, pos = poles.get(ax, ("−", "+"))
            r["axis"] = ax
            r["axis_label"] = labels.get(ax, ax)
            r["axis_delta"] = round(float(diff[i]), 2)
            r["direction"] = pos if diff[i] > 0 else neg
    return top


# ───────────────────────────────────────────────────────────── network


def network(db: Session, days: int = 90, top_journalists: int = 60) -> dict:
    days = int(days or 90)
    top_journalists = int(top_journalists or 60)
    if days == 90 and top_journalists == 60:
        from . import prepared
        hit = prepared.load(db, prepared.network_key(days, top_journalists))
        if hit is not None:
            return hit
        return prepared.empty_network(days)
    return _cached(f"network:{days}:{top_journalists}", lambda: _network(db, days, top_journalists))


def _network(db: Session, days: int, top_journalists: int) -> dict:
    import networkx as nx

    since = datetime.utcnow() - timedelta(days=days)
    outlets = _outlet_index(db)

    cites = (
        db.query(Citation.source_outlet_id, Citation.target_outlet_id, func.count(Citation.id))
        .filter(Citation.timestamp >= since, Citation.source_outlet_id != Citation.target_outlet_id)
        .group_by(Citation.source_outlet_id, Citation.target_outlet_id)
        .all()
    )
    g = nx.DiGraph()
    for oid in outlets:
        g.add_node(oid)
    for s, t, w in cites:
        if s in outlets and t in outlets:
            g.add_edge(s, t, weight=int(w))

    # Co-couverture : recouvrement des thèmes traités (Jaccard sur les 40 thèmes les plus fréquents)
    rows = db.query(Article.outlet_id, Article.extracted_data).filter(
        Article.analysis_status == "analyzed", Article.published_at >= since
    ).all()
    topics_by_outlet: dict[int, Counter] = defaultdict(Counter)
    for oid, d in rows:
        for t in (d or {}).get("topics", [])[:3]:
            k = _norm_topic(t.get("label", ""))
            if k:
                topics_by_outlet[oid][k] += 1
    top_sets = {oid: set(k for k, _ in c.most_common(40)) for oid, c in topics_by_outlet.items()}
    cocov = []
    ids = list(top_sets.keys())
    for a_i in range(len(ids)):
        for b_i in range(a_i + 1, len(ids)):
            a, b = ids[a_i], ids[b_i]
            inter = len(top_sets[a] & top_sets[b])
            union = len(top_sets[a] | top_sets[b]) or 1
            jac = inter / union
            if jac >= 0.12:
                cocov.append({"source": a, "target": b, "weight": round(jac, 3), "shared": inter, "type": "cocoverage"})

    pr = nx.pagerank(g, weight="weight") if g.number_of_edges() else {n: 1 / max(len(g), 1) for n in g}
    ug = nx.Graph()
    ug.add_nodes_from(g.nodes)
    for s, t, d in g.edges(data=True):
        ug.add_edge(s, t, weight=ug.get_edge_data(s, t, {}).get("weight", 0) + d["weight"])
    for e in cocov:
        w = ug.get_edge_data(e["source"], e["target"], {}).get("weight", 0)
        ug.add_edge(e["source"], e["target"], weight=w + e["weight"] * 3)
    communities: dict[int, int] = {}
    if ug.number_of_edges():
        try:
            comms = nx.community.louvain_communities(ug, weight="weight", seed=7)
        except Exception:  # noqa: BLE001
            comms = nx.community.greedy_modularity_communities(ug, weight="weight")
        for ci, members in enumerate(sorted(comms, key=len, reverse=True)):
            for m in members:
                communities[m] = ci

    nodes = []
    for oid, o in outlets.items():
        nodes.append({
            "id": f"o{oid}", "ref": oid, "kind": "outlet", "name": o.name, "country": o.country,
            "influence": round(o.influence_score or 0, 1), "pagerank": round(pr.get(oid, 0), 4),
            "in_citations": int(sum(d["weight"] for _, _, d in g.in_edges(oid, data=True))),
            "out_citations": int(sum(d["weight"] for _, _, d in g.out_edges(oid, data=True))),
            "community": communities.get(oid), "articles": int(sum(topics_by_outlet.get(oid, Counter()).values())),
        })
    edges = [{"source": f"o{s}", "target": f"o{t}", "weight": d["weight"], "type": "citation"} for s, t, d in g.edges(data=True)]
    edges += [{"source": f"o{e['source']}", "target": f"o{e['target']}", "weight": e["weight"], "shared": e["shared"], "type": "cocoverage"} for e in cocov]

    # Journalistes les plus prolifiques, rattachés à leur média
    jrows = (
        db.query(Article.journalist_id, func.count(Article.id))
        .filter(Article.journalist_id.isnot(None), Article.published_at >= since)
        .group_by(Article.journalist_id).order_by(func.count(Article.id).desc()).limit(top_journalists).all()
    )
    if jrows:
        js = {j.id: j for j in db.query(Journalist).filter(Journalist.id.in_([r[0] for r in jrows])).all()}
        for jid, n in jrows:
            j = js.get(jid)
            if not j or j.outlet_id not in outlets:
                continue
            beat = re.match(r"^\[([^\]]*)\]", j.bio or "")
            nodes.append({
                "id": f"j{jid}", "ref": jid, "kind": "journalist", "name": j.name, "outlet_id": j.outlet_id,
                "articles": int(n), "accessibility": round(j.accessibility_score or 0),
                "beat": beat.group(1) if beat else None, "community": communities.get(j.outlet_id),
            })
            edges.append({"source": f"j{jid}", "target": f"o{j.outlet_id}", "weight": 1, "type": "byline"})

    comm_summary = []
    for ci in sorted(set(communities.values())):
        members = [oid for oid, c in communities.items() if c == ci]
        comm_summary.append({"id": ci, "size": len(members), "members": members,
                             "label": ", ".join(outlets[m].name for m in sorted(members, key=lambda m: -(outlets[m].influence_score or 0))[:3])})
    return {"since": since.date().isoformat(), "nodes": nodes, "edges": edges, "communities": comm_summary,
            "stats": {"citations": int(sum(w for _, _, w in cites)), "cocoverage_pairs": len(cocov)}}


# ───────────────────────────────────────────────────────────── world


def world(db: Session, days: int = 30) -> dict:
    days = int(days or 30)
    if days == 30:
        from . import prepared
        hit = prepared.load(db, prepared.world_key(days))
        if hit is not None:
            return hit
        return prepared.empty_world(days)
    return _cached(f"world:{days}", lambda: _world(db, days))


def _world(db: Session, days: int) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    outlets = _outlet_index(db)
    art_counts = dict(db.query(Article.outlet_id, func.count(Article.id)).filter(Article.published_at >= since).group_by(Article.outlet_id).all())
    jour_counts = dict(db.query(Journalist.outlet_id, func.count(Journalist.id)).group_by(Journalist.outlet_id).all())

    countries: dict[str, dict] = {}
    for oid, o in outlets.items():
        code = (o.country or "").upper()
        c = countries.setdefault(code, {
            "code": code, "numeric": (geo.country(code) or {}).get("numeric"), "region": geo.region_of(code), "centroid": geo.centroid(code),
            "outlets": 0, "influence_sum": 0.0, "influence_max": 0.0, "articles": 0, "journalists": 0, "languages": Counter(), "top": [],
        })
        c["outlets"] += 1
        c["influence_sum"] += o.influence_score or 0
        c["influence_max"] = max(c["influence_max"], o.influence_score or 0)
        c["articles"] += int(art_counts.get(oid, 0))
        c["journalists"] += int(jour_counts.get(oid, 0))
        c["languages"][o.language] += 1
        c["top"].append({"id": oid, "name": o.name, "influence": round(o.influence_score or 0, 1)})
    for c in countries.values():
        c["influence_mean"] = round(c["influence_sum"] / max(c["outlets"], 1), 1)
        c["influence_sum"] = round(c["influence_sum"], 1)
        c["languages"] = dict(c["languages"].most_common())
        c["top"] = sorted(c["top"], key=lambda t: -t["influence"])[:5]

    flows: Counter = Counter()
    for s, t, w in (
        db.query(Citation.source_outlet_id, Citation.target_outlet_id, func.count(Citation.id))
        .filter(Citation.timestamp >= since).group_by(Citation.source_outlet_id, Citation.target_outlet_id).all()
    ):
        so, to = outlets.get(s), outlets.get(t)
        if so and to and so.country != to.country:
            flows[((so.country or "").upper(), (to.country or "").upper())] += int(w)
    flow_rows = [{"source": s, "target": t, "weight": w} for (s, t), w in flows.most_common(200)]

    regions = Counter(c["region"] for c in countries.values())
    return {
        "since": since.date().isoformat(), "countries": sorted(countries.values(), key=lambda c: -c["influence_sum"]),
        "flows": flow_rows, "regions": dict(regions), "total_countries_known": len(geo.all_countries()),
    }


# ───────────────────────────────────────────────────────────── corpus


def corpus(db: Session, limit: int = 1500, days: int = 60) -> dict:
    limit = int(limit or 1500)
    days = int(days or 60)
    if limit == 1500 and days == 60:
        from . import prepared
        hit = prepared.load(db, prepared.corpus_key(limit, days))
        if hit is not None:
            return hit
        return prepared.empty_corpus()
    return _cached(f"corpus:{limit}:{days}", lambda: _corpus(db, limit, days))


def _corpus(db: Session, limit: int, days: int) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    outlets = _outlet_index(db)
    rows = (
        db.query(Article.id, Article.title, Article.outlet_id, Article.published_at, Article.extracted_data, Article.embedding)
        .filter(Article.analysis_status == "analyzed", Article.embedding.isnot(None), Article.published_at >= since)
        .order_by(Article.published_at.desc()).limit(limit).all()
    )
    if not rows:
        return {"points": [], "topics": [], "blind_spots": [], "explained_variance": []}
    emb = np.stack([np.asarray(r[5], dtype=float) for r in rows])
    transform, _, var = _pca(emb)
    xy = transform(emb)
    # normalise en [-1, 1]
    for k in range(2):
        span = np.abs(xy[:, k]).max() or 1
        xy[:, k] = xy[:, k] / span

    points = []
    topic_outlets: dict[str, set] = defaultdict(set)
    topic_count: Counter = Counter()
    topic_label: dict[str, str] = {}
    for (aid, title, oid, pub, data, _), (x, y) in zip(rows, xy):
        topics = (data or {}).get("topics", [])
        first = topics[0]["label"] if topics else ""
        for t in topics[:3]:
            k = _norm_topic(t.get("label", ""))
            if k:
                topic_outlets[k].add(oid)
                topic_count[k] += 1
                topic_label.setdefault(k, t.get("label", ""))
        points.append({
            "id": aid, "title": title, "outlet_id": oid, "outlet": outlets[oid].name if oid in outlets else "",
            "country": outlets[oid].country if oid in outlets else None,
            "date": pub.date().isoformat() if pub else None, "topic": first, "tone": (data or {}).get("tone"),
            "x": round(float(x), 4), "y": round(float(y), 4),
        })

    # Angles morts : thèmes traités par un seul média alors qu'ils reviennent
    blind = []
    for k, n in topic_count.most_common(400):
        os_ = topic_outlets[k]
        if n >= 3 and len(os_) == 1:
            oid = next(iter(os_))
            blind.append({"topic": topic_label[k], "articles": n, "outlet_id": oid, "outlet": outlets[oid].name if oid in outlets else ""})
    # Thèmes dominants et leur concentration (part du premier média)
    top_topics = []
    for k, n in topic_count.most_common(30):
        top_topics.append({"topic": topic_label[k], "articles": n, "outlets": len(topic_outlets[k])})
    return {"since": since.date().isoformat(), "explained_variance": var, "points": points, "topics": top_topics, "blind_spots": blind[:40]}


# ───────────────────────────────────────────────────────────── lead-lag


def leadlag(db: Session, days: int = 30, window_hours: int = 72, cap: int | None = None) -> dict:
    days = int(days or 30)
    window_hours = int(window_hours or 72)
    if (days, window_hours, cap) in ((30, 72, None), (14, 72, 1500)):
        from . import prepared
        hit = prepared.load(db, prepared.leadlag_key(days, window_hours, cap))
        if hit is not None:
            return hit
        return prepared.empty_leadlag(window_hours)
    return _cached(f"leadlag:{days}:{window_hours}:{cap}", lambda: _leadlag(db, days, window_hours, cap))


def _leadlag(db: Session, days: int, window_hours: int, cap: int | None = None) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    outlets = _outlet_index(db)
    q = (
        db.query(Article.outlet_id, Article.published_at, Article.extracted_data)
        .filter(Article.analysis_status == "analyzed", Article.published_at >= since, Article.published_at.isnot(None))
    )
    if cap:
        q = q.order_by(Article.published_at.desc()).limit(int(cap))
    rows = q.all()
    by_topic: dict[str, list[tuple[datetime, int]]] = defaultdict(list)
    for oid, pub, data in rows:
        for t in (data or {}).get("topics", [])[:2]:
            k = _norm_topic(t.get("label", ""))
            if len(k) >= 6:
                by_topic[k].append((pub, oid))

    leads: Counter = Counter()
    follows: Counter = Counter()
    lags: dict[int, list[float]] = defaultdict(list)
    pair: Counter = Counter()
    pair_lags: dict[tuple[int, int], list[float]] = defaultdict(list)
    events = 0
    for k, items in by_topic.items():
        items.sort()
        # fenêtres : on avance tant que l'article suivant est dans les window_hours du premier
        i = 0
        while i < len(items):
            first_t, first_o = items[i]
            group = [(first_t, first_o)]
            j = i + 1
            while j < len(items) and (items[j][0] - first_t).total_seconds() <= window_hours * 3600:
                group.append(items[j])
                j += 1
            outs = {o for _, o in group}
            if len(outs) >= 2:
                events += 1
                leads[first_o] += 1
                seen = {first_o}
                for t, o in group[1:]:
                    if o in seen:
                        continue
                    seen.add(o)
                    follows[o] += 1
                    lag = (t - first_t).total_seconds() / 3600
                    lags[o].append(lag)
                    pair[(first_o, o)] += 1
                    pair_lags[(first_o, o)].append(lag)
            i = j

    ranking = []
    for oid, o in outlets.items():
        l, f = leads.get(oid, 0), follows.get(oid, 0)
        if l + f == 0:
            continue
        ranking.append({
            "outlet_id": oid, "name": o.name, "country": o.country, "influence": round(o.influence_score or 0, 1),
            "leads": l, "follows": f, "lead_ratio": round(l / (l + f), 3),
            "median_lag_h": round(median(lags[oid]), 1) if lags.get(oid) else None,
        })
    ranking.sort(key=lambda r: (-r["lead_ratio"], -r["leads"]))
    pairs = [{
        "leader": s, "leader_name": outlets[s].name if s in outlets else "", "follower": t, "follower_name": outlets[t].name if t in outlets else "",
        "count": n, "median_lag_h": round(median(pair_lags[(s, t)]), 1),
    } for (s, t), n in pair.most_common(40) if s in outlets and t in outlets]
    return {"since": since.date().isoformat(), "window_hours": window_hours, "events": events, "ranking": ranking, "pairs": pairs}


# ───────────────────────────────────────────────────────────── packs (meutes) / matrice


def packs(db: Session, days: int = 60) -> dict:
    days = int(days or 60)
    if days == 60:
        from . import prepared
        hit = prepared.load(db, prepared.packs_key(days))
        if hit is not None:
            return hit
        return prepared.empty_packs()
    return _cached(f"packs:{days}", lambda: _packs(db, days))


def _packs(db: Session, days: int) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    outlets = _outlet_index(db)
    rows = db.query(Article.outlet_id, Article.published_at, Article.extracted_data).filter(
        Article.analysis_status == "analyzed", Article.published_at >= since
    ).all()
    topics: dict[int, Counter] = defaultdict(Counter)
    daily: dict[int, Counter] = defaultdict(Counter)
    framing: dict[int, list[np.ndarray]] = defaultdict(list)
    for oid, pub, d in rows:
        for t in (d or {}).get("topics", [])[:3]:
            k = _norm_topic(t.get("label", ""))
            if k:
                topics[oid][k] += 1
        if pub:
            daily[oid][pub.date()] += 1
        v = _framing_vec(d, STRUCTURAL_IDS)
        if v is not None:
            framing[oid].append(v)
    ids = [oid for oid in outlets if topics.get(oid)]
    if len(ids) < 2:
        return {"outlets": [], "topic_similarity": [], "framing_similarity": [], "pairs": []}
    vocab = list({k for oid in ids for k, _ in topics[oid].most_common(150)})
    vi = {k: i for i, k in enumerate(vocab)}
    tm = np.zeros((len(ids), len(vocab)))
    for r, oid in enumerate(ids):
        for k, n in topics[oid].items():
            if k in vi:
                tm[r, vi[k]] = n
    tm = tm / np.maximum(np.linalg.norm(tm, axis=1, keepdims=True), 1e-9)
    tsim = tm @ tm.T
    n_ax = len(STRUCTURAL_IDS)
    fm = np.stack([_mean_nonzero(framing.get(oid, []), n_ax) for oid in ids])
    fnorm = fm / np.maximum(np.linalg.norm(fm, axis=1, keepdims=True), 1e-9)
    fsim = fnorm @ fnorm.T

    # Ordre par regroupement hiérarchique (moyenne) sur la similarité thématique
    try:
        from scipy.cluster.hierarchy import leaves_list, linkage
        dist = 1 - tsim
        iu = np.triu_indices(len(ids), 1)
        order = [int(i) for i in leaves_list(linkage(dist[iu], method="average"))]
    except Exception:  # noqa: BLE001
        order = list(range(len(ids)))

    pairs = []
    for a in range(len(ids)):
        for b in range(a + 1, len(ids)):
            pairs.append({
                "a": ids[a], "a_name": outlets[ids[a]].name, "b": ids[b], "b_name": outlets[ids[b]].name,
                "topic_similarity": round(float(tsim[a, b]), 3), "framing_similarity": round(float(fsim[a, b]), 3),
            })
    pairs.sort(key=lambda p: -p["topic_similarity"])
    return {
        "since": since.date().isoformat(),
        "outlets": [{"id": oid, "name": outlets[oid].name, "country": outlets[oid].country, "articles": int(sum(daily[oid].values()))} for oid in ids],
        "order": order,
        "topic_similarity": [[round(float(x), 3) for x in row] for row in tsim],
        "framing_similarity": [[round(float(x), 3) for x in row] for row in fsim],
        "pairs": pairs[:30],
    }


# ───────────────────────────────────────────────────────────── entities


def entities(db: Session, days: int = 60, limit: int = 40, country: str | None = None, cap: int | None = None) -> dict:
    country = (country or "").upper() or None
    days = int(days or 60)
    limit = int(limit or 40)
    from . import prepared
    if cap is None and days == 60 and 1 <= limit <= 80:
        hit = prepared.load(db, prepared.entities_key(60, 80, country, None))
        if hit is not None:
            if limit < 80:
                hit = {**hit, "entities": (hit.get("entities") or [])[:limit]}
            return hit
        return prepared.empty_entities()
    if days == 30 and limit == 40 and cap == 1500:
        hit = prepared.load(db, prepared.entities_key(30, 40, country, 1500))
        if hit is not None:
            return hit
        return prepared.empty_entities()
    return _cached(f"entities:{days}:{limit}:{country}:{cap}", lambda: _entities(db, days, limit, country, cap))


def _entities(db: Session, days: int, limit: int, country: str | None = None, cap: int | None = None) -> dict:
    since = datetime.utcnow() - timedelta(days=days)
    outlets = _outlet_index(db)
    if country:
        outlets = {i: o for i, o in outlets.items() if (o.country or "").upper() == country}
    q = db.query(Article.outlet_id, Article.extracted_data).filter(
        Article.analysis_status == "analyzed", Article.published_at >= since
    )
    if cap:
        q = q.order_by(Article.published_at.desc()).limit(int(cap))
    rows = q.all()
    total: Counter = Counter()
    per: dict[str, dict[int, list[float]]] = defaultdict(lambda: defaultdict(list))
    kind: dict[str, str] = {}
    for oid, d in rows:
        if oid not in outlets:
            continue
        ents = (d or {}).get("entities") or {}
        val = TONE_VALENCE.get(((d or {}).get("tone") or "").lower(), 0.0)
        for bucket in ("people", "organizations"):
            for e in ents.get(bucket, []) or []:
                name = e.strip()
                if len(name) < 3 or len(name) > 60:
                    continue
                total[name] += 1
                per[name][oid].append(val)
                kind.setdefault(name, bucket)
    top = [name for name, _ in total.most_common(limit)]
    out = []
    for name in top:
        cells = []
        for oid, vals in per[name].items():
            if oid in outlets:
                cells.append({"outlet_id": oid, "outlet": outlets[oid].name, "mentions": len(vals), "valence": round(float(np.mean(vals)), 2)})
        cells.sort(key=lambda c: -c["mentions"])
        allv = [v for vs in per[name].values() for v in vs]
        out.append({"entity": name, "kind": kind[name], "mentions": total[name], "outlets": len(cells),
                    "valence": round(float(np.mean(allv)), 2), "spread": round(float(np.std([c["valence"] for c in cells])), 2) if len(cells) > 1 else 0.0,
                    "cells": cells})
    return {"since": since.date().isoformat(), "entities": out, "outlets": [{"id": oid, "name": o.name} for oid, o in outlets.items()]}
