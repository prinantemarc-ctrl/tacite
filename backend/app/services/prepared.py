"""Vues précalculées.

L'agenda et la cartographie ne se calculent plus dans la requête HTTP : le worker
les écrit ici, l'API ne fait qu'une lecture. Une clé absente répond tout de suite
avec ``preparing`` plutôt que de lancer un clustering.
"""

from __future__ import annotations

import copy
import logging
import time
from datetime import date, datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from ..i18n import get_locale, set_locale
from ..models import Outlet, PreparedView
from ..tenant import current_user_id

log = logging.getLogger("tacite.prepared")

LOCALES = ("fr", "en")
AGENDA_CAP = {1: 400, 7: 700, 14: 700, 30: 700, 60: 700}
LANDSCAPE_WEEKS = (8, 4, 12, 26)


def _scope(country: str | None) -> str:
    return (country or "").upper() or "_"


def agenda_key(days: int, country: str | None) -> str:
    return f"agenda:{int(days)}:{_scope(country)}:{AGENDA_CAP[int(days)]}"


def landscape_key(weeks: int, country: str | None) -> str:
    return f"landscape:{int(weeks)}:5:{_scope(country)}"


def dissidents_key() -> str:
    return "dissidents:8:5:40"


def leadlag_key(days: int, window_hours: int, cap: int | None) -> str:
    return f"leadlag:{int(days)}:{int(window_hours)}:{cap if cap else '_'}"


def entities_key(days: int, limit: int, country: str | None, cap: int | None) -> str:
    return f"entities:{int(days)}:{int(limit)}:{_scope(country)}:{cap if cap else '_'}"


def network_key(days: int = 90, top_journalists: int = 60) -> str:
    return f"network:{int(days)}:{int(top_journalists)}"


def world_key(days: int = 30) -> str:
    return f"world:{int(days)}"


def corpus_key(limit: int = 1500, days: int = 60) -> str:
    return f"corpus:{int(limit)}:{int(days)}"


def packs_key(days: int = 60) -> str:
    return f"packs:{int(days)}"


def jsonable(obj):
    """Dict / listes prêts pour une colonne JSON (les centroïdes numpy deviennent des listes)."""
    if obj is None or isinstance(obj, (str, bool)):
        return obj
    if isinstance(obj, dict):
        return {str(k): jsonable(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple, set)):
        return [jsonable(v) for v in obj]
    if isinstance(obj, np.ndarray):
        return jsonable(obj.tolist())
    if isinstance(obj, (np.integer, int)):
        return int(obj)
    if isinstance(obj, (np.floating, float)):
        x = float(obj)
        if x != x or x in (float("inf"), float("-inf")):
            return None
        return round(x, 5)
    if isinstance(obj, datetime):
        return obj.isoformat()
    if isinstance(obj, date):
        return obj.isoformat()
    return obj


def _full(key: str, locale: str | None = None) -> str:
    return f"{locale or get_locale()}:{key}"


def load(db: Session, key: str):
    uid = current_user_id()
    q = db.query(PreparedView).filter(PreparedView.key == _full(key))
    if uid is not None:
        q = q.filter(PreparedView.user_id == uid)
    row = q.order_by(PreparedView.computed_at.desc()).first()
    if row is None or row.payload is None:
        return None
    return copy.deepcopy(row.payload)


def exists(db: Session, key: str) -> bool:
    uid = current_user_id()
    q = db.query(PreparedView.id).filter(PreparedView.key == _full(key))
    if uid is not None:
        q = q.filter(PreparedView.user_id == uid)
    return q.first() is not None


def put(db: Session, key: str, payload, locales: tuple[str, ...] | None = None) -> None:
    uid = current_user_id()
    if uid is None:
        return
    data = jsonable(payload)
    now = datetime.utcnow()
    for loc in (locales or (get_locale(),)):
        full = _full(key, loc)
        blob = copy.deepcopy(data)
        row = (
            db.query(PreparedView)
            .filter(PreparedView.user_id == uid, PreparedView.key == full)
            .one_or_none()
        )
        if row is None:
            db.add(PreparedView(user_id=uid, key=full, payload=blob, computed_at=now))
        else:
            row.payload = blob
            row.computed_at = now
    db.commit()


def _since_days(days: int) -> str:
    return (datetime.utcnow() - timedelta(days=days)).date().isoformat()


def _since_weeks(weeks: int) -> str:
    return (datetime.utcnow() - timedelta(weeks=weeks)).date().isoformat()


def empty_landscape(weeks: int, country: str | None) -> dict:
    return {
        "since": _since_weeks(weeks), "weeks": weeks, "explained_variance": [], "axes": [],
        "outlets": [], "journalists": [], "clusters": [],
        "country": country, "kit_axes": [], "preparing": True,
    }


def empty_network(days: int = 90) -> dict:
    return {
        "since": _since_days(days), "nodes": [], "edges": [], "communities": [],
        "stats": {"citations": 0, "cocoverage_pairs": 0}, "preparing": True,
    }


def empty_world(days: int = 30) -> dict:
    return {
        "since": _since_days(days), "countries": [], "flows": [], "regions": {},
        "total_countries_known": 0, "preparing": True,
    }


def empty_corpus() -> dict:
    return {"points": [], "topics": [], "blind_spots": [], "explained_variance": [], "preparing": True}


def empty_leadlag(window_hours: int = 72) -> dict:
    return {
        "since": _since_days(30), "window_hours": window_hours, "events": 0,
        "ranking": [], "pairs": [], "preparing": True,
    }


def empty_packs() -> dict:
    return {"outlets": [], "topic_similarity": [], "framing_similarity": [], "pairs": [], "order": [], "preparing": True}


def empty_entities() -> dict:
    return {"since": _since_days(60), "entities": [], "outlets": [], "preparing": True}


def _step(db: Session, key: str, fn, locales: tuple[str, ...] | None = None):
    t0 = time.perf_counter()
    try:
        payload = fn()
        put(db, key, payload, locales=locales)
        log.info("vue %s prête (%.1fs)", key, time.perf_counter() - t0)
        return payload
    except Exception:
        log.exception("vue %s échouée", key)
        db.rollback()
        return None


def refresh_user(db: Session, with_briefs: bool = False, full: bool = False) -> None:
    """Recalcule les vues du compte courant, sans bypass : chaque compte garde son corpus.

    ``full`` est le passage horaire (paysage, fenêtres longues, briefs). Le passage
    court, toutes les dix minutes, ne refait que l'agenda du jour et de la semaine.
    """
    from . import cartography as carto
    from . import topics as topics_svc

    from sqlalchemy import func

    from ..models import Article

    carto.invalidate()
    topics_svc.invalidate()
    since = datetime.utcnow() - timedelta(days=60)
    counted = (
        db.query(Outlet.country, func.count(Article.id))
        .join(Article, Article.outlet_id == Outlet.id)
        .filter(Article.analysis_status == "analyzed", Article.published_at >= since)
        .group_by(Outlet.country)
        .all()
    )
    # Les pays sans article récent n'ont pas de vue à préparer. Les plus fournis d'abord.
    countries = [(code or "").upper() for code, _n in sorted(counted, key=lambda r: -r[1]) if code]
    log.info("calcul des vues (%d pays, full=%s, briefs=%s)", len(countries), full, with_briefs)

    def agenda(days: int, country: str | None):
        return topics_svc._agenda(
            db, days, country, None, None, topics_svc.MIN_CLUSTER, False, AGENDA_CAP[days],
        )

    def save_agenda(days: int, country: str | None):
        _step(db, agenda_key(days, country), lambda d=days, c=country: agenda(d, c), locales=LOCALES)

    def save_landscape(weeks: int, country: str | None):
        for loc in LOCALES:
            set_locale(loc)
            data = _step(
                db, landscape_key(weeks, country),
                lambda w=weeks, c=country: carto._landscape(db, w, 5, c, None),
            )
            if data is not None and weeks == 8 and country is None:
                try:
                    put(db, dissidents_key(), carto.dissidents_from(db, data, 8, 40))
                    log.info("vue %s prête (%s)", dissidents_key(), loc)
                except Exception:
                    log.exception("vue %s échouée", dissidents_key())
                    db.rollback()

    # D'abord ce que le tableau de bord affiche sans filtre pays.
    for days in (7, 1):
        save_agenda(days, None)
    save_landscape(8, None)
    _step(db, leadlag_key(14, 72, 1500), lambda: carto._leadlag(db, 14, 72, 1500), locales=LOCALES)
    _step(db, entities_key(30, 40, None, 1500), lambda: carto._entities(db, 30, 40, None, 1500), locales=LOCALES)

    for country in countries:
        for days in (7, 1):
            save_agenda(days, country)
        _step(
            db, entities_key(30, 40, country, 1500),
            lambda c=country: carto._entities(db, 30, 40, c, 1500),
            locales=LOCALES,
        )

    if not full:
        return

    for country in countries:
        save_landscape(8, country)

    for days in (14, 30, 60):
        save_agenda(days, None)
        for country in countries:
            save_agenda(days, country)

    for weeks in (4, 12, 26):
        save_landscape(weeks, None)
        for country in countries:
            save_landscape(weeks, country)

    _step(db, leadlag_key(30, 72, None), lambda: carto._leadlag(db, 30, 72, None), locales=LOCALES)
    _step(db, network_key(), lambda: carto._network(db, 90, 60), locales=LOCALES)
    _step(db, world_key(), lambda: carto._world(db, 30), locales=LOCALES)
    _step(db, corpus_key(), lambda: carto._corpus(db, 1500, 60), locales=LOCALES)
    _step(db, packs_key(), lambda: carto._packs(db, 60), locales=LOCALES)
    _step(db, entities_key(60, 80, None, None), lambda: carto._entities(db, 60, 80, None, None), locales=LOCALES)
    for country in countries:
        _step(
            db, entities_key(60, 80, country, None),
            lambda c=country: carto._entities(db, 60, 80, c, None),
            locales=LOCALES,
        )

    if not with_briefs:
        return
    for country in (None, *countries):
        for loc in LOCALES:
            set_locale(loc)
            raw = load(db, agenda_key(7, country))
            if not raw:
                continue
            try:
                put(db, agenda_key(7, country), topics_svc._with_briefs(db, raw))
                log.info("briefs agenda 7 %s (%s)", _scope(country), loc)
            except Exception:
                log.exception("briefs agenda 7 %s (%s)", _scope(country), loc)
                db.rollback()
