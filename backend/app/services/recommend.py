"""Recommendation engine: stance evaluation, vulnerability detection, action selection,
plan generation, priority ranking, and the learning loop."""

import logging
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from ..constants import ACTION_DOWNGRADE, ACTION_TYPES, RISK_ORDER, axes_for_country
from ..models import (
    ActionHistory,
    Article,
    Client,
    ClientBlacklist,
    Journalist,
    Outlet,
    OutletProfile,
    Recommendation,
)
from ..settings_store import get_setting, set_setting
from . import embeddings, llm

log = logging.getLogger("tacite.recommend")


def _stance_for_outlet(article_vecs: list, push_vecs: list, counter_vecs: list) -> float:
    """Raw stance: similarity to push narratives minus similarity to counter narratives."""
    if not article_vecs or (not push_vecs and not counter_vecs):
        return 0.0
    arts = np.array(article_vecs)

    def mean_top_sim(narr_vecs):
        if not narr_vecs:
            return 0.0
        sims = arts @ np.array(narr_vecs).T
        per_article = sims.max(axis=1)
        top = np.sort(per_article)[-min(5, len(per_article)):]
        return float(top.mean())

    return mean_top_sim(push_vecs) - mean_top_sim(counter_vecs)


def _vulnerabilities(db: Session, outlet: Outlet, profile: OutletProfile | None,
                     best_journalist: Journalist | None, gap_threshold: float) -> tuple[float, list[str]]:
    """Returns (strength 0..1, signals in French)."""
    signals, strength = [], 0.0
    max_gap = 0.0
    if profile and profile.gap_from_official:
        usable = axes_for_country(outlet.country, db)
        axis_n = profile.axis_n or {}
        vals = [abs(v) for a, v in profile.gap_from_official.items()
                if a in usable and (axis_n.get(a) or 0) >= 10]
        max_gap = max(vals) if vals else 0.0
        if max_gap > gap_threshold:
            signals.append(f"Écart officiel/réel exploitable (max {max_gap:.2f})")
            strength += 0.3
    if profile and profile.drift_alerts:
        signals.append(f"Dérive éditoriale détectée ({len(profile.drift_alerts)} axe(s))")
        strength += 0.2
    if best_journalist and best_journalist.accessibility_score:
        acc = best_journalist.accessibility_score
        if acc >= 70:
            signals.append(f"Journaliste accessible ({best_journalist.name}, score {acc:.0f})")
            strength += 0.25
        elif acc >= 50:
            signals.append(f"Journaliste moyennement accessible ({best_journalist.name}, score {acc:.0f})")
            strength += 0.1
    # Check if outlet has low article volume (potentially desperate for content)
    if profile and profile.article_count is not None and profile.article_count < 10:
        signals.append("Volume de publication faible — peut être en recherche de contenu")
        strength += 0.15
    return min(strength, 1.0), signals


def _select_action(stance: float, influence: float, vuln_strength: float,
                   risk_tolerance: str) -> tuple[str, str]:
    """Returns (action_type, risk_level). Applies downgrade if action exceeds client tolerance."""
    high_infl = influence >= get_setting_static("influence_high_threshold")
    med_infl = influence >= get_setting_static("influence_medium_threshold")
    exploitable = vuln_strength >= 0.3

    # Primary selection
    if stance < -0.15:  # hostile
        if high_infl and exploitable:
            action, risk = "RETOURNER", "high"
        elif high_infl:
            action, risk = "ISOLER", "high"
        elif med_infl:
            action, risk = "COOPTER", "medium"
        else:
            action, risk = "SURVEILLER", "low"
    elif stance > 0.15:  # favorable
        if high_infl:
            action, risk = "NOURRIR", "low"
        elif med_infl:
            action, risk = "AMORCER", "low"
        else:
            action, risk = "DILUER", "medium"
    else:  # neutral
        if high_infl:
            action, risk = "NOURRIR", "low"
        elif med_infl:
            action, risk = "AMORCER", "low"
        else:
            action, risk = "SURVEILLER", "low"

    # Downgrade if action risk exceeds client tolerance
    max_risk = RISK_ORDER.get(risk_tolerance, 1)
    while RISK_ORDER.get(risk, 0) > max_risk:
        action = ACTION_DOWNGRADE.get(action)
        if action is None:
            action, risk = "SURVEILLER", "low"
            break
        risk = ACTION_TYPES[action]

    return action, risk


# Cache-free accessor for settings used in action selection (avoids DB in pure-logic path)
_settings_cache = {}


def get_setting_static(key: str):
    return _settings_cache.get(key, 50)


def refresh_settings_cache(db: Session):
    from ..settings_store import get_settings
    _settings_cache.update(get_settings(db))


def _best_journalist(db: Session, outlet_id: int, topic_keywords: list[str] | None = None) -> Journalist | None:
    """Pick the journalist with the highest accessibility score at this outlet."""
    q = db.query(Journalist).filter(Journalist.outlet_id == outlet_id)
    journalists = q.all()
    if not journalists:
        return None
    return max(journalists, key=lambda j: j.accessibility_score or 0)


def _budget_for_action(action_type: str) -> str:
    if action_type in ("RETOURNER", "DIVISER", "ISOLER"):
        return "high"
    if action_type in ("COOPTER", "CONTOURNER", "DILUER"):
        return "medium"
    return "low"


def generate_recommendations(db: Session, client: Client) -> tuple[list[Recommendation], list[Recommendation]]:
    """Generate recommendations for one client across all outlets."""
    refresh_settings_cache(db)

    # Embed client narratives
    push_narratives = client.narratives_push or []
    counter_narratives = client.narratives_counter or []
    push_vecs = embeddings.embed_texts(push_narratives) if push_narratives else []
    counter_vecs = embeddings.embed_texts(counter_narratives) if counter_narratives else []

    # Blacklisted outlets
    blacklisted = {b.outlet_id for b in db.query(ClientBlacklist).filter(ClientBlacklist.client_id == client.id).all()}

    # Existing contacts
    contact_journalist_ids = {
        c.journalist_id
        for c in db.query(Client.id).filter(Client.id == client.id).first() and []
    }

    outlets = db.query(Outlet).all()
    model = get_setting(db, "llm_model")
    gap_threshold = _adaptive_thresholds.get("gap_exploitable_threshold",
                     float(get_setting(db, "gap_exploitable_threshold") or 0.35))
    pitch_threshold = _adaptive_thresholds.get("accessibility_pitch_threshold",
                       float(get_setting(db, "accessibility_pitch_threshold") or 55))
    # Refresh adaptive thresholds from history
    _refresh_adaptive_thresholds(db)
    since = datetime.utcnow() - timedelta(days=7)

    recs = []
    kept = []
    for outlet in outlets:
        if outlet.id in blacklisted:
            continue

        # Articles from last 7 days
        articles = (
            db.query(Article)
            .filter(Article.outlet_id == outlet.id, Article.published_at >= since,
                    Article.analysis_status.in_(["analyzed", "embedded_only"]))
            .all()
        )
        if not articles:
            continue

        # Stance
        article_vecs = [a.embedding for a in articles if a.embedding]
        stance = _stance_for_outlet(article_vecs, push_vecs, counter_vecs)

        # Best journalist
        best_j = _best_journalist(db, outlet.id)
        if best_j and (best_j.accessibility_score or 0) < pitch_threshold:
            # Still include them but note lower accessibility
            pass

        # Outlet profile
        profile = (
            db.query(OutletProfile)
            .filter(OutletProfile.outlet_id == outlet.id)
            .order_by(OutletProfile.week.desc())
            .first()
        )

        # Vulnerabilities
        vuln_strength, vuln_signals = _vulnerabilities(db, outlet, profile, best_j, gap_threshold)

        # Action selection
        action, risk = _select_action(stance, outlet.influence_score or 0, vuln_strength, client.risk_tolerance)

        open_same = (
            db.query(Recommendation)
            .filter(
                Recommendation.client_id == client.id,
                Recommendation.outlet_id == outlet.id,
                Recommendation.action_type == action,
                Recommendation.status.in_(["proposed", "accepted", "in_progress"]),
            )
            .first()
        )
        if open_same:
            kept.append(open_same)
            continue

        # Priority = influence × |stance| × vulnerability
        influence_norm = (outlet.influence_score or 0) / 100
        priority = influence_norm * max(abs(stance), 0.1) * max(vuln_strength, 0.2)

        # Generate plan via LLM
        plan_context = {
            "action_type": action,
            "outlet": outlet.name,
            "outlet_influence": outlet.influence_score,
            "stance": round(stance, 3),
            "client_sector": client.sector,
            "client_objectives": client.objectives,
            "narratives_push": push_narratives[:3],
            "narratives_counter": counter_narratives[:3],
            "vulnerabilities": vuln_signals,
            "journalist": best_j.name if best_j else None,
            "journalist_accessibility": best_j.accessibility_score if best_j else None,
        }
        plan = llm.generate_plan(db, model, plan_context)

        # Stance label in French
        if stance < float(get_setting_static("stance_hostile_threshold") or -0.15):
            stance_label = "hostile"
        elif stance > float(get_setting_static("stance_favorable_threshold") or 0.15):
            stance_label = "favorable"
        else:
            stance_label = "neutre"

        rec = Recommendation(
            client_id=client.id,
            outlet_id=outlet.id,
            journalist_id=best_j.id if best_j else None,
            action_type=action,
            priority=round(priority, 4),
            status="proposed",
            plan=plan,
            risk_level=risk,
            budget_level=_budget_for_action(action),
            justification={
                "stance": stance_label,
                "stance_score": round(stance, 3),
                "influence": outlet.influence_score,
                "vulnerability_strength": round(vuln_strength, 3),
                "vulnerability_signals": vuln_signals,
                "summary": f"{outlet.name} est {stance_label} vis-à-vis des narratifs du client. "
                           f"Action recommandée : {action}.",
            },
        )
        db.add(rec)
        recs.append(rec)

    db.commit()
    return recs, kept


def run_all_recommendations(db: Session) -> int:
    """Generate recommendations for all active clients."""
    total = 0
    for client in db.query(Client).all():
        try:
            created, _kept = generate_recommendations(db, client)
            total += len(created)
        except Exception as e:  # noqa: BLE001
            log.warning("recommendations failed for client %s: %s", client.name, e)
            db.rollback()
    return total


# ---------------------------------------------------------------- learning loop

# Adaptive thresholds — adjusted based on action history success rates.
_adaptive_thresholds: dict[str, float] = {
    "accessibility_pitch_threshold": 55.0,
    "gap_exploitable_threshold": 0.35,
}


def _refresh_adaptive_thresholds(db: Session) -> None:
    """Adjust thresholds based on historical success rates per action type.
    If an action type has >75% success, lower its barrier by 5 points.
    If it has <30% success, raise its barrier by 5 points."""
    rates = get_success_rates(db)
    acc_thresh = float(get_setting(db, "accessibility_pitch_threshold") or 55)
    gap_thresh = float(get_setting(db, "gap_exploitable_threshold") or 0.35)

    # Aggregate success rates by risk level
    low_actions = ["NOURRIR", "AMORCER", "SURVEILLER"]
    med_actions = ["COOPTER", "CONTOURNER", "DILUER"]
    high_actions = ["RETOURNER", "DIVISER", "ISOLER"]

    def avg_rate(actions):
        vals = [rates.get(a, 0.5) for a in actions if a in rates]
        return sum(vals) / len(vals) if vals else 0.5

    low_rate = avg_rate(low_actions)
    med_rate = avg_rate(med_actions)
    high_rate = avg_rate(high_actions)

    # Adjust accessibility threshold: if low-risk actions succeed often,
    # we can be less picky about journalist accessibility
    if low_rate > 0.75:
        acc_thresh = max(30, acc_thresh - 5)
    elif low_rate < 0.30:
        acc_thresh = min(80, acc_thresh + 5)

    # Adjust gap threshold: if high-risk actions succeed, we need less of a gap
    if high_rate > 0.75:
        gap_thresh = max(0.15, gap_thresh - 0.05)
    elif high_rate < 0.30:
        gap_thresh = min(0.60, gap_thresh + 0.05)

    _adaptive_thresholds["accessibility_pitch_threshold"] = acc_thresh
    _adaptive_thresholds["gap_exploitable_threshold"] = gap_thresh

    # Store adjusted thresholds back to settings for transparency
    set_setting(db, "_adaptive_accessibility_threshold", round(acc_thresh, 1))
    set_setting(db, "_adaptive_gap_threshold", round(gap_thresh, 3))


def record_outcome(db: Session, recommendation_id: int, outcome: str,
                   impact_metrics: dict | None = None, lessons: str | None = None) -> ActionHistory | None:
    rec = db.get(Recommendation, recommendation_id)
    if not rec:
        return None
    rec.status = "completed"
    rec.updated_at = datetime.utcnow()
    history = ActionHistory(
        recommendation_id=recommendation_id,
        client_id=rec.client_id,
        outlet_id=rec.outlet_id,
        action_type=rec.action_type,
        outcome=outcome,
        impact_metrics=impact_metrics or {},
        lessons_learned=lessons,
        started_at=rec.created_at,
        completed_at=datetime.utcnow(),
    )
    db.add(history)
    db.commit()
    return history


def get_success_rates(db: Session) -> dict[str, float]:
    """Success rate per action type from history. Used for learning adjustments."""
    rows = db.query(ActionHistory).all()
    if not rows:
        return {}
    buckets: dict[str, list[bool]] = {}
    for r in rows:
        buckets.setdefault(r.action_type, []).append(r.outcome == "success")
    return {action: sum(v) / len(v) for action, v in buckets.items() if v}
