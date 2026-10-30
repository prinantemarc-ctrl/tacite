"""FastAPI application — Tacite API."""

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime, timedelta

from fastapi import Depends, FastAPI, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, String
from sqlalchemy.orm import Session
from starlette.middleware.base import BaseHTTPMiddleware

from .constants import AXES, AXIS_LABELS_FR, ACTION_TYPES, DEFAULT_SETTINGS, FR_AXIS_ZONE, FR_SPECIFIC_AXES, axes_for_country
from .i18n import parse_accept_language, set_locale, axis_labels, axis_poles_map, msg
from .database import get_db, init_db
from pydantic import BaseModel

from .models import (
    ActionHistory, AgentAction, Article, ArticleJournalist, Artifact, Client, ClientBlacklist, ClientContact, ContactScan,
    Conversation, IngestionLog, Journalist, JournalistContact, JournalistProfile, LLMUsage, Message, Outlet,
    OutletFeed, OutletProfile, Recommendation, Setting, row_to_dict,
)
from .schemas import (
    ArticleSearchIn, BlacklistIn, ClientIn, ClientUpdate, ContactIn, JournalistIn,
    JournalistUpdate, OutletIn, OutletUpdate, OutcomeIn,
    RecommendationUpdate, SettingsUpdate,
)
from .services import rss, analysis, profiles, recommend
from .settings_store import get_setting, get_settings, set_setting

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
log = logging.getLogger("tacite")


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    from .accounts import bootstrap_owner
    bootstrap_owner()
    log.info("Database initialised")
    yield


app = FastAPI(title="Tacite API", version="0.1.0", lifespan=lifespan)


from .accounts import AuthMiddleware, router as auth_router

app.add_middleware(AuthMiddleware)


class LocaleMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        set_locale(parse_accept_language(request.headers.get("accept-language")))
        return await call_next(request)


app.add_middleware(LocaleMiddleware)


app.include_router(auth_router)

from .mcp_server import router as mcp_router

app.include_router(mcp_router)


@app.get("/api/health")
def health():
    return {"ok": True}


def _outlet_names(db: Session) -> dict[int, str]:
    return {o.id: o.name for o in db.query(Outlet).all()}


def _journalist_names(db: Session) -> dict[int, str]:
    return {j.id: j.name for j in db.query(Journalist).all()}


def _latest_journalist_themes(db: Session, journalist_ids: list[int]) -> dict[int, list]:
    """Dernières fixations (sujets de prédilection) par journaliste."""
    if not journalist_ids:
        return {}
    latest = (
        db.query(JournalistProfile.journalist_id, func.max(JournalistProfile.date).label("d"))
        .filter(JournalistProfile.journalist_id.in_(journalist_ids))
        .group_by(JournalistProfile.journalist_id)
        .subquery()
    )
    rows = (
        db.query(JournalistProfile)
        .join(latest, (JournalistProfile.journalist_id == latest.c.journalist_id) & (JournalistProfile.date == latest.c.d))
        .all()
    )
    out: dict[int, list] = {}
    for p in rows:
        cleaned = []
        for t in (p.themes or [])[:6]:
            if isinstance(t, dict) and t.get("label"):
                cleaned.append({"label": t["label"], "count": t.get("count") or 0})
            elif isinstance(t, str) and t.strip():
                cleaned.append({"label": t.strip(), "count": 0})
        out[p.journalist_id] = cleaned
    return out


# ----------------------------------------------------------------- dashboard

@app.get("/api/dashboard")
def dashboard(country: str | None = Query(None), db: Session = Depends(get_db)):
    from .services import dashboard as dash
    return dash.build(db, country=country)


@app.get("/api/pipeline/health")
def pipeline_health(db: Session = Depends(get_db)):
    from .services import dashboard as dash
    return dash.pipeline_health(db)


@app.get("/api/dashboard/legacy")
def dashboard_legacy(db: Session = Depends(get_db)):
    outlets = db.query(Outlet).count()
    journalists = db.query(Journalist).count()
    articles = db.query(Article).count()
    alerts = (
        db.query(OutletProfile)
        .filter(OutletProfile.drift_alerts.cast(String) != "[]")
        .order_by(OutletProfile.week.desc())
        .limit(10)
        .all()
    )
    recent_recs = (
        db.query(Recommendation)
        .order_by(Recommendation.created_at.desc())
        .limit(10)
        .all()
    )
    today = datetime.utcnow().date()
    month_start = today.replace(day=1)
    cost_row = db.query(func.sum(LLMUsage.cost_usd)).filter(LLMUsage.date >= month_start).scalar() or 0
    onames = _outlet_names(db)
    return {
        "outlets": outlets,
        "journalists": journalists,
        "articles": articles,
        "alerts": [{**row_to_dict(a), "outlet_name": onames.get(a.outlet_id)} for a in alerts],
        "recent_recommendations": [{**row_to_dict(r), "outlet_name": onames.get(r.outlet_id)} for r in recent_recs],
        "monthly_cost_usd": round(float(cost_row), 2),
    }


# ------------------------------------------------------------------- outlets

@app.get("/api/outlets")
def list_outlets(country: str | None = None, view: str = Query("full"), db: Session = Depends(get_db)):
    """`view=brief` : id, nom, pays — pour les listes déroulantes.
    `view=full` : volume, influence, écart, dérive. Les sujets et les journalistes
    restent sur la fiche : les recalculer ici relit huit semaines d'articles."""
    q = db.query(Outlet)
    if country:
        q = q.filter(Outlet.country == country.upper())
    if view == "brief":
        rows = (
            q.with_entities(
                Outlet.id, Outlet.name, Outlet.country, Outlet.language,
                Outlet.influence_score, Outlet.collect_enabled,
            )
            .order_by(Outlet.name.asc())
            .all()
        )
        return [
            {
                "id": i, "name": name, "country": c, "language": lang,
                "influence_score": infl, "collect_enabled": enabled,
            }
            for i, name, c, lang, infl, enabled in rows
        ]
    rows = q.order_by(Outlet.influence_score.desc(), Outlet.name.asc()).all()
    if not rows:
        return []
    # Dernier profil hebdomadaire par média (écart officiel/réel, nb d'articles)
    latest_week = (
        db.query(OutletProfile.outlet_id, func.max(OutletProfile.week).label("week"))
        .group_by(OutletProfile.outlet_id).subquery()
    )
    profs = (
        db.query(OutletProfile)
        .join(latest_week, (OutletProfile.outlet_id == latest_week.c.outlet_id) & (OutletProfile.week == latest_week.c.week))
        .all()
    )
    by_outlet = {p.outlet_id: p for p in profs}
    feed_counts = dict(db.query(OutletFeed.outlet_id, func.count()).filter(OutletFeed.enabled == 1).group_by(OutletFeed.outlet_id).all())
    article_counts = dict(db.query(Article.outlet_id, func.count()).group_by(Article.outlet_id).all())
    from .kits import axes_for_countries
    axes = axes_for_countries((o.country for o in rows), db)
    out = []
    for o in rows:
        d = row_to_dict(o)
        p = by_outlet.get(o.id)
        d["latest_profile"] = {"week": p.week.isoformat(), "gap_from_official": p.gap_from_official, "article_count": p.article_count, "drift_alerts": p.drift_alerts, "axis_n": p.axis_n or {}} if p else None
        d["feeds_count"] = feed_counts.get(o.id, 0)
        d["articles_total"] = int(article_counts.get(o.id, 0) or 0)
        d["articles_week"] = int(p.article_count or 0) if p else 0
        d["confidence"] = profiles.confidence_label(profiles.evidence_n(p.axis_n if p else None, p.article_count if p else 0))
        d["max_gap"] = profiles.max_usable_gap(
            o.country, p.gap_from_official if p else None, p.axis_n if p else None,
            usable=axes.get((o.country or "").upper()),
        )
        out.append(d)
    return out


def _complete_outlet(db: Session, o: Outlet) -> None:
    """Fill official classification + influence meta via LLM when missing."""
    from .services import llm
    has_oc = any(v for v in (o.official_classification or {}).values())
    if has_oc and o.meta:
        return
    est = llm.estimate_official_classification(
        db, get_setting(db, "llm_profile_model"), o.name, o.country or "", o.language or "", o.declared_orientation or ""
    )
    if est:
        if not has_oc:
            o.official_classification = est["official_classification"]
        if not o.meta:
            o.meta = est["meta"]


@app.post("/api/outlets", status_code=201)
def create_outlet(data: OutletIn, db: Session = Depends(get_db)):
    from . import geo
    payload = data.model_dump()
    payload["country"] = (payload.get("country") or "").upper()
    if not geo.is_valid(payload["country"]):
        raise HTTPException(400, msg(f"Code pays inconnu : {payload['country']}", f"Unknown country code: {payload['country']}"))
    o = Outlet(**payload)
    db.add(o)
    db.flush()
    _complete_outlet(db, o)
    if o.rss_url:
        db.add(OutletFeed(outlet_id=o.id, url=o.rss_url, label="une", feed_type="rss"))
    db.commit()
    from .services import cartography, topics as topics_svc
    cartography.invalidate()
    topics_svc.invalidate()
    return row_to_dict(o)


@app.post("/api/outlets/import")
async def import_outlets(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """Import CSV : name, country, language, website_url, rss_url, declared_orientation,
    audience_score, elite_score, network_score, longevity_score. Ligne existante (même nom + pays) → mise à jour."""
    import csv
    import io
    from . import geo

    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    sample = raw[:2048]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(raw), dialect=dialect)
    created = updated = 0
    errors: list[str] = []
    existing = {(o.name.strip().lower(), (o.country or "").upper()): o for o in db.query(Outlet).all()}
    for i, row in enumerate(reader, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        name, country = row.get("name", ""), row.get("country", "").upper()
        if not name or not geo.is_valid(country):
            errors.append(f"ligne {i}: nom ou pays invalide ({name!r}, {country!r})")
            continue
        meta = {k: int(float(row[k])) for k in ("audience_score", "elite_score", "network_score", "longevity_score") if row.get(k)}
        o = existing.get((name.lower(), country))
        if o:
            for k in ("website_url", "rss_url", "declared_orientation", "language"):
                if row.get(k):
                    setattr(o, k, row[k])
            if meta:
                o.meta = {**(o.meta or {}), **meta}
            updated += 1
        else:
            o = Outlet(name=name, country=country, language=row.get("language") or "en", website_url=row.get("website_url") or None,
                       rss_url=row.get("rss_url") or None, declared_orientation=row.get("declared_orientation") or None,
                       official_classification={}, meta=meta)
            db.add(o)
            db.flush()
            existing[(name.lower(), country)] = o
            created += 1
        if o.rss_url and not db.query(OutletFeed).filter(OutletFeed.outlet_id == o.id, OutletFeed.url == o.rss_url).first():
            db.add(OutletFeed(outlet_id=o.id, url=o.rss_url, label="une", feed_type="rss"))
        try:
            _complete_outlet(db, o)
        except Exception as e:  # noqa: BLE001
            errors.append(f"ligne {i}: estimation LLM impossible ({e})")
    db.commit()
    from .services import cartography, topics as topics_svc
    cartography.invalidate()
    topics_svc.invalidate()
    return {"created": created, "updated": updated, "errors": errors[:50]}


# ------------------------------------------------- suggestion de médias par pays

class KitAssignIn(BaseModel):
    kit_id: str


class KitCreateIn(BaseModel):
    id: str | None = None
    label_fr: str
    label_en: str
    prompt_en: str | None = None
    prompt: str | None = None
    countries: list[str] = []
    axes: list[dict] = []


@app.get("/api/kits")
def api_list_kits(db: Session = Depends(get_db)):
    from . import kits as K
    from .i18n import get_locale
    loc = get_locale()
    return {
        "kits": [K.serialize_kit(None if k["id"] == K.STRUCTURAL_ONLY_ID else K.get_kit(k["id"], db) or k, loc) for k in K.list_kits(db)],
        "country_kits": {**K.DEFAULT_COUNTRY_KIT, **K._country_overrides(db)},
        "structural": [K.public_axis_meta(a, loc) for a in K.STRUCTURAL_IDS],
    }


@app.get("/api/kits/for-country/{code}")
def api_kit_for_country(code: str, db: Session = Depends(get_db)):
    from . import kits as K
    from .i18n import get_locale
    loc = get_locale()
    kid = K.kit_id_for_country(code, db)
    assigned = kid is not None or code.upper() in K._country_overrides(db)
    kit = K.kit_for_country(code, db)
    return {
        "country": code.upper(),
        "kit_id": kid or (K.STRUCTURAL_ONLY_ID if assigned else None),
        "assigned": bool(kid) or code.upper() in K._country_overrides(db) or code.upper() in K.DEFAULT_COUNTRY_KIT,
        "builtin_default": K.DEFAULT_COUNTRY_KIT.get(code.upper()),
        "kit": K.serialize_kit(kit, loc),
        "display_axes": K.axes_for_country(code, db),
    }


@app.post("/api/kits/assign/{code}")
def api_assign_kit(code: str, data: KitAssignIn, db: Session = Depends(get_db)):
    from . import kits as K
    from . import geo
    if not geo.is_valid(code.upper()):
        raise HTTPException(400, msg(f"Code pays inconnu : {code}", f"Unknown country code: {code}"))
    try:
        return K.assign_country_kit(db, code, data.kit_id)
    except ValueError as e:
        raise HTTPException(400, str(e)) from e


@app.post("/api/kits", status_code=201)
def api_create_kit(data: KitCreateIn, db: Session = Depends(get_db)):
    from . import kits as K
    try:
        kit = K.create_custom_kit(db, data.model_dump())
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    from .i18n import get_locale
    return K.serialize_kit(kit, get_locale())


class SuggestedOutletIn(BaseModel):
    name: str
    website_url: str | None = None
    language: str | None = None
    declared_orientation: str | None = None
    feeds: list[str] = []


class BulkOutletsIn(BaseModel):
    items: list[SuggestedOutletIn]


@app.get("/api/countries/{code}/suggest-outlets")
def suggest_outlets_for_country(code: str, force: bool = Query(False), cached: bool = Query(False), db: Session = Depends(get_db)):
    """Médias proposés pour un pays : LLM + recherche web, puis vérification (site, flux RSS).
    Long au premier appel (~30-60 s), mis en cache 3 jours.
    cached=true : renvoie uniquement le cache (suggestions=null s'il n'y en a pas), sans rien lancer."""
    from .services import suggest
    try:
        if cached and not force:
            return {"country": code.upper(), "suggestions": suggest.cached_suggestions(db, code)}
        return {"country": code.upper(), "suggestions": suggest.suggest(db, code, force=force)}
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # noqa: BLE001
        log.exception("suggest outlets")
        raise HTTPException(502, msg(f"suggestion impossible : {e}", f"suggestion failed: {e}"))


@app.post("/api/countries/{code}/resolve-outlet")
def resolve_outlet_name(code: str, name: str = Query(...), db: Session = Depends(get_db)):
    """Résout un nom de média saisi librement : site officiel via recherche web + vérification des flux."""
    from .services import suggest
    try:
        return suggest.resolve(db, name, code)
    except Exception as e:  # noqa: BLE001
        log.exception("resolve outlet")
        raise HTTPException(502, msg(f"résolution impossible : {e}", f"resolution failed: {e}"))


class ReverifyIn(BaseModel):
    name: str
    website_url: str | None = None
    language: str | None = None
    type: str | None = None
    declared_orientation: str | None = None
    audience: str | None = None


@app.post("/api/countries/{code}/reverify-outlet")
def reverify_outlet(code: str, data: ReverifyIn, db: Session = Depends(get_db)):
    """Re-teste un candidat (site, flux) — bouton « Réessayer » de la modale."""
    from .services import suggest
    return suggest.reverify(db, code, data.model_dump())


@app.post("/api/countries/{code}/outlets", status_code=201)
def add_outlets_bulk(code: str, data: BulkOutletsIn, db: Session = Depends(get_db)):
    """Crée d'un coup les médias sélectionnés dans la modale (fiches + flux + estimation LLM)."""
    from . import geo
    from .services import suggest
    if not geo.is_valid(code.upper()):
        raise HTTPException(400, msg(f"Code pays inconnu : {code}", f"Unknown country code: {code}"))
    return suggest.create_from_suggestions(db, code, [i.model_dump() for i in data.items])


@app.get("/api/outlets/{outlet_id}")
def get_outlet(outlet_id: int, db: Session = Depends(get_db)):
    o = db.get(Outlet, outlet_id)
    if not o:
        raise HTTPException(404, "Outlet not found")
    result = row_to_dict(o)
    journalists = db.query(Journalist).filter(Journalist.outlet_id == outlet_id).all()
    result["journalists"] = [row_to_dict(j) for j in journalists]
    # Feeds
    feeds = db.query(OutletFeed).filter(OutletFeed.outlet_id == outlet_id).all()
    result["feeds"] = [row_to_dict(f) for f in feeds]
    # Latest profile
    prof = db.query(OutletProfile).filter(OutletProfile.outlet_id == outlet_id).order_by(OutletProfile.week.desc()).first()
    result["latest_profile"] = row_to_dict(prof) if prof else None
    result["articles_total"] = db.query(func.count(Article.id)).filter(Article.outlet_id == outlet_id).scalar() or 0
    result["articles_week"] = int(prof.article_count or 0) if prof else 0
    result["confidence"] = profiles.confidence_label(profiles.evidence_n(prof.axis_n if prof else None, prof.article_count if prof else 0))
    result["max_gap"] = profiles.max_usable_gap(o.country, prof.gap_from_official if prof else None, prof.axis_n if prof else None, db)
    recap = profiles.recap_for_outlets(db, [outlet_id], topics_n=8, journalists_n=200).get(outlet_id) or {}
    result["topics"] = recap.get("topics") or []
    result["top_journalists"] = recap.get("journalists") or []
    result["journalists_count"] = int(recap.get("journalists_count") or len(journalists))
    by_n = {j["id"]: j["articles"] for j in result["top_journalists"]}
    for j in result["journalists"]:
        j["articles_window"] = by_n.get(j["id"], 0)
    return result


@app.put("/api/outlets/{outlet_id}")
def update_outlet(outlet_id: int, data: OutletUpdate, db: Session = Depends(get_db)):
    o = db.get(Outlet, outlet_id)
    if not o:
        raise HTTPException(404)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(o, k, v)
    db.commit()
    return row_to_dict(o)


@app.delete("/api/outlets/{outlet_id}", status_code=204)
def delete_outlet(outlet_id: int, db: Session = Depends(get_db)):
    o = db.get(Outlet, outlet_id)
    if not o:
        raise HTTPException(404)
    db.delete(o)
    db.commit()


@app.get("/api/outlets/{outlet_id}/profiles")
def outlet_profiles(outlet_id: int, db: Session = Depends(get_db)):
    rows = db.query(OutletProfile).filter(OutletProfile.outlet_id == outlet_id).order_by(OutletProfile.week.desc()).all()
    return [row_to_dict(p) for p in rows]


@app.get("/api/outlets/{outlet_id}/articles")
def outlet_articles(outlet_id: int, limit: int = Query(50, le=200), offset: int = 0, db: Session = Depends(get_db)):
    rows = db.query(Article).filter(Article.outlet_id == outlet_id).order_by(Article.published_at.desc()).offset(offset).limit(limit).all()
    onames = _outlet_names(db)
    jids = {a.journalist_id for a in rows if a.journalist_id}
    jnames = {j.id: j.name for j in db.query(Journalist).filter(Journalist.id.in_(jids)).all()} if jids else {}
    authors = _authors_of(db, [a.id for a in rows])
    return [_article_public(a, onames, jnames, authors.get(a.id)) for a in rows]


# --------------------------------------------------------------- journalists

@app.get("/api/journalists")
def list_journalists(db: Session = Depends(get_db)):
    from .services import contacts as C
    rows = db.query(Journalist).all()
    ids = [j.id for j in rows]
    outlets = db.query(Outlet.id, Outlet.name, Outlet.country).all()
    onames = {oid: name for oid, name, _ in outlets}
    ocountries = {oid: (country or "").upper() for oid, _, country in outlets}
    cs = C.summary_for_many(db, ids)
    themes = _latest_journalist_themes(db, ids)
    out = []
    for j in rows:
        d = row_to_dict(j)
        d["outlet_name"] = onames.get(j.outlet_id)
        d["country"] = ocountries.get(j.outlet_id) or ""
        c = cs.get(j.id) or {"kinds": [], "best": None, "n": 0, "has_contact": False}
        if not c.get("has_contact") and (j.twitter_handle or j.linkedin_url):
            c = {**c, "has_contact": True}
        d["contacts"] = c
        d["themes"] = themes.get(j.id) or []
        out.append(d)
    return out


# ---------------------------------------------------------------- contacts

class ContactCreate(BaseModel):
    kind: str
    value: str
    note: str | None = None


@app.get("/api/journalists/{jid}/contacts")
def journalist_contacts(jid: int, db: Session = Depends(get_db)):
    from .services import contacts as C
    if not db.get(Journalist, jid):
        raise HTTPException(404)
    scan = db.get(ContactScan, jid)
    return {"contacts": C.list_for(db, jid, include_invalid=True), "scanned_at": scan.scanned_at.isoformat() if scan else None}


@app.post("/api/journalists/{jid}/contacts", status_code=201)
def journalist_add_contact(jid: int, data: ContactCreate, db: Session = Depends(get_db)):
    from .services import contacts as C
    if not db.get(Journalist, jid):
        raise HTTPException(404)
    if data.kind not in C.KINDS:
        raise HTTPException(400, msg("type inconnu", "unknown type"))
    C.upsert_many(db, jid, [{"kind": data.kind, "value": data.value.strip(), "confidence": "verified", "method": "manual", "note": data.note or "saisi manuellement"}], None)
    return C.list_for(db, jid, include_invalid=True)


@app.post("/api/journalists/{jid}/contacts/discover")
def journalist_discover_contacts(jid: int, db: Session = Depends(get_db)):
    from .services import contacts as C
    j = db.get(Journalist, jid)
    if not j:
        raise HTTPException(404)
    r = C.discover(db, j, fetch_pages=True, bluesky=True)
    return {**r, "contacts": C.list_for(db, jid, include_invalid=True)}


@app.put("/api/contacts/{cid}")
def update_contact(cid: int, invalid: bool | None = Query(None), note: str | None = Query(None), db: Session = Depends(get_db)):
    from .services import contacts as C
    c = db.get(JournalistContact, cid)
    if not c:
        raise HTTPException(404)
    if invalid is not None:
        c.invalid = 1 if invalid else 0
    if note is not None:
        c.note = note
    db.commit()
    C._refresh_denormalized(db, c.journalist_id)
    return row_to_dict(c)


@app.delete("/api/contacts/{cid}", status_code=204)
def delete_contact(cid: int, db: Session = Depends(get_db)):
    from .services import contacts as C
    c = db.get(JournalistContact, cid)
    if not c:
        raise HTTPException(404)
    jid = c.journalist_id
    db.delete(c)
    db.commit()
    C._refresh_denormalized(db, jid)


@app.get("/api/maintenance/contacts")
def contacts_status(db: Session = Depends(get_db)):
    from .services import contacts as C
    return C.stats(db)


@app.post("/api/maintenance/contacts")
def contacts_run(limit: int = Query(300, le=5000), fetch_pages: bool = Query(True)):
    from .services import contacts as C
    return {"started": C.start_background(limit=limit, fetch_pages=fetch_pages), "job": C.STATE}


@app.post("/api/maintenance/bylines")
def bylines_run(limit: int | None = Query(None), db: Session = Depends(get_db)):
    from .services import bylines
    return bylines.backfill(db, limit=limit)


@app.post("/api/maintenance/purge-guessed-handles")
def purge_guessed(db: Session = Depends(get_db)):
    from .services import contacts as C
    bad = C.purge_bad_contacts(db)
    return {"cleared": C.purge_unsourced_handles(db), "bad_contacts_removed": bad}


@app.post("/api/journalists", status_code=201)
def create_journalist(data: JournalistIn, db: Session = Depends(get_db)):
    j = Journalist(**data.model_dump())
    db.add(j)
    db.commit()
    return row_to_dict(j)


@app.get("/api/journalists/{jid}")
def get_journalist(jid: int, db: Session = Depends(get_db)):
    j = db.get(Journalist, jid)
    if not j:
        raise HTTPException(404)
    onames = _outlet_names(db)
    result = row_to_dict(j)
    result["outlet_name"] = onames.get(j.outlet_id)
    # Latest profile
    prof = db.query(JournalistProfile).filter(JournalistProfile.journalist_id == jid).order_by(JournalistProfile.date.desc()).first()
    result["latest_profile"] = row_to_dict(prof) if prof else None
    from .services import contacts as C
    result["contacts"] = C.list_for(db, jid, include_invalid=True)
    scan = db.get(ContactScan, jid)
    result["contacts_scanned_at"] = scan.scanned_at.isoformat() if scan else None
    return result


@app.put("/api/journalists/{jid}")
def update_journalist(jid: int, data: JournalistUpdate, db: Session = Depends(get_db)):
    j = db.get(Journalist, jid)
    if not j:
        raise HTTPException(404)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(j, k, v)
    db.commit()
    return row_to_dict(j)


@app.delete("/api/journalists/{jid}", status_code=204)
def delete_journalist(jid: int, db: Session = Depends(get_db)):
    j = db.get(Journalist, jid)
    if not j:
        raise HTTPException(404)
    db.query(Article).filter(Article.journalist_id == jid).update({Article.journalist_id: None}, synchronize_session=False)
    db.query(Recommendation).filter(Recommendation.journalist_id == jid).update({Recommendation.journalist_id: None}, synchronize_session=False)
    for model in (JournalistProfile, JournalistContact, ContactScan, ClientContact):
        db.query(model).filter(model.journalist_id == jid).delete(synchronize_session=False)
    db.delete(j)
    db.commit()


@app.post("/api/journalists/cleanup")
def cleanup_journalists(db: Session = Depends(get_db)):
    """Normalise journalist names with the same rules as the RSS parser.

    - invalid bylines (media names, agencies, desks, single words...) are removed
    - names carrying byline noise ("X in Berlin", "X Political editor", "Recueilli par X")
      are renamed, or merged into the existing clean entry of the same outlet
    Articles are always preserved (re-attached or detached).
    """
    from .services.rss import clean_author_name

    all_js = db.query(Journalist).all()
    by_key = {(j.outlet_id, j.name.strip().lower()): j for j in all_js}

    renamed = merged = 0
    remove_ids: list[int] = []
    for j in all_js:
        clean = clean_author_name(j.name)
        if clean is None:
            remove_ids.append(j.id)
            continue
        if clean == j.name.strip():
            continue
        target = by_key.get((j.outlet_id, clean.lower()))
        if target and target.id != j.id:
            db.query(Article).filter(Article.journalist_id == j.id).update(
                {Article.journalist_id: target.id}, synchronize_session=False
            )
            db.query(JournalistContact).filter(JournalistContact.journalist_id == j.id).update(
                {JournalistContact.journalist_id: target.id}, synchronize_session=False
            )
            db.query(ClientContact).filter(ClientContact.journalist_id == j.id).update(
                {ClientContact.journalist_id: target.id}, synchronize_session=False
            )
            db.query(Recommendation).filter(Recommendation.journalist_id == j.id).update(
                {Recommendation.journalist_id: target.id}, synchronize_session=False
            )
            # keep enrichment if the target has none
            if not target.bio and j.bio:
                target.bio, target.role = j.bio, j.role
                target.twitter_handle = target.twitter_handle or j.twitter_handle
            remove_ids.append(j.id)
            merged += 1
        else:
            j.name = clean
            by_key[(j.outlet_id, clean.lower())] = j
            renamed += 1
    db.flush()

    removed = 0
    if remove_ids:
        # Merged ids already had their articles moved; invalid ones get detached
        db.query(Article).filter(Article.journalist_id.in_(remove_ids)).update(
            {Article.journalist_id: None}, synchronize_session=False
        )
        db.query(Recommendation).filter(Recommendation.journalist_id.in_(remove_ids)).update(
            {Recommendation.journalist_id: None}, synchronize_session=False
        )
        db.query(ClientContact).filter(ClientContact.journalist_id.in_(remove_ids)).delete(
            synchronize_session=False
        )
        db.query(JournalistProfile).filter(JournalistProfile.journalist_id.in_(remove_ids)).delete(
            synchronize_session=False
        )
        db.query(JournalistContact).filter(JournalistContact.journalist_id.in_(remove_ids)).delete(synchronize_session=False)
        db.query(ContactScan).filter(ContactScan.journalist_id.in_(remove_ids)).delete(synchronize_session=False)
        removed = db.query(Journalist).filter(Journalist.id.in_(remove_ids)).delete(
            synchronize_session=False
        )
    db.commit()
    return {
        "removed": removed - merged,
        "merged": merged,
        "renamed": renamed,
        "remaining": db.query(Journalist).count(),
    }


@app.get("/api/journalists/{jid}/profiles")
def journalist_profiles(jid: int, db: Session = Depends(get_db)):
    rows = db.query(JournalistProfile).filter(JournalistProfile.journalist_id == jid).order_by(JournalistProfile.date.desc()).all()
    return [row_to_dict(p) for p in rows]


@app.get("/api/journalists/{jid}/articles")
def journalist_articles(jid: int, limit: int = Query(50, le=200), offset: int = 0, db: Session = Depends(get_db)):
    rows = db.query(Article).filter(Article.journalist_id == jid).order_by(Article.published_at.desc()).offset(offset).limit(limit).all()
    return [row_to_dict(a) for a in rows]


# ------------------------------------------------------------------ articles

def _authors_of(db: Session, article_ids: list[int]) -> dict[int, list[dict]]:
    if not article_ids:
        return {}
    rows = (
        db.query(ArticleJournalist, Journalist)
        .join(Journalist, Journalist.id == ArticleJournalist.journalist_id)
        .filter(ArticleJournalist.article_id.in_(article_ids))
        .order_by(ArticleJournalist.position)
        .all()
    )
    out: dict[int, list[dict]] = {}
    for link, j in rows:
        out.setdefault(link.article_id, []).append({"id": j.id, "name": j.name, "position": link.position})
    return out


def _article_public(a: Article, onames: dict, jnames: dict, authors: list[dict] | None = None) -> dict:
    d = row_to_dict(a)
    d.pop("raw_html", None)
    d.pop("embedding", None)
    d["outlet_name"] = onames.get(a.outlet_id)
    d["journalist_name"] = jnames.get(a.journalist_id) if a.journalist_id else None
    d["authors"] = authors or ([{"id": a.journalist_id, "name": d["journalist_name"], "position": 0}] if a.journalist_id and d["journalist_name"] else [])
    return d


@app.get("/api/articles")
def list_articles(outlet_id: int | None = None, journalist_id: int | None = None,
                  status: str | None = None, country: str | None = None,
                  limit: int = Query(50, le=200), offset: int = 0,
                  db: Session = Depends(get_db)):
    q = db.query(Article)
    if outlet_id:
        q = q.filter(Article.outlet_id == outlet_id)
    if journalist_id:
        q = q.filter(Article.journalist_id == journalist_id)
    if status:
        q = q.filter(Article.analysis_status == status)
    if country:
        q = q.join(Outlet, Article.outlet_id == Outlet.id).filter(Outlet.country == country.upper())
    rows = q.order_by(Article.published_at.desc()).offset(offset).limit(limit).all()
    onames = _outlet_names(db)
    jids = {a.journalist_id for a in rows if a.journalist_id}
    jnames = {j.id: j.name for j in db.query(Journalist).filter(Journalist.id.in_(jids)).all()} if jids else {}
    authors = _authors_of(db, [a.id for a in rows])
    return [_article_public(a, onames, jnames, authors.get(a.id)) for a in rows]


@app.get("/api/articles/{aid}")
def get_article(aid: int, db: Session = Depends(get_db)):
    a = db.get(Article, aid)
    if not a:
        raise HTTPException(404)
    onames = _outlet_names(db)
    jnames = {a.journalist_id: db.get(Journalist, a.journalist_id).name} if a.journalist_id and db.get(Journalist, a.journalist_id) else {}
    authors = _authors_of(db, [a.id]).get(a.id)
    d = _article_public(a, onames, jnames, authors)
    o = db.get(Outlet, a.outlet_id)
    d["outlet_country"] = o.country if o else None
    return d


@app.post("/api/articles/search")
def search_articles(data: ArticleSearchIn, db: Session = Depends(get_db)):
    from .services import embeddings
    vec = embeddings.embed_text(data.query)
    q = db.query(Article).filter(Article.embedding.isnot(None))
    if data.analyzed_only:
        q = q.filter(Article.analysis_status == "analyzed")
    if data.outlet_id:
        q = q.filter(Article.outlet_id == data.outlet_id)
    if data.days:
        q = q.filter(Article.published_at >= datetime.utcnow() - timedelta(days=data.days))
    dist = Article.embedding.cosine_distance(vec)
    limit = min(max(data.limit or 20, 1), 100)
    rows = q.add_columns(dist.label("dist")).order_by(dist).limit(limit).all()
    onames = _outlet_names(db)
    arts = [a for a, _ in rows]
    jids = {a.journalist_id for a in arts if a.journalist_id}
    jnames = {j.id: j.name for j in db.query(Journalist).filter(Journalist.id.in_(jids)).all()} if jids else {}
    authors = _authors_of(db, [a.id for a in arts])
    results = []
    for a, d in rows:
        item = _article_public(a, onames, jnames, authors.get(a.id))
        item["similarity"] = round(float(1 - d), 4)
        results.append(item)
    return results


# ------------------------------------------------------------------- clients

@app.get("/api/clients")
def list_clients(db: Session = Depends(get_db)):
    return [row_to_dict(c) for c in db.query(Client).all()]


@app.post("/api/clients", status_code=201)
def create_client(data: ClientIn, db: Session = Depends(get_db)):
    c = Client(**data.model_dump())
    db.add(c)
    db.commit()
    return row_to_dict(c)


@app.get("/api/clients/{cid}")
def get_client(cid: int, db: Session = Depends(get_db)):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    d = row_to_dict(c)
    d["adaptive"] = {
        "accessibility_pitch_threshold": get_setting(db, "_adaptive_accessibility_threshold") or get_setting(db, "accessibility_pitch_threshold"),
        "gap_exploitable_threshold": get_setting(db, "_adaptive_gap_threshold") or get_setting(db, "gap_exploitable_threshold"),
    }
    last = db.query(ActionHistory).filter(ActionHistory.client_id == cid).order_by(ActionHistory.completed_at.desc()).first()
    d["last_outcome"] = row_to_dict(last) if last else None
    return d


@app.put("/api/clients/{cid}")
def update_client(cid: int, data: ClientUpdate, db: Session = Depends(get_db)):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(c, k, v)
    db.commit()
    return row_to_dict(c)


@app.delete("/api/clients/{cid}", status_code=204)
def delete_client(cid: int, db: Session = Depends(get_db)):
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404)
    db.delete(c)
    db.commit()


@app.post("/api/clients/{cid}/contacts", status_code=201)
def add_contact(cid: int, data: ContactIn, db: Session = Depends(get_db)):
    if not db.get(Client, cid):
        raise HTTPException(404)
    c = ClientContact(client_id=cid, **data.model_dump())
    db.add(c)
    db.commit()
    return row_to_dict(c)


@app.post("/api/clients/{cid}/blacklist", status_code=201)
def add_blacklist(cid: int, data: BlacklistIn, db: Session = Depends(get_db)):
    if not db.get(Client, cid):
        raise HTTPException(404)
    b = ClientBlacklist(client_id=cid, **data.model_dump())
    db.add(b)
    db.commit()
    return row_to_dict(b)


# ----------------------------------------------------------- recommendations

@app.get("/api/clients/{cid}/recommendations")
def client_recommendations(cid: int, action_type: str | None = None,
                           status: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Recommendation).filter(Recommendation.client_id == cid)
    if action_type:
        q = q.filter(Recommendation.action_type == action_type)
    if status:
        q = q.filter(Recommendation.status == status)
    rows = q.order_by(Recommendation.priority.desc()).all()
    onames = _outlet_names(db)
    jnames = _journalist_names(db)
    from .services import contacts as C
    cs = C.summary_for_many(db, [r.journalist_id for r in rows if r.journalist_id])
    out = []
    for r in rows:
        d = row_to_dict(r)
        d["outlet_name"] = onames.get(r.outlet_id)
        d["journalist_name"] = jnames.get(r.journalist_id)
        d["contact"] = cs.get(r.journalist_id) if r.journalist_id else None
        out.append(d)
    return out


@app.put("/api/recommendations/{rid}")
def update_recommendation(rid: int, data: RecommendationUpdate, db: Session = Depends(get_db)):
    r = db.get(Recommendation, rid)
    if not r:
        raise HTTPException(404)
    for k, v in data.model_dump(exclude_unset=True).items():
        setattr(r, k, v)
    r.updated_at = datetime.utcnow()
    db.commit()
    return row_to_dict(r)


@app.post("/api/recommendations/{rid}/outcome")
def record_outcome(rid: int, data: OutcomeIn, db: Session = Depends(get_db)):
    lesson = (data.lessons_learned or "").strip()
    if len(lesson) < 10:
        raise HTTPException(400, msg("leçon obligatoire (≥ 10 caractères)", "lesson required (≥ 10 characters)"))
    h = recommend.record_outcome(db, rid, data.outcome, data.impact_metrics, lesson)
    if not h:
        raise HTTPException(404)
    return row_to_dict(h)


@app.get("/api/clients/{cid}/strategic-map")
def strategic_map(cid: int, db: Session = Depends(get_db)):
    """Data for the stance × influence scatter plot."""
    client = db.get(Client, cid)
    if not client:
        raise HTTPException(404)

    push_narratives = client.narratives_push or []
    counter_narratives = client.narratives_counter or []
    from .services import embeddings as emb
    push_vecs = emb.embed_texts(push_narratives) if push_narratives else []
    counter_vecs = emb.embed_texts(counter_narratives) if counter_narratives else []

    blacklisted = {b.outlet_id for b in db.query(ClientBlacklist).filter(ClientBlacklist.client_id == cid).all()}
    since = datetime.utcnow() - __import__("datetime").timedelta(days=7)

    outlets = db.query(Outlet).all()
    points = []
    for outlet in outlets:
        if outlet.id in blacklisted:
            continue
        articles = db.query(Article).filter(
            Article.outlet_id == outlet.id, Article.published_at >= since,
            Article.analysis_status.in_(["analyzed", "embedded_only"]),
        ).all()
        article_vecs = [a.embedding for a in articles if a.embedding]
        stance = recommend._stance_for_outlet(article_vecs, push_vecs, counter_vecs) if article_vecs else 0.0
        # Latest recommendation for this outlet
        rec = db.query(Recommendation).filter(
            Recommendation.client_id == cid, Recommendation.outlet_id == outlet.id
        ).order_by(Recommendation.priority.desc()).first()
        points.append({
            "outlet_id": outlet.id,
            "outlet_name": outlet.name,
            "stance": round(stance, 3),
            "influence": outlet.influence_score or 0,
            "action_type": rec.action_type if rec else None,
            "recommendation_id": rec.id if rec else None,
        })
    return points


@app.get("/api/clients/{cid}/history")
def client_history(cid: int, db: Session = Depends(get_db)):
    rows = db.query(ActionHistory).filter(ActionHistory.client_id == cid).order_by(ActionHistory.completed_at.desc()).all()
    onames = _outlet_names(db)
    return [{**row_to_dict(h), "outlet_name": onames.get(h.outlet_id)} for h in rows]


# --------------------------------------------------------------- influence

@app.get("/api/influence-ranking")
def influence_ranking(sort_by: str = Query("influence_score"), db: Session = Depends(get_db)):
    rows = db.query(Outlet).order_by(Outlet.influence_score.desc()).all()
    out = []
    for o in rows:
        d = row_to_dict(o)
        prof = db.query(OutletProfile).filter(OutletProfile.outlet_id == o.id).order_by(OutletProfile.week.desc()).first()
        d["component_scores"] = prof.component_scores if prof else {}
        out.append(d)
    return out


@app.get("/api/double-classification/{outlet_id}")
def double_classification(outlet_id: int, db: Session = Depends(get_db)):
    o = db.get(Outlet, outlet_id)
    if not o:
        raise HTTPException(404)
    prof = db.query(OutletProfile).filter(OutletProfile.outlet_id == outlet_id).order_by(OutletProfile.week.desc()).first()
    return {
        "outlet_name": o.name,
        "official": o.official_classification or {},
        "real": prof.real_classification if prof else {},
        "gap": prof.gap_from_official if prof else {},
    }


# ------------------------------------------------------------ ingestion / jobs

@app.post("/api/ingest/{outlet_id}")
def trigger_ingestion(outlet_id: int, db: Session = Depends(get_db)):
    o = db.get(Outlet, outlet_id)
    if not o:
        raise HTTPException(404)
    count = rss.ingest_outlet_rss(db, o)
    if count == 0 and not rss._rss_healthy(db, o):
        count = rss.ingest_sitemap(db, o)
    if count == 0 and not o.rss_url:
        count = rss.ingest_outlet_scrape(db, o)
    return {"captured": count}


@app.post("/api/ingest")
def trigger_ingest_all(source: str = Query("all"), db: Session = Depends(get_db)):
    """source: 'rss', 'google_news', 'gdelt', 'scrape', or 'all'."""
    return rss.ingest_all(db, feed_type=source)


@app.post("/api/ingest/{outlet_id}/google-news")
def trigger_google_news(outlet_id: int, db: Session = Depends(get_db)):
    o = db.get(Outlet, outlet_id)
    if not o:
        raise HTTPException(404)
    count = rss.ingest_google_news(db, o)
    return {"captured": count}


@app.post("/api/ingest/{outlet_id}/gdelt")
def trigger_gdelt(outlet_id: int, db: Session = Depends(get_db)):
    o = db.get(Outlet, outlet_id)
    if not o:
        raise HTTPException(404)
    count = rss.ingest_gdelt(db, o)
    return {"captured": count}


@app.post("/api/ingest/{outlet_id}/playwright")
def trigger_playwright(outlet_id: int, db: Session = Depends(get_db)):
    o = db.get(Outlet, outlet_id)
    if not o:
        raise HTTPException(404)
    from .services import scraping
    count = scraping.scrape_with_playwright(db, o)
    return {"captured": count}


# --------------------------------------------------------------- outlet feeds

@app.get("/api/outlets/{outlet_id}/feeds")
def list_feeds(outlet_id: int, db: Session = Depends(get_db)):
    feeds = db.query(OutletFeed).filter(OutletFeed.outlet_id == outlet_id).all()
    return [row_to_dict(f) for f in feeds]


@app.post("/api/outlets/{outlet_id}/feeds", status_code=201)
def add_feed(outlet_id: int, url: str = "", label: str = "default", feed_type: str = "rss", db: Session = Depends(get_db)):
    if not db.get(Outlet, outlet_id):
        raise HTTPException(404)
    f = OutletFeed(outlet_id=outlet_id, url=url, label=label, feed_type=feed_type)
    db.add(f)
    db.commit()
    return row_to_dict(f)


@app.delete("/api/feeds/{feed_id}", status_code=204)
def delete_feed(feed_id: int, db: Session = Depends(get_db)):
    f = db.get(OutletFeed, feed_id)
    if not f:
        raise HTTPException(404)
    db.delete(f)
    db.commit()


@app.post("/api/analyze")
def trigger_analysis(limit: int = Query(50, le=500), db: Session = Depends(get_db)):
    done = analysis.process_pending(db, limit)
    return {"analyzed": done}


@app.post("/api/profiles/journalists")
def trigger_journalist_profiles(db: Session = Depends(get_db)):
    count = profiles.run_journalist_profiles(db)
    return {"profiles": count}


@app.post("/api/journalists/enrich")
def trigger_journalist_enrichment(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    from .services.enrich import enrich_all
    count = enrich_all(db, limit)
    return {"enriched": count}


@app.get("/api/maintenance/polluted")
def count_polluted(db: Session = Depends(get_db)):
    """Articles dont le texte est un bandeau cookies / mur de consentement / page Google News,
    et état de la requalification en cours."""
    from .services import cleanup
    s = cleanup.summary(db)
    return {"count": s["active"], "recoverable": s["recoverable"], "job": cleanup.STATE}


@app.post("/api/maintenance/requalify")
def requalify_polluted(refetch: bool = Query(True), limit: int | None = Query(None)):
    """Lance en arrière-plan : récupère le vrai texte (résolution Google News, re-extraction)
    ou classe hors champ. Les articles récupérés repassent en attente d'analyse."""
    from .services import cleanup
    started = cleanup.start_background(refetch=refetch, limit=limit)
    return {"started": started, "job": cleanup.STATE}


@app.post("/api/profiles/outlets")
def trigger_outlet_profiles(db: Session = Depends(get_db)):
    count = profiles.run_outlet_profiles(db)
    return {"profiles": count}


@app.post("/api/recommendations/generate/{cid}")
def trigger_recommendations(cid: int, db: Session = Depends(get_db)):
    client = db.get(Client, cid)
    if not client:
        raise HTTPException(404)
    recs = recommend.generate_recommendations(db, client)
    created, kept = recs
    return {"generated": len(created), "kept": len(kept)}


@app.post("/api/recommendations/generate")
def trigger_all_recommendations(db: Session = Depends(get_db)):
    count = recommend.run_all_recommendations(db)
    return {"generated": count}


# ----------------------------------------------------------------- settings

@app.get("/api/settings")
def read_settings(db: Session = Depends(get_db)):
    s = dict(get_settings(db))
    s.pop("worker_last_run", None)
    return s


@app.put("/api/settings")
def update_settings(data: SettingsUpdate, db: Session = Depends(get_db)):
    for k, v in data.values.items():
        set_setting(db, k, v)
    return get_settings(db)


# ------------------------------------------------------------------ assistant

class ConversationIn(BaseModel):
    title: str | None = None
    context: dict | None = None


class MessageIn(BaseModel):
    text: str
    attachments: list[dict] = []   # [{name, text}] déjà extraits côté /api/agent/upload


@app.get("/api/agent/conversations")
def list_conversations(limit: int = Query(50, le=200), db: Session = Depends(get_db)):
    rows = db.query(Conversation).order_by(Conversation.updated_at.desc()).limit(limit).all()
    return [{"id": c.id, "title": c.title, "context": c.context, "cost_usd": round(c.cost_usd or 0, 4), "updated_at": c.updated_at.isoformat(), "created_at": c.created_at.isoformat()} for c in rows]


@app.post("/api/agent/conversations", status_code=201)
def create_conversation(data: ConversationIn, db: Session = Depends(get_db)):
    c = Conversation(title=data.title or "Nouvelle conversation", context=data.context or {}, state={})
    db.add(c)
    db.commit()
    return {"id": c.id, "title": c.title, "context": c.context, "cost_usd": 0, "updated_at": c.updated_at.isoformat(), "created_at": c.created_at.isoformat()}


@app.get("/api/agent/conversations/{cid}")
def get_conversation(cid: int, db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404)
    msgs = db.query(Message).filter(Message.conversation_id == cid).order_by(Message.created_at.asc(), Message.id.asc()).all()
    actions = {a.id: a.status for a in db.query(AgentAction).filter(AgentAction.conversation_id == cid).all()}
    out = []
    for m in msgs:
        parts = []
        for p in (m.parts or []):
            if p.get("type") == "confirm" and p.get("action_id") in actions:
                p = {**p, "status": actions[p["action_id"]]}
            parts.append(p)
        out.append({"id": m.id, "role": m.role, "content": m.content, "parts": parts, "cost_usd": m.cost_usd, "created_at": m.created_at.isoformat()})
    return {"id": c.id, "title": c.title, "context": c.context, "cost_usd": round(c.cost_usd or 0, 4), "messages": out}


@app.put("/api/agent/conversations/{cid}")
def update_conversation(cid: int, data: ConversationIn, db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404)
    if data.title is not None:
        c.title = data.title[:120]
    if data.context is not None:
        c.context = {**(c.context or {}), **data.context}
    db.commit()
    return {"id": c.id, "title": c.title, "context": c.context}


@app.delete("/api/agent/conversations/{cid}", status_code=204)
def delete_conversation(cid: int, db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404)
    db.query(Message).filter(Message.conversation_id == cid).delete()
    db.query(AgentAction).filter(AgentAction.conversation_id == cid).update({"conversation_id": None})
    db.query(Artifact).filter(Artifact.conversation_id == cid).update({"conversation_id": None, "message_id": None})
    db.delete(c)
    db.commit()


@app.post("/api/agent/conversations/{cid}/messages")
def post_message(cid: int, data: MessageIn, db: Session = Depends(get_db)):
    """Tour de conversation en flux SSE."""
    from fastapi.responses import StreamingResponse
    from .services import agent
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404)
    text = data.text.strip()
    for att in data.attachments or []:
        if att.get("text"):
            text += f"\n\n--- Pièce jointe : {att.get('name', 'fichier')} ---\n{att['text'][:40000]}"
    if not text:
        raise HTTPException(400, msg("message vide", "empty message"))

    # Le tour vit dans son propre fil : si l'utilisateur quitte la page, le flux HTTP
    # est coupé mais la réponse est quand même calculée et enregistrée.
    import queue
    import threading
    from contextvars import copy_context

    from .database import SessionLocal

    events: queue.Queue = queue.Queue()

    def worker():
        s = SessionLocal()
        try:
            conv = s.get(Conversation, cid)
            if conv is None:
                events.put(agent._sse({"type": "error", "message": msg("conversation introuvable", "conversation not found")}))
                return
            for ev in agent.run_turn(s, conv, text):
                events.put(ev)
        except Exception as e:  # noqa: BLE001
            log.exception("agent stream failed")
            events.put(agent._sse({"type": "error", "message": str(e)[:500]}))
        finally:
            s.close()
            events.put(None)

    threading.Thread(target=copy_context().run, args=(worker,), name=f"agent-{cid}", daemon=True).start()

    def gen():
        while True:
            item = events.get()
            if item is None:
                break
            yield item

    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.post("/api/agent/upload")
async def agent_upload(file: UploadFile = File(...)):
    from .services import agent
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(413, msg("fichier trop volumineux (20 Mo max)", "file too large (20 MB max)"))
    text = agent.extract_attachment_text(file.filename or "", data)
    return {"name": file.filename, "chars": len(text), "text": text[:60000]}


@app.get("/api/agent/actions")
def list_actions(limit: int = Query(100, le=500), db: Session = Depends(get_db)):
    rows = db.query(AgentAction).order_by(AgentAction.created_at.desc()).limit(limit).all()
    return [row_to_dict(a) for a in rows]


@app.post("/api/agent/actions/{aid}/{verb}")
def act_on_action(aid: int, verb: str, db: Session = Depends(get_db)):
    from .services import agent
    a = db.get(AgentAction, aid)
    if not a:
        raise HTTPException(404)
    try:
        if verb == "apply":
            agent.apply_action(db, a)
        elif verb == "reject":
            agent.reject_action(db, a)
        elif verb == "undo":
            agent.undo_action(db, a)
        else:
            raise HTTPException(400, msg("verbe inconnu", "unknown verb"))
    except ValueError as e:
        raise HTTPException(400, str(e))
    return row_to_dict(a)


@app.get("/api/agent/tools")
def list_agent_tools():
    from .services import agent_tools
    return [{"name": n, "kind": k, "description": s["description"][:160]} for n, (s, _, k) in agent_tools.REGISTRY.items()]


@app.get("/api/artifacts")
def list_artifacts(limit: int = Query(100, le=500), kind: str | None = None, db: Session = Depends(get_db)):
    q = db.query(Artifact)
    if kind:
        q = q.filter(Artifact.kind == kind)
    rows = q.order_by(Artifact.created_at.desc()).limit(limit).all()
    return [{**row_to_dict(a), "url": f"/api/artifacts/{a.id}/download"} for a in rows]


@app.get("/api/artifacts/{aid}/download")
def download_artifact(aid: int, inline: bool = Query(False), db: Session = Depends(get_db)):
    from fastapi.responses import FileResponse
    a = db.get(Artifact, aid)
    if not a:
        raise HTTPException(404)
    import os
    if not os.path.exists(a.path):
        raise HTTPException(410, msg("fichier disparu", "file gone"))
    disposition = "inline" if inline or a.kind in ("pdf", "html") else "attachment"
    return FileResponse(a.path, media_type=a.mime, filename=a.filename, content_disposition_type=disposition)


@app.delete("/api/artifacts/{aid}", status_code=204)
def delete_artifact(aid: int, db: Session = Depends(get_db)):
    a = db.get(Artifact, aid)
    if not a:
        raise HTTPException(404)
    import os
    try:
        os.remove(a.path)
    except OSError:
        pass
    db.delete(a)
    db.commit()


class ReportIn(BaseModel):
    kind: str
    target: str | None = None
    notes: str | None = None
    weeks: int = 8
    country: str | None = None


class ReportPatch(BaseModel):
    title: str | None = None
    subtitle: str | None = None
    body: dict | None = None
    blocks: list | None = None


@app.post("/api/reports")
def create_report(data: ReportIn, db: Session = Depends(get_db)):
    from .services import reports
    try:
        r = reports.compose(db, data.kind, data.target, notes=data.notes, weeks=data.weeks, country=data.country)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return reports.public_report(r)


@app.get("/api/reports")
def list_reports(limit: int = Query(80, le=200), db: Session = Depends(get_db)):
    from .services import reports
    from .models import Report
    rows = db.query(Report).order_by(Report.updated_at.desc()).limit(limit).all()
    return [reports.public_report(r) for r in rows]


@app.get("/api/reports/{rid}")
def get_report(rid: int, db: Session = Depends(get_db)):
    from .services import reports
    from .models import Report
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    return reports.public_report(r)


@app.patch("/api/reports/{rid}")
def patch_report(rid: int, data: ReportPatch, db: Session = Depends(get_db)):
    from .services import reports
    from .models import Report
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    reports.apply_patch(r, data.model_dump(exclude_unset=True))
    db.commit()
    db.refresh(r)
    return reports.public_report(r)


@app.delete("/api/reports/{rid}", status_code=204)
def delete_report(rid: int, db: Session = Depends(get_db)):
    from .models import Report
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    db.delete(r)
    db.commit()


@app.post("/api/reports/{rid}/export")
def export_report(rid: int, db: Session = Depends(get_db)):
    from .services import reports
    from .models import Report
    r = db.get(Report, rid)
    if not r:
        raise HTTPException(404)
    art = reports.export_pdf(db, r)
    return {**reports.public_report(r), "url": f"/api/artifacts/{art.id}/download"}


# ------------------------------------------------------------------- stats

@app.get("/api/stats/cost")
def cost_stats(db: Session = Depends(get_db)):
    from datetime import date
    today = date.today()
    month_start = today.replace(day=1)
    rows = db.query(LLMUsage).filter(LLMUsage.date >= month_start).all()
    total = sum(r.cost_usd for r in rows)
    by_purpose = {}
    for r in rows:
        by_purpose.setdefault(r.purpose, 0.0)
        by_purpose[r.purpose] += r.cost_usd
    return {"month": today.strftime("%Y-%m"), "total_usd": round(total, 2), "by_purpose": {k: round(v, 2) for k, v in by_purpose.items()}}


# ---------------------------------------------------------------- constants

@app.get("/api/constants")
def get_constants(db: Session = Depends(get_db)):
    from . import kits as K
    from .i18n import get_locale
    loc = get_locale()
    return {
        "axes": AXES,
        "structural_axes": K.STRUCTURAL_IDS,
        "axis_labels_fr": AXIS_LABELS_FR,
        "axis_labels": axis_labels(),
        "axis_poles": {a: list(v) for a, v in axis_poles_map().items()},
        "action_types": ACTION_TYPES,
        "fr_axis_zone": sorted(FR_AXIS_ZONE),
        "fr_specific_axes": list(FR_SPECIFIC_AXES),
        "kits": [K.serialize_kit(k if k.get("id") != K.STRUCTURAL_ONLY_ID else None, loc) for k in K.list_kits(db)],
        "country_kits": {**K.DEFAULT_COUNTRY_KIT, **K._country_overrides(db)},
    }


@app.get("/api/countries")
def list_countries(all: bool = Query(False, description="true = tous les pays du monde, pas seulement ceux suivis"), db: Session = Depends(get_db)):
    from . import geo
    counts = {(r[0] or "").upper(): r[1] for r in db.query(Outlet.country, func.count(Outlet.id)).group_by(Outlet.country).all()}
    rows = []
    for c in geo.all_countries():
        n = counts.get(c["code"], 0)
        if n or all:
            rows.append({**c, "outlets": n})
    return sorted(rows, key=lambda r: (-r["outlets"], r["name_en"]))


# ------------------------------------------------------------------ cartography

@app.get("/api/map/landscape")
def map_landscape(weeks: int = Query(8, ge=1, le=52), min_articles: int = Query(5, ge=1), country: str | None = None, db: Session = Depends(get_db)):
    from .services import cartography
    return cartography.landscape(db, weeks, min_articles, country)


@app.get("/api/map/dissidents")
def map_dissidents(weeks: int = Query(8, ge=1, le=52), limit: int = Query(40, le=200), db: Session = Depends(get_db)):
    from .services import cartography
    return cartography.dissidents(db, weeks, limit=limit)


@app.get("/api/map/network")
def map_network(days: int = Query(90, ge=7, le=365), db: Session = Depends(get_db)):
    from .services import cartography
    return cartography.network(db, days)


@app.get("/api/map/world")
def map_world(days: int = Query(30, ge=1, le=365), db: Session = Depends(get_db)):
    from .services import cartography
    return cartography.world(db, days)


@app.get("/api/map/corpus")
def map_corpus(limit: int = Query(1500, ge=50, le=5000), days: int = Query(60, ge=1, le=365), db: Session = Depends(get_db)):
    from .services import cartography
    return cartography.corpus(db, limit, days)


@app.get("/api/map/leadlag")
def map_leadlag(days: int = Query(30, ge=3, le=365), window_hours: int = Query(72, ge=6, le=240), db: Session = Depends(get_db)):
    from .services import cartography
    return cartography.leadlag(db, days, window_hours)


@app.get("/api/map/packs")
def map_packs(days: int = Query(60, ge=7, le=365), db: Session = Depends(get_db)):
    from .services import cartography
    return cartography.packs(db, days)


@app.get("/api/map/entities")
def map_entities(days: int = Query(60, ge=7, le=365), limit: int = Query(40, ge=5, le=200), country: str | None = None, db: Session = Depends(get_db)):
    from .services import cartography
    return cartography.entities(db, days, limit, country)


@app.get("/api/map/topics")
def map_topics(
    days: int = Query(7, ge=1, le=90),
    country: str | None = None,
    outlet_id: int | None = None,
    journalist_id: int | None = None,
    min_articles: int = Query(2, ge=1, le=20),
    include_singletons: bool = Query(False),
    q: str | None = Query(None, max_length=200),
    briefs: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Agenda : articles de la fenêtre regroupés par similarité sémantique (même affaire, libellés différents)."""
    from .services import topics as topics_svc
    return topics_svc.agenda(
        db, days=days, country=country, outlet_id=outlet_id,
        journalist_id=journalist_id, min_articles=min_articles,
        include_singletons=include_singletons, briefs=briefs, q=q,
    )


@app.post("/api/map/refresh")
def map_refresh():
    from .services import cartography, topics as topics_svc
    cartography.invalidate()
    topics_svc.invalidate()
    return {"ok": True}


def _mount_interface() -> None:
    """Sert l'interface à côté de l'API, pour un seul adresse publique."""
    root = os.environ.get("STATIC_DIR", "")
    if not root or not os.path.isdir(root):
        return
    assets = os.path.join(root, "assets")
    if os.path.isdir(assets):
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    index = os.path.join(root, "index.html")

    @app.get("/", include_in_schema=False)
    @app.get("/{full_path:path}", include_in_schema=False)
    def interface(full_path: str = ""):
        if full_path == "api" or full_path.startswith("api/") or full_path == "mcp" or full_path.startswith("mcp/"):
            raise HTTPException(404)
        safe = os.path.normpath(full_path)
        if safe.startswith("..") or safe == "..":
            raise HTTPException(404)
        candidate = os.path.join(root, safe)
        if full_path and os.path.isfile(candidate):
            return FileResponse(candidate)
        return FileResponse(index)


_mount_interface()
