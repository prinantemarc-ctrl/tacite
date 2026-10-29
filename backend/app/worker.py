"""Background worker — scheduled tasks for ingestion, analysis, profiling, recommendations."""

import logging
import threading
import time
from datetime import datetime, timezone

from .database import SessionLocal, init_db
from .models import Outlet, User
from .services import analysis, profiles, recommend, rss, scraping
from .settings_store import get_setting, set_setting
from .tenant import bypass_tenant, reset_bypass, reset_current_user, set_current_user

log = logging.getLogger("tacite.worker")

POLL_INTERVAL = 30  # seconds between scheduling checks


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
            batch = int(get_setting(db, "analysis_batch_size") or 50)
            done = analysis.process_pending(db, batch)
            if done:
                did = True
                log.info("Analyzed %d articles", done)
                analyzed_since_profile += done
                if analyzed_since_profile >= 50:
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
    last_run[key] = datetime.now(timezone.utc)
    set_setting(db, "worker_last_run", {k: v.isoformat() for k, v in last_run.items()})


def _minutes_since(last_run: dict, key: str) -> float:
    ts = last_run.get(key)
    if ts is None:
        return 1e9  # jamais lancé → dû immédiatement (9999 min < 7 j bloquait les profils médias)
    return (datetime.now(timezone.utc) - ts).total_seconds() / 60


def run():
    init_db()
    log.info("Worker started")
    threading.Thread(target=_analysis_loop, name="analysis", daemon=True).start()
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

    interval = int(get_setting(db, "rss_interval_minutes") or 15)
    if _minutes_since(last_run, "rss") >= interval:
        log.info("Running RSS ingestion (multi-feed)...")
        for o in db.query(Outlet).all():
            try:
                rss.ingest_outlet_rss(db, o)
                if not rss._rss_healthy(db, o) and rss.recover_feeds(db, o):
                    rss.ingest_outlet_rss(db, o)
                if not rss._rss_healthy(db, o):
                    rss.ingest_sitemap(db, o)
            except Exception as e:
                log.warning("RSS ingestion error for %s: %s", o.name, e)
                db.rollback()
        _save_last_run(db, last_run, "rss")

    # 15 min, même si le réglage stocké est plus long : sinon les titres sortent
    # de la liste Google (100 entrées) avant d'avoir été décodés.
    if _minutes_since(last_run, "google_news") >= 15:
        log.info("Running Google News catch-up...")
        try:
            n = rss.drain_google_news(db, budget_s=10 * 60)
            if n:
                log.info("Google News: %s articles", n)
        except Exception as e:
            log.warning("Google News error: %s", e)
            db.rollback()
        _save_last_run(db, last_run, "google_news")

    gdelt_interval = int(get_setting(db, "gdelt_interval_minutes") or 360)
    if _minutes_since(last_run, "gdelt") >= gdelt_interval:
        log.info("Running GDELT enrichment...")
        for o in db.query(Outlet).all():
            try:
                rss.ingest_gdelt(db, o)
            except Exception as e:
                log.warning("GDELT error for %s: %s", o.name, e)
                db.rollback()
        _save_last_run(db, last_run, "gdelt")

    scrape_interval = int(get_setting(db, "scrape_interval_minutes") or 60)
    if _minutes_since(last_run, "scrape") >= scrape_interval:
        log.info("Running scraping fallback...")
        for o in db.query(Outlet).all():
            if rss._source_healthy(db, o):
                continue
            try:
                count = scraping.scrape_with_playwright(db, o)
                if count == 0:
                    rss.ingest_outlet_scrape(db, o)
            except Exception as e:
                log.warning("Scraping error for %s: %s", o.name, e)
                db.rollback()
        _save_last_run(db, last_run, "scrape")

    if _minutes_since(last_run, "enrich") >= 30:
        from .services import enrich
        max_cost = float(get_setting(db, "max_daily_cost_usd") or 5.0)
        if max_cost <= 0 or analysis.daily_cost(db) < max_cost:
            n = enrich.enrich_all(db, limit=25)
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
