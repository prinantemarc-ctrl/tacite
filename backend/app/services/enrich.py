"""Journalist enrichment — use LLM to infer role, beat, and find social handles."""

import json
import logging
import re

from sqlalchemy.orm import Session

from ..models import Article, Journalist
from ..settings_store import get_setting
from . import llm

log = logging.getLogger("tacite.enrich")

BEATS = ["Politique", "Économie", "International", "Justice", "Société", "Écologie", "Santé", "Éducation", "Culture", "Médias", "Technologie", "Sciences", "Défense", "Religion", "Sport", "Régions", "Généraliste"]

ENRICH_SYSTEM = """You are a press intelligence analyst. Given a journalist's name, outlet, and a sample of their recent article titles, infer:

1. Their professional role (e.g. "Grand reporter", "Éditorialiste", "Chef du service politique", "Correspondant Europe", "Chroniqueur", "Journaliste d'investigation", "Journaliste")
2. Their beat/specialty — EXACTLY one of: """ + ", ".join(BEATS) + """ (pick the closest; "Généraliste" if none dominates)
3. A 1-2 sentence bio in French, based only on the titles (no invented biography, no contact details).

FIRST, check the name: if it is NOT a person's name (a phrase like "Article rédigé par", a newsroom, an agency, a media brand, a section, a placeholder), respond ONLY with {"not_a_person": true, "reason": "..."} and nothing else. Never write a biography for something that is not a person.
Never guess social handles or e-mail addresses: contact channels are collected from verifiable sources elsewhere.

Respond with JSON only:
{
  "role": "...",
  "beat": "...",
  "bio": "..."
}"""


def _discard_non_person(db: Session, journalist: Journalist, reason: str) -> None:
    """Le nom n'est pas une personne : on détache ses articles et on supprime la fiche (jamais de profil fabriqué)."""
    from ..models import ArticleJournalist, ClientContact, ContactScan, JournalistContact, JournalistProfile, Recommendation
    log.info("Not a person, removing journalist %r (%s)", journalist.name, reason)
    db.query(Article).filter(Article.journalist_id == journalist.id).update({Article.journalist_id: None}, synchronize_session=False)
    db.query(Recommendation).filter(Recommendation.journalist_id == journalist.id).update({Recommendation.journalist_id: None}, synchronize_session=False)
    for model in (ArticleJournalist, ClientContact, JournalistProfile, JournalistContact, ContactScan):
        db.query(model).filter(model.journalist_id == journalist.id).delete(synchronize_session=False)
    db.delete(journalist)
    db.commit()


_BEAT_ALIASES = {
    "tech": "Technologie", "technologie": "Technologie", "numérique": "Technologie", "numerique": "Technologie", "ia": "Technologie", "digital": "Technologie", "high-tech": "Technologie",
    "economie": "Économie", "économie": "Économie", "finance": "Économie", "entreprises": "Économie", "business": "Économie", "bourse": "Économie", "social": "Société",
    "environnement": "Écologie", "ecologie": "Écologie", "écologie": "Écologie", "climat": "Écologie", "énergie": "Écologie", "energie": "Écologie",
    "monde": "International", "europe": "International", "géopolitique": "International", "geopolitique": "International", "diplomatie": "International",
    "police": "Justice", "faits divers": "Justice", "sécurité": "Justice", "securite": "Justice", "renseignement": "Défense", "armées": "Défense", "armees": "Défense",
    "science": "Sciences", "sciences": "Sciences", "espace": "Sciences", "medias": "Médias", "médias": "Médias", "presse": "Médias", "télévision": "Médias",
    "education": "Éducation", "éducation": "Éducation", "enseignement": "Éducation", "sante": "Santé", "santé": "Santé", "médecine": "Santé",
    "culture": "Culture", "cinéma": "Culture", "livres": "Culture", "musique": "Culture", "arts": "Culture", "sport": "Sport", "sports": "Sport", "football": "Sport",
    "religion": "Religion", "laïcité": "Religion", "laicite": "Religion", "régions": "Régions", "regions": "Régions", "local": "Régions", "politique": "Politique", "élections": "Politique",
}


def normalize_beat(raw: str | None) -> str:
    b = (raw or "").strip().strip("[]").strip()
    if not b:
        return ""
    if b in BEATS:
        return b
    low = b.lower()
    if low in _BEAT_ALIASES:
        return _BEAT_ALIASES[low]
    for k, v in _BEAT_ALIASES.items():
        if k in low:
            return v
    for x in BEATS:
        if x.lower() in low:
            return x
    return b[:30]


def enrich_journalist(db: Session, journalist: Journalist) -> dict | None:
    """Use LLM to enrich a journalist's profile based on their recent articles."""
    # Collect recent article titles
    articles = (
        db.query(Article.title)
        .filter(Article.journalist_id == journalist.id)
        .order_by(Article.published_at.desc())
        .limit(15)
        .all()
    )
    titles = [a[0] for a in articles if a[0]]

    if not titles:
        return None

    from ..models import Outlet
    from .rss import clean_author_name
    # Première ligne de défense : la forme du nom. Pas de profil pour « Article rédigé par ».
    if clean_author_name(journalist.name) is None:
        _discard_non_person(db, journalist, "name shape")
        return None
    outlet = db.get(Outlet, journalist.outlet_id)
    outlet_name = outlet.name if outlet else "Unknown"
    content = f"Journalist: {journalist.name}\nOutlet: {outlet_name}\n\nRecent articles:\n" + "\n".join(f"- {t}" for t in titles[:15])

    model = get_setting(db, "llm_profile_model")
    try:
        resp = llm.get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": ENRICH_SYSTEM},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        data = json.loads(resp.choices[0].message.content)
        if data.get("not_a_person"):
            # Seconde ligne de défense : le modèle lui-même signale que ce n'est pas une personne.
            _discard_non_person(db, journalist, data.get("reason") or "llm")
            return None

        # Update journalist record
        if data.get("role"):
            journalist.role = data["role"]
        # Beat is stored as a "[Beat] " prefix on the bio (parsed by the frontend), normalised to the closed list.
        beat = normalize_beat(data.get("beat"))
        bio = (data.get("bio") or journalist.bio or "").strip()
        bio = re.sub(r"^\[[^\]]*\]\s*", "", bio)  # drop any previous prefix
        journalist.beat = beat
        journalist.bio = f"[{beat}] {bio}".strip() if beat else bio

        db.commit()

        # Track usage
        if resp.usage:
            from ..models import LLMUsage
            from datetime import date
            from ..constants import MODEL_PRICING
            pin, pout = MODEL_PRICING.get(model, (0.5, 1.5))
            cost = (resp.usage.prompt_tokens * pin + resp.usage.completion_tokens * pout) / 1_000_000
            db.add(LLMUsage(date=date.today(), model=model, purpose="enrichment",
                            prompt_tokens=resp.usage.prompt_tokens,
                            completion_tokens=resp.usage.completion_tokens,
                            cost_usd=cost))
            db.commit()

        return data
    except Exception as e:  # noqa: BLE001
        log.warning("Journalist enrichment failed for %s: %s", journalist.name, e)
        return None


def normalize_all_beats(db: Session) -> int:
    """Ramène les beats déjà stockés (« [Tech] », « [Numérique] »…) à la liste fermée."""
    n = 0
    for j in db.query(Journalist).filter(Journalist.bio.like("[%")).all():
        m = re.match(r"^\[([^\]]*)\]\s*(.*)$", j.bio or "", re.S)
        if not m:
            continue
        nb = normalize_beat(m.group(1)) or m.group(1)
        if nb:
            j.beat = nb
            j.bio = f"[{nb}] {m.group(2)}".strip()
            n += 1
    db.commit()
    return n


def enrich_all(db: Session, limit: int = 50) -> int:
    """Enrich journalists that haven't been enriched yet (no "[Beat]" prefix in bio).

    Most prolific journalists first, so the cartography fills in where it matters.
    """
    from sqlalchemy import func

    counts = (
        db.query(Article.journalist_id, func.count(Article.id).label("n"))
        .filter(Article.journalist_id.isnot(None))
        .group_by(Article.journalist_id)
        .subquery()
    )
    journalists = (
        db.query(Journalist)
        .join(counts, counts.c.journalist_id == Journalist.id)
        .filter(
            (Journalist.bio == None) | (Journalist.bio == "") | (~Journalist.bio.like("[%"))  # noqa: E711
        )
        .order_by(counts.c.n.desc())
        .limit(limit)
        .all()
    )
    done = 0
    for j in journalists:
        result = enrich_journalist(db, j)
        if result:
            done += 1
    return done
