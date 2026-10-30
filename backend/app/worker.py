"""Background worker — scheduled tasks for ingestion, analysis, profiling, recommendations."""

import logging
import threading
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import func

from .database import SessionLocal, init_db
from .models import Article, IngestionLog, Outlet, OutletFeed, User
from .services import analysis, profiles, recommend, rss, scraping
from .settings_store import get_setting, set_setting
from .tenant import bypass_tenant, reset_bypass, reset_current_user, set_current_user

log = logging.getLogger("tacite.worker")

_state_lock = threading.Lock()

POLL_INTERVAL = 30  # seconds between scheduling checks
RSS_BATCH = 40
SITEMAP_BATCH = 20
GOOGLE_BATCH = 40
GDELT_BATCH = 15
SCRAPE_BATCH = 4


def _primary_user_id() -> int | None:
    """La base est unique. Le premier compte sert aux réglages ; tout le monde voit les mêmes lignes."""
    db = SessionLocal()
    try:
        row = db.query(User.id).order_by(User.id).first()
        return row[0] if row else None
    finally:
        db.close()


def _analysis_loop() -> None:
    """Thread dédié : dépile les articles en attente en continu sans être bloqué par l'ingestion."""
    analyzed_since_profile = 0
    while True:
        uid = _primary_user_id()
        if uid is None:
            time.sleep(10)
            continue
        user_token = set_current_user(uid)
        bypass = bypass_tenant(True)
        did = False
        db = SessionLocal()
        try:
            batch = max(200, int(get_setting(db, "analysis_batch_size") or 200))
            done = analysis.process_pending(db, batch)
            if done:
                did = True
                log.info("Analyzed %d articles", done)
                analyzed_since_profile += done
                if analyzed_since_profile >= 500:
                    try:
                        profiles.run_outlet_profiles(db)
                        log.info("Updated outlet profiles after %d analyzed articles", analyzed_since_profile)
                    except Exception as e:  # noqa: BLE001
                        log.warning("outlet profiles update failed: %s", e)
                        db.rollback()
                    analyzed_since_profile = 0
        except Exception as e:  # noqa: BLE001
            log.error("Analysis loop error: %s", e)
        finally:
            db.close()
            reset_bypass(bypass)
            reset_current_user(user_token)
        if not did:
            time.sleep(10)


def _parse_ts(v) -> datetime | None:
    if v is None:
        return None
    if isinstance(v, datetime):
        return v if v.tzinfo else v.replace(tzinfo=timezone.utc)
    try:
        dt = datetime.fromisoformat(str(v).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _load_last_run(db) -> dict[str, datetime]:
    raw = get_setting(db, "worker_last_run") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, datetime] = {}
    for k, v in raw.items():
        ts = _parse_ts(v)
        if ts:
            out[k] = ts
    return out


def _save_last_run(db, last_run: dict[str, datetime], key: str) -> None:
    now = datetime.now(timezone.utc)
    last_run[key] = now
    with _state_lock:
        stored = get_setting(db, "worker_last_run") or {}
        if not isinstance(stored, dict):
            stored = {}
        stored[key] = now.isoformat()
        set_setting(db, "worker_last_run", stored)


def _rotate(ids: list[int], cursor: int) -> list[int]:
    """ids triés, en commençant juste après le curseur, puis au début."""
    return [i for i in ids if i > cursor] + [i for i in ids if i <= cursor]


def _order_ids(ids: list[int], cursor: int, never: set[int], due: set[int], empty: set[int] | None = None) -> list[int]:
    """Jamais collectés d'abord — et parmi eux, ceux qui n'ont aucun article —, puis les délais échus."""
    empty = empty or set()
    rotated = _rotate(sorted(ids), cursor)
    return (
        [i for i in rotated if i in never and i in empty]
        + [i for i in rotated if i in never and i not in empty]
        + [i for i in rotated if i in due and i not in never]
    )


def _cursors(db) -> dict:
    raw = get_setting(db, "worker_cursor") or {}
    return dict(raw) if isinstance(raw, dict) else {}


def _set_cursor(db, cursors: dict, kind: str, outlet_id: int) -> None:
    cursors[kind] = int(outlet_id)
    with _state_lock:
        stored = get_setting(db, "worker_cursor") or {}
        if not isinstance(stored, dict):
            stored = {}
        stored[kind] = int(outlet_id)
        set_setting(db, "worker_cursor", stored)
        cursors.update({k: stored[k] for k in stored})


def _last_logs(db, prefix: str) -> dict[int, datetime]:
    rows = (
        db.query(IngestionLog.outlet_id, func.max(IngestionLog.timestamp))
        .filter(IngestionLog.feed_type.like(prefix))
        .group_by(IngestionLog.outlet_id)
        .all()
    )
    return {oid: ts for oid, ts in rows if oid and ts}


def _pick(outlets: list[Outlet], eligible: set[int], cursor: int, limit: int, last: dict[int, datetime], due_before: datetime, empty: set[int] | None = None) -> list[Outlet]:
    ids = [o.id for o in outlets if o.id in eligible]
    never = {i for i in ids if i not in last}
    due = {i for i in ids if i not in never and last[i] < due_before}
    chosen = _order_ids(ids, cursor, never, due, empty)[:limit]
    by_id = {o.id: o for o in outlets}
    return [by_id[i] for i in chosen]


def _ok_ids(db, since: datetime, prefix: str, captured: bool = False) -> set[int]:
    q = db.query(IngestionLog.outlet_id).filter(
        IngestionLog.status == "ok", IngestionLog.timestamp >= since, IngestionLog.feed_type.like(prefix),
    )
    if captured:
        q = q.filter(IngestionLog.articles_captured > 0)
    return {oid for (oid,) in q.distinct() if oid}


def _minutes_since(last_run: dict, key: str) -> float:
    ts = last_run.get(key)
    if ts is None:
        return 1e9  # jamais lancé → dû immédiatement (9999 min < 7 j bloquait les profils médias)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60


VIEW_INTERVAL = 600
BRIEF_INTERVAL = 3600


def _views_loop() -> None:
    """Fil indépendant : les vues des pages, par compte, sans le bypass d'ingestion."""
    from .services.prepared import refresh_user

    last_full = 0.0
    while True:
        try:
            db = SessionLocal()
            try:
                ids = [row[0] for row in db.query(User.id).order_by(User.id).all()]
            finally:
                db.close()
            full = time.time() - last_full >= BRIEF_INTERVAL
            for uid in ids:
                token = set_current_user(uid)
                db = SessionLocal()
                try:
                    refresh_user(db, with_briefs=full, full=full)
                except Exception as e:  # noqa: BLE001
                    log.error("Views refresh error for user %s: %s", uid, e)
                finally:
                    db.close()
                    reset_current_user(token)
            if full and ids:
                last_full = time.time()
        except Exception as e:  # noqa: BLE001
            log.error("Views loop error: %s", e)
        time.sleep(VIEW_INTERVAL)


def _active_and_empty(db):
    active = [o for o in db.query(Outlet).order_by(Outlet.id).all() if not rss.collection_suspended(o)]
    have = {oid for (oid,) in db.query(Article.outlet_id).distinct().all() if oid}
    return active, {o.id for o in active if o.id not in have}


def _pass_sitemap(db, last_run: dict[str, datetime]) -> None:
    if _minutes_since(last_run, "sitemap") < 1:
        return
    active, empty = _active_and_empty(db)
    cursors = _cursors(db)
    now = datetime.utcnow()
    eligible = {o.id for o in active if o.website_url}
    batch = _pick(active, eligible, int(cursors.get("sitemap") or 0), SITEMAP_BATCH, _last_logs(db, "sitemap%"), now - timedelta(minutes=20), empty)
    if batch:
        log.info("Sitemap batch: %s", ", ".join(o.name for o in batch))
        for o in batch:
            try:
                if not rss._rss_healthy(db, o) and rss.recover_feeds(db, o):
                    rss.ingest_outlet_rss(db, o)
                rss.ingest_sitemap(db, o)
            except Exception as e:
                log.warning("Sitemap error for %s: %s", o.name, e)
                db.rollback()
        _set_cursor(db, cursors, "sitemap", batch[-1].id)
    _save_last_run(db, last_run, "sitemap")


def _pass_google(db, last_run: dict[str, datetime]) -> None:
    from .services.extract import google_blocked
    if google_blocked() or _minutes_since(last_run, "google_news") < 1:
        return
    active, empty = _active_and_empty(db)
    cursors = _cursors(db)
    now = datetime.utcnow()
    day_ago = now - timedelta(hours=24)
    fed = _ok_ids(db, day_ago, "rss%", captured=True) | _ok_ids(db, day_ago, "sitemap%", captured=True)
    eligible = {o.id for o in active if o.website_url and o.id not in fed}
    batch = _pick(active, eligible, int(cursors.get("google") or 0), GOOGLE_BATCH, _last_logs(db, "google_news%"), now - timedelta(hours=2), empty)
    log.info("Google News batch: %d", len(batch))
    try:
        n = rss.drain_google_news(db, budget_s=8 * 60, outlet_ids=[o.id for o in batch]) if batch else 0
        if n:
            log.info("Google News: %s articles", n)
    except Exception as e:
        log.warning("Google News error: %s", e)
        db.rollback()
    if batch:
        _set_cursor(db, cursors, "google", batch[-1].id)
    _save_last_run(db, last_run, "google_news")


def _pass_rss(db, last_run: dict[str, datetime]) -> None:
    if _minutes_since(last_run, "rss") < 1:
        return
    active, empty = _active_and_empty(db)
    cursors = _cursors(db)
    interval = int(get_setting(db, "rss_interval_minutes") or 15)
    feed_ids = {
        oid for (oid,) in db.query(OutletFeed.outlet_id).filter(OutletFeed.enabled == 1, OutletFeed.feed_type == "rss").all() if oid
    }
    eligible = {o.id for o in active if o.rss_url or o.id in feed_ids}
    batch = _pick(active, eligible, int(cursors.get("rss") or 0), RSS_BATCH, _last_logs(db, "rss%"), datetime.utcnow() - timedelta(minutes=interval), empty)
    if batch:
        log.info("RSS batch: %d", len(batch))
        for o in batch:
            try:
                rss.ingest_outlet_rss(db, o)
            except Exception as e:
                log.warning("RSS ingestion error for %s: %s", o.name, e)
                db.rollback()
        _set_cursor(db, cursors, "rss", batch[-1].id)
    _save_last_run(db, last_run, "rss")


def _pass_gdelt(db, last_run: dict[str, datetime]) -> None:
    if _minutes_since(last_run, "gdelt") < 2:
        return
    active, empty = _active_and_empty(db)
    cursors = _cursors(db)
    eligible = {o.id for o in active if o.website_url}
    batch = _pick(active, eligible, int(cursors.get("gdelt") or 0), GDELT_BATCH, _last_logs(db, "gdelt%"), datetime.utcnow() - timedelta(hours=6), empty)
    if batch:
        log.info("GDELT batch: %d", len(batch))
        for o in batch:
            try:
                rss.ingest_gdelt(db, o)
            except Exception as e:
                log.warning("GDELT error for %s: %s", o.name, e)
                db.rollback()
        _set_cursor(db, cursors, "gdelt", batch[-1].id)
    _save_last_run(db, last_run, "gdelt")


def _pass_scrape(db, last_run: dict[str, datetime]) -> None:
    if _minutes_since(last_run, "scrape") < 5:
        return
    active, empty = _active_and_empty(db)
    cursors = _cursors(db)
    now = datetime.utcnow()
    fed = _ok_ids(db, now - timedelta(hours=24), "rss%", captured=True) | _ok_ids(db, now - timedelta(hours=24), "sitemap%", captured=True)
    eligible = {o.id for o in active if o.website_url and o.id not in fed}
    scraped = _last_logs(db, "scrape%")
    for oid, ts in _last_logs(db, "playwright%").items():
        if oid not in scraped or ts > scraped[oid]:
            scraped[oid] = ts
    batch = _pick(active, eligible, int(cursors.get("scrape") or 0), SCRAPE_BATCH, scraped, now - timedelta(hours=12), empty)
    for o in batch:
        try:
            count = scraping.scrape_with_playwright(db, o)
            if count == 0:
                rss.ingest_outlet_scrape(db, o)
        except Exception as e:
            log.warning("Scraping error for %s: %s", o.name, e)
            db.rollback()
    if batch:
        _set_cursor(db, cursors, "scrape", batch[-1].id)
    _save_last_run(db, last_run, "scrape")


def _collection_thread(name: str, step, idle: float) -> None:
    last_run: dict[str, datetime] | None = None
    while True:
        uid = _primary_user_id()
        if uid is None:
            time.sleep(10)
            continue
        user_token = set_current_user(uid)
        bypass = bypass_tenant(True)
        db = SessionLocal()
        try:
            if last_run is None:
                last_run = _load_last_run(db)
            step(db, last_run)
        except Exception as e:  # noqa: BLE001
            log.error("%s loop error: %s", name, e)
            db.rollback()
        finally:
            db.close()
            reset_bypass(bypass)
            reset_current_user(user_token)
        time.sleep(idle)


def run():
    init_db()
    log.info("Worker started")
    threading.Thread(target=_analysis_loop, name="analysis", daemon=True).start()
    threading.Thread(target=_views_loop, name="views", daemon=True).start()
    for name, step, idle in (
        ("sitemap", _pass_sitemap, 2),
        ("google", _pass_google, 5),
        ("rss", _pass_rss, 2),
        ("gdelt", _pass_gdelt, 5),
        ("scrape", _pass_scrape, 15),
    ):
        threading.Thread(target=_collection_thread, args=(name, step, idle), name=name, daemon=True).start()
    last_run: dict[str, datetime] | None = None

    while True:
        uid = _primary_user_id()
        if uid is None:
            time.sleep(POLL_INTERVAL)
            continue
        user_token = set_current_user(uid)
        bypass = bypass_tenant(True)
        try:
            db = SessionLocal()
            try:
                if last_run is None:
                    last_run = _load_last_run(db)
                _tick(db, last_run)
            finally:
                db.close()
        except Exception as e:  # noqa: BLE001
            log.error("Worker loop error: %s", e)
        finally:
            reset_bypass(bypass)
            reset_current_user(user_token)

        time.sleep(POLL_INTERVAL)


def _tick(db, last_run: dict[str, datetime]) -> None:
    if _minutes_since(last_run, "unreachable") >= 360:
        from .services import suggest
        try:
            r = suggest.retry_unreachable(db)
            if r["tried"]:
                log.info("Injoignables : %s", r)
        except Exception as e:  # noqa: BLE001
            log.warning("unreachable retry error: %s", e)
            db.rollback()
        _save_last_run(db, last_run, "unreachable")

    if _minutes_since(last_run, "enrich") >= 30:
        from .services import enrich
        max_cost = float(get_setting(db, "max_daily_cost_usd") or 0)
        if max_cost <= 0 or analysis.daily_cost(db) < max_cost:
            n = enrich.enrich_all(db, limit=100)
            if n:
                log.info("Enriched %d journalists", n)
        else:
            log.info("Daily LLM cost cap reached, skipping enrichment")
        _save_last_run(db, last_run, "enrich")

    contacts_interval = int(get_setting(db, "contacts_interval_minutes") or 60)
    if _minutes_since(last_run, "contacts") >= contacts_interval:
        from .services import contacts as C
        if not C.STATE["running"]:
            try:
                r = C.run_discovery(db, limit=40)
                if r["contacts"]:
                    log.info("Contacts : %s", r)
            except Exception as e:  # noqa: BLE001
                log.warning("contacts discovery error: %s", e)
                db.rollback()
        _save_last_run(db, last_run, "contacts")

    bylines_interval = int(get_setting(db, "bylines_interval_minutes") or 360)
    if _minutes_since(last_run, "bylines") >= bylines_interval:
        from .services import bylines
        try:
            r = bylines.backfill(db, limit=500)
            if r["attached"]:
                log.info("Bylines : %s", r)
        except Exception as e:  # noqa: BLE001
            log.warning("bylines error: %s", e)
            db.rollback()
        _save_last_run(db, last_run, "bylines")

    if _minutes_since(last_run, "journalist_profiles") >= 1440:
        log.info("Running journalist profiles...")
        profiles.run_journalist_profiles(db)
        _save_last_run(db, last_run, "journalist_profiles")

    if _minutes_since(last_run, "outlet_profiles") >= 1440:
        log.info("Running outlet profiles...")
        profiles.run_outlet_profiles(db)
        _save_last_run(db, last_run, "outlet_profiles")

    rec_interval = int(get_setting(db, "recommendation_interval_days") or 7) * 1440
    if _minutes_since(last_run, "recommendations") >= rec_interval:
        log.info("Running recommendation generation...")
        recommend.run_all_recommendations(db)
        _save_last_run(db, last_run, "recommendations")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    run()
