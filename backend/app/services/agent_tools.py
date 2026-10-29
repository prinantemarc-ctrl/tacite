"""Outils de l'assistant Tacite.

Trois familles :
- lecture  : interrogent la base et les services existants (cartographie, tableau de bord…), Google News, GDELT, lecture d'URL ;
- production : graphiques inline, fichiers (CSV, XLSX, MD, DOCX, HTML, PDF), rapports ;
- écriture : modifient la base. Elles ne s'exécutent jamais directement : l'agent les propose,
  l'utilisateur confirme (voir agent.py / AgentAction), puis `apply_write` les applique.

Chaque outil = une spec JSON (pour le modèle) + une fonction python (db, args) -> résultat JSON-sérialisable.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Callable

from sqlalchemy import String, func, text
from sqlalchemy.orm import Session

from ..constants import AXES, ACTION_TYPES, DEFAULT_SETTINGS, axes_for_country
from ..kits import STRUCTURAL_IDS
from ..i18n import axis_labels, axis_poles_map
from ..models import (
    ActionHistory, Article, Citation, Client, ClientBlacklist, ClientContact, IngestionLog, Journalist, JournalistProfile,
    Outlet, OutletFeed, OutletProfile, Recommendation, row_to_dict,
)
from ..settings_store import get_setting, get_settings, set_setting
from . import cartography, embeddings, extract, files, profiles

log = logging.getLogger("tacite.agent.tools")

# Nom d'outil -> (spec, fn, kind) ; kind ∈ {"read", "produce", "write"}
REGISTRY: dict[str, tuple[dict, Callable, str]] = {}


def tool(name: str, description: str, params: dict, kind: str = "read", required: list[str] | None = None):
    def deco(fn):
        REGISTRY[name] = ({
            "type": "function", "name": name, "description": description,
            "parameters": {"type": "object", "properties": params, "required": required or [], "additionalProperties": False},
        }, fn, kind)
        return fn
    return deco


def specs(include_write: bool = True) -> list[dict]:
    return [s for s, _, k in REGISTRY.values() if include_write or k != "write"]


def kind_of(name: str) -> str:
    return REGISTRY[name][2] if name in REGISTRY else "read"


def run(name: str, db: Session, args: dict, ctx: dict) -> Any:
    """Exécute un outil de lecture ou de production. ctx : {conversation_id, message_parts (liste mutable)}."""
    if name not in REGISTRY:
        return {"error": f"outil inconnu : {name}"}
    _, fn, kind = REGISTRY[name]
    if kind == "write":
        return {"error": "outil d'écriture : doit passer par une confirmation"}
    return fn(db, args, ctx)


# ═══════════════════════════════════════════════════════════════ helpers

def _f(v, nd=2):
    try:
        return round(float(v), nd)
    except (TypeError, ValueError):
        return None


def _latest_profiles(db: Session, outlet_ids: list[int] | None = None) -> dict[int, OutletProfile]:
    sub = db.query(OutletProfile.outlet_id, func.max(OutletProfile.week).label("week")).group_by(OutletProfile.outlet_id).subquery()
    q = db.query(OutletProfile).join(sub, (OutletProfile.outlet_id == sub.c.outlet_id) & (OutletProfile.week == sub.c.week))
    if outlet_ids:
        q = q.filter(OutletProfile.outlet_id.in_(outlet_ids))
    return {p.outlet_id: p for p in q.all()}


def _outlet_brief(o: Outlet, p: OutletProfile | None, recap: dict | None = None, db=None) -> dict:
    d = {"id": o.id, "name": o.name, "country": o.country, "language": o.language, "declared_orientation": o.declared_orientation,
         "influence": _f(o.influence_score, 1), "influence_rank": o.influence_rank, "website": o.website_url}
    if p:
        g = profiles.max_usable_gap(o.country, p.gap_from_official, p.axis_n, db)
        if g:
            d["max_gap"] = g
        d["articles_week"] = p.article_count
        d["confidence"] = profiles.confidence_label(profiles.evidence_n(p.axis_n, p.article_count))
        d["week"] = p.week.isoformat()
        d["drift_alerts"] = [
            {"axis": axis_labels().get(a.get("axis"), a.get("axis")), "change": _f(a.get("change"))}
            for a in (p.drift_alerts or [])
        ]
    if recap:
        d["topics"] = recap.get("topics") or []
        d["top_journalists"] = recap.get("journalists") or []
        d["journalists_count"] = recap.get("journalists_count") or 0
    return d


def _axes_of(o: Outlet | None, db=None) -> list[str]:
    return axes_for_country(o.country if o else None, db)


def _axes_table(declared: dict, measured: dict, axes: list[str] | None = None) -> list[dict]:
    rows = []
    labels = axis_labels()
    poles = axis_poles_map()
    for a in (axes or list(STRUCTURAL_IDS)):
        dv, mv = float(declared.get(a, 0) or 0), float(measured.get(a, 0) or 0)
        neg, pos = poles.get(a, ("−", "+"))
        rows.append({"axis": a, "label": labels.get(a, a), "poles": f"{neg} (−1) ↔ {pos} (+1)", "declared": _f(dv), "measured": _f(mv), "gap": _f(mv - dv)})
    return rows


def _article_row(a: Article, onames: dict, jnames: dict, with_text: bool = False) -> dict:
    d = (a.extracted_data or {})
    row = {"id": a.id, "title": a.title, "outlet": onames.get(a.outlet_id), "outlet_id": a.outlet_id,
           "journalist": jnames.get(a.journalist_id) if a.journalist_id else None, "journalist_id": a.journalist_id,
           "published_at": a.published_at.isoformat() if a.published_at else None, "url": a.url, "status": a.analysis_status,
           "topics": [t.get("label") for t in (d.get("topics") or [])][:3], "tone": d.get("tone"), "angle": d.get("angle"),
           "framing": {k: _f(v) for k, v in (d.get("framing") or {}).items() if v}}
    if with_text:
        row["text"] = (a.text or "")[:6000]
        row["sources"] = d.get("sources")
        row["entities"] = d.get("entities")
    return row


def _names(db: Session):
    return {o.id: o.name for o in db.query(Outlet.id, Outlet.name).all()}, {j.id: j.name for j in db.query(Journalist.id, Journalist.name).all()}


def _find_outlet(db: Session, ident) -> Outlet | None:
    if ident is None:
        return None
    if isinstance(ident, int) or (isinstance(ident, str) and ident.isdigit()):
        return db.get(Outlet, int(ident))
    q = db.query(Outlet).filter(func.lower(Outlet.name) == str(ident).lower()).first()
    return q or db.query(Outlet).filter(Outlet.name.ilike(f"%{ident}%")).first()


def _find_journalist(db: Session, ident, outlet_id: int | None = None) -> Journalist | None:
    if ident is None:
        return None
    if isinstance(ident, int) or (isinstance(ident, str) and ident.isdigit()):
        return db.get(Journalist, int(ident))
    q = db.query(Journalist).filter(Journalist.name.ilike(f"%{ident}%"))
    if outlet_id:
        q = q.filter(Journalist.outlet_id == outlet_id)
    return q.first()


def _find_client(db: Session, ident) -> Client | None:
    if ident is None:
        return None
    if isinstance(ident, int) or (isinstance(ident, str) and ident.isdigit()):
        return db.get(Client, int(ident))
    return db.query(Client).filter(Client.name.ilike(f"%{ident}%")).first()


# ═══════════════════════════════════════════════════════════════ LECTURE — médias

@tool("list_outlets", "Liste des médias suivis avec influence, orientation déclarée, écart max (axe + valeur), confiance, sujets de prédilection (8 semaines) et journalistes les plus actifs.",
      {"country": {"type": "string", "description": "Code ISO-2 (FR, DE, GB…) pour filtrer, optionnel"}})
def list_outlets(db, args, ctx):
    q = db.query(Outlet)
    if args.get("country"):
        q = q.filter(Outlet.country == args["country"].upper())
    rows = q.order_by(Outlet.influence_score.desc()).all()
    profs = _latest_profiles(db)
    recaps = profiles.recap_for_outlets(db, [o.id for o in rows])
    return {"outlets": [_outlet_brief(o, profs.get(o.id), recaps.get(o.id), db) for o in rows], "count": len(rows)}


@tool("get_outlet", "Fiche complète d'un média : ligne déclarée et mesurée sur les 12 axes, écarts, composantes d'influence, dérives, trajectoire hebdomadaire, journalistes principaux, qui il cite / qui le cite.",
      {"outlet": {"type": "string", "description": "id numérique ou nom du média"}}, required=["outlet"])
def get_outlet(db, args, ctx):
    o = _find_outlet(db, args.get("outlet"))
    if not o:
        return {"error": "média introuvable"}
    profs = db.query(OutletProfile).filter(OutletProfile.outlet_id == o.id).order_by(OutletProfile.week.desc()).limit(12).all()
    latest = profs[0] if profs else None
    recap = profiles.recap_for_outlets(db, [o.id], topics_n=8, journalists_n=12).get(o.id)
    d = _outlet_brief(o, latest, recap, db)
    axes = _axes_of(o, db)
    d["axes"] = _axes_table(o.official_classification or {}, latest.real_classification if latest else {}, axes)
    d["influence_components"] = latest.component_scores if latest else {}
    d["drift_alerts"] = latest.drift_alerts if latest else []
    d["trajectory"] = [{"week": p.week.isoformat(), "articles": p.article_count, **{a: _f((p.real_classification or {}).get(a, 0)) for a in axes}} for p in reversed(profs)]
    js = db.query(Journalist, func.count(Article.id).label("n")).outerjoin(Article, Article.journalist_id == Journalist.id).filter(Journalist.outlet_id == o.id).group_by(Journalist.id).order_by(func.count(Article.id).desc()).limit(12).all()
    d["journalists"] = [{"id": j.id, "name": j.name, "role": j.role, "accessibility": _f(j.accessibility_score, 0), "articles": n} for j, n in js]
    since = datetime.utcnow() - timedelta(days=90)
    onames, _ = _names(db)
    cites = db.query(Citation.target_outlet_id, func.count()).filter(Citation.source_outlet_id == o.id, Citation.timestamp >= since).group_by(Citation.target_outlet_id).order_by(func.count().desc()).limit(8).all()
    cited = db.query(Citation.source_outlet_id, func.count()).filter(Citation.target_outlet_id == o.id, Citation.timestamp >= since).group_by(Citation.source_outlet_id).order_by(func.count().desc()).limit(8).all()
    d["cites"] = [{"outlet": onames.get(t), "n": n} for t, n in cites]
    d["cited_by"] = [{"outlet": onames.get(s), "n": n} for s, n in cited]
    d["feeds"] = [{"url": f.url, "label": f.label, "type": f.feed_type, "enabled": bool(f.enabled)} for f in db.query(OutletFeed).filter(OutletFeed.outlet_id == o.id).all()]
    d["article_counts"] = dict(db.query(Article.analysis_status, func.count()).filter(Article.outlet_id == o.id).group_by(Article.analysis_status).all())
    return d


@tool("compare_outlets", "Compare plusieurs médias sur les 12 axes (ligne mesurée, ligne déclarée, écart) et leur influence.",
      {"outlets": {"type": "array", "items": {"type": "string"}, "description": "ids ou noms"}}, required=["outlets"])
def compare_outlets(db, args, ctx):
    outs = [o for o in (_find_outlet(db, x) for x in args.get("outlets", [])) if o]
    profs = _latest_profiles(db, [o.id for o in outs])
    countries = {o.country for o in outs}
    axes = _axes_of(outs[0], db) if len(countries) == 1 else list(STRUCTURAL_IDS)
    res = []
    for o in outs:
        p = profs.get(o.id)
        res.append({**_outlet_brief(o, p, db=db), "measured": {a: _f((p.real_classification or {}).get(a, 0)) for a in axes} if p else None,
                    "declared": {a: _f((o.official_classification or {}).get(a, 0)) for a in axes}})
    return {"outlets": res, "axis_labels": axis_labels(), "poles": {a: list(v) for a, v in axis_poles_map().items()}}


# ═══════════════════════════════════════════════════════════════ LECTURE — journalistes

@tool("list_journalists", "Recherche de journalistes par média, beat, nom, accessibilité minimale. Renvoie rôle, beat, accessibilité, nombre d'articles, réseaux.",
      {"outlet": {"type": "string"}, "query": {"type": "string", "description": "fragment de nom"}, "beat": {"type": "string"},
       "min_accessibility": {"type": "number"}, "limit": {"type": "integer", "default": 30}})
def list_journalists(db, args, ctx):
    q = db.query(Journalist, Outlet.name, func.count(Article.id)).join(Outlet, Outlet.id == Journalist.outlet_id).outerjoin(Article, Article.journalist_id == Journalist.id)
    o = _find_outlet(db, args.get("outlet")) if args.get("outlet") else None
    if o:
        q = q.filter(Journalist.outlet_id == o.id)
    if args.get("query"):
        q = q.filter(Journalist.name.ilike(f"%{args['query']}%"))
    if args.get("beat"):
        from .enrich import normalize_beat
        nb = normalize_beat(args["beat"])
        # beat normalisé en préfixe, ou mot présent dans la bio, ou dans les fixations du profil
        jids_theme = [r[0] for r in db.query(JournalistProfile.journalist_id).filter(JournalistProfile.themes.cast(String).ilike(f"%{args['beat']}%")).all()]
        q = q.filter((Journalist.bio.ilike(f"[{nb}%")) | (Journalist.bio.ilike(f"%{args['beat']}%")) | (Journalist.id.in_(jids_theme or [0])))
    if args.get("min_accessibility") is not None:
        q = q.filter(Journalist.accessibility_score >= float(args["min_accessibility"]))
    rows = q.group_by(Journalist.id, Outlet.name).order_by(Journalist.accessibility_score.desc(), func.count(Article.id).desc()).limit(int(args.get("limit") or 30)).all()
    from . import contacts as C
    cs = C.summary_for_many(db, [j.id for j, _, _ in rows])
    out = []
    for j, oname, n in rows:
        m = re.match(r"^\[([^\]]*)\]\s*(.*)$", j.bio or "", re.S)
        out.append({"id": j.id, "name": j.name, "outlet": oname, "outlet_id": j.outlet_id, "role": j.role, "beat": m.group(1) if m else None,
                    "bio": (m.group(2) if m else (j.bio or ""))[:200], "accessibility": _f(j.accessibility_score, 0), "articles": n,
                    "contact": (cs.get(j.id) or {}).get("best"), "contact_kinds": (cs.get(j.id) or {}).get("kinds", [])})
    return {"journalists": out, "count": len(out)}


@tool("get_journalist", "Fiche complète d'un journaliste : profil (fixations, biais, sources, ton, vulnérabilités, accessibilité), cadrage mesuré, écart avec son média, derniers articles, réseaux.",
      {"journalist": {"type": "string", "description": "id ou nom"}, "outlet": {"type": "string", "description": "pour lever une ambiguïté"}}, required=["journalist"])
def get_journalist(db, args, ctx):
    o = _find_outlet(db, args.get("outlet")) if args.get("outlet") else None
    j = _find_journalist(db, args.get("journalist"), o.id if o else None)
    if not j:
        return {"error": "journaliste introuvable"}
    outlet = db.get(Outlet, j.outlet_id)
    prof = db.query(JournalistProfile).filter(JournalistProfile.journalist_id == j.id).order_by(JournalistProfile.date.desc()).first()
    arts = db.query(Article).filter(Article.journalist_id == j.id).order_by(Article.published_at.desc()).limit(15).all()
    onames, jnames = _names(db)
    from . import contacts as C
    d = {"id": j.id, "name": j.name, "outlet": outlet.name if outlet else None, "outlet_id": j.outlet_id, "role": j.role, "bio": j.bio,
         "accessibility": _f(j.accessibility_score, 0),
         "contacts": [{k: c[k] for k in ("kind", "label", "value", "confidence", "method", "source_url")} for c in C.list_for(db, j.id)],
         "contacts_note": "confidence: verified = lien attaché à la signature ou page auteur ; probable = texte d'article ou recherche publique ; guess = motif d'adresse du média, à vérifier avant usage",
         "profile": {"date": prof.date.isoformat(), "themes": prof.themes, "biases": prof.biases, "preferred_sources": prof.preferred_sources, "tone": prof.tone,
                     "productivity": prof.productivity, "vulnerabilities": prof.vulnerabilities, "summary": prof.raw_summary} if prof else None,
         "recent_articles": [_article_row(a, onames, jnames) for a in arts]}
    # cadrage mesuré du journaliste vs média
    vecs = [(a.extracted_data or {}).get("framing") for a in db.query(Article).filter(Article.journalist_id == j.id, Article.analysis_status == "analyzed").limit(200).all()]
    vecs = [v for v in vecs if v]
    if vecs:
        outlet = db.get(Outlet, j.outlet_id)
        axes = _axes_of(outlet, db)
        meas = {a: _f(sum(float(v.get(a, 0) or 0) for v in vecs if v.get(a)) / max(1, sum(1 for v in vecs if v.get(a)))) for a in axes}
        d["measured_framing"] = meas
        p = _latest_profiles(db, [j.outlet_id]).get(j.outlet_id)
        if p and p.real_classification:
            diffs = {a: _f(meas[a] - float(p.real_classification.get(a, 0) or 0)) for a in axes}
            d["gap_to_outlet"] = diffs
            a = max(diffs, key=lambda k: abs(diffs[k] or 0))
            poles = axis_poles_map().get(a, ("−", "+"))
            d["divergence_axis"] = {"axis": axis_labels().get(a, a), "delta": diffs[a], "direction": poles[1] if (diffs[a] or 0) > 0 else poles[0]}
        d["n_analyzed"] = len(vecs)
    return d


# ═══════════════════════════════════════════════════════════════ LECTURE — articles

@tool("search_articles", "Recherche sémantique dans les articles (par sens, pas seulement mots-clés), avec filtres média, journaliste, pays, période. Renvoie titre, média, date, thèmes, ton, cadrage, similarité.",
      {"query": {"type": "string"}, "outlet": {"type": "string"}, "journalist": {"type": "string"}, "country": {"type": "string"},
       "days": {"type": "integer", "description": "fenêtre en jours, défaut 60"}, "limit": {"type": "integer", "default": 20},
       "analyzed_only": {"type": "boolean", "default": True}}, required=["query"])
def search_articles(db, args, ctx):
    vec = embeddings.embed_text(args["query"])
    q = db.query(Article).filter(Article.embedding.isnot(None))
    if args.get("analyzed_only", True):
        q = q.filter(Article.analysis_status == "analyzed")
    o = _find_outlet(db, args.get("outlet")) if args.get("outlet") else None
    if o:
        q = q.filter(Article.outlet_id == o.id)
    j = _find_journalist(db, args.get("journalist")) if args.get("journalist") else None
    if j:
        q = q.filter(Article.journalist_id == j.id)
    if args.get("country"):
        ids = [x.id for x in db.query(Outlet.id).filter(Outlet.country == args["country"].upper()).all()]
        q = q.filter(Article.outlet_id.in_(ids or [0]))
    days = int(args.get("days") or 60)
    q = q.filter(Article.published_at >= datetime.utcnow() - timedelta(days=days))
    dist = Article.embedding.cosine_distance(vec)
    rows = q.add_columns(dist.label("dist")).order_by(dist).limit(int(args.get("limit") or 20)).all()
    onames, jnames = _names(db)
    return {"articles": [{**_article_row(a, onames, jnames), "similarity": _f(1 - d, 3)} for a, d in rows]}


@tool("list_articles", "Derniers articles avec filtres exacts (média, journaliste, statut, période, mot dans le titre). Pour la recherche par sens, préférer search_articles.",
      {"outlet": {"type": "string"}, "journalist": {"type": "string"}, "status": {"type": "string", "enum": ["analyzed", "embedded_only", "duplicate", "pending", "error"]},
       "days": {"type": "integer"}, "title_contains": {"type": "string"}, "limit": {"type": "integer", "default": 30}})
def list_articles(db, args, ctx):
    q = db.query(Article)
    o = _find_outlet(db, args.get("outlet")) if args.get("outlet") else None
    if o:
        q = q.filter(Article.outlet_id == o.id)
    j = _find_journalist(db, args.get("journalist")) if args.get("journalist") else None
    if j:
        q = q.filter(Article.journalist_id == j.id)
    if args.get("status"):
        q = q.filter(Article.analysis_status == args["status"])
    if args.get("days"):
        q = q.filter(Article.published_at >= datetime.utcnow() - timedelta(days=int(args["days"])))
    if args.get("title_contains"):
        q = q.filter(Article.title.ilike(f"%{args['title_contains']}%"))
    rows = q.order_by(Article.published_at.desc()).limit(int(args.get("limit") or 30)).all()
    onames, jnames = _names(db)
    return {"articles": [_article_row(a, onames, jnames) for a in rows]}


@tool("get_article", "Texte intégral (tronqué à 6 000 caractères) et analyse complète d'un article : thèmes, cadrage par axe, sources citées, entités, ton, angle.",
      {"id": {"type": "integer"}}, required=["id"])
def get_article(db, args, ctx):
    a = db.get(Article, int(args["id"]))
    if not a:
        return {"error": "article introuvable"}
    onames, jnames = _names(db)
    return _article_row(a, onames, jnames, with_text=True)


# ═══════════════════════════════════════════════════════════════ LECTURE — paysage / cartographie

@tool("landscape", "Positions mesurées et déclarées des médias documentés sur les 12 axes, moyenne du paysage, blocs éditoriaux, journalistes dissidents. Filtre pays optionnel (code ISO-2).",
      {"weeks": {"type": "integer", "default": 8}, "country": {"type": "string", "description": "Code ISO-2 (FR, DE, GB…) pour limiter aux médias de ce pays"}})
def landscape(db, args, ctx):
    code = (args.get("country") or "").strip().upper() or None
    data = cartography.landscape(db, int(args.get("weeks") or 8), country=code)
    outs = data["outlets"]
    axes = [a["axis"] for a in (data.get("axes") or [])] or list(STRUCTURAL_IDS)
    ids = {o["id"] for o in outs}
    mean = {a: _f(sum(o["real"].get(a, 0) for o in outs) / max(1, len(outs))) for a in axes}
    spread = sorted(axes, key=lambda a: -(max((o["real"].get(a, 0) for o in outs), default=0) - min((o["real"].get(a, 0) for o in outs), default=0)))
    clusters = []
    for c in data.get("clusters") or []:
        members = [m for m in (c.get("members") or []) if m in ids]
        if members:
            clusters.append({**c, "members": members, "size": len(members)})
    js = data.get("journalists") or []
    labels = axis_labels()
    return {"since": data["since"], "country": code, "landscape_mean": mean, "most_dividing_axes": [labels.get(a, a) for a in spread[:4]],
            "outlets": [{"id": o["id"], "name": o["name"], "country": o.get("country"), "influence": o.get("influence"), "confidence": o.get("confidence"), "n_articles": o.get("n_articles"),
                         "measured": {a: _f(o["real"].get(a, 0)) for a in axes}, "declared": {a: _f(o["official"].get(a, 0)) for a in axes}} for o in outs],
            "clusters": clusters,
            "dissidents": [{"id": j["id"], "name": j["name"], "outlet_id": j["outlet_id"], "deviation": j["deviation"]} for j in sorted(js, key=lambda j: -j["deviation"])[:10]]}


@tool("leadlag", "Qui donne le ton : pour chaque sujet repris par plusieurs médias sous 72 h, qui publie en premier (mène) et qui suit ; ratio, retard médian, paires meneur → suiveur.",
      {"days": {"type": "integer", "default": 30}})
def leadlag(db, args, ctx):
    d = cartography.leadlag(db, int(args.get("days") or 30))
    return {"since": d["since"], "events": d["events"], "ranking": d["ranking"][:20], "pairs": d["pairs"][:20]}


@tool("network", "Réseau d'influence : citations entre médias, PageRank, communautés (Louvain), co-couverture.", {"days": {"type": "integer", "default": 90}})
def network(db, args, ctx):
    d = cartography.network(db, int(args.get("days") or 90))
    nodes = sorted([n for n in d["nodes"] if n.get("kind") == "outlet"], key=lambda n: -(n.get("pagerank") or 0))
    names = {n["id"]: n["name"] for n in d["nodes"]}
    onames, _ = _names(db)
    comms = [{**c, "members": [onames.get(m) for m in c.get("members", [])]} for c in d["communities"]]
    return {"stats": d["stats"], "communities": comms,
            "top_pagerank": [{"name": n["name"], "pagerank": n.get("pagerank"), "in_citations": n.get("in_citations"), "out_citations": n.get("out_citations"), "community": n.get("community")} for n in nodes[:20]],
            "top_citations": [{"from": names.get(e["source"]), "to": names.get(e["target"]), "n": e["weight"]} for e in sorted([e for e in d["edges"] if e.get("type") == "citation"], key=lambda e: -(e.get("weight") or 0))[:30]]}


@tool("entities", "Personnes et organisations les plus citées, valence (ton) par média, entités clivantes. Filtre optionnel par nom et par pays.",
      {"days": {"type": "integer", "default": 60}, "name": {"type": "string"}, "limit": {"type": "integer", "default": 25}, "country": {"type": "string", "description": "Code ISO-2"}})
def entities(db, args, ctx):
    code = (args.get("country") or "").strip().upper() or None
    d = cartography.entities(db, int(args.get("days") or 60), 80, code)
    ents = d["entities"]
    if args.get("name"):
        ents = [e for e in ents if args["name"].lower() in e["entity"].lower()]
    return {"since": d["since"], "entities": ents[: int(args.get("limit") or 25)]}


@tool("topics", "Sujets du corpus regroupés sémantiquement : une affaire = un cluster, même si les libellés diffèrent. Volume, médias, journalistes, chaleur vs période précédente, angles morts (un seul média). Filtres pays, média, journaliste.",
      {"days": {"type": "integer", "default": 7}, "country": {"type": "string", "description": "Code ISO-2"},
       "outlet_id": {"type": "integer"}, "journalist_id": {"type": "integer"}})
def topics(db, args, ctx):
    from . import topics as topics_svc
    d = topics_svc.agenda(
        db, days=int(args.get("days") or 7), country=args.get("country"),
        outlet_id=args.get("outlet_id"), journalist_id=args.get("journalist_id"),
        briefs=True,
    )
    clusters = []
    for c in d.get("clusters") or []:
        clusters.append({
            "topic": c["label"], "aliases": c.get("aliases") or [],
            "articles": c["articles"], "outlets": c["outlets"], "journalists": c["journalists"],
            "heat": c["heat"], "heat_ratio": c["heat_ratio"], "polarization": c["polarization"],
            "spread": c.get("spread"), "lead": c.get("lead"), "brief": c.get("brief") or "",
            "outlets_detail": [{"name": o["name"], "n": o["n"]} for o in (c.get("outlets_detail") or [])[:8]],
            "journalists_detail": [{"name": j["name"], "outlet": j.get("outlet"), "n": j["n"]} for j in (c.get("journalists_detail") or [])[:8]],
        })
    blind = [c for c in clusters if c["outlets"] == 1 and c["articles"] >= 3][:15]
    return {
        "days": d["days"], "since": d["since"], "n_articles": d["n_articles"],
        "n_clusters": len(clusters), "n_themes": d.get("n_themes") or 0,
        "n_singletons": d.get("n_singletons") or 0,
        "themes": [{"topic": t["label"], "aliases": t.get("aliases") or [], "articles": t["articles"], "stories": t["stories"], "brief": t.get("brief") or ""} for t in (d.get("themes") or [])[:20]],
        "topics": clusters[:40], "blind_spots": [{"topic": b["topic"], "articles": b["articles"], "outlet": (b["outlets_detail"] or [{}])[0].get("name")} for b in blind],
    }


@tool("packs", "Meutes et proximité : paires de médias qui traitent les mêmes sujets (similarité de thèmes) et s'ils les cadrent pareil (similarité de cadrage).", {"days": {"type": "integer", "default": 60}})
def packs(db, args, ctx):
    d = cartography.packs(db, int(args.get("days") or 60))
    return {"pairs": d.get("pairs", [])[:30]}


@tool("world", "Vue par pays : nombre de médias, influence cumulée, articles, journalistes, langues ; flux de citations transfrontaliers.", {"days": {"type": "integer", "default": 30}})
def world(db, args, ctx):
    d = cartography.world(db, int(args.get("days") or 30))
    return {"countries": d["countries"], "flows": d["flows"][:30], "regions": d["regions"]}


@tool("dashboard", "Synthèse du jour : chiffres clés, mouvements de la semaine, écarts les plus forts, sujets, meneurs, dissidents, entités clivantes, état de la collecte et coûts.", {})
def dashboard(db, args, ctx):
    from . import dashboard as dash
    d = dash.build(db)
    d.pop("accessible", None)
    d["pipeline"].pop("daily", None)
    d["clients"].pop("list", None)
    for e in d.get("divisive", []):
        e.pop("cells", None)
    for k in ("gaps", "topics", "leaders", "dissidents", "divisive", "blind_spots"):
        if isinstance(d.get(k), list):
            d[k] = d[k][:6]
    return d


# ═══════════════════════════════════════════════════════════════ LECTURE — clients

@tool("list_clients", "Dossiers clients : secteur, exposition, tolérance au risque, narratifs à pousser / à contrer, nombre de recommandations.", {})
def list_clients(db, args, ctx):
    recs = dict(db.query(Recommendation.client_id, func.count()).group_by(Recommendation.client_id).all())
    return {"clients": [{**row_to_dict(c), "recommendations": recs.get(c.id, 0)} for c in db.query(Client).all()]}


@tool("get_client", "Dossier complet d'un client : narratifs, position de chaque média vis-à-vis du client (hostile/neutre/favorable × influence), recommandations avec plans, historique des actions et résultats, contacts, liste noire.",
      {"client": {"type": "string", "description": "id ou nom"}}, required=["client"])
def get_client(db, args, ctx):
    c = _find_client(db, args.get("client"))
    if not c:
        return {"error": "client introuvable"}
    from .. import main as _m  # réutilise le calcul de la carte stratégique
    stance = _m.strategic_map(c.id, db)
    onames, jnames = _names(db)
    recs = db.query(Recommendation).filter(Recommendation.client_id == c.id).order_by(Recommendation.priority.desc()).all()
    hist = db.query(ActionHistory).filter(ActionHistory.client_id == c.id).order_by(ActionHistory.completed_at.desc()).limit(30).all()
    return {**row_to_dict(c),
            "stance_map": sorted(stance, key=lambda p: -p["influence"]),
            "recommendations": [{"id": r.id, "outlet": onames.get(r.outlet_id), "journalist": jnames.get(r.journalist_id), "action": r.action_type, "variant": r.variant, "priority": _f(r.priority),
                                 "status": r.status, "risk": r.risk_level, "budget": r.budget_level, "justification": r.justification, "plan": r.plan, "created_at": r.created_at.isoformat()} for r in recs],
            "history": [{**row_to_dict(h), "outlet": onames.get(h.outlet_id)} for h in hist],
            "contacts": [{"journalist": jnames.get(x.journalist_id), "quality": x.quality, "notes": x.notes} for x in db.query(ClientContact).filter(ClientContact.client_id == c.id).all()],
            "blacklist": [{"outlet": onames.get(b.outlet_id), "reason": b.reason} for b in db.query(ClientBlacklist).filter(ClientBlacklist.client_id == c.id).all()]}


# ═══════════════════════════════════════════════════════════════ LECTURE — réglages, SQL, web

@tool("get_settings", "Réglages du moteur : seuils (dérive, écart exploitable, pitch, position), pondérations d'influence, modèles LLM, plafond de coût, intervalles.", {})
def get_settings_tool(db, args, ctx):
    return get_settings(db)


SCHEMA_DOC = """Tables (PostgreSQL, lecture seule) :
outlets(id, name, country, language, website_url, rss_url, declared_orientation, official_classification json{axe:-1..1}, influence_score, influence_rank, meta json)
outlet_feeds(id, outlet_id, url, label, feed_type, enabled)
journalists(id, name, outlet_id, role, twitter_handle, linkedin_url, bio, beat, accessibility_score)
articles(id, outlet_id, journalist_id, url, title, text, language, published_at, extracted_data json{topics:[{label,framing}], framing{axe}, tone, angle, sources, entities}, analysis_status analyzed|embedded_only|duplicate|pending|error, captured_at)
article_journalists(article_id, journalist_id, position)
journalist_profiles(id, journalist_id, date, themes json, biases json, preferred_sources json, tone, productivity, vulnerabilities json, accessibility_score, raw_summary)
outlet_profiles(id, outlet_id, week, real_classification json, gap_from_official json, drift_alerts json, component_scores json, article_count, axis_n json)
clients(id, name, sector, type, exposure, risk_tolerance, budget_level, objectives, narratives_push json, narratives_counter json, sensitive_topics json)
recommendations(id, client_id, outlet_id, journalist_id, action_type, variant, priority, status, plan json, risk_level, budget_level, justification json, created_at)
action_history(id, recommendation_id, client_id, outlet_id, action_type, outcome success|partial|failure, lessons_learned, completed_at)
citations(id, source_outlet_id, target_outlet_id, article_id, match_type, timestamp)
ingestion_logs(id, outlet_id, feed_type, status ok|error, articles_captured, error_message, timestamp)
llm_usage(id, date, model, purpose, prompt_tokens, completion_tokens, cost_usd)
Axes : economy, society, immigration, europe, ecology, security, secularism, international, institutions, media, justice, technology.
Accès JSON : extracted_data->'framing'->>'economy', (x->>'k')::float."""


@tool("sql_query", "Requête SQL SELECT en lecture seule sur la base Tacite, pour les questions que les autres outils ne couvrent pas (agrégats, croisements). LIMIT 200 imposé, 8 s max. Schéma : " + SCHEMA_DOC,
      {"sql": {"type": "string"}, "purpose": {"type": "string", "description": "ce que la requête cherche, en une phrase"}}, required=["sql"])
def sql_query(db, args, ctx):
    sql = (args.get("sql") or "").strip().rstrip(";")
    if not re.match(r"^\s*(select|with)\b", sql, re.I):
        return {"error": "seules les requêtes SELECT sont autorisées"}
    if re.search(r"\b(insert|update|delete|drop|alter|create|truncate|grant|copy|into|pg_sleep|pg_catalog|information_schema|set_config|current_setting|auth_sessions|users)\b", sql, re.I):
        return {"error": "requête refusée"}
    if ";" in sql:
        return {"error": "requête refusée"}
    if re.search(r"\bsettings\b", sql, re.I):
        return {"error": "la table settings n'est pas interrogeable"}
    if not re.search(r"\blimit\s+\d+", sql, re.I):
        sql += " LIMIT 200"
    from ..database import engine
    from ..tenant import read_only_tx
    try:
        with read_only_tx(), engine.connect() as conn:
            conn.execute(text("SET LOCAL statement_timeout = 8000"))
            res = conn.execute(text(sql))
            cols = list(res.keys())
            rows = [dict(zip(cols, [(_json_safe(v)) for v in r])) for r in res.fetchmany(200)]
            conn.rollback()
        return {"columns": cols, "rows": rows, "count": len(rows)}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:500]}


def _json_safe(v):
    if isinstance(v, (datetime,)):
        return v.isoformat()
    if hasattr(v, "isoformat"):
        return v.isoformat()
    if isinstance(v, (bytes, memoryview)):
        return None
    try:
        json.dumps(v)
        return v
    except TypeError:
        return str(v)


@tool("google_news", "Recherche Google News (gratuit) : titres récents sur un sujet, tous médias, avec source et date. Pour l'actualité hors base.",
      {"query": {"type": "string"}, "lang": {"type": "string", "default": "fr"}, "country": {"type": "string", "default": "FR"}, "limit": {"type": "integer", "default": 15}}, required=["query"])
def google_news(db, args, ctx):
    import feedparser, httpx
    from urllib.parse import quote
    lang, ctry = (args.get("lang") or "fr"), (args.get("country") or "FR").upper()
    url = f"https://news.google.com/rss/search?q={quote(args['query'])}&hl={lang}&gl={ctry}&ceid={ctry}:{lang}"
    try:
        with httpx.Client(headers=extract.HEADERS, follow_redirects=True, timeout=15) as c:
            r = c.get(url)
        feed = feedparser.parse(r.content)
        items = []
        for e in feed.entries[: int(args.get("limit") or 15)]:
            items.append({"title": re.sub(r"\s+-\s+[^-]+$", "", e.get("title", "")), "source": (e.get("source") or {}).get("title"), "published": e.get("published"), "google_link": e.get("link")})
        return {"results": items, "note": "Les liens Google News ne sont pas lisibles directement : utiliser fetch_url sur le site source."}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:300]}


@tool("gdelt", "Recherche GDELT (base mondiale d'articles, gratuit) : articles récents par mots-clés, tous pays et langues, avec URL réelle.",
      {"query": {"type": "string"}, "days": {"type": "integer", "default": 7}, "limit": {"type": "integer", "default": 20}}, required=["query"])
def gdelt(db, args, ctx):
    import httpx
    from urllib.parse import quote
    url = f"https://api.gdeltproject.org/api/v2/doc/doc?query={quote(args['query'])}&mode=artlist&maxrecords={int(args.get('limit') or 20)}&format=json&timespan={int(args.get('days') or 7)}d&sort=datedesc"
    try:
        with httpx.Client(headers=extract.HEADERS, timeout=20) as c:
            r = c.get(url)
        data = r.json() if r.status_code == 200 else {}
        return {"results": [{"title": a.get("title"), "url": a.get("url"), "domain": a.get("domain"), "language": a.get("language"), "country": a.get("sourcecountry"), "date": a.get("seendate")} for a in data.get("articles", [])]}
    except Exception as e:  # noqa: BLE001
        return {"error": str(e)[:300]}


@tool("fetch_url", "Lit une page web et renvoie son texte nettoyé (bandeaux cookies retirés), tronqué à 8 000 caractères.", {"url": {"type": "string"}}, required=["url"])
def fetch_url(db, args, ctx):
    html, txt, final = extract.fetch_article(args["url"])
    if not txt:
        return {"error": "page illisible ou vide", "url": final}
    title = None
    if html:
        m = re.search(r"<title[^>]*>(.*?)</title>", html, re.I | re.S)
        title = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    return {"url": final, "title": title, "text": txt[:8000], "length": len(txt)}


# ═══════════════════════════════════════════════════════════════ OUTILS COMPOSÉS (métier)

def _topic_articles(db: Session, query: str, days: int, limit: int, country: str | None = None):
    vec = embeddings.embed_text(query)
    q = db.query(Article).filter(Article.embedding.isnot(None), Article.analysis_status == "analyzed", Article.published_at >= datetime.utcnow() - timedelta(days=days))
    if country:
        ids = [x.id for x in db.query(Outlet.id).filter(Outlet.country == country.upper()).all()]
        q = q.filter(Article.outlet_id.in_(ids or [0]))
    dist = Article.embedding.cosine_distance(vec)
    rows = q.add_columns(dist.label("dist")).order_by(dist).limit(limit).all()
    # on ne garde que ce qui ressemble vraiment au sujet (similarité cosinus ≥ 0,35), avec un plancher de 8 articles
    keep = [(a, 1 - d) for a, d in rows if (1 - d) >= 0.35] or [(a, 1 - d) for a, d in rows[:8]]
    return keep


def _relevant_axes(arts: list[Article], k: int = 3) -> list[str]:
    """Axes les plus mobilisés par ces articles (moyenne des valeurs absolues)."""
    tot = {a: 0.0 for a in AXES}
    n = 0
    for a in arts:
        fr = (a.extracted_data or {}).get("framing") or {}
        if fr:
            n += 1
            for ax in AXES:
                tot[ax] += abs(float(fr.get(ax, 0) or 0))
    return sorted(AXES, key=lambda ax: -tot[ax])[:k] if n else []


@tool("who_covers", "QUI TRAITE UN SUJET — l'outil à utiliser pour « qui contacter / qui écrit sur X / quel journaliste approcher ». Articles proches du sujet → signataires agrégés : nombre d'articles, cadrage moyen sur les axes mobilisés, ton dominant, accessibilité, fixations, dernier article (lien), média et position du média, canaux de contact connus. Trié par pertinence × accessibilité. Renvoie aussi la couverture par média et les articles non signés.",
      {"topic": {"type": "string"}, "days": {"type": "integer", "default": 60}, "country": {"type": "string"}, "limit_articles": {"type": "integer", "default": 60}}, required=["topic"])
def who_covers(db, args, ctx):
    days = int(args.get("days") or 60)
    pairs = _topic_articles(db, args["topic"], days, int(args.get("limit_articles") or 60), args.get("country"))
    arts = [a for a, _ in pairs]
    sim = {a.id: s for a, s in pairs}
    onames, jnames = _names(db)
    axes = _relevant_axes(arts)
    by_j: dict[int, list[Article]] = {}
    unsigned: dict[int, int] = {}
    by_o: dict[int, list[Article]] = {}
    for a in arts:
        by_o.setdefault(a.outlet_id, []).append(a)
        if a.journalist_id:
            by_j.setdefault(a.journalist_id, []).append(a)
        else:
            unsigned[a.outlet_id] = unsigned.get(a.outlet_id, 0) + 1
    from . import contacts as C
    js = {j.id: j for j in db.query(Journalist).filter(Journalist.id.in_(list(by_j) or [0])).all()}
    profs = {p.journalist_id: p for p in db.query(JournalistProfile).filter(JournalistProfile.journalist_id.in_(list(by_j) or [0])).order_by(JournalistProfile.date.asc()).all()}
    oprofs = _latest_profiles(db, list(by_o))
    cs = C.summary_for_many(db, list(by_j))
    contacts_full = {jid: [c for c in C.list_for(db, jid) if c["kind"] in ("email", "x", "bluesky", "mastodon", "linkedin", "author_page")][:5] for jid in by_j}
    from collections import Counter
    people = []
    for jid, lst in by_j.items():
        j = js.get(jid)
        if not j:
            continue
        frs = [(a.extracted_data or {}).get("framing") or {} for a in lst]
        framing = {ax: _f(sum(float(f.get(ax, 0) or 0) for f in frs if f.get(ax)) / max(1, sum(1 for f in frs if f.get(ax)))) for ax in axes}
        tones = Counter((a.extracted_data or {}).get("tone") for a in lst if (a.extracted_data or {}).get("tone"))
        last = max(lst, key=lambda a: a.published_at or datetime.min)
        p = profs.get(jid)
        m = re.match(r"^\[([^\]]*)\]", j.bio or "")
        rel = sum(sim[a.id] for a in lst) / len(lst)
        people.append({
            "id": jid, "name": j.name, "outlet": onames.get(j.outlet_id), "outlet_id": j.outlet_id, "role": j.role, "beat": m.group(1) if m else None,
            "articles_on_topic": len(lst), "relevance": _f(rel, 2), "accessibility": _f(j.accessibility_score, 0),
            "framing_on_topic": {axis_labels()[ax]: v for ax, v in framing.items()}, "dominant_tone": tones.most_common(1)[0][0] if tones else None,
            "themes": [t.get("label") for t in (p.themes or [])][:5] if p else None, "preferred_sources": [s.get("type") for s in (p.preferred_sources or [])][:4] if p else None,
            "vulnerabilities": [v.get("label") for v in (p.vulnerabilities or [])][:3] if p else None,
            "last_article": {"id": last.id, "title": last.title, "date": last.published_at.isoformat()[:10] if last.published_at else None, "link": f"/articles/{last.id}"},
            "contacts": contacts_full.get(jid) or [], "score": _f((rel ** 2) * (0.6 + (j.accessibility_score or 50) / 200) * (1 + 0.12 * min(len(lst), 5)), 3),
        })
    people.sort(key=lambda p: -(p["score"] or 0))
    outlets = []
    for oid, lst in by_o.items():
        frs = [(a.extracted_data or {}).get("framing") or {} for a in lst]
        framing = {axis_labels()[ax]: _f(sum(float(f.get(ax, 0) or 0) for f in frs if f.get(ax)) / max(1, sum(1 for f in frs if f.get(ax)))) for ax in axes}
        op = oprofs.get(oid)
        outlets.append({"outlet_id": oid, "outlet": onames.get(oid), "articles": len(lst), "signed": len(lst) - unsigned.get(oid, 0), "unsigned": unsigned.get(oid, 0),
                        "framing_on_topic": framing, "line_measured": {axis_labels()[ax]: _f((op.real_classification or {}).get(ax, 0)) for ax in axes} if op else None,
                        "link": f"/outlets/{oid}"})
    outlets.sort(key=lambda o: -o["articles"])
    poles = {axis_labels()[ax]: f"{axis_poles_map()[ax][0]} (−) ↔ {axis_poles_map()[ax][1]} (+)" for ax in axes}
    gaps = []
    if not people:
        gaps.append("aucun article proche du sujet n'est signé : impossible de nommer un journaliste ; proposer d'extraire les signatures (run_task) ou de regarder les médias couvreurs")
    if sum(unsigned.values()) > 0:
        gaps.append(f"{sum(unsigned.values())} articles non signés (signature absente du flux)")
    no_contact = [p["name"] for p in people[:5] if not p["contacts"]]
    if no_contact:
        gaps.append(f"pas de canal de contact connu pour : {', '.join(no_contact)} — proposer de lancer la détection des contacts (run_task contacts)")
    return {"topic": args["topic"], "days": days, "articles_found": len(arts), "axes_mobilised": poles, "journalists": people[:15], "outlets": outlets[:12],
            "articles_sample": [{"id": a.id, "title": a.title, "outlet": onames.get(a.outlet_id), "journalist": jnames.get(a.journalist_id), "date": a.published_at.isoformat()[:10] if a.published_at else None, "link": f"/articles/{a.id}"} for a in arts[:10]],
            "data_gaps": gaps,
            "next_step": "Pour recommander une approche, appeler approach_angle(journalist, topic) sur les 2 ou 3 premiers : l'angle doit sortir de leurs sources, biais et articles, pas d'un conseil général. Classement = pertinence² × accessibilité × volume ; regarder aussi 'relevance' et le titre du dernier article."}


@tool("topic_brief", "COMMENT UN SUJET EST TRAITÉ (INTELLIGENCE PRESSE & CLIENT) — paysage et poids d'influence, couverture par média (volume, influence, cadrage sur les axes mobilisés, ton, écart avec la ligne habituelle et déclarée, articles clés), anomalies éditoriales, menaces/risques et exposition des dossiers clients, qui a publié en premier, entités clivantes, grands médias influents silencieux, et Top journalistes à contacter (influence_targets : action, accès, contacts). Cette liste est due même sans dossier client. Sans signature, elle prend les fiches des rédactions qui portent la ligne (targets_basis=newsroom).",
      {"topic": {"type": "string"}, "days": {"type": "integer", "default": 30}, "country": {"type": "string"}, "client": {"type": "string"}}, required=["topic"])
def topic_brief(db, args, ctx):
    days = int(args.get("days") or 30)
    pairs = _topic_articles(db, args["topic"], days, 120, args.get("country"))
    arts = sorted([a for a, _ in pairs], key=lambda a: a.published_at or datetime.min)
    sim_by_id = {a.id: s for a, s in pairs}
    onames, jnames = _names(db)
    all_outlets = {o.id: o for o in db.query(Outlet).all()}
    axes = _relevant_axes(arts)
    labels_map = axis_labels()
    poles_map = axis_poles_map()
    from collections import Counter
    import numpy as np
    from . import contacts as C, topics as topics_svc

    by_o: dict[int, list[Article]] = {}
    by_j: dict[int, list[Article]] = {}
    for a in arts:
        by_o.setdefault(a.outlet_id, []).append(a)
        if a.journalist_id:
            by_j.setdefault(a.journalist_id, []).append(a)
    oprofs = _latest_profiles(db, list(by_o))
    cov = []
    anomalies = []
    for oid, lst in by_o.items():
        o = all_outlets.get(oid)
        infl = round(float(o.influence_score or 0), 1) if o else 0.0
        frs = [(a.extracted_data or {}).get("framing") or {} for a in lst]
        fr = {ax: _f(sum(float(f.get(ax, 0) or 0) for f in frs if f.get(ax)) / max(1, sum(1 for f in frs if f.get(ax)))) for ax in axes}
        op = oprofs.get(oid)
        line = {ax: float((op.real_classification or {}).get(ax, 0) or 0) for ax in axes} if op else {}
        decl = {ax: float(((o.official_classification if o else None) or {}).get(ax, 0) or 0) for ax in axes}
        vs_own = {labels_map[ax]: _f((fr[ax] or 0) - line[ax]) for ax in axes} if line else None
        vs_decl = {labels_map[ax]: _f((fr[ax] or 0) - decl[ax]) for ax in axes} if o and o.official_classification else None

        for ax in axes:
            val_topic = float(fr.get(ax) or 0)
            if abs(val_topic) < 0.12:
                continue
            neg_pole, pos_pole = poles_map.get(ax, ("−", "+"))
            if line and ax in line:
                delta_own = val_topic - line[ax]
                if abs(delta_own) >= 0.22:
                    pole = pos_pole if delta_own > 0 else neg_pole
                    anomalies.append({
                        "outlet": onames.get(oid), "outlet_id": oid, "country": o.country if o else None, "influence": infl,
                        "kind": "écart à sa ligne mesurée habituelle",
                        "axis": labels_map[ax], "topic_score": _f(val_topic), "usual_line": _f(line[ax]),
                        "delta": _f(delta_own), "direction": f"plus « {pole} » que d'habitude ({delta_own:+.2f})",
                    })
            elif o and o.official_classification and ax in decl:
                delta_decl = val_topic - decl[ax]
                if abs(delta_decl) >= 0.30:
                    pole = pos_pole if delta_decl > 0 else neg_pole
                    anomalies.append({
                        "outlet": onames.get(oid), "outlet_id": oid, "country": o.country if o else None, "influence": infl,
                        "kind": "écart à sa ligne déclarée",
                        "axis": labels_map[ax], "topic_score": _f(val_topic), "declared_line": _f(decl[ax]),
                        "delta": _f(delta_decl), "direction": f"plus « {pole} » que déclaré ({delta_decl:+.2f})",
                    })

        tones = Counter((a.extracted_data or {}).get("tone") for a in lst if (a.extracted_data or {}).get("tone"))
        angles = Counter((a.extracted_data or {}).get("angle") for a in lst if (a.extracted_data or {}).get("angle"))
        first = min(lst, key=lambda a: a.published_at or datetime.max)
        key_arts = sorted(lst, key=lambda a: (sim_by_id.get(a.id, 0), a.published_at or datetime.min), reverse=True)[:2]
        cov.append({
            "outlet_id": oid, "outlet": onames.get(oid), "country": o.country if o else None,
            "influence": infl, "declared_orientation": o.declared_orientation if o else None,
            "articles": len(lst), "first_article": first.published_at.isoformat()[:16] if first.published_at else None,
            "framing": {labels_map[ax]: v for ax, v in fr.items()},
            "vs_own_line": vs_own, "vs_declared_line": vs_decl,
            "tones": [t for t, _ in tones.most_common(2)],
            "angles": [t for t, _ in angles.most_common(2)],
            "signatories": sorted({jnames.get(a.journalist_id) for a in lst if a.journalist_id} - {None})[:6],
            "key_articles": [
                {"id": a.id, "title": a.title, "date": a.published_at.isoformat()[:10] if a.published_at else None, "link": f"/articles/{a.id}"}
                for a in key_arts
            ],
            "link": f"/outlets/{oid}",
        })
    cov.sort(key=lambda c: (-c["articles"], -c["influence"]))
    anomalies.sort(key=lambda a: (-abs(a.get("delta") or 0), -a.get("influence", 0)))

    # Entités filtrées des bruits (AFP, Google, noms de médias)
    ents: Counter = Counter()
    val: dict[str, list[float]] = {}
    from ..constants import TONE_VALENCE
    for a in arts:
        d = a.extracted_data or {}
        v = TONE_VALENCE.get((d.get("tone") or "").lower(), 0.0)
        for bucket in ("people", "organizations"):
            for e in (d.get("entities") or {}).get(bucket, []) or []:
                name = (e or "").strip()
                if not name or topics_svc._is_noise_entity(name):
                    continue
                ents[name] += 1
                val.setdefault(name, []).append(v)
    entities = [{"entity": e, "mentions": n, "article_tone_valence": _f(sum(val[e]) / len(val[e]))} for e, n in ents.most_common(12)]

    # Top journalistes actionnables sur ce sujet (qui contacter pour influer)
    js = {j.id: j for j in db.query(Journalist).filter(Journalist.id.in_(list(by_j) or [0])).all()}
    jprofs = {p.journalist_id: p for p in db.query(JournalistProfile).filter(JournalistProfile.journalist_id.in_(list(by_j) or [0])).order_by(JournalistProfile.date.asc()).all()}
    contacts_full = {jid: [c for c in C.list_for(db, jid) if c["kind"] in ("email", "x", "bluesky", "mastodon", "linkedin", "author_page")][:3] for jid in by_j}
    influence_targets = []
    for jid, lst in by_j.items():
        j = js.get(jid)
        if not j:
            continue
        o = all_outlets.get(j.outlet_id)
        infl = float(o.influence_score or 50) if o else 50.0
        acc_raw = j.accessibility_score
        acc = float(acc_raw) if acc_raw is not None else 50.0
        rel = sum(sim_by_id.get(a.id, 0.5) for a in lst) / len(lst)
        p = jprofs.get(jid)
        last = max(lst, key=lambda a: a.published_at or datetime.min)
        pref_src = [f"{s.get('type')} (×{s.get('count')})" for s in sorted((p.preferred_sources if p else None) or [], key=lambda x: -(x.get("count") or 0))[:3]]
        vulns = [v.get("label") for v in ((p.vulnerabilities if p else None) or [])[:2] if v.get("label")]
        action = "NOURRIR" if acc >= 55 and infl >= 60 else "AMORCER" if acc >= 55 else "COOPTER" if infl >= 65 else "SURVEILLER"
        influence_targets.append({
            "journalist_id": jid, "name": j.name, "link": f"/journalists/{jid}",
            "outlet": onames.get(j.outlet_id), "outlet_id": j.outlet_id, "outlet_influence": round(infl, 1),
            "role": j.role, "accessibility": round(float(acc_raw)) if acc_raw is not None else None, "articles_on_topic": len(lst),
            "recommended_action": action,
            "preferred_sources": pref_src,
            "vulnerabilities": vulns,
            "last_article": {"id": last.id, "title": last.title, "date": last.published_at.isoformat()[:10] if last.published_at else None, "link": f"/articles/{last.id}"},
            "contacts": contacts_full.get(jid) or [],
            "_rank": (rel ** 2) * (0.5 + acc / 200) * (0.5 + infl / 200) * (1 + 0.15 * min(len(lst), 4)),
        })
    influence_targets.sort(key=lambda x: -x["_rank"])
    for t_row in influence_targets:
        t_row.pop("_rank", None)

    # Analyse des risques & impact sur les dossiers clients
    clients = db.query(Client).all()
    if args.get("client"):
        c_match = _find_client(db, args["client"])
        if c_match:
            clients = [c_match]
    topic_vec = np.mean([ np.asarray(a.embedding, dtype=float) for a in arts if a.embedding is not None ], axis=0) if arts else None
    if topic_vec is not None:
        tnorm = float(np.linalg.norm(topic_vec)) or 1.0
        topic_vec = topic_vec / tnorm
    client_impacts = []
    for cl in clients[:5]:
        sens_hits = []
        for s_topic in (cl.sensitive_topics or []):
            sv = embeddings.embed_text(s_topic)
            sim = float(np.dot(topic_vec, sv)) if topic_vec is not None else 0.0
            if sim >= 0.38 or s_topic.lower() in args["topic"].lower():
                sens_hits.append({"sensitive_topic": s_topic, "proximity": _f(sim)})
        counter_hits = []
        for cn in (cl.narratives_counter or []):
            cv = embeddings.embed_text(cn)
            sim = float(np.dot(topic_vec, cv)) if topic_vec is not None else 0.0
            if sim >= 0.36:
                counter_hits.append({"hostile_narrative": cn, "proximity": _f(sim)})
        push_hits = []
        for pn in (cl.narratives_push or []):
            pv = embeddings.embed_text(pn)
            sim = float(np.dot(topic_vec, pv)) if topic_vec is not None else 0.0
            if sim >= 0.36:
                push_hits.append({"opportunity_narrative": pn, "proximity": _f(sim)})
        if sens_hits or counter_hits or push_hits or len(clients) == 1:
            client_impacts.append({
                "client_id": cl.id, "client": cl.name, "sector": cl.sector, "risk_tolerance": cl.risk_tolerance,
                "sensitive_topics_triggered": sens_hits,
                "hostile_narratives_amplified": counter_hits,
                "push_narratives_opportunities": push_hits,
                "link": f"/clients/{cl.id}",
            })

    countries_cov = Counter(c["country"] for c in cov if c.get("country"))
    high_infl_cov = [c["outlet"] for c in cov if (c.get("influence") or 0) >= 70]
    inv_or_edito = sum(1 for a in arts if ((a.extracted_data or {}).get("angle") in ("investigation", "editorial", "opinion")))
    neg_tones = sum(1 for a in arts if ((a.extracted_data or {}).get("tone") in ("anger", "indignation", "fear", "alarm", "outrage")))
    risk_summary = {
        "escalation_level": "high" if (len(high_infl_cov) >= 3 and (inv_or_edito >= 4 or neg_tones >= len(arts) * 0.4)) else "medium" if len(cov) >= 4 else "low",
        "high_influence_outlets_active": high_infl_cov,
        "countries_reached": dict(countries_cov.most_common()),
        "investigative_or_editorial_articles": inv_or_edito,
        "negative_tone_articles": neg_tones,
        "client_impacts": client_impacts,
    }

    # Grands médias influents qui ne couvrent pas encore le sujet (triés par influence décroissante)
    country_filter = (args.get("country") or "").upper() or None
    not_cov_outlets = [
        o for oid, o in all_outlets.items()
        if oid not in by_o and (not country_filter or (o.country or "").upper() == country_filter)
    ]
    not_cov_outlets.sort(key=lambda o: -(float(o.influence_score or 0)))
    high_infl_silent = [
        {"outlet": o.name, "outlet_id": o.id, "country": o.country, "influence": round(float(o.influence_score or 0), 1), "link": f"/outlets/{o.id}"}
        for o in not_cov_outlets[:10]
    ]

    timeline = [{"date": a.published_at.isoformat()[:10] if a.published_at else None, "outlet": onames.get(a.outlet_id), "title": a.title, "link": f"/articles/{a.id}"} for a in arts[:6]] + \
               [{"date": a.published_at.isoformat()[:10] if a.published_at else None, "outlet": onames.get(a.outlet_id), "title": a.title, "link": f"/articles/{a.id}"} for a in arts[-4:]] if len(arts) > 10 else \
               [{"date": a.published_at.isoformat()[:10] if a.published_at else None, "outlet": onames.get(a.outlet_id), "title": a.title, "link": f"/articles/{a.id}"} for a in arts]
    leaders = [c["outlet"] for c in sorted(cov, key=lambda c: c["first_article"] or "9")[:3]]

    # ── Tradecraft (ICD 203) : diversité des sources, dépendance et niveau de confiance
    src_type_counts: Counter = Counter()
    named_src_counts: Counter = Counter()
    named_src_types: dict[str, str] = {}
    for a in arts:
        for s in ((a.extracted_data or {}).get("sources") or []):
            stype = (s.get("type") or "other").strip()
            sname = (s.get("name") or "").strip()
            src_type_counts[stype] += 1
            if sname and len(sname) >= 3:
                named_src_counts[sname] += 1
                named_src_types.setdefault(sname, stype)
    total_src_refs = sum(src_type_counts.values()) or 1
    top_src_type, top_src_type_n = src_type_counts.most_common(1)[0] if src_type_counts else ("none", 0)
    top_named = [{"name": k, "type": named_src_types.get(k), "mentions": v} for k, v in named_src_counts.most_common(6)]
    dep_warnings = []
    if total_src_refs >= 3 and (top_src_type_n / total_src_refs) >= 0.55:
        dep_warnings.append(f"Forte dépendance à un seul type de source : {top_src_type} ({round(100 * top_src_type_n / total_src_refs)} % des sources citées)")
    if top_named and top_named[0]["mentions"] >= max(3, int(len(arts) * 0.45)):
        dep_warnings.append(f"Source primaire dominante reprise à travers les articles : {top_named[0]['name']} ({top_named[0]['mentions']} mentions)")
    if len(arts) >= 15 and len(cov) >= 4 and len(src_type_counts) >= 3 and not dep_warnings:
        conf_level = "high"
    elif len(arts) >= 6 and len(cov) >= 2:
        conf_level = "moderate"
    else:
        conf_level = "low"
    tradecraft = {
        "confidence_level": conf_level,
        "distinct_source_types": len(src_type_counts),
        "source_types_distribution": dict(src_type_counts.most_common()),
        "primary_named_sources": top_named,
        "source_dependency_warnings": dep_warnings,
    }

    # ── NATO ABCDE : Originators, Amplifiers, Interpreters, Degree, Lifecycle
    interpreters = [c["outlet"] for c in cov if any(ang in ("editorial", "analysis", "investigation") for ang in (c.get("angles") or []))]
    lifecycle = (
        "mainstreaming" if len(high_infl_cov) >= 3 and len(countries_cov) >= 2
        else "expansion" if len(cov) >= 4
        else "emergence"
    )
    abcde = {
        "actors": {
            "originators": leaders,
            "high_reach_amplifiers": high_infl_cov[:5],
            "interpreters_and_reframing": interpreters[:5],
        },
        "degree": {
            "volume_articles": len(arts),
            "independent_outlets": len(cov),
            "countries_spread": len(countries_cov),
            "mean_outlet_influence": _f(sum(c["influence"] for c in cov) / max(1, len(cov)), 1),
            "lifecycle_stage": lifecycle,
        },
    }

    targets_basis = "byline" if influence_targets else "none"
    if not influence_targets:
        influence_targets = _newsroom_targets(db, cov, by_o, all_outlets, onames)
        targets_basis = "newsroom" if influence_targets else "none"
    return {
        "topic": args["topic"], "days": days, "articles": len(arts), "outlets_covering": len(cov),
        "targets_basis": targets_basis,
        "influence_targets": influence_targets[:12],
        "axes_mobilised": {labels_map[ax]: f"{poles_map[ax][0]} (−) ↔ {poles_map[ax][1]} (+)" for ax in axes},
        "tradecraft_assessment": tradecraft,
        "abcde_dynamics": abcde,
        "coverage": cov,
        "anomalies": anomalies[:8],
        "risks_and_threats": risk_summary,
        "first_to_publish": leaders,
        "entities": entities,
        "timeline": timeline,
        "blind_spot": [c["outlet"] for c in cov if len(cov) == 1] or None,
        "high_influence_silent_outlets": high_infl_silent,
    }


@tool("approach_angle", "COMMENT APPROCHER UN JOURNALISTE sur un sujet : ce qu'il a écrit sur le sujet (extraits), son cadrage vs la ligne de son média, ses sources habituelles, ses biais, ses fixations, ses vulnérabilités, son ton, sa productivité, ses canaux de contact. Tout ce qu'il faut pour un angle de pitch fondé sur les données — pas de conseil générique.",
      {"journalist": {"type": "string"}, "topic": {"type": "string"}, "outlet": {"type": "string"}}, required=["journalist", "topic"])
def approach_angle(db, args, ctx):
    o = _find_outlet(db, args.get("outlet")) if args.get("outlet") else None
    j = _find_journalist(db, args["journalist"], o.id if o else None)
    if not j:
        return {"error": "journaliste introuvable"}
    base = get_journalist(db, {"journalist": str(j.id)}, ctx)
    vec = embeddings.embed_text(args["topic"])
    dist = Article.embedding.cosine_distance(vec)
    rows = db.query(Article).add_columns(dist.label("dist")).filter(Article.journalist_id == j.id, Article.embedding.isnot(None)).order_by(dist).limit(6).all()
    on_topic = []
    for a, d in rows:
        if 1 - d < 0.3:
            continue
        ex = (a.extracted_data or {})
        on_topic.append({"id": a.id, "title": a.title, "date": a.published_at.isoformat()[:10] if a.published_at else None, "similarity": _f(1 - d), "tone": ex.get("tone"), "angle": ex.get("angle"),
                         "sources": [f"{s.get('name')} ({s.get('type')})" for s in (ex.get("sources") or [])][:6], "framing": {axis_labels()[k]: _f(v) for k, v in (ex.get("framing") or {}).items() if v and abs(v) >= 0.2},
                         "excerpt": (a.text or "")[:500], "link": f"/articles/{a.id}"})
    others = db.query(Article).filter(Article.journalist_id == j.id, Article.published_at >= datetime.utcnow() - timedelta(days=30)).count()
    hints = []
    prof = base.get("profile") or {}
    src = Counter_src(prof.get("preferred_sources") or [])
    if src:
        hints.append(f"sources habituelles : {src}")
    if base.get("divergence_axis"):
        da = base["divergence_axis"]
        hints.append(f"s'écarte de son média sur {da['axis']} vers « {da['direction']} » ({da['delta']:+.2f})")
    if not on_topic:
        hints.append("n'a rien publié de proche du sujet : approche à froid, s'appuyer sur ses fixations")
    if (j.accessibility_score or 0) < 40:
        hints.append("accessibilité faible : privilégier une information exclusive et documentée, pas un angle")
    return {**base, "topic": args["topic"], "articles_on_topic": on_topic, "articles_last_30_days": others, "data_hints": hints}


_NEWSROOM_BASIS = (
    "Aucune signature sur ce sujet dans l'échantillon. "
    "Noms tirés des fiches des rédactions qui portent la ligne, pas des signatures."
)


def _newsroom_targets(db, cov, by_o, all_outlets, onames) -> list[dict]:
    """Deux journalistes déjà en fiche par média couvreur, quand aucun article n'est signé."""
    from . import contacts as C
    ids = list(by_o)
    if not ids:
        return []
    roster: dict[int, list] = {}
    for j in db.query(Journalist).filter(Journalist.outlet_id.in_(ids)).all():
        roster.setdefault(j.outlet_id, []).append(j)
    out: list[dict] = []
    order = [c["outlet_id"] for c in cov if c.get("outlet_id") in by_o]
    kinds = ("email", "x", "bluesky", "mastodon", "linkedin", "author_page")
    for oid in order:
        people = sorted(
            roster.get(oid) or [],
            key=lambda j: -(j.accessibility_score if j.accessibility_score is not None else -1),
        )
        o = all_outlets.get(oid)
        infl = float(o.influence_score or 0) if o else 0.0
        for j in people[:2]:
            contacts = [c for c in C.list_for(db, j.id) if c["kind"] in kinds][:3]
            out.append({
                "journalist_id": j.id, "name": j.name, "link": f"/journalists/{j.id}",
                "outlet": onames.get(j.outlet_id), "outlet_id": j.outlet_id, "outlet_influence": round(infl, 1),
                "role": j.role,
                "accessibility": round(float(j.accessibility_score)) if j.accessibility_score is not None else None,
                "articles_on_topic": 0, "recommended_action": "SURVEILLER", "basis": _NEWSROOM_BASIS,
                "preferred_sources": [], "vulnerabilities": [], "last_article": None, "contacts": contacts,
            })
            if len(out) >= 12:
                return out
    return out


def Counter_src(sources: list[dict]) -> str:
    return ", ".join(f"{s.get('type')} ×{s.get('count')}" for s in sorted(sources, key=lambda s: -(s.get("count") or 0))[:4])


# ═══════════════════════════════════════════════════════════════ PRODUCTION

CHART_TYPES = ["bar", "hbar", "line", "area", "scatter", "radar", "axis_strip", "pie"]


@tool("render_chart", "Affiche un graphique dans la conversation. Types : bar, hbar (barres horizontales), line, area, scatter, radar (12 axes déclaré/mesuré ou séries libres), axis_strip (positions de médias sur un ou plusieurs axes −1..+1), pie. "
      "data = liste d'objets ; x = clé des catégories ; series = clés numériques à tracer. Pour radar : data = [{axis, série1, série2…}]. Pour axis_strip : data = [{name, axis, value, size?, declared?}]. Pour scatter : x et y numériques, label = clé du libellé.",
      {"type": {"type": "string", "enum": CHART_TYPES}, "title": {"type": "string"}, "subtitle": {"type": "string"},
       "data": {"type": "array", "items": {"type": "object"}}, "x": {"type": "string"}, "y": {"type": "string"}, "label": {"type": "string"},
       "series": {"type": "array", "items": {"type": "string"}}, "domain": {"type": "array", "items": {"type": "number"}, "description": "bornes de l'axe des valeurs, ex. [-1, 1]"},
       "unit": {"type": "string"}, "note": {"type": "string", "description": "légende / source sous le graphique"}},
      kind="produce", required=["type", "title", "data"])
def render_chart(db, args, ctx):
    if not isinstance(args.get("data"), list) or not args["data"]:
        return {"error": "data vide"}
    spec = {k: args.get(k) for k in ("type", "title", "subtitle", "data", "x", "y", "label", "series", "domain", "unit", "note") if args.get(k) is not None}
    spec["data"] = spec["data"][:400]
    ctx.setdefault("parts", []).append({"type": "chart", "spec": spec})
    return {"ok": True, "displayed": True, "points": len(spec["data"]), "note": "Le graphique est affiché sous ce message ; ne pas le redécrire point par point."}


@tool("press_note", "SEUL outil pour une note ou un rapport PDF. Produit le fichier dans le plan fixe (Lecture, chiffres, Cadrages, Preuves, Effets, Levier) et le design Tacite. Le bloc Levier inclut le tableau des journalistes. Ne pas réécrire le HTML, ne pas imprimer un PDF soi-même : enregistrer l'URL renvoyée telle quelle.",
      {"title": {"type": "string"}, "filename": {"type": "string"},
       "subtitle": {"type": "string", "description": "2 ou 3 lignes : type de note, périmètre, confiance"},
       "reading": {"type": "string", "description": "Lecture : établi ou non établi, cadrage mesuré, jugement limité à l'échantillon, confiance et sa raison. 4 phrases maximum."},
       "figures": {"type": "array", "items": {"type": "object"}, "description": "Jusqu'à 4 chiffres : {label, value}. value = nombre puis légende courte, ex. « 249 articles, 14 médias »."},
       "frames": {"type": "string", "description": "Cadrage mesuré et cadrages déjà écrits ailleurs. Pas le cadrage du pays."},
       "evidence": {"type": "string", "description": "Chaîne de sources, puis l'hypothèse qui peut annuler le jugement. Un bloc > **Réserve** si besoin."},
       "effects": {"type": "string", "description": "Effets établis seulement, puis 2 ou 3 indicateurs politiques."},
       "lever": {"type": "string", "description": "Une phrase : exposition et média qui fixe le cadre. Ne pas y refuser la liste de journalistes. Le tableau est le paramètre journalists, ou il est rempli via topic."},
       "journalists": {"type": "array", "items": {"type": "object"}, "description": "Lignes de topic_brief.influence_targets ou who_covers.journalists (name, outlet, articles_on_topic, accessibility, recommended_action, contacts, basis). À passer dès que la liste n'est pas vide. L'absence de dossier client n'est pas une raison de l'omettre."},
       "topic": {"type": "string", "description": "Sujet de la note. Si journalists est vide, le serveur rappelle topic_brief et imprime les cibles, signatures ou fiches de rédaction."},
       "country": {"type": "string"},
       "days": {"type": "integer"},
       "client": {"type": "string", "description": "Dossier client optionnel. Son absence n'ôte pas le tableau."}},
      kind="produce", required=["title", "filename", "reading", "frames", "evidence", "effects", "lever"])
def press_note(db, args, ctx):
    title = args.get("title") or "Note"
    rows = files.journalist_rows(args.get("journalists"))
    basis = None
    if not rows and (args.get("topic") or "").strip():
        try:
            brief = topic_brief(db, {
                "topic": args["topic"],
                "days": int(args.get("days") or 30),
                "country": args.get("country"),
                "client": args.get("client"),
            }, ctx)
            rows = files.journalist_rows(brief.get("influence_targets"))
            basis = brief.get("targets_basis")
        except Exception:  # noqa: BLE001
            log.exception("press_note journalists")
    try:
        html = files.render_press_note(
            title=title,
            reading=args.get("reading") or "",
            frames=args.get("frames") or "",
            evidence=args.get("evidence") or "",
            effects=args.get("effects") or "",
            lever=args.get("lever") or "",
            figures=args.get("figures") or [],
            subtitle=args.get("subtitle") or "",
            journalists=rows,
        )
        data = files.pdf_from_html(html)
    except Exception as e:  # noqa: BLE001
        log.exception("press_note")
        return {"error": f"note impossible : {e}"}
    art = files.save_artifact(db, "pdf", args["filename"], data, title=title, conversation_id=ctx.get("conversation_id"))
    part = {"type": "artifact", "id": art.id, "kind": "pdf", "title": art.title, "filename": art.filename, "size": art.size, "url": f"/api/artifacts/{art.id}/download"}
    ctx.setdefault("parts", []).append(part)
    return {
        "ok": True, "artifact_id": art.id, "url": part["url"], "filename": art.filename, "size": art.size,
        "journalists": len(rows), "targets_basis": basis,
        "note": "PDF déjà mis en page, tableau de journalistes inclus. Enregistrez cette URL telle quelle. N'écrivez pas de HTML et ne réimprimez pas le fichier.",
    }


@tool("create_file", "Crée un fichier de données (csv, xlsx, md, json, docx). Pour une note ou un rapport PDF, utiliser press_note, pas cet outil. kind=html|pdf reste le gabarit Tacite et refuse le HTML.",
      {"kind": {"type": "string", "enum": ["csv", "xlsx", "md", "html", "docx", "pdf", "json"]}, "filename": {"type": "string"}, "title": {"type": "string"},
       "rows": {"type": "array", "items": {"type": "object"}}, "columns": {"type": "array", "items": {"type": "string"}}, "content": {"type": "string"}, "subtitle": {"type": "string"}},
      kind="produce", required=["kind", "filename"])
def create_file(db, args, ctx):
    kind, title = args["kind"], args.get("title") or args["filename"]
    try:
        if kind == "csv":
            data = files.csv_bytes(args.get("rows") or [], args.get("columns"))
        elif kind == "xlsx":
            data = files.xlsx_bytes(args.get("rows") or [], args.get("columns"), sheet=title[:31])
        elif kind == "md":
            data = (args.get("content") or "").encode("utf-8")
        elif kind == "json":
            data = (args.get("content") or "{}").encode("utf-8")
        elif kind == "docx":
            data = files.docx_from_markdown(title, args.get("content") or "", args.get("subtitle") or "")
        else:  # html / pdf — même gabarit que les notes de l'application
            body = files.render_markdown_body(args.get("content") or "")
            html = files.html_document(title, body, subtitle=args.get("subtitle") or "")
            data = html.encode("utf-8") if kind == "html" else files.pdf_from_html(html)
    except Exception as e:  # noqa: BLE001
        log.exception("create_file")
        return {"error": f"création impossible : {e}"}
    art = files.save_artifact(db, kind, args["filename"], data, title=title, conversation_id=ctx.get("conversation_id"))
    part = {"type": "artifact", "id": art.id, "kind": art.kind, "title": art.title, "filename": art.filename, "size": art.size, "url": f"/api/artifacts/{art.id}/download"}
    ctx.setdefault("parts", []).append(part)
    return {"ok": True, "artifact_id": art.id, "url": part["url"], "filename": art.filename, "size": art.size, "note": "Le fichier est joint sous ce message ; donner simplement son nom."}


@tool("generate_report", "Rédige une note Tacite (brouillon éditable, puis PDF). kind=outlet, journalist, client, landscape, country, topic, theme. Le PDF est joint ; le brouillon reste ouvrable pour correction et widgets.",
      {"kind": {"type": "string", "enum": ["outlet", "journalist", "client", "landscape", "country", "topic", "theme"]},
       "target": {"type": "string", "description": "id ou nom du média / journaliste / client ; pour topic : le sujet ; pour country : code ISO-2 (FR, DE, GB…) ou nom anglais (France)"},
       "country": {"type": "string", "description": "filtre ISO-2 optionnel pour landscape, topic et theme"},
       "notes": {"type": "string", "description": "consignes de l'utilisateur (angle, longueur, destinataire)"}, "weeks": {"type": "integer", "default": 8}},
      kind="produce", required=["kind"])
def generate_report(db, args, ctx):
    from . import reports
    try:
        report = reports.compose(db, args["kind"], args.get("target"), notes=args.get("notes"), weeks=int(args.get("weeks") or 8), conversation_id=ctx.get("conversation_id"), country=args.get("country"))
        art = reports.export_pdf(db, report)
    except Exception as e:  # noqa: BLE001
        log.exception("generate_report")
        return {"error": f"rapport impossible : {e}"}
    part = {"type": "artifact", "id": art.id, "kind": art.kind, "title": art.title, "filename": art.filename, "size": art.size, "url": f"/api/artifacts/{art.id}/download", "report": True, "report_id": report.id}
    ctx.setdefault("parts", []).append(part)
    return {"ok": True, "artifact_id": art.id, "report_id": report.id, "edit_url": f"/reports/{report.id}", "url": part["url"], "title": art.title, "sections": (art.meta or {}).get("sections"), "note": "Le PDF est joint. Un brouillon éditable est aussi disponible (edit_url) pour corriger le texte et ajouter des graphiques."}


# ═══════════════════════════════════════════════════════════════ ÉCRITURE (proposées, puis confirmées)

WRITABLE_OUTLET = ["name", "country", "language", "website_url", "rss_url", "declared_orientation", "official_classification", "meta"]
WRITABLE_JOURNALIST = ["name", "outlet_id", "role", "twitter_handle", "linkedin_url", "bio", "accessibility_score"]
WRITABLE_CLIENT = ["name", "sector", "type", "exposure", "risk_tolerance", "budget_level", "objectives", "narratives_push", "narratives_counter", "sensitive_topics"]


@tool("update_outlet", "Modifie un média. Champs de `fields` : name, country, language, website_url, rss_url, declared_orientation, official_classification (ligne déclarée, {axe: −1..+1}, fusionnée avec l'existante), meta ({audience_score, elite_score, network_score, longevity_score} 0-100). Nécessite confirmation.",
      {"outlet": {"type": "string"}, "fields": {"type": "object", "description": "champs à modifier"}}, kind="write", required=["outlet", "fields"])
def update_outlet(db, args, ctx):
    o = _find_outlet(db, args["outlet"])
    if not o:
        raise ValueError("média introuvable")
    raw = dict(args.get("fields") or {})
    for a, b in {"declared_classification": "official_classification", "orientation": "declared_orientation", "website": "website_url", "rss": "rss_url"}.items():
        if a in raw and b not in raw:
            raw[b] = raw.pop(a)
    fields = {k: v for k, v in raw.items() if k in WRITABLE_OUTLET}
    unknown = [k for k in raw if k not in WRITABLE_OUTLET]
    if unknown:
        raise ValueError(f"champs inconnus : {', '.join(unknown)} (autorisés : {', '.join(WRITABLE_OUTLET)})")
    if "official_classification" in fields:
        fields["official_classification"] = {**(o.official_classification or {}), **{a: max(-1.0, min(1.0, float(v))) for a, v in fields["official_classification"].items() if a in AXES}}
    if "meta" in fields:
        fields["meta"] = {**(o.meta or {}), **fields["meta"]}
    before = {k: getattr(o, k) for k in fields}
    for k, v in fields.items():
        setattr(o, k, v)
    db.commit()
    cartography.invalidate()
    return {"before": before, "after": fields, "entity": {"type": "outlet", "id": o.id, "name": o.name}}


@tool("create_outlet", "Ajoute un média à suivre. La classification déclarée et les scores d'influence sont estimés par le LLM si absents ; un flux RSS crée la collecte. Nécessite confirmation.",
      {"name": {"type": "string"}, "country": {"type": "string"}, "language": {"type": "string"}, "website_url": {"type": "string"}, "rss_url": {"type": "string"},
       "declared_orientation": {"type": "string"}, "official_classification": {"type": "object"}}, kind="write", required=["name", "country", "language"])
def create_outlet(db, args, ctx):
    if db.query(Outlet).filter(func.lower(Outlet.name) == args["name"].lower()).first():
        raise ValueError("un média de ce nom existe déjà")
    from ..schemas import OutletIn
    from .. import main as _m
    payload = OutletIn(**{k: v for k, v in args.items() if k in OutletIn.model_fields})
    d = _m.create_outlet(payload, db)
    return {"before": None, "after": d, "entity": {"type": "outlet", "id": d["id"], "name": d["name"]}}


@tool("delete_outlet", "Supprime un média et ce qui lui est rattaché. Irréversible. Nécessite confirmation.", {"outlet": {"type": "string"}}, kind="write", required=["outlet"])
def delete_outlet(db, args, ctx):
    o = _find_outlet(db, args["outlet"])
    if not o:
        raise ValueError("média introuvable")
    before = row_to_dict(o)
    from .. import main as _m
    _m.delete_outlet(o.id, db)
    return {"before": before, "after": None, "entity": {"type": "outlet", "id": before["id"], "name": before["name"]}}


@tool("add_outlet_feed", "Ajoute un flux de collecte (RSS) à un média. Nécessite confirmation.",
      {"outlet": {"type": "string"}, "url": {"type": "string"}, "label": {"type": "string", "default": "default"}}, kind="write", required=["outlet", "url"])
def add_outlet_feed(db, args, ctx):
    o = _find_outlet(db, args["outlet"])
    if not o:
        raise ValueError("média introuvable")
    f = OutletFeed(outlet_id=o.id, url=args["url"], label=args.get("label") or "default", feed_type="rss", enabled=1)
    db.add(f)
    db.commit()
    return {"before": None, "after": row_to_dict(f), "entity": {"type": "outlet_feed", "id": f.id, "name": f"{o.name} · {f.label}"}}


@tool("update_journalist", "Modifie un journaliste. Champs de `fields` : name, outlet_id, role, twitter_handle, linkedin_url, bio, beat (spécialité, ex. Politique), accessibility_score (0-100). Nécessite confirmation.",
      {"journalist": {"type": "string"}, "outlet": {"type": "string", "description": "pour lever une ambiguïté sur le nom"}, "fields": {"type": "object"}}, kind="write", required=["journalist", "fields"])
def update_journalist(db, args, ctx):
    o = _find_outlet(db, args.get("outlet")) if args.get("outlet") else None
    j = _find_journalist(db, args["journalist"], o.id if o else None)
    if not j:
        raise ValueError("journaliste introuvable")
    raw = dict(args.get("fields") or {})
    aliases = {"accessibility": "accessibility_score", "twitter": "twitter_handle", "x": "twitter_handle", "linkedin": "linkedin_url"}
    for a, b in aliases.items():
        if a in raw and b not in raw:
            raw[b] = raw.pop(a)
    if "outlet" in raw and "outlet_id" not in raw:
        no = _find_outlet(db, raw.pop("outlet"))
        if no:
            raw["outlet_id"] = no.id
    fields = {k: v for k, v in raw.items() if k in WRITABLE_JOURNALIST}
    if "beat" in raw:
        bio = re.sub(r"^\[[^\]]*\]\s*", "", fields.get("bio", j.bio or ""))
        fields["bio"] = f"[{raw['beat']}] {bio}".strip()
    unknown = [k for k in raw if k not in WRITABLE_JOURNALIST and k != "beat"]
    if unknown:
        raise ValueError(f"champs inconnus : {', '.join(unknown)} (autorisés : {', '.join(WRITABLE_JOURNALIST)}, beat)")
    if "accessibility_score" in fields:
        fields["accessibility_score"] = max(0.0, min(100.0, float(fields["accessibility_score"])))
    before = {k: getattr(j, k) for k in fields}
    for k, v in fields.items():
        setattr(j, k, v)
    db.commit()
    return {"before": before, "after": fields, "entity": {"type": "journalist", "id": j.id, "name": j.name}}


@tool("create_journalist", "Crée un journaliste rattaché à un média. Nécessite confirmation.",
      {"name": {"type": "string"}, "outlet": {"type": "string"}, "role": {"type": "string"}, "bio": {"type": "string"}, "twitter_handle": {"type": "string"}, "linkedin_url": {"type": "string"}},
      kind="write", required=["name", "outlet"])
def create_journalist(db, args, ctx):
    o = _find_outlet(db, args["outlet"])
    if not o:
        raise ValueError("média introuvable")
    j = Journalist(name=args["name"].strip(), outlet_id=o.id, role=args.get("role") or "Journaliste", bio=args.get("bio"), twitter_handle=args.get("twitter_handle"), linkedin_url=args.get("linkedin_url"))
    db.add(j)
    db.commit()
    return {"before": None, "after": row_to_dict(j), "entity": {"type": "journalist", "id": j.id, "name": j.name}}


@tool("delete_journalist", "Supprime un journaliste (ses articles sont conservés, détachés). Nécessite confirmation.", {"journalist": {"type": "string"}, "outlet": {"type": "string"}}, kind="write", required=["journalist"])
def delete_journalist(db, args, ctx):
    o = _find_outlet(db, args.get("outlet")) if args.get("outlet") else None
    j = _find_journalist(db, args["journalist"], o.id if o else None)
    if not j:
        raise ValueError("journaliste introuvable")
    before = row_to_dict(j)
    from .. import main as _m
    _m.delete_journalist(j.id, db)
    return {"before": before, "after": None, "entity": {"type": "journalist", "id": before["id"], "name": before["name"]}}


@tool("merge_journalists", "Fusionne deux fiches du même journaliste (doublon) : les articles, profils et recommandations de `remove` passent sur `keep`, puis `remove` est supprimée. Nécessite confirmation.",
      {"keep": {"type": "string", "description": "id à conserver"}, "remove": {"type": "string", "description": "id à supprimer"}}, kind="write", required=["keep", "remove"])
def merge_journalists(db, args, ctx):
    keep, rem = _find_journalist(db, args["keep"]), _find_journalist(db, args["remove"])
    if not keep or not rem or keep.id == rem.id:
        raise ValueError("journalistes introuvables ou identiques")
    before = {"keep": row_to_dict(keep), "remove": row_to_dict(rem)}
    n = db.query(Article).filter(Article.journalist_id == rem.id).update({"journalist_id": keep.id})
    db.query(JournalistProfile).filter(JournalistProfile.journalist_id == rem.id).update({"journalist_id": keep.id})
    db.query(Recommendation).filter(Recommendation.journalist_id == rem.id).update({"journalist_id": keep.id})
    db.query(ClientContact).filter(ClientContact.journalist_id == rem.id).update({"journalist_id": keep.id})
    from ..models import ContactScan, JournalistContact
    db.query(JournalistContact).filter(JournalistContact.journalist_id == rem.id).update({"journalist_id": keep.id})
    db.query(ContactScan).filter(ContactScan.journalist_id == rem.id).delete()
    for f in ("twitter_handle", "linkedin_url", "bio"):
        if not getattr(keep, f) and getattr(rem, f):
            setattr(keep, f, getattr(rem, f))
    db.delete(rem)
    db.commit()
    return {"before": before, "after": {"moved_articles": n, "kept": row_to_dict(keep)}, "entity": {"type": "journalist", "id": keep.id, "name": keep.name}}


@tool("merge_outlets", "Fusionne deux fiches du même média (homonyme intra-pays) : articles, journalistes, flux, profils et recommandations de `remove` passent sur `keep`, puis `remove` est supprimée. Nécessite confirmation.",
      {"keep": {"type": "string", "description": "id à conserver"}, "remove": {"type": "string", "description": "id à supprimer"}}, kind="write", required=["keep", "remove"])
def merge_outlets(db, args, ctx):
    keep, rem = _find_outlet(db, args["keep"]), _find_outlet(db, args["remove"])
    if not keep or not rem or keep.id == rem.id:
        raise ValueError("médias introuvables ou identiques")
    before = {"keep": row_to_dict(keep), "remove": row_to_dict(rem)}
    from ..models import Citation, ClientBlacklist, OutletFeed, OutletProfile
    n_art = db.query(Article).filter(Article.outlet_id == rem.id).update({"outlet_id": keep.id})
    n_j = db.query(Journalist).filter(Journalist.outlet_id == rem.id).update({"outlet_id": keep.id})
    db.query(OutletFeed).filter(OutletFeed.outlet_id == rem.id).update({"outlet_id": keep.id})
    db.query(OutletProfile).filter(OutletProfile.outlet_id == rem.id).update({"outlet_id": keep.id})
    db.query(Recommendation).filter(Recommendation.outlet_id == rem.id).update({"outlet_id": keep.id})
    db.query(ClientBlacklist).filter(ClientBlacklist.outlet_id == rem.id).update({"outlet_id": keep.id})
    db.query(ActionHistory).filter(ActionHistory.outlet_id == rem.id).update({"outlet_id": keep.id})
    db.query(Citation).filter(Citation.source_outlet_id == rem.id).update({"source_outlet_id": keep.id})
    db.query(Citation).filter(Citation.target_outlet_id == rem.id).update({"target_outlet_id": keep.id})
    for f in ("website_url", "rss_url", "declared_orientation"):
        if not getattr(keep, f) and getattr(rem, f):
            setattr(keep, f, getattr(rem, f))
    db.delete(rem)
    db.commit()
    from . import cartography
    cartography.invalidate()
    return {"before": before, "after": {"moved_articles": n_art, "moved_journalists": n_j, "kept": row_to_dict(keep)}, "entity": {"type": "outlet", "id": keep.id, "name": keep.name}}


@tool("update_client", "Modifie un dossier client : nom, secteur, type, exposition, tolérance au risque, budget, objectifs, narratifs à pousser / à contrer, sujets sensibles. Nécessite confirmation.",
      {"client": {"type": "string"}, "fields": {"type": "object"}}, kind="write", required=["client", "fields"])
def update_client(db, args, ctx):
    c = _find_client(db, args["client"])
    if not c:
        raise ValueError("client introuvable")
    raw = dict(args.get("fields") or {})
    fields = {k: v for k, v in raw.items() if k in WRITABLE_CLIENT}
    unknown = [k for k in raw if k not in WRITABLE_CLIENT]
    if unknown:
        raise ValueError(f"champs inconnus : {', '.join(unknown)} (autorisés : {', '.join(WRITABLE_CLIENT)})")
    before = {k: getattr(c, k) for k in fields}
    for k, v in fields.items():
        setattr(c, k, v)
    db.commit()
    return {"before": before, "after": fields, "entity": {"type": "client", "id": c.id, "name": c.name}}


@tool("create_client", "Crée un dossier client. Nécessite confirmation.",
      {"name": {"type": "string"}, "sector": {"type": "string"}, "type": {"type": "string", "enum": ["corporate", "government", "ngo", "political"]},
       "exposure": {"type": "string", "enum": ["low", "medium", "high"]}, "risk_tolerance": {"type": "string", "enum": ["low", "medium", "high"]}, "budget_level": {"type": "string", "enum": ["low", "medium", "high"]},
       "narratives_push": {"type": "array", "items": {"type": "string"}}, "narratives_counter": {"type": "array", "items": {"type": "string"}}, "sensitive_topics": {"type": "array", "items": {"type": "string"}}},
      kind="write", required=["name"])
def create_client(db, args, ctx):
    from ..schemas import ClientIn
    c = Client(**ClientIn(**{k: v for k, v in args.items() if k in ClientIn.model_fields}).model_dump())
    db.add(c)
    db.commit()
    return {"before": None, "after": row_to_dict(c), "entity": {"type": "client", "id": c.id, "name": c.name}}


@tool("delete_client", "Supprime un dossier client et ses recommandations. Irréversible. Nécessite confirmation.", {"client": {"type": "string"}}, kind="write", required=["client"])
def delete_client(db, args, ctx):
    c = _find_client(db, args["client"])
    if not c:
        raise ValueError("client introuvable")
    before = row_to_dict(c)
    from .. import main as _m
    _m.delete_client(c.id, db)
    return {"before": before, "after": None, "entity": {"type": "client", "id": before["id"], "name": before["name"]}}


@tool("update_recommendation", "Change une recommandation : statut (proposed, accepted, in_progress, completed, cancelled), type d'action, journaliste d'entrée. Nécessite confirmation.",
      {"id": {"type": "integer"}, "status": {"type": "string"}, "action_type": {"type": "string", "enum": list(ACTION_TYPES)}, "journalist_id": {"type": "integer"}}, kind="write", required=["id"])
def update_recommendation(db, args, ctx):
    r = db.get(Recommendation, int(args["id"]))
    if not r:
        raise ValueError("recommandation introuvable")
    fields = {k: args[k] for k in ("status", "action_type", "journalist_id") if args.get(k) is not None}
    before = {k: getattr(r, k) for k in fields}
    for k, v in fields.items():
        setattr(r, k, v)
    r.updated_at = datetime.utcnow()
    db.commit()
    return {"before": before, "after": fields, "entity": {"type": "recommendation", "id": r.id, "name": f"{r.action_type} #{r.id}"}}


@tool("record_outcome", "Enregistre le résultat d'une action (success, partial, failure) avec les leçons ; alimente les seuils adaptatifs. Nécessite confirmation.",
      {"recommendation_id": {"type": "integer"}, "outcome": {"type": "string", "enum": ["success", "partial", "failure"]}, "lessons_learned": {"type": "string"}}, kind="write", required=["recommendation_id", "outcome"])
def record_outcome(db, args, ctx):
    from . import recommend
    h = recommend.record_outcome(db, int(args["recommendation_id"]), args["outcome"], {}, args.get("lessons_learned"))
    if not h:
        raise ValueError("recommandation introuvable")
    return {"before": None, "after": row_to_dict(h), "entity": {"type": "action_history", "id": h.id, "name": f"{h.action_type} → {h.outcome}"}}


@tool("update_settings", "Modifie les réglages du moteur (seuils, pondérations d'influence, modèles, plafond de coût, intervalles). Clés : " + ", ".join(DEFAULT_SETTINGS.keys()) + ". Nécessite confirmation.",
      {"values": {"type": "object"}}, kind="write", required=["values"])
def update_settings(db, args, ctx):
    vals = {k: v for k, v in (args.get("values") or {}).items() if k in DEFAULT_SETTINGS}
    if not vals:
        raise ValueError("aucune clé de réglage valide")
    before = {k: get_setting(db, k) for k in vals}
    for k, v in vals.items():
        set_setting(db, k, v)
    return {"before": before, "after": vals, "entity": {"type": "settings", "id": 0, "name": "Paramètres"}}


@tool("suggest_outlets", "MÉDIAS À AJOUTER POUR UN PAYS — propose les médias influents d'un pays puis les VÉRIFIE : site joignable, flux RSS testés, déjà suivi ou non. À utiliser pour « ajoute les médias de tel pays », « qu'est-ce qui manque pour la France ». Long au premier appel (~30-60 s), en cache ensuite. Pour créer les fiches, enchaîner avec add_outlets.",
      {"country": {"type": "string", "description": "code ISO-2 (PL, BR…)"}, "force": {"type": "boolean", "description": "ignorer le cache", "default": False}}, required=["country"])
def suggest_outlets(db, args, ctx):
    from . import suggest as S
    res = S.suggest(db, args["country"], force=bool(args.get("force")))
    return {"country": args["country"].upper(), "suggestions": res,
            "note": "status: verified = flux RSS testé, collecte directe (15 min) ; site_only = pas de flux, collecte indirecte (Google News, GDELT, scraping) ; robot_blocked = le site bloque les robots, collecte par navigateur possible ; already = déjà suivi ; unreachable = échec (voir 'reason', ne pas proposer). Présenter le mode de collecte à l'utilisateur, pas le code de statut. Pour ajouter : add_outlets avec les noms choisis."}


@tool("add_outlets", "Ajoute au suivi plusieurs médias d'un pays, choisis dans les suggestions de suggest_outlets ou nommés librement (chaque nom libre est résolu par recherche web puis vérifié). Crée les fiches, branche les flux RSS vérifiés, estime la ligne déclarée. Nécessite confirmation.",
      {"country": {"type": "string", "description": "code ISO-2"}, "names": {"type": "array", "items": {"type": "string"}, "description": "noms exacts des médias à ajouter"}}, kind="write", required=["country", "names"])
def add_outlets(db, args, ctx):
    from . import suggest as S
    code = args["country"].upper()
    cached = {s["name"].lower(): s for s in (S._cache.get(code, (0, []))[1])}
    items, not_found = [], []
    for name in args.get("names", []):
        it = cached.get(name.strip().lower())
        if not it or it["status"] in ("unreachable", "invalid"):
            it = S.resolve(db, name, code)
        if it.get("status") in ("verified", "site_only", "robot_blocked", "already"):
            items.append(it)
        else:
            not_found.append({"name": name, "reason": it.get("reason") or it.get("status")})
    res = S.create_from_suggestions(db, code, items)
    return {"before": None, "after": {**res, "not_found": not_found}, "entity": {"type": "outlet", "id": 0, "name": f"{len(res['created'])} médias · {code}"}}


@tool("add_contact", "Ajoute manuellement un canal de contact à un journaliste (email, x, bluesky, mastodon, linkedin, instagram, threads, phone, signal, website, other) avec une note de provenance. Nécessite confirmation.",
      {"journalist": {"type": "string"}, "outlet": {"type": "string"}, "kind": {"type": "string", "enum": ["email", "x", "bluesky", "mastodon", "linkedin", "instagram", "threads", "phone", "signal", "website", "author_page", "other"]},
       "value": {"type": "string"}, "note": {"type": "string", "description": "d'où vient l'information"}}, kind="write", required=["journalist", "kind", "value"])
def add_contact(db, args, ctx):
    from . import contacts as C
    o = _find_outlet(db, args.get("outlet")) if args.get("outlet") else None
    j = _find_journalist(db, args["journalist"], o.id if o else None)
    if not j:
        raise ValueError("journaliste introuvable")
    n = C.upsert_many(db, j.id, [{"kind": args["kind"], "value": args["value"].strip(), "confidence": "verified", "method": "manual", "note": args.get("note") or "saisi via l'assistant"}], None)
    return {"before": None, "after": {"kind": args["kind"], "value": args["value"], "new": bool(n)}, "entity": {"type": "journalist", "id": j.id, "name": j.name}}


TASKS = ["ingest", "analyze", "profiles_journalists", "profiles_outlets", "enrich_journalists", "recommendations", "requalify", "cleanup_journalists", "contacts", "bylines", "normalize_beats"]


@tool("run_task", "Lance une tâche de maintenance : ingest (collecte des flux), analyze (analyser les articles en attente, limit), profiles_journalists, profiles_outlets (positions mesurées + influence), enrich_journalists (limit), recommendations (client requis), requalify (textes parasites), cleanup_journalists, contacts (détection des canaux de contact, arrière-plan, limit journalistes), bylines (rattacher les signatures depuis le HTML des articles, limit), normalize_beats. Nécessite confirmation.",
      {"task": {"type": "string", "enum": TASKS}, "client": {"type": "string"}, "limit": {"type": "integer"}}, kind="write", required=["task"])
def run_task(db, args, ctx):
    t = args["task"]
    from .. import main as _m
    if t == "ingest":
        res = _m.rss.ingest_all(db, "rss")
    elif t == "analyze":
        res = {"analyzed": _m.analysis.process_pending(db, int(args.get("limit") or 50))}
    elif t == "profiles_journalists":
        res = {"profiles": _m.profiles.run_journalist_profiles(db)}
    elif t == "profiles_outlets":
        res = {"profiles": _m.profiles.run_outlet_profiles(db)}
        cartography.invalidate()
    elif t == "enrich_journalists":
        from .enrich import enrich_all
        res = {"enriched": enrich_all(db, int(args.get("limit") or 50))}
    elif t == "recommendations":
        c = _find_client(db, args.get("client"))
        if not c:
            raise ValueError("client requis")
        from . import recommend
        created, kept = recommend.generate_recommendations(db, c)
        res = {"recommendations": len(created), "kept": len(kept)}
    elif t == "requalify":
        from . import cleanup
        res = {"started": cleanup.start_background(refetch=True)}
    elif t == "cleanup_journalists":
        res = _m.cleanup_journalists(db)
    elif t == "contacts":
        from . import contacts as C
        res = {"started": C.start_background(limit=int(args.get("limit") or 300))}
    elif t == "bylines":
        from . import bylines
        res = bylines.backfill(db, limit=int(args.get("limit") or 2000))
    elif t == "normalize_beats":
        from .enrich import normalize_all_beats
        res = {"normalized": normalize_all_beats(db)}
    else:
        raise ValueError("tâche inconnue")
    return {"before": None, "after": res, "entity": {"type": "task", "id": 0, "name": t}}


# ═══════════════════════════════════════════════════════════════ application / annulation des écritures

def describe_write(name: str, args: dict, db: Session) -> str:
    """Phrase lisible pour la carte de confirmation."""
    try:
        if name == "update_outlet":
            o = _find_outlet(db, args.get("outlet"))
            ch = ", ".join(f"{k} → {json.dumps(v, ensure_ascii=False)[:60]}" for k, v in (args.get("fields") or {}).items())
            return f"Modifier le média « {o.name if o else args.get('outlet')} » : {ch}"
        if name == "update_journalist":
            j = _find_journalist(db, args.get("journalist"))
            ch = ", ".join(f"{k} → {json.dumps(v, ensure_ascii=False)[:60]}" for k, v in (args.get("fields") or {}).items())
            return f"Modifier le journaliste « {j.name if j else args.get('journalist')} » : {ch}"
        if name == "update_client":
            c = _find_client(db, args.get("client"))
            ch = ", ".join(f"{k} → {json.dumps(v, ensure_ascii=False)[:60]}" for k, v in (args.get("fields") or {}).items())
            return f"Modifier le client « {c.name if c else args.get('client')} » : {ch}"
        if name.startswith("create_"):
            return f"Créer {name.split('_', 1)[1]} « {args.get('name')} »"
        if name.startswith("delete_"):
            return f"Supprimer {name.split('_', 1)[1]} « {args.get(name.split('_', 1)[1]) or args.get('journalist') or args.get('client')} » (irréversible)"
        if name == "merge_journalists":
            return f"Fusionner le journaliste #{args.get('remove')} dans #{args.get('keep')}"
        if name == "merge_outlets":
            return f"Fusionner le média #{args.get('remove')} dans #{args.get('keep')}"
        if name == "update_settings":
            return "Modifier les réglages : " + ", ".join(f"{k} → {v}" for k, v in (args.get("values") or {}).items())
        if name == "run_task":
            return f"Lancer la tâche « {args.get('task')} »" + (f" pour le client {args.get('client')}" if args.get("client") else "")
        if name == "add_contact":
            return f"Ajouter le contact {args.get('kind')} « {args.get('value')} » à « {args.get('journalist')} »"
        if name == "add_outlets":
            return f"Ajouter au suivi {len(args.get('names') or [])} médias ({args.get('country', '').upper()}) : {', '.join((args.get('names') or [])[:8])}"
        if name == "add_outlet_feed":
            return f"Ajouter le flux {args.get('url')} au média « {args.get('outlet')} »"
        if name == "update_recommendation":
            return f"Recommandation #{args.get('id')} : " + ", ".join(f"{k} → {v}" for k, v in args.items() if k != "id" and v is not None)
        if name == "record_outcome":
            return f"Enregistrer le résultat « {args.get('outcome')} » pour la recommandation #{args.get('recommendation_id')}"
    except Exception:  # noqa: BLE001
        pass
    return f"{name} {json.dumps(args, ensure_ascii=False)[:120]}"


def apply_write(name: str, db: Session, args: dict) -> dict:
    if name not in REGISTRY or REGISTRY[name][2] != "write":
        raise ValueError("outil d'écriture inconnu")
    return REGISTRY[name][1](db, args, {})


def undo_write(name: str, db: Session, args: dict, result: dict) -> dict:
    """Annulation pour les modifications et créations simples."""
    before, ent = (result or {}).get("before"), (result or {}).get("entity") or {}
    model = {"outlet": Outlet, "journalist": Journalist, "client": Client, "recommendation": Recommendation}.get(ent.get("type"))
    if name.startswith("update_") and model and isinstance(before, dict) and name != "update_settings":
        obj = db.get(model, ent["id"])
        if not obj:
            raise ValueError("entité disparue")
        for k, v in before.items():
            setattr(obj, k, v)
        db.commit()
        cartography.invalidate()
        return {"restored": before}
    if name == "update_settings":
        for k, v in (before or {}).items():
            set_setting(db, k, v)
        return {"restored": before}
    if name in ("create_outlet", "create_journalist", "create_client") and model:
        obj = db.get(model, ent["id"])
        if obj:
            db.delete(obj)
            db.commit()
        return {"deleted": ent}
    if name == "add_outlet_feed":
        f = db.get(OutletFeed, ent["id"])
        if f:
            db.delete(f)
            db.commit()
        return {"deleted": ent}
    raise ValueError("cette action ne peut pas être annulée automatiquement")
