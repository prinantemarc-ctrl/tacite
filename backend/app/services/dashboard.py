"""Tableau de bord — synthèse de la veille.

Regroupe en une réponse ce qui est utile à lire chaque matin : état de la collecte,
mouvements du paysage, écarts, sujets, meneurs, dissidents, entités clivantes, clients.
Tout est dérivé des données déjà en base ; les blocs coûteux passent par le cache
de la cartographie.
"""

from __future__ import annotations

import logging
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import axes_for_country
from ..kits import kit_for_country, serialize_kit
from ..i18n import axis_label, axis_poles
from ..models import (
    ActionHistory, Article, Client, IngestionLog, Journalist, JournalistProfile,
    LLMUsage, Outlet, OutletFeed, OutletProfile, Recommendation,
)
from ..settings_store import get_setting
from . import cartography

log = logging.getLogger("tacite.dashboard")


def _topics_by_country(agenda: dict) -> list[dict]:
    """Top sujets par pays, dérivés de l'agenda global déjà calculé."""
    buckets: dict[str, dict] = {}
    for cluster in agenda.get("clusters") or []:
        per_country: dict[str, int] = defaultdict(int)
        for outlet in cluster.get("outlets_detail") or []:
            code = (outlet.get("country") or "").upper()
            if code:
                per_country[code] += int(outlet.get("n") or 0)
        for code, n in per_country.items():
            if n <= 0:
                continue
            bucket = buckets.setdefault(code, {"articles": 0, "topics": []})
            bucket["articles"] += n
            bucket["topics"].append({
                "id": cluster.get("id"),
                "topic": cluster.get("label"),
                "articles": n,
                "outlets": cluster.get("outlets"),
                "heat": cluster.get("heat"),
                "journalists": cluster.get("journalists"),
                "theme_id": cluster.get("theme_id"),
            })
    rows = []
    for code, bucket in buckets.items():
        topics = sorted(bucket["topics"], key=lambda t: -(t["articles"] or 0))[:4]
        if topics:
            rows.append({"country": code, "topics": topics, "n_articles": bucket["articles"]})
    rows.sort(key=lambda r: -r["n_articles"])
    return rows


def _axis(a: str, value: float) -> dict:
    neg, pos = axis_poles(a)
    return {"axis": a, "label": axis_label(a), "value": round(float(value), 2), "pole": pos if value > 0 else neg}


def build(db: Session, country: str | None = None) -> dict:
    now = datetime.utcnow()
    today = now.date()
    country = (country or "").upper() or None
    all_outlets = {o.id: o for o in db.query(Outlet).all()}
    outlets = {i: o for i, o in all_outlets.items() if not country or (o.country or "").upper() == country}

    # ── profils hebdo : dernier et avant-dernier par média
    profs = db.query(OutletProfile).order_by(OutletProfile.outlet_id, OutletProfile.week.desc()).all()
    by_outlet: dict[int, list[OutletProfile]] = defaultdict(list)
    for p in profs:
        if len(by_outlet[p.outlet_id]) < 2:
            by_outlet[p.outlet_id].append(p)

    documented = 0
    gaps: list[dict] = []
    mean_abs_gaps: list[float] = []
    movements: list[dict] = []
    drift_threshold = float(get_setting(db, "drift_threshold") or 0.3)
    for oid, lst in by_outlet.items():
        o = outlets.get(oid)
        if not o:
            continue
        latest = lst[0]
        n = latest.article_count or 0
        if n >= 10:
            documented += 1
        g = latest.gap_from_official or {}
        axis_n = latest.axis_n or {}
        usable = [a for a in axes_for_country(o.country, db) if (axis_n.get(a) or n) >= 10]
        if g and n >= 10 and usable:
            vals = {a: float(g.get(a, 0) or 0) for a in usable}
            mean_abs_gaps.append(float(np.mean([abs(v) for v in vals.values()])))
            a = max(vals, key=lambda k: abs(vals[k]))
            gaps.append({
                "outlet_id": oid, "name": o.name, "country": o.country, "influence": round(o.influence_score or 0),
                "articles": n, "week": latest.week.isoformat(), **_axis(a, vals[a]),
                "declared": round(float((o.official_classification or {}).get(a, 0) or 0), 2),
                "measured": round(float((latest.real_classification or {}).get(a, 0) or 0), 2),
            })
        if len(lst) == 2 and n >= 10 and (lst[1].article_count or 0) >= 10:
            cur, prev = latest.real_classification or {}, lst[1].real_classification or {}
            prev_n = lst[1].axis_n or {}
            for a in usable:
                if (axis_n.get(a) or n) < 10 or (prev_n.get(a) or lst[1].article_count or 0) < 10:
                    continue
                c, p = float(cur.get(a, 0) or 0), float(prev.get(a, 0) or 0)
                if c == 0 or p == 0:
                    continue
                movements.append({
                    "outlet_id": oid, "name": o.name, "influence": round(o.influence_score or 0),
                    "previous": round(p, 2), "current": round(c, 2), "week": latest.week.isoformat(),
                    "above_threshold": abs(c - p) >= drift_threshold, **_axis(a, c - p),
                })
    gaps.sort(key=lambda r: -abs(r["value"]))
    movements.sort(key=lambda r: -abs(r["value"]))

    # ── articles : statuts, flux 14 jours
    art_base = db.query(Article)
    if country:
        art_base = art_base.filter(Article.outlet_id.in_(list(outlets.keys()) or [0]))
    status_counts = dict(art_base.with_entities(Article.analysis_status, func.count()).group_by(Article.analysis_status).all())
    since14 = now - timedelta(days=14)
    daily_q = db.query(func.date(Article.captured_at), Article.analysis_status, func.count()).filter(Article.captured_at >= since14)
    if country:
        daily_q = daily_q.filter(Article.outlet_id.in_(list(outlets.keys()) or [0]))
    daily_rows = daily_q.group_by(func.date(Article.captured_at), Article.analysis_status).all()
    daily: dict[str, dict] = {}
    for i in range(14):
        d = (today - timedelta(days=13 - i)).isoformat()
        daily[d] = {"date": d, "analyzed": 0, "other": 0}
    for d, st, n in daily_rows:
        k = d.isoformat() if hasattr(d, "isoformat") else str(d)
        if k in daily:
            daily[k]["analyzed" if st == "analyzed" else "other"] += n
    since7 = now - timedelta(days=7)
    analyzed_7d_q = db.query(func.count(Article.id)).filter(Article.analysis_status == "analyzed", Article.captured_at >= since7)
    captured_24h_q = db.query(func.count(Article.id)).filter(Article.captured_at >= now - timedelta(hours=24))
    if country:
        analyzed_7d_q = analyzed_7d_q.filter(Article.outlet_id.in_(list(outlets.keys()) or [0]))
        captured_24h_q = captured_24h_q.filter(Article.outlet_id.in_(list(outlets.keys()) or [0]))
    analyzed_7d = analyzed_7d_q.scalar() or 0
    captured_24h = captured_24h_q.scalar() or 0
    captured_by_country = [
        {"country": c, "n": int(n)}
        for c, n in (
            db.query(Outlet.country, func.count(Article.id))
            .join(Article, Article.outlet_id == Outlet.id)
            .filter(Article.captured_at >= now - timedelta(hours=24))
            .group_by(Outlet.country)
            .order_by(func.count(Article.id).desc())
            .all()
        )
    ]

    def _topic_rows(ag: dict, n: int = 10) -> list[dict]:
        return [{
            "id": c.get("id"), "topic": c["label"], "articles": c["articles"], "outlets": c["outlets"],
            "heat": c.get("heat"), "journalists": c.get("journalists"),
            "theme_id": c.get("theme_id"),
        } for c in (ag.get("clusters") or [])[:n]]

    agenda_today, agenda_week, topics_map, blind = {}, {}, {}, []
    by_country: list[dict] = []
    try:
        from . import topics as topics_svc
        agenda_today = topics_svc.agenda(db, days=1, country=country, cap=400)
        agenda_week = topics_svc.agenda(db, days=7, country=country, cap=500)
        topics_map = agenda_week
        topics = _topic_rows(agenda_week)
        for c in agenda_week.get("clusters") or []:
            if c["outlets"] == 1 and c["articles"] >= 3 and c.get("outlets_detail"):
                o = c["outlets_detail"][0]
                blind.append({"topic": c["label"], "articles": c["articles"], "outlet_id": o["id"], "outlet": o["name"]})
            if len(blind) >= 6:
                break
        # Un seul calcul d'agenda (déjà en cache). Relancer agenda() par pays
        # recharge les embeddings de chaque corpus et bloque le tableau de bord.
        if not country:
            by_country = _topics_by_country(agenda_week)
    except Exception:
        log.exception("dashboard: topics")
        topics = []

    # ── blocs mis en cache par la cartographie
    try:
        ll = cartography.leadlag(db, days=14, cap=1500)
        leaders = [r for r in ll["ranking"] if r["leads"] >= 2][:6]
        if country:
            leaders = [r for r in leaders if (all_outlets.get(r.get("outlet_id")) and all_outlets[r["outlet_id"]].country == country)]
        leadlag_events = ll["events"]
    except Exception:
        leaders, leadlag_events = [], 0
    try:
        all_diss = cartography.dissidents(db, cap=2000)
        if country:
            all_diss = [d for d in all_diss if all_outlets.get(d.get("outlet_id")) and all_outlets[d["outlet_id"]].country == country]
        diss = [d for d in all_diss if d["deviation"] > 0.35][:6]
        dissident_threshold_met = bool(diss)
        if not diss:
            diss = all_diss[:5]
    except Exception:
        log.exception("dashboard: dissidents")
        diss, dissident_threshold_met = [], False
    try:
        ents = cartography.entities(db, days=30, limit=40, country=country, cap=1500)["entities"]
        min_outlets = 2 if country else 3
        divisive = []
        for e in sorted([e for e in ents if e["outlets"] >= min_outlets], key=lambda e: -e["spread"])[:6]:
            cells = sorted([c for c in e.get("cells", []) if c["mentions"] >= 2], key=lambda c: c["valence"])
            # copie : ne pas muter les objets du cache de la cartographie
            divisive.append({k: v for k, v in e.items() if k != "cells"} | {
                "most_negative": cells[0] if cells else None,
                "most_positive": cells[-1] if len(cells) > 1 else None,
            })
    except Exception:
        log.exception("dashboard: entités")
        divisive = []

    # ── journalistes
    accessible_q = (
        db.query(Journalist, Outlet.name).join(Outlet, Outlet.id == Journalist.outlet_id)
        .filter(Journalist.accessibility_score >= float(get_setting(db, "accessibility_pitch_threshold") or 55))
    )
    if country:
        accessible_q = accessible_q.filter(Outlet.country == country)
    accessible = accessible_q.order_by(Journalist.accessibility_score.desc()).limit(6).all()

    j_total_q = db.query(func.count(Journalist.id))
    profiled_q = (
        db.query(func.count(func.distinct(JournalistProfile.journalist_id)))
        .join(Journalist, Journalist.id == JournalistProfile.journalist_id)
    )
    if country:
        j_total_q = j_total_q.join(Outlet, Outlet.id == Journalist.outlet_id).filter(Outlet.country == country)
        profiled_q = profiled_q.join(Outlet, Outlet.id == Journalist.outlet_id).filter(Outlet.country == country)
    journalists_total = j_total_q.scalar() or 0
    profiled = profiled_q.scalar() or 0

    # ── clients et actions
    clients = db.query(Client).all()
    rec_status = dict(db.query(Recommendation.status, func.count()).group_by(Recommendation.status).all())
    recent_recs = db.query(Recommendation).order_by(Recommendation.priority.desc(), Recommendation.created_at.desc()).limit(6).all()
    outcomes = dict(db.query(ActionHistory.outcome, func.count()).group_by(ActionHistory.outcome).all())
    jnames = {j.id: j.name for j in db.query(Journalist.id, Journalist.name).filter(Journalist.id.in_([r.journalist_id for r in recent_recs if r.journalist_id] or [0])).all()}
    cnames = {c.id: c.name for c in clients}

    # ── collecte et coûts
    outlet_ids = list(outlets.keys()) or [0]
    last_q = db.query(func.max(IngestionLog.timestamp))
    last_per_outlet_sub = (
        db.query(IngestionLog.outlet_id, func.max(IngestionLog.timestamp).label("ts"))
        .filter(IngestionLog.timestamp >= now - timedelta(hours=24))
    )
    feeds_q = db.query(func.count(OutletFeed.id)).filter(OutletFeed.enabled == 1)
    if country:
        last_q = last_q.filter(IngestionLog.outlet_id.in_(outlet_ids))
        last_per_outlet_sub = last_per_outlet_sub.filter(IngestionLog.outlet_id.in_(outlet_ids))
        feeds_q = feeds_q.filter(OutletFeed.outlet_id.in_(outlet_ids))
    last_per_outlet_sub = last_per_outlet_sub.group_by(IngestionLog.outlet_id).subquery()
    errors_24h = (
        db.query(func.count(func.distinct(IngestionLog.outlet_id)))
        .join(
            last_per_outlet_sub,
            (IngestionLog.outlet_id == last_per_outlet_sub.c.outlet_id)
            & (IngestionLog.timestamp == last_per_outlet_sub.c.ts),
        )
        .filter(IngestionLog.status == "error")
        .scalar()
        or 0
    )
    last_ing = last_q.scalar()
    feeds = feeds_q.scalar() or 0
    month_start = today.replace(day=1)
    cost_month = float(db.query(func.sum(LLMUsage.cost_usd)).filter(LLMUsage.date >= month_start).scalar() or 0)
    cost_today = float(db.query(func.sum(LLMUsage.cost_usd)).filter(LLMUsage.date == today).scalar() or 0)
    cap = float(get_setting(db, "max_daily_cost_usd") or 0)

    oldest_pending = db.query(func.min(Article.captured_at)).filter(Article.analysis_status == "pending").scalar()
    batch = int(get_setting(db, "analysis_batch_size") or 50)

    countries = Counter(o.country for o in outlets.values())
    from ..i18n import get_locale
    kit_pub = serialize_kit(kit_for_country(country, db) if country else None, get_locale()) if country else None

    return {
        "generated_at": now.isoformat(),
        "country": country,
        "country_options": sorted({o.country for o in all_outlets.values() if o.country}),
        "kit": kit_pub,
        "kpis": {
            "outlets": len(outlets), "outlets_documented": documented, "countries": len(countries),
            "journalists": journalists_total, "journalists_profiled": profiled,
            "articles": sum(status_counts.values()), "analyzed_7d": analyzed_7d, "pending": status_counts.get("pending", 0),
            "pending_oldest": oldest_pending.isoformat() if oldest_pending else None,
            "analysis_batch_size": batch,
            "mean_gap": round(float(np.mean(mean_abs_gaps)), 2) if mean_abs_gaps else None,
            "cost_month": round(cost_month, 2), "cost_today": round(cost_today, 2), "cost_cap": cap,
        },
        "pipeline": {
            "status_counts": status_counts, "daily": list(daily.values()), "captured_24h": captured_24h,
            "last_ingestion": last_ing.isoformat() if last_ing else None, "errors_24h": errors_24h, "feeds": feeds,
            "captured_by_country": captured_by_country,
        },
        "movements": {"threshold": drift_threshold, "alerts": [m for m in movements if m["above_threshold"]][:8], "top": movements[:8]},
        "gaps": gaps[:8],
        "topics": topics, "blind_spots": blind,
        "agenda_today": _topic_rows(agenda_today, 8) if agenda_today else [],
        "topics_map": topics_map,
        "by_country": by_country,
        "leaders": leaders, "leadlag_events": leadlag_events,
        "dissidents": diss, "dissidents_above_threshold": dissident_threshold_met,
        "divisive": divisive,
        "accessible": [{"id": j.id, "name": j.name, "outlet_id": j.outlet_id, "outlet": oname, "role": j.role, "accessibility": round(j.accessibility_score or 0)} for j, oname in accessible],
        "clients": {
            "count": len(clients),
            "list": [{"id": c.id, "name": c.name, "sector": c.sector, "exposure": c.exposure} for c in clients[:6]],
            "recommendations": rec_status, "outcomes": outcomes,
            "recent": [{
                "id": r.id, "client_id": r.client_id, "client": cnames.get(r.client_id), "outlet_id": r.outlet_id, "outlet": outlets[r.outlet_id].name if r.outlet_id in outlets else None,
                "journalist": jnames.get(r.journalist_id), "action_type": r.action_type, "priority": round(r.priority or 0, 2), "status": r.status, "risk_level": r.risk_level,
            } for r in recent_recs],
        },
    }


def pipeline_health(db: Session) -> dict:
    """Dernier log d'ingestion, dernier article, flux, pause Google News."""
    from .extract import google_backoff_remaining
    now = datetime.utcnow()
    outlets = db.query(Outlet).order_by(Outlet.name).all()
    last_logs = (
        db.query(IngestionLog.outlet_id, func.max(IngestionLog.timestamp))
        .group_by(IngestionLog.outlet_id).all()
    )
    last_ts = dict(last_logs)
    last_err = {}
    for oid, ts in last_ts.items():
        row = (
            db.query(IngestionLog)
            .filter(IngestionLog.outlet_id == oid, IngestionLog.timestamp == ts)
            .first()
        )
        if row:
            last_err[oid] = {"status": row.status, "feed_type": row.feed_type, "error": row.error_message, "captured": row.articles_captured}
    last_art = dict(db.query(Article.outlet_id, func.max(Article.captured_at)).group_by(Article.outlet_id).all())
    feed_counts = dict(db.query(OutletFeed.outlet_id, func.count()).filter(OutletFeed.enabled == 1).group_by(OutletFeed.outlet_id).all())
    rows = []
    for o in outlets:
        last = last_art.get(o.id)
        stale = (not last) or ((now - last).total_seconds() > 48 * 3600)
        logi = last_err.get(o.id) or {}
        rows.append({
            "id": o.id, "name": o.name, "country": o.country,
            "collect_enabled": o.collect_enabled, "feeds_count": feed_counts.get(o.id, 0),
            "last_article": last.isoformat() if last else None,
            "stale_48h": stale and o.collect_enabled != 0,
            "last_ingest": last_ts[o.id].isoformat() if o.id in last_ts else None,
            "last_status": logi.get("status"), "last_error": logi.get("error"),
            "last_feed_type": logi.get("feed_type"), "last_captured": logi.get("captured"),
        })
    pending = db.query(func.count(Article.id)).filter(Article.analysis_status == "pending").scalar() or 0
    oldest = db.query(func.min(Article.captured_at)).filter(Article.analysis_status == "pending").scalar()
    backoff = google_backoff_remaining()
    return {
        "outlets": rows,
        "pending": pending,
        "pending_oldest": oldest.isoformat() if oldest else None,
        "google_news_backoff_s": round(backoff, 0),
        "generated_at": now.isoformat(),
    }
