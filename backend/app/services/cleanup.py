"""Requalification des articles pollués par du texte parasite.

Deux sources de pollution repérées :
- liens Google News non résolus : la page capturée est l'application Google News
  (liste de langues + mur de consentement), toujours le même texte de ~2 700 caractères.
  Le LLM a alors « analysé » le titre seul ;
- murs de consentement / bandeaux cookies à la place de l'article (Mediapart, TX Group…).

Pour chaque article touché : on tente de récupérer le vrai texte (résolution du lien
Google News, nouvelle extraction avec cookies de consentement). Si ça marche, l'article
repasse en « pending » et sera ré-analysé ; sinon il est classé hors champ (Boilerplate)
et sort de toutes les positions mesurées.

Le traitement réseau est parallélisé ; l'état d'avancement est exposé pour l'interface.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from sqlalchemy.orm import Session

from ..database import SessionLocal
from ..models import Article
from . import cartography, extract
from .analysis import BOILERPLATE_DATA

log = logging.getLogger("tacite.cleanup")

_TOPIC_RE = re.compile(r"consent|cookie|privacy|personal data|données personnelles|confidentialit|datenschutz|privacidad|boilerplate", re.I)

STATE: dict = {"running": False, "total": 0, "done": 0, "stats": None, "started_at": None, "finished_at": None, "error": None}
_lock = threading.Lock()


def _is_polluted(url: str, title: str | None, text: str | None, data: dict | None) -> bool:
    if extract.is_google_news_url(url):
        return True
    if extract.is_boilerplate(text, title):
        return True
    topics = [(t.get("label") or "") for t in ((data or {}).get("topics") or [])]
    return sum(1 for t in topics if _TOPIC_RE.search(t)) >= 2


def find_polluted(db: Session, only_active: bool = False) -> list[int]:
    """Articles pollués. only_active=True : seulement ceux qui comptent encore dans les mesures
    (pas déjà classés hors champ « Boilerplate »)."""
    ids = []
    q = db.query(Article.id, Article.url, Article.title, Article.text, Article.extracted_data, Article.analysis_status).filter(
        Article.analysis_status.in_(["analyzed", "embedded_only", "pending", "error"])
    ).yield_per(500)
    for id_, url, title, text, data, st in q:
        if only_active and st == "embedded_only" and (data or {}).get("boilerplate"):
            continue
        if _is_polluted(url, title, text, data):
            ids.append(id_)
    return ids


_summary_cache: tuple[float, dict] | None = None


def summary(db: Session, max_age: float = 60.0) -> dict:
    """Compteurs pollués (une seule passe, mis en cache max_age secondes : la page Paramètres sonde souvent)."""
    global _summary_cache
    if _summary_cache and time.time() - _summary_cache[0] < max_age:
        return _summary_cache[1]
    active = recoverable = 0
    q = db.query(Article.url, Article.title, Article.text, Article.extracted_data, Article.analysis_status).filter(
        Article.analysis_status.in_(["analyzed", "embedded_only", "pending", "error"])
    ).yield_per(500)
    for url, title, text, data, st in q:
        if not _is_polluted(url, title, text, data):
            continue
        if st == "embedded_only" and (data or {}).get("boilerplate"):
            recoverable += 1
        else:
            active += 1
    out = {"active": active, "recoverable": recoverable, "total": active + recoverable}
    _summary_cache = (time.time(), out)
    return out


def _fetch(id_: int, url: str, title: str | None) -> tuple[int, str | None, str | None, bool]:
    """Réseau seulement (hors session DB) : (id, url_finale_si_différente, texte_ou_None, différé).
    différé = Google a limité les requêtes ; l'article reste un lien Google News et sera
    retenté à la prochaine passe."""
    try:
        if extract.is_google_news_url(url):
            # Pendant une pause 429, on attend plutôt que de brûler la file.
            while extract.google_blocked() and STATE["running"]:
                time.sleep(5)
            try:
                real = extract.resolve_google_news_url(url)
            except extract.GoogleRateLimited:
                return id_, None, None, True
            if not real:
                return id_, None, None, False
            html = extract.fetch_html(real)
            text = extract.extract_text(html) if html else None
            if text and extract.is_boilerplate(text, title):
                text = None
            return id_, real, text, False
        _, text, final = extract.fetch_article(url)
        if text and extract.is_boilerplate(text, title):
            text = None
        return id_, (final if final != url else None), text, False
    except Exception as e:  # noqa: BLE001
        log.debug("fetch %s failed: %s", id_, e)
        return id_, None, None, False


def _apply(db: Session, id_: int, new_url: str | None, text: str | None, stats: dict) -> None:
    a = db.get(Article, id_)
    if not a:
        return
    if new_url:
        other = db.query(Article.id).filter(Article.url == new_url, Article.id != a.id).first()
        if other:
            a.analysis_status = "duplicate"
            a.duplicate_of_id = other[0]
            a.extracted_data = None
            stats["duplicate"] += 1
            return
        a.url = new_url
        if a.title and (a.title.startswith("- ") or len(a.title) < 8):
            a.title = new_url
    if text and len(text) >= 100:
        a.text = text
        a.raw_html = None
        a.embedding = None
        a.extracted_data = None
        a.analysis_status = "pending"
        a.language = extract.detect_language(text, a.language or "fr")
        stats["recovered"] += 1
    else:
        # Hors champ. Si l'URL est encore un lien Google News, la prochaine passe retentera.
        a.extracted_data = BOILERPLATE_DATA
        a.analysis_status = "embedded_only"
        stats["boilerplate"] += 1


def requalify(db: Session, refetch: bool = True, limit: int | None = None, workers: int = 8) -> dict:
    ids = find_polluted(db)
    if limit:
        ids = ids[:limit]
    stats = {"found": len(ids), "recovered": 0, "duplicate": 0, "boilerplate": 0, "deferred": 0}
    with _lock:
        STATE.update(running=True, total=len(ids), done=0, stats=stats, started_at=time.time(), finished_at=None, error=None)
    try:
        rows = {r[0]: (r[1], r[2]) for r in db.query(Article.id, Article.url, Article.title).filter(Article.id.in_(ids)).all()} if ids else {}
        if refetch:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                futures = [pool.submit(_fetch, i, rows[i][0], rows[i][1]) for i in ids if i in rows]
                for n, fut in enumerate(as_completed(futures), 1):
                    id_, new_url, text, deferred = fut.result()
                    if deferred:
                        stats["deferred"] += 1
                    try:
                        _apply(db, id_, new_url, text, stats)
                        db.commit()
                    except Exception as e:  # noqa: BLE001
                        db.rollback()
                        log.warning("requalify %s failed: %s", id_, e)
                    STATE["done"] = n
                    if n % 100 == 0:
                        log.info("requalify: %d/%d  %s", n, len(ids), stats)
        else:
            for n, id_ in enumerate(ids, 1):
                try:
                    _apply(db, id_, None, None, stats)
                    db.commit()
                except Exception as e:  # noqa: BLE001
                    db.rollback()
                    log.warning("requalify %s failed: %s", id_, e)
                STATE["done"] = n
        cartography.invalidate()
        global _summary_cache
        _summary_cache = None
        # Les positions mesurées ne doivent plus compter les articles écartés.
        try:
            from . import profiles
            profiles.run_outlet_profiles(db)
        except Exception as e:  # noqa: BLE001
            log.warning("profiles after requalify failed: %s", e)
    except Exception as e:  # noqa: BLE001
        STATE["error"] = str(e)
        log.exception("requalify failed")
    finally:
        with _lock:
            STATE.update(running=False, finished_at=time.time())
    return stats


def start_background(refetch: bool = True, limit: int | None = None) -> bool:
    """Lance la requalification dans un thread ; False si une passe est déjà en cours."""
    with _lock:
        if STATE["running"]:
            return False
        STATE["running"] = True

    def _run():
        db = SessionLocal()
        try:
            requalify(db, refetch=refetch, limit=limit)
        finally:
            db.close()

    from contextvars import copy_context
    threading.Thread(target=copy_context().run, args=(_run,), name="requalify", daemon=True).start()
    return True
