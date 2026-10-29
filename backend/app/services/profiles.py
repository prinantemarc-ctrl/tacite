"""Journalist daily profiles and outlet weekly profiles (real classification, gap, drift, influence)."""

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from ..constants import AXES, axes_for_country
from ..kits import all_axis_ids, framing_value
from ..i18n import axis_label
from ..models import Article, ArticleJournalist, Journalist, JournalistProfile, Outlet, OutletProfile
from ..settings_store import get_setting
from . import llm

log = logging.getLogger("tacite.profiles")


# ---------------------------------------------------------------- journalists

def build_journalist_profile(db: Session, journalist: Journalist) -> JournalistProfile | None:
    since = datetime.utcnow() - timedelta(days=7)
    articles = (
        db.query(Article)
        .filter(Article.journalist_id == journalist.id, Article.published_at >= since)
        .order_by(Article.published_at.desc())
        .all()
    )
    if not articles:
        return None

    digest, topic_counter, tone_counter, source_counter = [], Counter(), Counter(), Counter()
    for a in articles:
        data = a.extracted_data or {}
        topics = [t.get("label") for t in data.get("topics", []) if t.get("label")]
        topic_counter.update(topics)
        if data.get("tone"):
            tone_counter[data["tone"]] += 1
        for s in data.get("sources", []):
            source_counter[s.get("type", "other")] += 1
        digest.append({
            "title": a.title,
            "topics": topics,
            "tone": data.get("tone"),
            "angle": data.get("angle"),
            "framing": data.get("framing", {}),
        })

    productivity = len(articles)  # articles over 7 days
    synthesis = llm.synthesize_journalist_profile(
        db, get_setting(db, "llm_profile_model"), journalist.name,
        journalist.outlet.name if journalist.outlet else "", digest,
    )

    if synthesis:
        themes = synthesis.get("themes") or [{"label": t, "count": c} for t, c in topic_counter.most_common(6)]
        biases = synthesis.get("biases", [])
        vulnerabilities = synthesis.get("vulnerabilities", [])
        tone = synthesis.get("tone") or (tone_counter.most_common(1)[0][0] if tone_counter else "neutre")
        accessibility = float(synthesis.get("accessibility_score", 50))
        summary = synthesis.get("summary", "")
        preferred_sources = synthesis.get("preferred_sources") or [
            {"type": t, "count": c} for t, c in source_counter.most_common(5)
        ]
    else:
        # Heuristic fallback (no LLM available)
        themes = [{"label": t, "count": c} for t, c in topic_counter.most_common(6)]
        biases = []
        vulnerabilities = []
        if productivity >= 7:
            vulnerabilities.append({"label": "cadence élevée", "explanation": "Publie beaucoup, probablement en recherche de sujets."})
        tone = tone_counter.most_common(1)[0][0] if tone_counter else "neutre"
        accessibility = min(95.0, 35 + productivity * 5 + len(topic_counter) * 2)
        summary = ""
        preferred_sources = [{"type": t, "count": c} for t, c in source_counter.most_common(5)]

    profile = JournalistProfile(
        journalist_id=journalist.id,
        date=date.today(),
        themes=themes,
        biases=biases,
        preferred_sources=preferred_sources,
        tone=tone,
        productivity=productivity,
        vulnerabilities=vulnerabilities,
        accessibility_score=accessibility,
        raw_summary=summary,
    )
    db.add(profile)
    journalist.accessibility_score = accessibility
    db.commit()
    return profile


def run_journalist_profiles(db: Session) -> int:
    count = 0
    for j in db.query(Journalist).all():
        try:
            if build_journalist_profile(db, j):
                count += 1
        except Exception as e:  # noqa: BLE001
            log.warning("journalist profile failed for %s: %s", j.name, e)
            db.rollback()
    return count


# -------------------------------------------------------------------- outlets

def _monday(d: date) -> date:
    return d - timedelta(days=d.weekday())


def _evidence_weight(article: Article) -> float:
    """Un chapô compte pour moitié : il ouvre le cadrage, il ne porte pas les sources."""
    data = getattr(article, "extracted_data", None) or {}
    cov = data.get("coverage") or getattr(article, "text_coverage", None)
    return 0.5 if cov == "excerpt" else 1.0


def _as_n(total: float) -> int | float:
    if abs(total - round(total)) < 1e-9:
        return int(round(total))
    return round(total, 1)


def _real_classification(articles: list[Article]) -> tuple[dict, dict]:
    """Moyenne pondérée des cadrages non nuls. Un chapô pèse 0,5."""
    real, axis_n = {}, {}
    for axis in all_axis_ids():
        weighted: list[tuple[float, float]] = []
        for a in articles:
            v = framing_value((a.extracted_data or {}).get("framing") or {}, axis)
            if v:
                weighted.append((v, _evidence_weight(a)))
        if weighted:
            denom = sum(w for _, w in weighted)
            real[axis] = round(sum(v * w for v, w in weighted) / denom, 3)
            axis_n[axis] = _as_n(denom)
        else:
            real[axis] = 0.0
            axis_n[axis] = 0
    axis_n["_evidence"] = _as_n(sum(_evidence_weight(a) for a in articles))
    return real, axis_n


def evidence_n(axis_n: dict | None, article_count: int | None) -> float:
    """Effectif qui porte la confiance : les chapôs comptent pour moitié quand le profil le sait."""
    if axis_n and axis_n.get("_evidence") is not None:
        return float(axis_n["_evidence"])
    return float(article_count or 0)


def _citation_counts(db: Session, outlets: list[Outlet], since: datetime) -> dict[int, int]:
    """How many articles from OTHER outlets mention/cite each outlet.
    Uses entity matching, title matching, URL matching, and name variants."""
    from ..models import Citation
    from urllib.parse import urlparse
    import re

    # Build name variants for each outlet
    outlet_variants: dict[int, list[str]] = {}
    outlet_domains: dict[int, str] = {}
    for o in outlets:
        variants = {o.name.lower()}
        # Remove common prefixes/articles
        clean = re.sub(r"^(le |la |les |l'|el |il |der |die |das )", "", o.name.lower())
        variants.add(clean)
        # Add without special chars
        variants.add(re.sub(r"[^a-z0-9àâäéèêëïîôùûüÿçœæ\s]", "", o.name.lower()).strip())
        # Domain-based variant
        if o.website_url:
            domain = urlparse(o.website_url).netloc.lower()
            outlet_domains[o.id] = domain
            # e.g. "lemonde.fr" from "www.lemonde.fr"
            domain_no_www = re.sub(r"^www\.", "", domain)
            variants.add(domain_no_www.replace(".", " ").replace("-", " "))
        outlet_variants[o.id] = list(variants)

    # Clear old citations for this period and rebuild
    # (We recompute from scratch each week for accuracy)
    counts = {o.id: 0 for o in outlets}

    articles = (
        db.query(Article.id, Article.outlet_id, Article.title, Article.text, Article.extracted_data)
        .filter(Article.published_at >= since, Article.analysis_status.in_(["analyzed", "embedded_only"]))
        .all()
    )

    # Delete old citations from this period
    db.query(Citation).filter(Citation.timestamp >= since).delete()
    db.flush()

    for art_id, src_outlet_id, title, text, data in articles:
        if src_outlet_id is None:
            continue
        # Build the search text: title + organizations from NER/LLM + raw text (for URL matching)
        orgs = " ".join(((data or {}).get("entities") or {}).get("organizations", [])).lower()
        search_text = f"{title or ''} {orgs}".lower()
        raw_text = (text or "").lower()

        for target_outlet in outlets:
            if target_outlet.id == src_outlet_id:
                continue
            matched = False
            match_type = None

            # 1) Entity / title matching (name variants)
            for variant in outlet_variants.get(target_outlet.id, []):
                if variant and variant in search_text:
                    matched, match_type = True, "entity"
                    break

            # 2) URL matching — check if article text contains a link to the outlet's domain
            if not matched and target_outlet.id in outlet_domains:
                domain = outlet_domains[target_outlet.id]
                if domain in raw_text:
                    matched, match_type = True, "url"

            if matched:
                counts[target_outlet.id] += 1
                db.add(Citation(
                    source_outlet_id=src_outlet_id,
                    target_outlet_id=target_outlet.id,
                    article_id=art_id,
                    match_type=match_type,
                ))

    db.commit()
    return counts


def _agenda_lead_rates(db: Session, outlets: list[Outlet], since: datetime) -> dict[int, float]:
    """Cluster articles by main topic within the window; outlets among the first 3 publishers lead."""
    articles = (
        db.query(Article.outlet_id, Article.published_at, Article.extracted_data)
        .filter(Article.published_at >= since, Article.analysis_status == "analyzed")
        .order_by(Article.published_at.asc())
        .all()
    )
    events = defaultdict(list)  # topic label -> [(published, outlet_id)]
    for outlet_id, published, data in articles:
        topics = (data or {}).get("topics", [])
        if topics and topics[0].get("label"):
            events[topics[0]["label"].lower().strip()].append((published, outlet_id))

    led, participated = Counter(), Counter()
    for _label, items in events.items():
        outlets_in_event = {oid for _, oid in items}
        if len(outlets_in_event) < 2:
            continue  # not a shared news event
        first_three = []
        for _, oid in items:
            if oid not in first_three:
                first_three.append(oid)
            if len(first_three) == 3:
                break
        for oid in outlets_in_event:
            participated[oid] += 1
            if oid in first_three:
                led[oid] += 1
    return {o.id: (led[o.id] / participated[o.id] if participated[o.id] else 0.0) for o in outlets}


def _longevity_score(db: Session, outlet: Outlet) -> float:
    manual = (outlet.meta or {}).get("longevity_score")
    if manual is not None:
        return float(manual)
    # Regularity: share of the last 8 weeks with at least one article.
    since = datetime.utcnow() - timedelta(weeks=8)
    articles = db.query(Article.published_at).filter(
        Article.outlet_id == outlet.id, Article.published_at >= since
    ).all()
    weeks = {_monday(a[0].date()) for a in articles if a[0]}
    return len(weeks) / 8 * 100


def _normalize(raw: dict[int, float]) -> dict[int, float]:
    """Conservé pour tests / usages ponctuels. L'influence hebdo n'y passe plus."""
    vals = list(raw.values())
    lo, hi = min(vals), max(vals)
    if hi == lo:
        return {k: 0.5 for k in raw}
    return {k: (v - lo) / (hi - lo) for k, v in raw.items()}


CITATION_CAP = 40.0  # citations/semaine → score 100


def _anchored_citation(n: float) -> float:
    import math
    if n <= 0:
        return 0.0
    return min(100.0, 100.0 * math.log1p(n) / math.log1p(CITATION_CAP))


def _anchored_agenda(rate: float) -> float:
    return max(0.0, min(100.0, float(rate) * 100))


def run_outlet_profiles(db: Session) -> int:
    """Weekly job: real classification, gap, drift alerts, influence components + score."""
    outlets = db.query(Outlet).all()
    if not outlets:
        return 0
    now = datetime.utcnow()
    since_week = now - timedelta(days=7)
    week = _monday(date.today())
    drift_threshold = float(get_setting(db, "drift_threshold"))
    weights = get_setting(db, "influence_weights")

    citation_raw = _citation_counts(db, outlets, since_week)
    agenda_raw = _agenda_lead_rates(db, outlets, since_week)
    audience_raw = {o.id: float((o.meta or {}).get("audience_score", 50)) for o in outlets}
    elite_raw = {o.id: float((o.meta or {}).get("elite_score", 50)) for o in outlets}
    network_raw = {o.id: float((o.meta or {}).get("network_score", 50)) for o in outlets}
    longevity_raw = {o.id: _longevity_score(db, o) for o in outlets}

    count = 0
    scores = {}
    for outlet in outlets:
        try:
            articles = (
                db.query(Article)
                .filter(Article.outlet_id == outlet.id,
                        Article.published_at >= since_week,
                        Article.analysis_status == "analyzed")
                .all()
            )
            real, axis_n = _real_classification(articles)
            official = outlet.official_classification or {}
            usable = axes_for_country(outlet.country, db)
            gap = {axis: round(real.get(axis, 0) - float(official.get(axis, 0) or 0), 3) for axis in usable}

            # Drift vs previous 4-week average
            previous = (
                db.query(OutletProfile)
                .filter(OutletProfile.outlet_id == outlet.id, OutletProfile.week < week)
                .order_by(OutletProfile.week.desc())
                .limit(4)
                .all()
            )
            alerts = []
            if previous:
                for axis in usable:
                    if (axis_n.get(axis) or 0) < 10:
                        continue
                    prev_vals = [(p.real_classification or {}).get(axis, 0) for p in previous]
                    prev_avg = sum(prev_vals) / len(prev_vals)
                    change = real[axis] - prev_avg
                    if abs(change) > drift_threshold and articles:
                        alerts.append({"axis": axis, "change": round(change, 3),
                                       "previous": round(prev_avg, 3), "current": real[axis]})

            components = {
                "audience": round(audience_raw[outlet.id] / 100, 3),
                "citation": round(_anchored_citation(float(citation_raw.get(outlet.id, 0))) / 100, 3),
                "agenda": round(_anchored_agenda(agenda_raw.get(outlet.id, 0)) / 100, 3),
                "elite": round(elite_raw[outlet.id] / 100, 3),
                "network": round(network_raw[outlet.id] / 100, 3),
                "longevity": round(longevity_raw[outlet.id] / 100, 3),
            }
            score = sum(components[c] * float(weights.get(c, 0)) for c in components) * 100
            scores[outlet.id] = score

            existing = db.query(OutletProfile).filter(
                OutletProfile.outlet_id == outlet.id, OutletProfile.week == week
            ).first()
            if existing:
                existing.real_classification = real
                existing.gap_from_official = gap
                existing.drift_alerts = alerts
                existing.component_scores = components
                existing.article_count = len(articles)
                existing.axis_n = axis_n
            else:
                db.add(OutletProfile(
                    outlet_id=outlet.id, week=week, real_classification=real,
                    gap_from_official=gap, drift_alerts=alerts,
                    component_scores=components, article_count=len(articles),
                    axis_n=axis_n,
                ))
            outlet.influence_score = round(score, 1)
            db.commit()
            count += 1
        except Exception as e:  # noqa: BLE001
            log.warning("outlet profile failed for %s: %s", outlet.name, e)
            db.rollback()

    # Ranks
    ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
    for rank, (outlet_id, _s) in enumerate(ranked, start=1):
        db.query(Outlet).filter(Outlet.id == outlet_id).update({"influence_rank": rank})
    db.commit()
    return count


# ---------------------------------------------------------------- recap médias

SKIP_TOPIC_KEYS = frozenset({"non-political", "non political", "hors sujet", "hors-sujet"})
RECAP_WEEKS = 8


def confidence_label(n: int) -> str:
    return "élevée" if n >= 30 else "moyenne" if n >= 10 else "faible"


def max_usable_gap(country: str | None, gaps: dict | None, axis_n: dict | None, db=None) -> dict | None:
    """Plus grand écart |mesuré − déclaré| parmi les axes assez renseignés. Valeur signée."""
    if not gaps:
        return None
    usable = axes_for_country(country, db)
    has_n = bool(axis_n)
    scored: list[tuple[str, float]] = []
    for axis, val in gaps.items():
        if axis not in usable:
            continue
        if has_n and (axis_n.get(axis) or 0) < 10:
            continue
        scored.append((axis, float(val or 0)))
    if not scored:
        return None
    axis, val = max(scored, key=lambda x: abs(x[1]))
    return {"axis": axis, "label": axis_label(axis), "value": round(val, 2)}


def topics_from_extracted(items: list, n: int = 3) -> list[dict]:
    """Compte les thèmes d'une liste de extracted_data (ou de listes `topics`)."""
    counts: Counter = Counter()
    labels: dict[str, str] = {}
    for data in items:
        topics = data
        if isinstance(data, dict):
            topics = data.get("topics")
        if isinstance(topics, str):
            try:
                topics = json.loads(topics)
            except (TypeError, ValueError):
                continue
        if not isinstance(topics, list):
            continue
        for t in topics:
            raw = (t.get("label") if isinstance(t, dict) else str(t or "")).strip()
            if not raw:
                continue
            key = re.sub(r"\s+", " ", raw.lower())
            if key in SKIP_TOPIC_KEYS or key.startswith("non-polit"):
                continue
            counts[key] += 1
            labels.setdefault(key, raw)
    return [{"label": labels[k], "count": c} for k, c in counts.most_common(n)]


def recap_for_outlets(
    db: Session,
    outlet_ids: list[int] | None = None,
    weeks: int = RECAP_WEEKS,
    topics_n: int = 3,
    journalists_n: int = 3,
) -> dict[int, dict]:
    """Sujets de prédilection et journalistes les plus actifs, sur `weeks` semaines."""
    if outlet_ids is not None and not outlet_ids:
        return {}
    since = datetime.utcnow() - timedelta(weeks=weeks)
    out: dict[int, dict] = defaultdict(lambda: {"topics": [], "journalists": [], "journalists_count": 0})

    jcounts = db.query(Journalist.outlet_id, func.count(Journalist.id)).group_by(Journalist.outlet_id)
    if outlet_ids is not None:
        jcounts = jcounts.filter(Journalist.outlet_id.in_(outlet_ids))
    for oid, n in jcounts.all():
        out[oid]["journalists_count"] = int(n or 0)

    topic_q = db.query(Article.outlet_id, Article.extracted_data).filter(
        Article.analysis_status == "analyzed",
        Article.published_at.isnot(None),
        Article.published_at >= since,
    )
    if outlet_ids is not None:
        topic_q = topic_q.filter(Article.outlet_id.in_(outlet_ids))
    by_topics: dict[int, list] = defaultdict(list)
    for oid, data in topic_q.all():
        by_topics[oid].append(data)
    for oid, items in by_topics.items():
        out[oid]["topics"] = topics_from_extracted(items, topics_n)

    not_dup = Article.analysis_status != "duplicate"
    aj = (
        db.query(Article.outlet_id.label("oid"), ArticleJournalist.journalist_id.label("jid"), Article.id.label("aid"))
        .join(ArticleJournalist, ArticleJournalist.article_id == Article.id)
        .filter(Article.published_at.isnot(None), Article.published_at >= since, not_dup)
    )
    legacy = (
        db.query(Article.outlet_id.label("oid"), Article.journalist_id.label("jid"), Article.id.label("aid"))
        .filter(Article.journalist_id.isnot(None), Article.published_at.isnot(None), Article.published_at >= since, not_dup)
    )
    if outlet_ids is not None:
        aj = aj.filter(Article.outlet_id.in_(outlet_ids))
        legacy = legacy.filter(Article.outlet_id.in_(outlet_ids))
    sub = aj.union(legacy).subquery()
    jrows = (
        db.query(
            sub.c.oid,
            Journalist.id,
            Journalist.name,
            Journalist.accessibility_score,
            func.count(func.distinct(sub.c.aid)),
        )
        .join(Journalist, Journalist.id == sub.c.jid)
        .group_by(sub.c.oid, Journalist.id, Journalist.name, Journalist.accessibility_score)
    )
    by_j: dict[int, list] = defaultdict(list)
    for oid, jid, name, acc, n in jrows.all():
        if n:
            by_j[oid].append({
                "id": jid, "name": name,
                "accessibility": round(float(acc or 0), 0),
                "articles": int(n),
            })
    for oid, lst in by_j.items():
        lst.sort(key=lambda x: (-x["articles"], x["name"] or ""))
        out[oid]["journalists"] = lst[:journalists_n]

    return dict(out)
