"""Article analysis pipeline: embedding -> topic filter -> dedup -> LLM extraction -> NER merge."""

from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
import logging
import threading
import time

from sqlalchemy.orm import Session

from ..models import Article, Outlet
from ..settings_store import get_setting
from . import embeddings, extract, llm, ner

log = logging.getLogger("tacite.analysis")

BOILERPLATE_DATA = {"entities": {}, "topics": [{"label": "Boilerplate", "framing": {}}], "framing": {}, "tone": "neutral", "angle": "brief", "boilerplate": True}

LLM_CALL_INTERVAL = 0.5  # Reduced from 1.0 to speed up pipeline
_last_llm_call = 0.0
_llm_lock = threading.Lock()
# Appels LLM simultanés pour l'analyse. Aleria tolère la concurrence ; la latence par
# article (10-30 s de raisonnement) plafonne le débit à un appel à la fois.
EXTRACTION_CONCURRENCY = 2

DEDUP_SIMILARITY_THRESHOLD = 0.95

# Political/current-affairs topics — used to decide if an article needs LLM analysis.
# Heuristique limitée aux langues pour lesquelles on a une liste (sinon on laisse le LLM).
NON_POLITICAL_BY_LANG = {
    "fr": [
        "match", "but", "goal", "score", "victoire", "défaite", "championnat", "ligue",
        "rugby", "football", "tennis", "basket", "cyclisme", "natation", "athlétisme",
        "équipe", "jouer", "joueu", "entraîneur", "arbitre", "stade", "terrain",
        "cinéma", "film", "série", "chanson", "album", "concert", "spectacle",
        "festival", "musée", "exposition", "roman", "livre", "sortie", "bande-annonce",
        "people", "célébrité", "star", "influenceur", "instagram", "tiktok",
        "mode", "fashion", "recette", "cuisine", "voyage", "tourisme",
        "météo", "prévision", "température", "pluie", "soleil", "neige",
    ],
    "en": [
        "match", "goal", "league", "fixture", "coach", "stadium", "premier league",
        "movie", "album", "concert", "festival", "recipe", "celebrity", "forecast",
        "tennis", "basketball", "championship",
    ],
    "de": [
        "spiel", "tor", "bundesliga", "trainer", "stadion", "film", "konzert",
        "rezept", "wetter", "meisterschaft",
    ],
}
NON_POLITICAL_KEYWORDS = NON_POLITICAL_BY_LANG["fr"]


def daily_cost(db: Session) -> float:
    """Total LLM spend (USD) recorded today, across all purposes."""
    from datetime import date as _date
    from sqlalchemy import func as _func
    from ..models import LLMUsage

    spent = db.query(_func.sum(LLMUsage.cost_usd)).filter(LLMUsage.date == _date.today()).scalar()
    return float(spent or 0)


def _is_likely_non_political(title: str, text: str, language: str = "fr") -> bool:
    """Sports/people/météo : skip LLM. Langues hors liste : on n'applique pas le filtre FR."""
    lang = (language or "fr")[:2].lower()
    kws = NON_POLITICAL_BY_LANG.get(lang)
    if not kws:
        return False
    check_text = f"{title} {text[:500]}".lower()
    matches = sum(1 for kw in kws if kw in check_text)
    return matches >= 3


def _check_duplicate(db: Session, article: Article) -> Article | None:
    """Near-duplicate via pgvector cosine distance, 14 jours, hors même média."""
    if article.embedding is None:
        return None
    since = datetime.utcnow() - timedelta(days=14)
    dist = Article.embedding.cosine_distance(article.embedding)
    row = (
        db.query(Article)
        .filter(
            Article.id != article.id,
            Article.outlet_id != article.outlet_id,
            Article.embedding.isnot(None),
            Article.analysis_status.in_(["analyzed", "embedded_only"]),
            Article.duplicate_of_id.is_(None),
            Article.published_at >= since,
        )
        .add_columns(dist.label("dist"))
        .order_by(dist)
        .first()
    )
    if not row:
        return None
    other, d = row
    if d is not None and float(d) <= (1.0 - DEDUP_SIMILARITY_THRESHOLD):
        return other
    return None


def _stored_coverage(article: Article, min_len: int) -> str:
    cov = getattr(article, "text_coverage", None)
    if cov in ("body", "excerpt"):
        return cov
    return "body" if len(article.text or "") >= int(min_len) else "excerpt"


def _prompt_mode(stored: str, text: str, min_len: int) -> str:
    """Un chapô, ou un corps trop court pour le seuil, est lu comme un lead."""
    if stored == "excerpt" or len(text) < int(min_len):
        return "excerpt"
    return "body"


def _finish(extracted: dict | None, ner_entities: dict, coverage: str) -> dict:
    if extracted:
        extracted["entities"] = ner.merge_entities(extracted.get("entities"), ner_entities)
        extracted["coverage"] = coverage
        return extracted
    return {"entities": ner_entities, "topics": [], "framing": {}, "coverage": coverage}


def analyze_article(db: Session, article: Article) -> None:
    global _last_llm_call
    text = article.text or ""
    title = article.title or ""
    language = article.language or "fr"

    # 0) Texte parasite (bandeau cookies, mur de consentement, page de politique) : jamais d'appel LLM
    if extract.is_boilerplate(text, title):
        article.extracted_data = BOILERPLATE_DATA
        article.analysis_status = "embedded_only"
        db.commit()
        return

    # 1) Local embedding (always)
    if article.embedding is None:
        article.embedding = embeddings.embed_text(f"{title}\n{text[:2000]}")

    # 2) Quick non-political filter — skip LLM for sports/entertainment/lifestyle
    if _is_likely_non_political(title, text, language):
        ner_entities = ner.extract_entities(text, language)
        article.extracted_data = {
            "entities": ner_entities,
            "topics": [{"label": "Non-political", "framing": {}}],
            "framing": {},
            "tone": "neutral",
            "angle": "brief",
        }
        article.analysis_status = "embedded_only"
        db.commit()
        return

    # 3) Deduplication check
    original = _check_duplicate(db, article)
    if original:
        article.analysis_status = "duplicate"
        article.duplicate_of_id = original.id
        log.info("Article %s is duplicate of %s (similarity check)", article.id, original.id)
        db.commit()
        return

    # 4) LLM — le chapô est analysé aussi. Le corps long est lu comme un article entier.
    min_len = int(get_setting(db, "min_text_length_for_llm") or 400)
    stored = _stored_coverage(article, min_len)
    mode = _prompt_mode(stored, text, min_len)
    model = get_setting(db, "llm_model")
    outlet = db.get(Outlet, article.outlet_id)
    country = outlet.country if outlet else None
    extracted = None
    if len(text) >= extract.EXCERPT_MIN:
        db.commit()
        elapsed = time.time() - _last_llm_call
        if elapsed < LLM_CALL_INTERVAL:
            time.sleep(LLM_CALL_INTERVAL - elapsed)
        max_daily = float(get_setting(db, "max_daily_cost_usd") or 0)
        if max_daily > 0 and daily_cost(db) >= max_daily:
            log.info("Daily LLM cost cap reached (%.2f / %.2f), skipping LLM for article %s",
                     daily_cost(db), max_daily, article.id)
        else:
            extracted = llm.extract_article(db, model, title, text, country, coverage=mode)
            _last_llm_call = time.time()

    # 5) Local NER second pass + merge (language-aware)
    ner_entities = ner.extract_entities(text, language)
    article.extracted_data = _finish(extracted, ner_entities, stored)
    article.analysis_status = "analyzed" if extracted else "embedded_only"
    db.commit()


def _select_pending_batch(db: Session, limit: int) -> list[Article]:
    """Priorise les articles récents (<7j) des médias pas encore documentés (<15 articles analysés sur 7j)."""
    from sqlalchemy import func
    since7 = datetime.utcnow() - timedelta(days=7)
    analyzed_counts = dict(
        db.query(Article.outlet_id, func.count(Article.id))
        .filter(Article.analysis_status == "analyzed", Article.published_at >= since7)
        .group_by(Article.outlet_id)
        .all()
    )
    all_outlet_ids = [r[0] for r in db.query(Outlet.id).all()]
    under_ids = [oid for oid in all_outlet_ids if analyzed_counts.get(oid, 0) < 15]
    picked: list[Article] = []
    if under_ids:
        picked = (
            db.query(Article)
            .filter(
                Article.analysis_status == "pending",
                Article.published_at >= since7,
                Article.outlet_id.in_(under_ids),
            )
            .order_by(Article.captured_at.desc())
            .limit(limit)
            .all()
        )
    if len(picked) < limit:
        seen = {a.id for a in picked}
        q = db.query(Article).filter(Article.analysis_status == "pending")
        if seen:
            q = q.filter(~Article.id.in_(seen))
        picked.extend(q.order_by(Article.captured_at.desc()).limit(limit - len(picked)).all())
    return picked


def process_pending(db: Session, limit: int | None = None) -> int:
    if limit is None:
        limit = int(get_setting(db, "analysis_batch_size"))
    pending = _select_pending_batch(db, limit)
    if not pending:
        return 0
    n = max(1, int(EXTRACTION_CONCURRENCY))
    if n == 1:
        return _process_sequential(db, pending)
    return _process_parallel(db, pending, n)


def _process_sequential(db: Session, pending: list[Article]) -> int:
    done = 0
    for article in pending:
        try:
            analyze_article(db, article)
            done += 1
        except Exception as e:  # noqa: BLE001
            log.warning("analysis failed for article %s: %s", article.id, e)
            db.rollback()
            article.analysis_status = "error"
            db.commit()
    return done


def _process_parallel(db: Session, pending: list[Article], workers: int) -> int:
    """Phase 1 en parallèle : pré-traitement local + appel LLM (I/O bound).

    Chaque worker a sa session ; la session de la boucle n'est touchée que par le
    thread courant. Les embeddings tournent dans les threads (GIL relâché par
    torch), le NER est refait dans le thread principal après commit.
    """
    from ..database import SessionLocal

    def prepare(article_id: int) -> dict | None:
        """Pré-traitement + extraction LLM. Retourne le contexte ou None si traité sans LLM."""
        s = SessionLocal()
        try:
            a = s.get(Article, article_id)
            if a is None or a.analysis_status != "pending":
                return None
            text = a.text or ""
            title = a.title or ""
            language = a.language or "fr"
            if extract.is_boilerplate(text, title):
                a.extracted_data = BOILERPLATE_DATA
                a.analysis_status = "embedded_only"
                s.commit()
                return None
            if a.embedding is None:
                a.embedding = embeddings.embed_text(f"{title}\n{text[:2000]}")
            if _is_likely_non_political(title, text, language):
                a.extracted_data = {
                    "entities": {},
                    "topics": [{"label": "Non-political", "framing": {} }],
                    "framing": {},
                    "tone": "neutral",
                    "angle": "brief",
                }
                a.analysis_status = "embedded_only"
                s.commit()
                return None
            original = _check_duplicate(s, a)
            if original:
                a.analysis_status = "duplicate"
                a.duplicate_of_id = original.id
                s.commit()
                return None
            min_len = int(get_setting(s, "min_text_length_for_llm") or 400)
            stored = _stored_coverage(a, min_len)
            if len(text) < extract.EXCERPT_MIN:
                return {"needs_llm": False, "text": text, "language": language, "coverage": stored}
            model = get_setting(s, "llm_model")
            outlet = s.get(Outlet, a.outlet_id)
            country = outlet.country if outlet else None
            max_daily = float(get_setting(s, "max_daily_cost_usd") or 0)
            if max_daily > 0:
                with _llm_lock:
                    if daily_cost(s) >= max_daily:
                        log.info("Daily LLM cost cap reached (%.2f / %.2f), skipping LLM for article %s",
                                 daily_cost(s), max_daily, article_id)
                        return {"needs_llm": False, "text": text, "language": language, "coverage": stored}
            s.commit()
            global _last_llm_call
            with _llm_lock:
                elapsed = time.time() - _last_llm_call
                if elapsed < LLM_CALL_INTERVAL:
                    time.sleep(LLM_CALL_INTERVAL - elapsed)
                _last_llm_call = time.time()
            mode = _prompt_mode(stored, text, min_len)
            extracted = llm.extract_article(s, model, title, text, country, coverage=mode)
            return {"needs_llm": True, "extracted": extracted, "text": text, "language": language, "coverage": stored}
        except Exception as e:  # noqa: BLE001
            log.warning("analysis prepare failed for article %s: %s", article_id, e)
            s.rollback()
            try:
                a = s.get(Article, article_id)
                if a is not None:
                    a.analysis_status = "error"
                    s.commit()
            except Exception:  # noqa: BLE001
                s.rollback()
            return None
        finally:
            s.close()

    ids = [a.id for a in pending]
    db.commit()  # referme la transaction de lecture avant le travail parallèle des threads
    done = 0
    from contextvars import copy_context
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(copy_context().run, prepare, aid): aid for aid in ids}
        for fut in as_completed(futures):
            article_id = futures[fut]
            try:
                ctx = fut.result()
            except Exception as e:  # noqa: BLE001
                log.warning("analysis future failed for article %s: %s", article_id, e)
                continue
            if ctx is None:
                continue  # déjà traité et commité dans le thread (boilerplate / dup / erreur)
            a = db.get(Article, article_id)
            if a is None:
                continue
            try:
                ner_entities = ner.extract_entities(ctx["text"], ctx["language"])
                coverage = ctx.get("coverage") or "body"
                if ctx["needs_llm"] and ctx.get("extracted"):
                    a.extracted_data = _finish(ctx["extracted"], ner_entities, coverage)
                    a.analysis_status = "analyzed"
                else:
                    a.extracted_data = _finish(None, ner_entities, coverage)
                    a.analysis_status = "embedded_only"
                db.commit()
            except Exception as e:  # noqa: BLE001
                log.warning("analysis finalize failed for article %s: %s", article_id, e)
                db.rollback()
                a.analysis_status = "error"
                db.commit()
            done += 1
    return done
