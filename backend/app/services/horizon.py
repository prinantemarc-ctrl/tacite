"""Horizon — Renseignement géopolitique, géoéconomique et prévision stratégique.

Architecture :
1. Filtrage souverain strict (élimination des faits divers, accidents civils, sport, people, météo, municipal).
2. Regroupement sémantique trans-linguistique sur les vecteurs 384D (`articles.embedding`),
   unifiant les publications arabes, allemandes, anglaises, espagnoles, françaises, italiennes, néerlandaises et polonaises.
3. Calcul des fractures de cadrage inter-pays, de la dépendance des sources (ICD 203),
   et des ruptures de ligne éditoriale (`vs_own_line >= 0.22`) vis-à-vis de `OutletProfile`.
4. Synthèse analytique de niveau cabinet (1 appel JSON groupé mis en cache dans `PreparedView`,
   avec repli analytique structuré immédiat si l'API modèle est indisponible).
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import time
import unicodedata
from collections import Counter, defaultdict
from datetime import datetime, timedelta

import numpy as np
from sqlalchemy.orm import Session

from ..constants import TONE_VALENCE
from ..geo import all_countries, country as geo_country
from ..i18n import get_locale
from ..kits import framing_value
from ..models import Article, Outlet, OutletProfile
from ..settings_store import get_setting
from ..tenant import current_user_id
from . import llm, prepared

log = logging.getLogger("tacite.horizon")

WINDOW_DAYS = 14
LOAD_DAYS = 75
CLUSTER_ART_CAP = 5500
CLUSTER_DIST = 0.25  # 1 - 0.75 cosine similarity (average linkage)
CACHE_TTL = 300

_mem_cache: dict[str, tuple[float, dict]] = {}

# ───────────────────────────────────────────── Filtres souverains & entités

JUNK_TOPICS = {
    "non-political", "non political", "non politique", "boilerplate", "hors champ",
    "غير سياسي", "sports match", "celebrity news",
}

# Faits divers, accidents civils, météo, sport, people, local — exclus sauf enjeu interétatique explicite
INCIDENT_RE = re.compile(
    r"\b("
    r"train collision|zugunglück|collision de trains|collision ferroviaire|accidente ferroviario|"
    r"railway crash|derailment|plane crash|car crash|bus crash|traffic accident|"
    r"earthquake|erdbeben|tremblement de terre|terremoto|typhoon|taifun|hurricane|ouragan|flood|inondation|"
    r"météo|weather forecast|incendie de la mairie|pope_health|santé du pape|"
    r"mbappé|mbappe|real madrid|champions league|ballon d'or|world cup|premier league|bundesliga|"
    r"halloween|téléthon|telethon|recette|horoscope|loterie|lottery|"
    r"pakjestaks|scpi|bajas laborales|listas de espera|parcoursup|"
    r"mobilisation sociale|mobilisation lycéenne|mobilisation contre la vie chère|intersyndicale|grève des transports|"
    r"violences urbaines|incendie volontaire|attentat raciste|councillor shot|braquage|cambriolage|meurtre conjugal|faits divers"
    r")\b",
    re.IGNORECASE,
)

# Lexique positif de gravité géopolitique, militaire, diplomatique ou géoéconomique
SOVEREIGN_RE = re.compile(
    r"\b("
    r"sanction|embargo|tariff|tarif|douan|dette souveraine|sovereign debt|banque centrale|central bank|bce|ecb|fed|imf|fmi|"
    r"otan|nato|brics|opec|opep|cpi|icc|cour pénale|onu|un security council|conseil de sécurité|union européenne|european union|commission européenne|"
    r"missile|drone|frappe|airstrike|strike|ceasefire|trêve|treve|waffenruhe|peace talks|négociations de paix|pourparlers|summit|sommet|"
    r"military|militaire|armée|army|defense|défense|air defense|espion|spy|spion|sabotage|cyber|nucléaire|nuclear|dissuasion|"
    r"hormuz|ormuz|suez|bab el-mandeb|mandeb|mer rouge|red sea|malacca|taiwan|taïwan|arctique|arctic|groenland|greenland|"
    r"gazoduc|pipeline|lng|gnl|pétrole|petrole|brent|uranium|lithium|terres rares|rare earth|semi-conduct|semiconduct|"
    r"élection|election|wahl|elezioni|elecciones|wybor|knesset|kremlin|kreml|white house|maison blanche|pentagon|quai d'orsay|"
    r"houthi|huthi|hamas|hezbollah|daech|isis|fsr|rsf|coalition|diplomat|ambassad|embassy|annexion|frontex|souveraineté|sovereignty"
    r")\b",
    re.IGNORECASE,
)

GEO_ECON_RE = re.compile(
    r"\b("
    r"tariff|tarif|douan|sanction|embargo|dette|debt|moody|fitch|s&p|bce|ecb|fmi|imf|taux d'intérêt|bond yield|"
    r"gazoduc|pipeline|gaz|gas|lng|gnl|pétrole|petrole|oil|opec|opep|hormuz|ormuz|suez|mandeb|mer rouge|red sea|"
    r"semi-conduct|semiconduct|chip|lithium|uranium|cobalt|terres rares|rare earth|arctique|arctic|groenland|"
    r"automobile|industrie|industrial|commerce|trade|export|import|nis|gazprom"
    r")\b",
    re.IGNORECASE,
)

CHOKEPOINTS = [
    {"id": "hormuz", "lat": 26.56, "lon": 56.25, "fr": "Détroit d'Ormuz", "en": "Strait of Hormuz", "keys": ["ormuz", "hormuz", "dammam", "persian gulf", "golfe persique"]},
    {"id": "bab", "lat": 12.58, "lon": 43.33, "fr": "Bab el-Mandeb · Mer Rouge", "en": "Bab el-Mandeb · Red Sea", "keys": ["bab el-mandeb", "bab-el-mandeb", "mandeb", "houthi", "huthi", "red sea", "mer rouge"]},
    {"id": "suez", "lat": 30.0, "lon": 32.55, "fr": "Canal de Suez", "en": "Suez Canal", "keys": ["canal de suez", "suez canal", "suez"]},
    {"id": "arctic", "lat": 72.0, "lon": -40.0, "fr": "Route Arctique · Groenland", "en": "Arctic Route · Greenland", "keys": ["arctique", "arctic", "groenland", "greenland"]},
    {"id": "taiwan_strait", "lat": 24.5, "lon": 119.5, "fr": "Détroit de Taïwan", "en": "Taiwan Strait", "keys": ["détroit de taïwan", "detroit de taiwan", "taiwan strait", "taiwan", "taïwan"]},
    {"id": "malacca", "lat": 2.5, "lon": 101.2, "fr": "Détroit de Malacca", "en": "Strait of Malacca", "keys": ["malacca", "malaka"]},
    {"id": "panama", "lat": 9.08, "lon": -79.68, "fr": "Canal de Panama", "en": "Panama Canal", "keys": ["canal de panama", "panama canal"]},
]

# Alias multilingues (FR, EN, DE, ES, IT, NL, PL, AR translittéré/arabe) -> ISO alpha-2
_ALIASES: dict[str, list[str]] = {
    "US": ["états-unis", "etats-unis", "united states", "usa", "u.s.", "washington", "white house", "maison blanche", "weißes haus", "biały dom", "stany zjednoczone", "estados unidos", "stati uniti", "أمريكا", "الولايات المتحدة", "واشنطن"],
    "RU": ["russie", "russia", "russland", "rosja", "rosji", "rosją", "rusia", "moscou", "moscow", "moskau", "moskwa", "kremlin", "kreml", "poutine", "putin", "روسيا", "موسكو"],
    "CN": ["chine", "china", "chiny", "pékin", "pekin", "beijing", "peking", "الصين", "بكين"],
    "UA": ["ukraine", "ukraina", "ukrainie", "ucrania", "ucraina", "kiev", "kyiv", "kijów", "zelensky", "zełenski", "selenskyj", "oleschky", "olechky", "kupiansk", "أوكرانيا", "كييف"],
    "IL": ["israël", "israel", "israele", "izrael", "izraela", "tel aviv", "jerusalem", "jérusalem", "knesset", "netanyahu", "netanyahou", "netanjahu", "إسرائيل", "تل أبيب"],
    "PS": ["palestine", "gaza", "gazastreifen", "cisjordanie", "west bank", "westjordanland", "hebron", "hamas", "غزة", "فلسطين"],
    "IR": ["iran", "téhéran", "tehran", "teheran", "إيران", "طهران"],
    "SA": ["arabie saoudite", "saudi arabia", "arabia saudyjska", "saudi-arabien", "arabia saudita", "riyad", "riyadh", "dammam", "العودية", "السعودية", "الرياض", "الدمام"],
    "AE": ["émirats", "emirats", "united arab emirates", "abou dhabi", "abu dhabi", "dubaï", "dubai", "الإمارات", "أبوظبي", "دبي"],
    "YE": ["yémen", "yemen", "jemen", "houthi", "houthis", "huthi", "huthis", "اليمن", "الحوثي"],
    "SY": ["syrie", "syria", "syrien", "damas", "damascus", "deraa", "سوريا", "دمشق"],
    "JO": ["jordanie", "jordan", "jordanien", "amman", "الأردن", "عمان"],
    "LB": ["liban", "lebanon", "libanon", "beyrouth", "beirut", "hezbollah", "لبنان", "بيروت"],
    "EG": ["égypte", "egypte", "egypt", "ägypten", "egipt", "le caire", "cairo", "mada masr", "مصر", "القاهرة"],
    "SD": ["soudan", "sudan", "darfour", "darfur", "nyala", "khartoum", "السودان", "دارفور"],
    "TR": ["turquie", "turkey", "türkiye", "türkei", "turcja", "ankara", "erdogan", "تركيا", "أنقرة"],
    "QA": ["qatar", "katar", "doha", "قطر", "الدوحة"],
    "FR": ["france", "frankreich", "francja", "francia", "paris", "quai d'orsay", "élysée", "فرنسا", "باريس"],
    "DE": ["allemagne", "germany", "deutschland", "niemcy", "niemczech", "alemania", "germania", "berlin", "bundeswehr", "ألمانيا", "برلين"],
    "GB": ["royaume-uni", "united kingdom", "britain", "großbritannien", "wielka brytania", "reino unido", "regno unito", "londres", "london", "بريطانيا", "لندن"],
    "IT": ["italie", "italy", "italien", "włochy", "italia", "rome", "roma", "meloni", "إيطاليا"],
    "ES": ["espagne", "spain", "spanien", "hiszpania", "españa", "madrid"],
    "PL": ["pologne", "poland", "polen", "polska", "varsovie", "warsaw", "warszawa", "tusk", "sikorski"],
    "NO": ["norvège", "norway", "norwegen", "norwegia", "oslo", "stoere", "støre"],
    "FI": ["finlande", "finland", "finnland", "finlandia", "helsinki", "stubb"],
    "DK": ["danemark", "denmark", "dänemark", "dania", "groenland", "greenland", "grönland"],
    "NL": ["pays-bas", "netherlands", "niederlande", "holandia", "la haye", "the hague", "den haag"],
    "BE": ["belgique", "belgium", "belgien", "belgia", "bruxelles", "brussels"],
    "CH": ["suisse", "switzerland", "schweiz", "szwajcaria", "genève", "geneva"],
    "RS": ["serbie", "serbia", "serbien", "belgrade", "belgrad", "vučić", "vucic", "nis"],
    "BY": ["biélorussie", "belarus", "weißrussland", "białoruś", "minsk"],
    "BR": ["brésil", "brazil", "brasilien", "brazylia", "brasil", "brasilia", "lula", "bolsonaro"],
    "AR": ["argentine", "argentina", "argentinien", "buenos aires", "milei"],
    "VE": ["venezuela", "caracas", "maduro"],
    "MX": ["mexique", "mexico", "mexiko"],
    "CA": ["canada", "kanada", "ottawa"],
    "IN": ["inde", "india", "indien", "new delhi", "modi", "الهند"],
    "PK": ["pakistan", "islamabad", "باكستان"],
    "KP": ["corée du nord", "north korea", "nordkorea", "korea północna", "corea del nord", "pyongyang", "kim jong-un", "kim jong un"],
    "KR": ["corée du sud", "south korea", "südkorea", "korea południowa", "séoul", "seoul"],
    "JP": ["japon", "japan", "japonia", "tokyo"],
    "TW": ["taïwan", "taiwan", "taipei"],
    "ZA": ["afrique du sud", "south africa", "südafrika", "pretoria", "johannesburg"],
    "CD": ["rdc", "congo", "kinshasa"],
    "ET": ["éthiopie", "ethiopia", "äthiopien", "addis abeba", "abiy ahmed"],
    "MA": ["maroc", "morocco", "marokko", "rabat"],
    "DZ": ["algérie", "algeria", "algerien", "alger"],
    "GA": ["gabon", "libreville"],
}

_FR_NAMES = {
    "US": "États-Unis", "RU": "Russie", "CN": "Chine", "UA": "Ukraine", "IL": "Israël",
    "PS": "Palestine / Gaza", "IR": "Iran", "SA": "Arabie saoudite", "AE": "Émirats arabes unis",
    "YE": "Yémen", "SY": "Syrie", "JO": "Jordanie", "LB": "Liban", "EG": "Égypte",
    "SD": "Soudan", "TR": "Turquie", "QA": "Qatar", "FR": "France", "DE": "Allemagne",
    "GB": "Royaume-Uni", "IT": "Italie", "ES": "Espagne", "PL": "Pologne", "NO": "Norvège",
    "FI": "Finlande", "DK": "Danemark / Groenland", "NL": "Pays-Bas", "BE": "Belgique",
    "CH": "Suisse", "RS": "Serbie", "BY": "Biélorussie", "BR": "Brésil", "AR": "Argentine",
    "VE": "Venezuela", "MX": "Mexique", "CA": "Canada", "IN": "Inde", "PK": "Pakistan",
    "KP": "Corée du Nord", "KR": "Corée du Sud", "JP": "Japon", "TW": "Taïwan",
    "ZA": "Afrique du Sud", "CD": "RD Congo", "ET": "Éthiopie", "MA": "Maroc",
    "DZ": "Algérie", "GA": "Gabon", "NG": "Nigeria", "UG": "Ouganda", "KE": "Kenya",
    "EC": "Équateur", "CO": "Colombie", "XK": "Kosovo", "AF": "Afghanistan",
}

_FOLD_RX = re.compile(r"[\s\-'’]+")
_alias_rx: re.Pattern | None = None
_alias_map: dict[str, str] = {}


def _fold(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return _FOLD_RX.sub(" ", text.casefold()).strip()


def _compile_aliases() -> None:
    global _alias_rx, _alias_map
    pairs: list[tuple[str, str]] = []
    seen: set[str] = set()
    for code, names in _ALIASES.items():
        for name in names:
            key = _fold(name)
            if len(key) < 3 or key in seen:
                continue
            seen.add(key)
            pairs.append((key, code))
    for row in all_countries():
        code = row["code"]
        raw = (row.get("name_en") or "").split(",")[0]
        key = _fold(raw)
        if len(key) < 5 or key in seen:
            continue
        if any(other.startswith(key + " ") or key.startswith(other + " ") for other in seen):
            continue
        seen.add(key)
        pairs.append((key, code))
    pairs.sort(key=lambda item: -len(item[0]))
    _alias_map = {name: code for name, code in pairs}
    pattern = "|".join(re.escape(name) for name, _ in pairs)
    _alias_rx = re.compile(rf"(?<![a-z0-9])(?:{pattern})(?![a-z0-9])")


def _extract_actors(title: str, data: dict) -> Counter:
    """Extrait les États impliqués dans un article avec leur poids (titre + lieux + sujets)."""
    if _alias_rx is None:
        _compile_aliases()
    counts: Counter = Counter()
    if _alias_rx is None:
        return counts
    ents = data.get("entities") or {}
    locs = " ".join(str(x) for x in (ents.get("locations") or [])[:12])
    orgs = " ".join(str(x) for x in (ents.get("organizations") or [])[:10])
    topics = " ".join(str(t.get("label") or "") for t in (data.get("topics") or [])[:3] if isinstance(t, dict))
    for weight, chunk in ((2, f"{title} {topics}"), (1, f"{locs} {orgs}")):
        folded = _fold(chunk)
        if not folded:
            continue
        found = {_alias_map[m.group(0)] for m in _alias_rx.finditer(folded)}
        for code in found:
            counts[code] += weight
    return counts


def _country_label(code: str, en: bool) -> str:
    if en:
        row = geo_country(code) or {}
        return (row.get("name_en") or code).split(",")[0]
    return _FR_NAMES.get(code) or code


def _clean_title(title: str) -> str:
    return re.sub(r"\s+", " ", (title or "").strip().strip("«»\"“”")).strip()


def _is_sovereign_relevant(title: str, data: dict) -> bool:
    """Écarte impitoyablement les faits divers, accidents civils, sport, people et météo."""
    topics = data.get("topics") or []
    t_labels = [str(t.get("label") or "").strip() for t in topics if isinstance(t, dict)]
    if not t_labels:
        return False
    if all(lbl.lower() in JUNK_TOPICS for lbl in t_labels):
        return False
    ents = data.get("entities") or {}
    locs = " ".join(str(x) for x in (ents.get("locations") or [])[:8])
    orgs = " ".join(str(x) for x in (ents.get("organizations") or [])[:8])
    blob = f"{title} {' '.join(t_labels)} {orgs} {locs}"
    if INCIDENT_RE.search(blob):
        return False
    has_sovereign = bool(SOVEREIGN_RE.search(blob))
    fr = data.get("framing") or {}
    strat_energy = (
        abs(framing_value(fr, "international"))
        + abs(framing_value(fr, "alignment"))
        + abs(framing_value(fr, "openness"))
        + abs(framing_value(fr, "order"))
        + abs(framing_value(fr, "economy"))
        + abs(framing_value(fr, "europe"))
        + abs(framing_value(fr, "sovereignty"))
        + abs(framing_value(fr, "us_rivalry"))
        + abs(framing_value(fr, "kremlin"))
    )
    sources = {str(s.get("type") if isinstance(s, dict) else s) for s in (data.get("sources") or [])}
    if has_sovereign:
        return True
    if strat_energy >= 0.55 and (sources & {"government", "anonymous", "judicial", "political_party", "expert"}) and len(ents.get("locations") or []) >= 1:
        return True
    return False


# ───────────────────────────────────────────── Clustering & détection des théâtres

def _load_outlet_baselines(db: Session) -> dict[int, dict[str, float]]:
    """Dernier profil réel mesuré par média (pour détecter les ruptures éditoriales >= 0.22)."""
    from sqlalchemy import func
    sub = (
        db.query(OutletProfile.outlet_id, func.max(OutletProfile.week).label("w"))
        .group_by(OutletProfile.outlet_id)
        .subquery()
    )
    rows = (
        db.query(OutletProfile)
        .join(sub, (OutletProfile.outlet_id == sub.c.outlet_id) & (OutletProfile.week == sub.c.w))
        .all()
    )
    return {r.outlet_id: (r.real_classification or {}) for r in rows}


def _compute_dossiers(db: Session, end: datetime) -> tuple[list[dict], datetime, datetime]:
    outlets = {o.id: o for o in db.query(Outlet).all()}
    baselines = _load_outlet_baselines(db)

    min_dt = (
        db.query(Article.published_at)
        .filter(Article.published_at.isnot(None), Article.published_at >= end - timedelta(days=LOAD_DAYS))
        .order_by(Article.published_at.asc())
        .limit(1)
        .scalar()
    ) or (end - timedelta(days=WINDOW_DAYS))
    max_dt = (
        db.query(Article.published_at)
        .filter(Article.published_at.isnot(None))
        .order_by(Article.published_at.desc())
        .limit(1)
        .scalar()
    ) or end

    recent_from = end - timedelta(days=WINDOW_DAYS)
    base_from = end - timedelta(days=WINDOW_DAYS * 2)

    rows = (
        db.query(
            Article.id, Article.outlet_id, Article.published_at,
            Article.title, Article.language, Article.extracted_data, Article.embedding,
        )
        .filter(
            Article.analysis_status == "analyzed",
            Article.embedding.isnot(None),
            Article.duplicate_of_id.is_(None),
            Article.published_at >= recent_from,
            Article.published_at <= end,
        )
        .order_by(Article.published_at.desc())
        .limit(8000)
        .all()
    )

    # Corpus de référence (quinzaine précédente) pour mesurer l'accélération réelle par centroïde
    prev_rows = (
        db.query(Article.embedding)
        .filter(
            Article.analysis_status == "analyzed",
            Article.embedding.isnot(None),
            Article.duplicate_of_id.is_(None),
            Article.published_at >= base_from,
            Article.published_at < recent_from,
        )
        .order_by(Article.published_at.desc())
        .limit(5000)
        .all()
    )
    prev_emb = (
        np.stack([np.asarray(r[0], dtype=np.float32) for r in prev_rows])
        if prev_rows else np.zeros((0, 384), dtype=np.float32)
    )
    if len(prev_emb):
        prev_emb = prev_emb / np.maximum(np.linalg.norm(prev_emb, axis=1, keepdims=True), 1e-9)

    salient = []
    for r in rows:
        oid = r[1]
        if oid not in outlets:
            continue
        data = r[5] if isinstance(r[5], dict) else {}
        title = _clean_title(r[3] or "")
        if not title or not _is_sovereign_relevant(title, data):
            continue
        actors = _extract_actors(title, data)
        if not actors:
            continue
        salient.append((r[0], oid, r[2], title, (r[4] or "fr")[:2].lower(), data, np.asarray(r[6], dtype=np.float32), actors))
        if len(salient) >= CLUSTER_ART_CAP:
            break

    if len(salient) < 6:
        return [], min_dt, max_dt

    emb = np.stack([x[6] for x in salient])
    emb = emb / np.maximum(np.linalg.norm(emb, axis=1, keepdims=True), 1e-9)

    from scipy.cluster.hierarchy import fcluster, linkage
    from scipy.spatial.distance import pdist

    dist = np.clip(pdist(emb, metric="cosine"), 0, 2)
    labels = fcluster(linkage(dist, method="average"), t=CLUSTER_DIST, criterion="distance") - 1

    groups: dict[int, list[int]] = defaultdict(list)
    for idx, lab in enumerate(labels):
        groups[int(lab)].append(idx)

    candidates: list[dict] = []
    for lab, idxs in groups.items():
        if len(idxs) < 4:
            continue
        press_countries = {outlets[salient[i][1]].country for i in idxs}
        distinct_outlets = {salient[i][1] for i in idxs}
        langs = sorted({salient[i][4] for i in idxs if salient[i][4]})
        if len(press_countries) < 2 or len(distinct_outlets) < 3:
            continue

        actor_counts: Counter = Counter()
        topic_counts: Counter = Counter()
        org_counts: Counter = Counter()
        person_counts: Counter = Counter()
        source_types: Counter = Counter()
        tones: list[float] = []
        order_vals: list[float] = []
        open_vals: list[float] = []
        econ_hits = 0
        ruptures: list[dict] = []
        by_press_country: dict[str, list[float]] = defaultdict(list)
        high_infl_outlets = 0

        for oid in distinct_outlets:
            if (outlets[oid].influence_score or 0) >= 65:
                high_infl_outlets += 1

        for i in idxs:
            aid, oid, pub, title, lang, data, _vec, actors = salient[i]
            outlet = outlets[oid]
            actor_counts.update(actors)
            for t in (data.get("topics") or [])[:2]:
                if isinstance(t, dict) and t.get("label"):
                    lbl = str(t["label"]).strip()
                    if lbl.lower() not in JUNK_TOPICS:
                        topic_counts[lbl] += 1
            ents = data.get("entities") or {}
            for o_name in (ents.get("organizations") or [])[:6]:
                if len(o_name) >= 3 and o_name.lower() not in {"afp", "reuters", "ap", "x", "instagram", "facebook", "bbc", "cnn", "infobae", "chyba", "021.rs", "ansa"}:
                    org_counts[o_name] += 1
            for p_name in (ents.get("people") or [])[:5]:
                if len(p_name) >= 4:
                    person_counts[p_name] += 1
            for s in (data.get("sources") or []):
                st = str(s.get("type") if isinstance(s, dict) else s)
                if st:
                    source_types[st] += 1

            tv = TONE_VALENCE.get(str(data.get("tone") or "").lower(), 0.0)
            fr = data.get("framing") or {}
            ord_v = framing_value(fr, "order")
            opn_v = framing_value(fr, "openness")
            tones.append(tv)
            order_vals.append(ord_v)
            open_vals.append(opn_v)
            by_press_country[outlet.country].append(0.5 * tv + 0.3 * opn_v + 0.2 * ord_v)

            blob_check = f"{title} {' '.join(topic_counts.keys())}"
            if GEO_ECON_RE.search(blob_check):
                econ_hits += 1

            # Détection de rupture éditoriale (vs ligne mesurée habituelle >= 0.25)
            base_line = baselines.get(oid) or {}
            for ax in ("loyalty", "openness", "order", "economy", "international", "alignment"):
                cur_v = framing_value(fr, ax)
                ref_v = float(base_line.get(ax) or 0.0)
                if cur_v != 0.0 and ref_v != 0.0 and abs(cur_v - ref_v) >= 0.32:
                    ruptures.append({
                        "outlet": outlet.name,
                        "country": outlet.country,
                        "axis": ax,
                        "shift": round(cur_v - ref_v, 2),
                    })
                    break

        # Acteurs étatiques principaux du théâtre (au moins mentionnés dans >= 25% des articles du cluster)
        min_actor_w = max(3, int(len(idxs) * 0.30))
        top_actors = [code for code, w in actor_counts.most_common(5) if w >= min_actor_w]
        if not top_actors:
            top_actors = [code for code, _ in actor_counts.most_common(2)]
        if not top_actors:
            continue

        # Écarte les clusters purement franco-français ou purement domestiques d'un seul pays sans enjeu externe
        if len(top_actors) == 1 and top_actors[0] in press_countries and len(press_countries) <= 2 and econ_hits < 2:
            continue

        # Accélération par rapport à la quinzaine précédente (via centroïde sémantique)
        centroid = emb[idxs].mean(axis=0)
        centroid = centroid / max(float(np.linalg.norm(centroid)), 1e-9)
        prev_matches = int((prev_emb @ centroid >= 0.72).sum()) if len(prev_emb) else 0
        accel_ratio = (len(idxs) + 1.0) / (prev_matches + 1.5)

        mean_tone = float(np.mean(tones)) if tones else 0.0
        mean_order = float(np.mean(order_vals)) if order_vals else 0.0
        mean_open = float(np.mean(open_vals)) if open_vals else 0.0
        regal_share = (
            (source_types["government"] + source_types["anonymous"] + source_types["judicial"])
            / max(sum(source_types.values()), 1)
        )
        econ_share = econ_hits / len(idxs)
        mainstream_share = high_infl_outlets / max(len(distinct_outlets), 1)

        # Classification doctrinale du dossier
        blob_all = _fold(
            " ".join(x[0] for x in topic_counts.most_common(6))
            + " " + " ".join(x[0] for x in org_counts.most_common(6))
            + " " + " ".join(salient[i][3] for i in idxs[:10])
        )
        matched_choke = None
        for cp in CHOKEPOINTS:
            if any(_fold(k) in blob_all for k in cp["keys"]):
                matched_choke = cp
                break

        if matched_choke or (econ_share >= 0.40 and (regal_share >= 0.20 or mean_order <= -0.08 or mean_open <= -0.08)):
            kind = "economy"      # Sécuritisation géoéconomique / corridor stratégique
            horizon_days = 30
        elif any(k in blob_all for k in ("frappe", "strike", "attack", "anschlag", "abriegelung", "opération militaire", "military operation", "houthi", "huthi", "sanction", "embargo", "spion", "spy", "sabotage")):
            kind = "conflict"     # Escalade militaire, sanctions ou guerre hybride
            horizon_days = 30
        elif any(k in blob_all for k in ("summit", "sommet", "accord", "brics", "call with putin", "anruf bei putin", "telefon", "négociations", "peace talks", "ceasefire", "trêve", "waffenruhe")):
            kind = "coalition"    # Canal diplomatique / recomposition d'alliance
            horizon_days = 60
        elif mean_tone <= -0.14 or mean_order <= -0.10:
            kind = "conflict"
            horizon_days = 30
        elif mean_open >= 0.22 and mean_tone >= 0.05 and len(top_actors) >= 2:
            kind = "rapprochement"
            horizon_days = 60
        elif mainstream_share <= 0.50 and accel_ratio >= 1.8:
            kind = "signal"       # Signal précurseur en forte accélération
            horizon_days = 14
        else:
            kind = "conflict" if mean_tone < 0 else "signal"
            horizon_days = 30

        # Niveau de vraisemblance étalonné (évite que tout sorte en « probable »)
        indep_score = math.log1p(len(distinct_outlets)) * math.log1p(len(press_countries))
        momentum = min(1.5, math.log1p(accel_ratio))
        raw_strength = 0.24 * indep_score + 0.36 * momentum + 0.40 * (regal_share * 1.8 + (0.25 if ruptures else 0.0))
        if raw_strength >= 1.95:
            chance = "likely"
        elif raw_strength >= 1.35:
            chance = "possible"
        else:
            chance = "unlikely"

        # Sélection des meilleurs articles preuves (diversité de pays et de langues, médias influents d'abord)
        sorted_idxs = sorted(
            idxs,
            key=lambda i: (-(outlets[salient[i][1]].influence_score or 0), salient[i][2]),
        )
        evidence = []
        seen_ev_countries: set[str] = set()
        for i in sorted_idxs:
            aid, oid, pub, title, lang, _d, _v, _ac = salient[i]
            oc = outlets[oid].country
            if oc in seen_ev_countries and len(evidence) < 3:
                continue
            seen_ev_countries.add(oc)
            evidence.append({
                "id": aid,
                "title": title,
                "outlet": outlets[oid].name,
                "country": oc,
                "language": lang,
                "date": pub.date().isoformat(),
            })
            if len(evidence) >= 4:
                break

        # Clivage entre presses nationales (ex: comment le Golfe vs l'Europe cadrent le même événement)
        camp_stances = []
        for pc, vals in sorted(by_press_country.items(), key=lambda kv: -len(kv[1])):
            if len(vals) >= 2:
                camp_stances.append({"country": pc, "stance": round(float(np.mean(vals)), 2), "n": len(vals)})

        # Déduplication des ruptures éditoriales par média
        uniq_ruptures = []
        seen_ro: set[str] = set()
        for rp in ruptures:
            if rp["outlet"] not in seen_ro:
                seen_ro.add(rp["outlet"])
                uniq_ruptures.append(rp)
            if len(uniq_ruptures) >= 3:
                break

        stable_seed = "|".join(sorted(top_actors[:3])) + "|" + (topic_counts.most_common(1)[0][0] if topic_counts else str(lab))
        did = "hz-" + hashlib.sha1(stable_seed.encode("utf-8")).hexdigest()[:10]

        salience_rank = (
            len(press_countries) * 2.2
            + len(distinct_outlets) * 0.9
            + min(len(idxs), 35) * 0.3
            + (4.0 if matched_choke else 0.0)
            + (3.0 if kind in {"economy", "coalition"} else 0.0)
            + min(accel_ratio, 4.0) * 1.2
        )

        candidates.append({
            "id": did,
            "kind": kind,
            "chance": chance,
            "horizon_days": horizon_days,
            "salience": round(salience_rank, 2),
            "actors": top_actors[:4],
            "press_countries": sorted(press_countries),
            "languages": langs,
            "n_articles": len(idxs),
            "n_prev": prev_matches,
            "n_outlets": len(distinct_outlets),
            "topics": [k for k, _ in topic_counts.most_common(5)],
            "organizations": [k for k, _ in org_counts.most_common(5)],
            "people": [k for k, _ in person_counts.most_common(4)],
            "regal_sources": round(regal_share, 2),
            "camp_stances": camp_stances[:4],
            "ruptures": uniq_ruptures,
            "chokepoint": matched_choke,
            "evidence": evidence,
        })

    # Déduplication stricte par théâtre stratégique (0 doublon sur un même binôme ou trinôme d'États)
    candidates.sort(key=lambda c: -c["salience"])
    selected: list[dict] = []
    primary_seen: Counter = Counter()
    actor_set_seen: list[set[str]] = []
    choke_seen: set[str] = set()

    def _overlaps(cand_actors: list[str]) -> bool:
        s = set(cand_actors[:3])
        for prev in actor_set_seen:
            if len(s & prev) >= 2 and len(s) >= 2 and len(prev) >= 2:
                return True
        return False

    # 1) Priorité aux corridors maritimes & goulets géoéconomiques actifs (Ormuz, Mer Rouge, Arctique…)
    for cand in candidates:
        cp = cand.get("chokepoint")
        if cp and cp["id"] not in choke_seen:
            choke_seen.add(cp["id"])
            actor_set_seen.append(set(cand["actors"][:3]))
            primary_seen[cand["actors"][0]] += 1
            selected.append(cand)
            if len(selected) >= 3:
                break

    # 2) Théâtres majeurs tous domaines confondus sans recouvrement d'acteurs
    for cand in candidates:
        if cand in selected:
            continue
        p0 = cand["actors"][0]
        if _overlaps(cand["actors"]) or primary_seen[p0] >= 2:
            continue
        actor_set_seen.append(set(cand["actors"][:3]))
        primary_seen[p0] += 1
        selected.append(cand)
        if len(selected) >= 8:
            break

    # 3) Complément géoéconomique / coalitions si sous-représentés
    for target_kind, quota in (("economy", 2), ("coalition", 2)):
        have_k = sum(1 for x in selected if x["kind"] == target_kind)
        if have_k < quota:
            for cand in candidates:
                if cand["kind"] == target_kind and cand not in selected and not _overlaps(cand["actors"]):
                    actor_set_seen.append(set(cand["actors"][:3]))
                    selected.append(cand)
                    have_k += 1
                    if have_k >= quota:
                        break

    return selected[:9], min_dt, max_dt


# ───────────────────────────────────────────── Synthèse stratégique de niveau cabinet

HORIZON_SINGLE_SYSTEM_FR = """Vous êtes le rédacteur en chef du renseignement stratégique (cellule géopolitique & géoéconomique destinée à un cabinet ministériel, un État-major ou un fonds souverain).
À partir d'un dossier détecté par corrélation multilingue de la presse mondiale, rédigez une fiche de prévision stratégique chirurgicale en FRANÇAIS.

RÈGLES ABSOLUES DE NIVEAU GOUVERNEMENTAL :
1. ZÉRO MÉTÉO DE PRESSE NI STATISTIQUE : n'écrivez JAMAIS « X articles », « Y médias », « score », « la presse parle sur un ton hostile » ou « va entrer dans les grands titres ». Parlez uniquement des manœuvres politiques, militaires, diplomatiques, énergétiques ou financières réelles.
2. INTERDICTION D'ENFONCER DES PORTES OUVERTES : ne résumez pas l'actualité. Déduisez le coup d'après (recomposition d'alliance, contournement de sanctions, levier énergétique, vulnérabilité d'un corridor, marchandage diplomatique, fracture entre capitales).
3. ANCRAGE FACTUEL STRICT : appuyez-vous uniquement sur les acteurs, capitales, organisations, dirigeants et titres fournis. N'inventez aucun fait. N'écrivez aucun pourcentage chiffré dans les scénarios.

Répondez UNIQUEMENT avec cet objet JSON compact :
{
  "title": "Titre géopolitique incisif en français (5 à 9 mots max)",
  "call": "Prévision opérationnelle datée en UNE phrase commençant par « Sous X jours, ... » et intégrant la vraisemblance fournie (probable / possible / peu probable).",
  "why_now": "2 à 3 phrases denses expliquant le signal précurseur, le jeu d'acteurs et la fracture stratégique sous-jacente.",
  "scenarios": [
    {"name": "Nom court scénario central", "desc": "1 phrase concrète sur la trajectoire retenue."},
    {"name": "Nom court scénario intermédiaire", "desc": "1 phrase concrète sur le marchandage ou endiguement."},
    {"name": "Nom court scénario de rupture", "desc": "1 phrase concrète sur l'escalade ou le désamorçage."}
  ],
  "confirm": "1 phrase nommant l'acte politique, militaire ou réglementaire précis qui confirmera la prévision.",
  "abort": "1 phrase nommant l'acte concret qui invalidera ou désamorcera la prévision.",
  "stake": "1 à 2 phrases sur l'enjeu souverain, énergétique, sécuritaire ou commercial concret pour un décideur."
}"""

HORIZON_SINGLE_SYSTEM_EN = """You are the Editor-in-Chief of Strategic Intelligence (geopolitical & geoeconomic cell briefing cabinet ministers, defense staffs and sovereign funds).
From a dossier detected across multilingual world press, write a surgical strategic forecast in ENGLISH.
Rules: ZERO media-monitoring jargon (never mention article counts, outlet counts, tone scores or 'entering mainstream media'). Do not state the obvious; deduce the next strategic move, leverage, corridor vulnerability or diplomatic realignment. Ground strictly in supplied actors, organizations, leaders and headlines. No percentages in scenarios.
Reply ONLY with this compact JSON object:
{
  "title": "Sharp geopolitical title in English (5-9 words)",
  "call": "One-sentence dated operational forecast starting with 'Within X days, ...' using the supplied likelihood (likely / possible / unlikely).",
  "why_now": "2-3 dense sentences on the underlying strategic maneuver and fault line.",
  "scenarios": [
    {"name": "Central trajectory", "desc": "1 concrete sentence."},
    {"name": "Sub-threshold / bargaining", "desc": "1 concrete sentence."},
    {"name": "Break / de-escalation", "desc": "1 concrete sentence."}
  ],
  "confirm": "1 concrete political, military or regulatory signpost confirming the shift.",
  "abort": "1 concrete signpost invalidating or defusing the shift.",
  "stake": "1-2 sentences on the sovereign, energy, security or trade stake."
}"""


def _fallback_brief(c: dict) -> dict:
    """Analyse stratégique structurée (sans jargon statistique ni phrase passe-partout) ancrée sur les faits du cluster."""
    actors_fr = [_country_label(a, False) for a in c["actors"][:4]]
    actors_en = [_country_label(a, True) for a in c["actors"][:4]]
    pair_fr = " et ".join(actors_fr[:2]) if len(actors_fr) >= 2 else (actors_fr[0] if actors_fr else "la zone")
    pair_en = " and ".join(actors_en[:2]) if len(actors_en) >= 2 else (actors_en[0] if actors_en else "the region")
    span_fr = " · ".join(actors_fr[:3])
    span_en = " · ".join(actors_en[:3])

    topics = c["topics"] or []
    t_blob = " ".join(topics).lower()
    h_blob = " ".join(e["title"] for e in c["evidence"]).lower()
    full_blob = f"{t_blob} {h_blob}"

    orgs_clean = [o for o in c["organizations"] if len(o) > 2 and not o.endswith("„")][:3]
    people_clean = []
    for p in c["people"]:
        if p and not any(p.lower() in ex.lower() or ex.lower() in p.lower() for ex in people_clean):
            people_clean.append(p)
        if len(people_clean) >= 3:
            break

    orgs_str = ", ".join(orgs_clean)
    people_str = ", ".join(people_clean)
    h = c["horizon_days"]
    ch_fr = {"likely": "probable", "possible": "possible"}.get(c["chance"], "sous surveillance")
    ch_en = {"likely": "likely", "possible": "possible"}.get(c["chance"], "on watchlist")

    rupt_fr = ""
    rupt_en = ""
    if c.get("ruptures"):
        r0 = c["ruptures"][0]
        rupt_fr = f" Signal notable : {r0['outlet']} ({_country_label(r0['country'], False)}) rompt nettement avec son cadrage habituel sur ce dossier."
        rupt_en = f" Notable signal: {r0['outlet']} ({_country_label(r0['country'], True)}) breaks sharply from its usual editorial baseline on this file."

    # Sous-archétypes géopolitiques précis selon la nature réelle du dossier
    if any(k in full_blob for k in ("houthi", "huthi", "huti", "dammam", "ormuz", "hormuz", "mer rouge", "red sea", "tehran talks")):
        title_fr = f"Sécurité maritime & marchandage régional ({span_fr})"
        title_en = f"Maritime security & regional bargaining ({span_en})"
        call_fr = f"Sous {h} jours, un couplage direct entre la désescalade houthie en mer Rouge et des garanties de sécurité régionales entre {span_fr} est {ch_fr}."
        call_en = f"Within {h} days, direct linkage between Houthi Red Sea de-escalation and regional security guarantees across {span_en} is {ch_en}."
        why_fr = (
            f"La pression sur le corridor Bab el-Mandeb / Golfe sert désormais de levier de négociation interétatique élargi ({span_fr}). "
            f"{f'Les discussions impliquent notamment {people_str}' if people_str else 'Les canaux sécuritaires régionaux s’activent'}"
            f"{f' autour de {orgs_str}' if orgs_str else ''}, liant la sûreté des infrastructures énergétiques et maritimes à un compromis diplomatique plus large.{rupt_fr}"
        )
        why_en = (
            f"Pressure on the Bab el-Mandeb / Gulf corridor is being leveraged as an interstate bargaining chip across {span_en}. "
            f"{f'Key figures involved include {people_str}' if people_str else 'Regional security channels are active'}."
            f"{rupt_en}"
        )
        sc_fr = [
            {"name": "Marchandage sécuritaire conditionné", "desc": f"Gel graduel des frappes asymétriques en échange de garanties politiques et d'un appui régional impliquant {span_fr}."},
            {"name": "Pression hybride intermittente", "desc": "Maintien d'attaques ponctuelles de drones ou menaces sur le fret pour conserver un levier sur Riyad et Le Caire."},
            {"name": "Escalade sur infrastructures critiques", "desc": "Frappe revendiquée sur un hub énergétique ou portuaire entraînant une riposte militaire coordonnée."},
        ]
        sc_en = [
            {"name": "Conditional security bargain", "desc": f"Gradual freeze of asymmetric strikes in exchange for regional guarantees across {span_en}."},
            {"name": "Intermittent hybrid pressure", "desc": "Sporadic drone or maritime threats maintained to preserve diplomatic leverage."},
            {"name": "Critical infrastructure escalation", "desc": "Claimed strike on an energy or port hub triggering coordinated military retaliation."},
        ]
        confirm_fr = f"Annonce d'un mécanisme de sécurité conjoint ou suspension vérifiable des tirs houthis après médiation impliquant {span_fr}."
        abort_fr = "Nouvelle salve revendiquée contre une infrastructure saoudienne ou mer Rouge rompant les pourparlers."
        stake_fr = "Sûreté du corridor énergétique mer Rouge – Golfe, primes d'assurance maritime et réalignement sécuritaire entre Riyad, Téhéran, Le Caire et Islamabad."
        stake_en = "Security of the Red Sea–Gulf energy corridor, war-risk shipping premiums and regional security alignment."

    elif any(k in full_blob for k in ("call with putin", "anruf bei putin", "appel téléphonique à poutine", "stubb", "stoere", "støre", "oleshky", "olechky", "gesprächen mit usa")):
        title_fr = f"Fissure européenne & canaux directs avec Moscou ({span_fr})"
        title_en = f"European fault line & direct Moscow channels ({span_en})"
        call_fr = f"Sous {h} jours, la multiplication de canaux exploratoires bilatéraux avec Moscou sur les paramètres d'un gel en Ukraine — au prix d'une fracture ouverte entre capitales européennes — est {ch_fr}."
        call_en = f"Within {h} days, proliferation of bilateral exploratory channels with Moscow over Ukraine freeze parameters—straining European unity—is {ch_en}."
        why_fr = (
            f"L'initiative directe prise par des dirigeants nordiques ({people_str or 'Oslo et Helsinki'}) auprès du Kremlin brise l'isolement diplomatique strict observé jusqu'ici et suscite des critiques immédiates au sein de l'OTAN et de l'UE. "
            f"Chaque capitale cherche à verrouiller sa propre lecture des garanties de sécurité avant un éventuel arbitrage américano-russe.{rupt_fr}"
        )
        why_en = (
            f"Direct outreach to the Kremlin ({people_str or 'Nordic capitals'}) breaks strict diplomatic isolation and triggers friction inside NATO and the EU as capitals position ahead of potential US-Russia talks.{rupt_en}"
        )
        sc_fr = [
            {"name": "Diplomatie parallèle fragmentée", "desc": "Poursuite de contacts exploratoires non coordonnés avec Moscou, creusant le clivage entre flanc nordique, Varsovie et Bruxelles."},
            {"name": "Recadrage OTAN / UE", "desc": "Verrouillage d'une ligne commune exigeant qu'aucun canal bilatéral ne précède l'accord de Kiev."},
            {"name": "Ouverture d'un format de trêve sectorielle", "desc": "Extension de cessez-le-feu locaux (type Olechky) ou de jalons techniques préparant un sommet tripartite."},
        ]
        sc_en = [
            {"name": "Fragmented parallel diplomacy", "desc": "Uncoordinated exploratory contacts with Moscow widen divides among European allies."},
            {"name": "NATO / EU discipline", "desc": "Allied coordination reasserts no bilateral outreach without Kyiv's mandate."},
            {"name": "Sectoral truce framework", "desc": "Localized ceasefires expand into technical talks toward a broader freeze."},
        ]
        confirm_fr = "Nouvel entretien bilatéral d'un chef d'exécutif européen avec Moscou ou annonce d'une réunion préparatoire en pays tiers (Abou Dhabi, Turquie)."
        abort_fr = "Reprise d'offensives massives sur les infrastructures ukrainiennes fermant immédiatement la fenêtre exploratoire."
        stake_fr = "Cohésion stratégique de l'OTAN et de l'UE, architecture future des garanties de sécurité européennes et poids de l'Europe face au bilatéralisme Washington–Moscou."
        stake_en = "NATO/EU strategic cohesion and Europe's seat at the table in future Ukraine security arrangements."

    elif any(k in full_blob for k in ("strafgerichtshof", "corte penale", "cpi", "sacharov", "sakharov")):
        title_fr = "Bras de fer transatlantique autour des sanctions visant la CPI"
        title_en = "Transatlantic standoff over ICC sanctions"
        call_fr = f"Sous {h} jours, l'activation de contre-mesures juridiques européennes (statut de blocage) face aux sanctions américaines visant la Cour pénale internationale est {ch_fr}."
        call_en = f"Within {h} days, European legal shielding measures in response to US sanctions targeting the International Criminal Court are {ch_en}."
        why_fr = (
            f"L'attribution du prix Sakharov à la CPI par le Parlement européen transforme une pression extraterritoriale américaine en test de souveraineté juridique pour l'Union européenne. "
            f"Les institutions financières et fournisseurs européens opérant avec La Haye se retrouvent exposés au risque de sanctions secondaires.{rupt_fr}"
        )
        why_en = (
            f"The European Parliament's political backing of the ICC turns US sanctions into a direct test of European legal autonomy and compliance risk.{rupt_en}"
        )
        sc_fr = [
            {"name": "Bouclier institutionnel européen", "desc": "Bruxelles protège financièrement le fonctionnement de la Cour tout en évitant l'affrontement commercial direct avec Washington."},
            {"name": "Sur-conformité bancaire privée", "desc": "Des prestataires bancaires et numériques suspendent préventivement leurs services à la CPI par crainte du Trésor américain."},
            {"name": "Escalade diplomatique transatlantique", "desc": "Extension des désignations individuelles américaines provoquant une crise ouverte entre capitales alliées."},
        ]
        sc_en = [
            {"name": "European institutional shielding", "desc": "EU institutionsring-fence ICC operations while avoiding broader trade retaliation."},
            {"name": "Private-sector over-compliance", "desc": "Banks and tech vendors preemptively cut services to the Court over US Treasury exposure."},
            {"name": "Transatlantic diplomatic clash", "desc": "Expanded US designations trigger open political confrontation with EU capitals."},
        ]
        confirm_fr = "Instruction de la Commission européenne activant des garanties opérationnelles pour La Haye ou nouvelles désignations de magistrats par Washington."
        abort_fr = "Gel d'application ou dérogations générales accordées par l'administration américaine."
        stake_fr = "Exposition aux sanctions secondaires américaines, autonomie juridique européenne et crédibilité de la juridiction pénale internationale."
        stake_en = "Secondary-sanctions compliance risk and European legal sovereignty."

    elif any(k in full_blob for k in ("wahl", "election", "élection", "elezioni", "elecciones", "wybor", "lula", "vučić", "vucic", "knesset", "netanyahu")):
        pivot_fr = actors_fr[0] if actors_fr else "le pays"
        pivot_en = actors_en[0] if actors_en else "the country"
        partners_fr = ", ".join(actors_fr[1:3]) if len(actors_fr) > 1 else "ses partenaires clés"
        partners_en = ", ".join(actors_en[1:3]) if len(actors_en) > 1 else "key external powers"
        title_fr = f"Recomposition post-électorale & réalignement externe ({span_fr})"
        title_en = f"Post-election realignment & external leverage ({span_en})"
        call_fr = f"Sous {h} jours, une inflexion marquée de la posture extérieure et des alliances ({pivot_fr}) — sous pression croisée ({partners_fr}) — est {ch_fr}."
        call_en = f"Within {h} days, a decisive shift in {pivot_en}'s foreign posture and coalition bargaining—under cross-pressure from {partners_en}—is {ch_en}."
        why_fr = (
            f"La séquence électorale impliquant {people_str or pivot_fr} ({orgs_str or 'partis clés'}) redistribue le pouvoir de blocage interne au moment précis où les capitales extérieures testent la solidité du futur exécutif. "
            f"Les marges de coalition imposent des concessions immédiates sur la politique étrangère, la sécurité ou la gouvernance économique.{rupt_fr}"
        )
        why_en = (
            f"The electoral sequence involving {people_str or pivot_en} reshapes domestic veto players just as external powers test the incoming executive's alignment.{rupt_en}"
        )
        sc_fr = [
            {"name": "Transaction de coalition sous contrainte", "desc": f"Formation d'une majorité fragile ({pivot_fr}) monnayant des gages sécuritaires ou diplomatiques précis."},
            {"name": "Blocage institutionnel & contestation", "desc": "Contestation des résultats ou paralysie parlementaire prolongeant la vacance stratégique et l'ingérence extérieure."},
            {"name": "Rupture doctrinale rapide", "desc": f"Réorientation brusque des engagements extérieurs ({pivot_fr}) vis-à-vis de {partners_fr}."},
        ]
        sc_en = [
            {"name": "Constrained coalition bargain", "desc": f"Fragile governing majority in {pivot_en} trades specific security or diplomatic concessions."},
            {"name": "Institutional deadlock & contestation", "desc": "Disputed mandate or parliamentary gridlock prolongs strategic vulnerability."},
            {"name": "Rapid doctrinal pivot", "desc": f"Sharp reorientation of {pivot_en}'s external commitments."},
        ]
        confirm_fr = f"Accord formel de coalition, nomination aux portefeuilles régaliens (Défense, Affaires étrangères) ou prise de position officielle côté {actors_fr[1] if len(actors_fr) > 1 else pivot_fr}."
        abort_fr = "Reconduction à l'identique des équilibres sortants avec gel des contentieux extérieurs."
        stake_fr = f"Continuité des accords stratégiques, stabilité institutionnelle ({pivot_fr}) et équilibre des puissances entre {span_fr}."
        stake_en = f"Continuity of strategic agreements, institutional stability in {pivot_en} and power balance across {span_en}."

    elif any(k in full_blob for k in ("frontex", "ceuta", "migration", "migratoire", "asile", "expulsions")):
        title_fr = "Durcissement migratoire européen & extension du mandat Frontex"
        title_en = "EU external-border hardening & Frontex mandate expansion"
        call_fr = f"Sous {h} jours, un élargissement opérationnel et budgétaire de Frontex vers des accords d'externalisation avec les pays de transit ({span_fr}) est {ch_fr}."
        call_en = f"Within {h} days, operational and budgetary expansion of Frontex tied to transit-country agreements ({span_en}) is {ch_en}."
        why_fr = (
            f"La Commission européenne ({people_str or 'Bruxelles et plusieurs ministères de l’Intérieur'}) pousse une réforme musclée du contrôle aux frontières extérieures et des retours anticipés. "
            f"Ce tournant rebat les cartes des contreparties financières et diplomatiques négociées avec Rabat et les partenaires méditerranéens.{rupt_fr}"
        )
        why_en = (
            f"Brussels and interior ministries ({people_str or 'EU capitals'}) are pushing an expanded Frontex mandate and return hubs, reshaping leverage with Mediterranean transit states.{rupt_en}"
        )
        sc_fr = [
            {"name": "Externalisation négociée", "desc": "Renforcement des moyens de Frontex assorti de nouveaux financements européens vers les États riverains."},
            {"name": "Blocage juridique européen", "desc": "Recours devant la CJUE et réserves parlementaires freinant les dispositifs d'expulsion extraterritoriale."},
            {"name": "Tension sur les routes méditerranéennes", "desc": "Instrumentalisation des flux migratoires comme levier diplomatique bilatéral."},
        ]
        sc_en = [
            {"name": "Negotiated externalization", "desc": "Expanded Frontex deployment paired with new EU financial packages for partner states."},
            {"name": "EU legal pushback", "desc": "Court and parliamentary challenges slow extraterritorial return mechanisms."},
            {"name": "Mediterranean route friction", "desc": "Migration control leveraged in bilateral diplomatic bargaining."},
        ]
        confirm_fr = "Présentation formelle par la Commission du nouveau règlement retour / mandat Frontex ou signature d'un protocole opérationnel bilatéral."
        abort_fr = "Ajournement du paquet migratoire au Conseil Justice et Affaires intérieures."
        stake_fr = "Architecture Schengen, accords euro-méditerranéens et conditionnalité budgétaire européenne."
        stake_en = "Schengen border governance and Euro-Mediterranean diplomatic leverage."

    elif any(k in full_blob for k in ("sommet ue-canada", "membre associé", "carney", "von der leyen")):
        title_fr = "Arrimage stratégique Ottawa–Bruxelles face à la pression américaine"
        title_en = "Ottawa–Brussels strategic anchoring under US trade pressure"
        call_fr = f"Sous {h} jours, un accord sectoriel défense-matières critiques entre le Canada et l'Union européenne — sans statut formel d'adhésion — est {ch_fr}."
        call_en = f"Within {h} days, a sectoral EU–Canada defense and critical-minerals pact—short of formal associate membership—is {ch_en}."
        why_fr = (
            f"À l'approche du sommet bilatéral ({people_str or 'Ottawa et la Commission européenne'}), l'hypothèse d'un statut d'associé se heurte aux verrous juridiques des traités européens, "
            f"mais traduit la volonté commune de diversifier les chaînes industrielles et de défense hors de la seule orbite américaine.{rupt_fr}"
        )
        why_en = (
            f"Ahead of the bilateral summit ({people_str or 'Ottawa and Brussels'}), treaty hurdles block formal associate status, steering both sides toward concrete defense and industrial integration.{rupt_en}"
        )
        sc_fr = [
            {"name": "Partenariat industriel & défense renforcé", "desc": "Signature d'accords sur les achats militaires conjoints, le numérique et les minerais critiques."},
            {"name": "Déclaration politique minimale", "desc": "Désaccord sémantique entre États membres limitant le sommet à un communiqué sans instrument financier."},
            {"name": " Clause d'intégration accélérée", "desc": "Ouverture d'un cadre institutionnel inédit arrimant étroitement Ottawa au marché unique européen."},
        ]
        sc_en = [
            {"name": "Deepened defense & industrial pact", "desc": "Concrete agreements on joint defense procurement and critical minerals."},
            {"name": "Minimalist political communiqué", "desc": "Member-state legal pushback limits the summit to symbolic language."},
            {"name": "Institutional integration track", "desc": "Unprecedented framework tying Ottawa closer to EU regulatory and defense mechanisms."},
        ]
        confirm_fr = "Publication d'une feuille de route conjointe UE–Canada incluant l'accès aux programmes industriels de défense européens (SAFE / EDIP)."
        abort_fr = "Retrait des volets industriels et budgétaires du communiqué final du sommet."
        stake_fr = "Diversification transatlantique des chaînes d'approvisionnement critiques, interopérabilité industrielle de défense et accès aux marchés publics européens."
        stake_en = "Critical-supply diversification and defense-industrial interoperability between Europe and Canada."

    else:
        main_topic = topics[0] if topics else span_fr
        title_fr = f"Point de friction sécuritaire & diplomatique ({pair_fr})"
        title_en = f"Security & diplomatic flashpoint ({pair_en})"
        call_fr = f"Sous {h} jours, des mesures de sécurité renforcées, de rétorsion ciblée ou de coordination d'urgence entre {span_fr} sont {'probables' if c['chance'] == 'likely' else 'possibles' if c['chance'] == 'possible' else 'sous surveillance'}."
        call_en = f"Within {h} days, tightened security posture, targeted retaliation or emergency coordination across {span_en} is {ch_en}."
        why_fr = (
            f"L'incident sécuritaire et les réactions officielles impliquant {span_fr} ({orgs_str or 'appareils sécuritaires nationaux'}) mobilisent directement les chancelleries et services de sécurité intérieure. "
            f"{f'Les prises de position de {people_str} ' if people_str else 'Les signaux officiels '}indiquent un rehaussement immédiat du niveau de vigilance.{rupt_fr}"
        )
        why_en = (
            f"Security developments and official reactions across {span_en} ({orgs_str or 'national security agencies'}) have triggered heightened diplomatic and counter-security coordination.{rupt_en}"
        )
        sc_fr = [
            {"name": "Verrouillage sécuritaire coordonné", "desc": f"Renforcement de la protection diplomatique, coopération policière/renseignement et opérations ciblées entre {pair_fr}."},
            {"name": "Instrumentalisation diplomatique", "desc": "Durcissement rhétorique et convocations d'ambassadeurs pesant sur la relation bilatérale."},
            {"name": "Incident réplique ou contagion", "desc": "Reproduction d'actions violentes ou asymétriques forçant des restrictions frontalières ou opérationnelles."},
        ]
        sc_en = [
            {"name": "Coordinated security lockdown", "desc": f"Tightened diplomatic protection and intelligence cooperation between {pair_en}."},
            {"name": "Diplomatic friction", "desc": "Political attributions and formal demarches straining bilateral ties."},
            {"name": "Copycat incident or spillover", "desc": "Follow-on asymmetric incident forcing operational or border restrictions."},
        ]
        confirm_fr = f"Annonce de mesures d'exception, d'arrestations transfrontalières ou d'un mécanisme conjoint par les autorités de {pair_fr}."
        abort_fr = "Clôture rapide de l'enquête concluant à un acte isolé sans ramification extérieure."
        stake_fr = f"Sûreté des emprises diplomatiques, coopération antiterroriste et stabilité bilatérale entre {span_fr}."
        stake_en = f"Diplomatic security, counter-intelligence cooperation and bilateral stability across {span_en}."

    return {
        "title_fr": title_fr, "title_en": title_en,
        "call_fr": call_fr, "call_en": call_en,
        "why_now_fr": why_fr, "why_now_en": why_en,
        "scenarios_fr": sc_fr, "scenarios_en": sc_en,
        "signposts_fr": {"confirm": confirm_fr, "abort": abort_fr},
        "signposts_en": {"confirm": confirm_fr if False else f"Official executive, military or regulatory action across {span_en} confirming this trajectory.", "abort": f"Verified de-escalation or formal settlement across {span_en}."},
        "stake_fr": stake_fr, "stake_en": stake_en,
    }


def _call_single_dossier_llm(db: Session, system: str, item: dict) -> dict | None:
    """Synthèse unitaire (~6s) via httpx direct pour contrôle absolu du timeout (0 retry bloquant)."""
    import httpx
    if not llm.LLM_API_KEY:
        return None
    base_url = (llm.LLM_BASE_URL or "https://inference.aleria.com/v1").rstrip("/")
    body = {
        "model": "deepseek-v4-flash",
        "temperature": 0.2,
        "max_tokens": 950,
        "response_format": {"type": "json_object"},
        "chat_template_kwargs": {"enable_thinking": False},
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps(item, ensure_ascii=False)},
        ],
    }
    try:
        with httpx.Client(timeout=httpx.Timeout(12.0, connect=4.0)) as client:
            r = client.post(
                f"{base_url}/chat/completions",
                headers={"Authorization": f"Bearer {llm.LLM_API_KEY}", "Content-Type": "application/json"},
                json=body,
            )
        if r.status_code != 200:
            log.info("Horizon LLM HTTP %s on %s — using structured domain brief", r.status_code, item.get("id"))
            return None
        data = r.json()
        raw = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or ""
        raw = raw.strip()
        if not raw:
            return None
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            m = re.search(r"\{.*\}", raw, re.S)
            if m:
                return json.loads(m.group(0))
    except Exception as exc:  # noqa: BLE001
        log.info("Horizon LLM timeout/skip on %s (%s) — using structured domain brief", item.get("id"), type(exc).__name__)
    return None


def _synthesize_executive_briefs(db: Session, raw_dossiers: list[dict], locale: str = "fr") -> tuple[dict[str, dict], dict[str, str]]:
    """Synthétise chaque dossier unitairement dans la langue active (~50s au premier calcul, 0ms ensuite via PreparedView)."""
    fallbacks = {c["id"]: _fallback_brief(c) for c in raw_dossiers}
    default_ov_fr = " ".join(fallbacks[c["id"]]["call_fr"] for c in raw_dossiers[:3])
    default_ov_en = " ".join(fallbacks[c["id"]]["call_en"] for c in raw_dossiers[:3])

    if not raw_dossiers or not llm.LLM_API_KEY:
        return fallbacks, {"fr": default_ov_fr, "en": default_ov_en}

    merged: dict[str, dict] = {}
    is_en = locale == "en"
    sys_prompt = HORIZON_SINGLE_SYSTEM_EN if is_en else HORIZON_SINGLE_SYSTEM_FR

    for idx, c in enumerate(raw_dossiers):
        if idx > 0:
            time.sleep(0.35)
        ch_word = (
            {"likely": "likely", "possible": "possible"}.get(c["chance"], "unlikely")
            if is_en else
            {"likely": "probable", "possible": "possible"}.get(c["chance"], "peu probable")
        )
        item_payload = {
            "id": c["id"],
            "category": c["kind"],
            "likelihood": ch_word,
            "horizon_days": c["horizon_days"],
            "state_actors": [_country_label(a, is_en) for a in c["actors"]],
            "observed_across_press_of": [_country_label(p, is_en) for p in c["press_countries"]],
            "key_topics": c["topics"],
            "organizations": c["organizations"],
            "key_figures": c["people"],
            "editorial_ruptures": c["ruptures"],
            "strategic_corridor": (c["chokepoint"]["en"] if is_en else c["chokepoint"]["fr"]) if c.get("chokepoint") else None,
            "headlines": [f"[{e['outlet']} - {e['country']}] {e['title']}" for e in c["evidence"]],
        }
        got = _call_single_dossier_llm(db, sys_prompt, item_payload) or {}
        fb = fallbacks[c["id"]]
        sc_got = got.get("scenarios") if isinstance(got.get("scenarios"), list) and len(got["scenarios"]) >= 2 else None
        sp_got = {"confirm": got["confirm"], "abort": got["abort"]} if got.get("confirm") and got.get("abort") else None

        if is_en:
            merged[c["id"]] = {
                **fb,
                "title_en": got.get("title") or fb["title_en"],
                "call_en": got.get("call") or fb["call_en"],
                "why_now_en": got.get("why_now") or fb["why_now_en"],
                "scenarios_en": sc_got or fb["scenarios_en"],
                "signposts_en": sp_got or fb["signposts_en"],
                "stake_en": got.get("stake") or fb["stake_en"],
            }
        else:
            merged[c["id"]] = {
                **fb,
                "title_fr": got.get("title") or fb["title_fr"],
                "call_fr": got.get("call") or fb["call_fr"],
                "why_now_fr": got.get("why_now") or fb["why_now_fr"],
                "scenarios_fr": sc_got or fb["scenarios_fr"],
                "signposts_fr": sp_got or fb["signposts_fr"],
                "stake_fr": got.get("stake") or fb["stake_fr"],
            }

    # Synthèse exécutive chapeau reliant les 3 dossiers prioritaires
    top_calls_fr = [merged[c["id"]]["call_fr"] for c in raw_dossiers[:3]]
    top_calls_en = [merged[c["id"]]["call_en"] for c in raw_dossiers[:3]]
    ov = {
        "fr": " ".join(top_calls_fr) if top_calls_fr else default_ov_fr,
        "en": " ".join(top_calls_en) if top_calls_en else default_ov_en,
    }
    return merged, ov


# ───────────────────────────────────────────── Assemblage Carte + Salle de Situation

def _delay_label(days: int) -> dict[str, str]:
    if days <= 14:
        return {"fr": "14 j", "en": "14d"}
    if days <= 30:
        return {"fr": "30 j", "en": "30d"}
    return {"fr": f"{days} j", "en": f"{days}d"}


def _assemble_payload(raw_dossiers: list[dict], briefs: dict[str, dict], overview: dict[str, str], end: datetime, min_dt: datetime, max_dt: datetime) -> dict:
    forecasts = []
    arcs = []
    signals = []
    blocs = []
    chokepoints = []
    seen_chokes: set[str] = set()

    mark_priority = {"conflict": 5, "economy": 4, "coalition": 3, "rapprochement": 3, "signal": 2}
    country_marks: dict[str, str] = {}
    country_dossiers: dict[str, list[str]] = defaultdict(list)

    for c in raw_dossiers:
        b = briefs[c["id"]]
        actors = c["actors"]
        delay = _delay_label(c["horizon_days"])
        kind_map = "rapprochement" if c["kind"] in {"coalition", "rapprochement"} else ("conflict" if c["kind"] == "conflict" else "probe")

        for code in actors:
            country_dossiers[code].append(c["id"])
            if mark_priority.get(c["kind"], 1) >= mark_priority.get(country_marks.get(code, ""), 0):
                country_marks[code] = "rapprochement" if c["kind"] in {"coalition", "rapprochement"} else c["kind"]

        # Arcs géopolitiques reliant les capitales/États impliqués dans le dossier
        if len(actors) >= 2:
            primary = actors[0]
            for partner in actors[1:3]:
                arcs.append({
                    "id": f"{c['id']}:{primary}-{partner}",
                    "dossier_id": c["id"],
                    "source": primary,
                    "target": partner,
                    "kind": kind_map,
                    "chance": c["chance"],
                    "delay": delay,
                    "label": {"fr": b["title_fr"], "en": b["title_en"]},
                })

        if c["kind"] == "coalition" and len(actors) >= 3:
            blocs.append({
                "id": c["id"],
                "countries": actors[:4],
                "label": {"fr": b["title_fr"], "en": b["title_en"]},
            })

        if c["kind"] == "signal" or len(actors) == 1:
            signals.append({"dossier_id": c["id"], "countries": actors[:3]})

        if c.get("chokepoint") and c["chokepoint"]["id"] not in seen_chokes:
            cp = c["chokepoint"]
            seen_chokes.add(cp["id"])
            chokepoints.append({
                "id": c["id"],
                "choke_id": cp["id"],
                "name": {"fr": cp["fr"], "en": cp["en"]},
                "lat": cp["lat"],
                "lon": cp["lon"],
                "delay": delay,
            })

        forecasts.append({
            "id": c["id"],
            "kind": c["kind"],
            "chance": c["chance"],
            "horizon_days": c["horizon_days"],
            "delay": delay,
            "countries": actors,
            "press_countries": c["press_countries"],
            "languages": c["languages"],
            "organizations": c["organizations"][:4],
            "ruptures": c["ruptures"],
            "title": {"fr": b["title_fr"], "en": b["title_en"]},
            "line": {"fr": b["call_fr"], "en": b["call_en"]},
            "blocks": {
                "forecast": {"fr": b["call_fr"], "en": b["call_en"]},
                "dynamic": {"fr": b["why_now_fr"], "en": b["why_now_en"]},
                "stake": {"fr": b["stake_fr"], "en": b["stake_en"]},
            },
            "scenarios": {"fr": b["scenarios_fr"], "en": b["scenarios_en"]},
            "signposts": {"fr": b["signposts_fr"], "en": b["signposts_en"]},
            "evidence": c["evidence"],
        })

    # Tri par vraisemblance puis saillance stratégique
    chance_order = {"likely": 0, "possible": 1, "unlikely": 2}
    forecasts.sort(key=lambda f: (chance_order.get(f["chance"], 9), f["kind"] == "signal"))

    country_rows = []
    for code, mark in country_marks.items():
        meta = geo_country(code) or {}
        country_rows.append({
            "code": code,
            "numeric": meta.get("numeric"),
            "centroid": [meta["lat"], meta["lon"]] if meta.get("lat") is not None else None,
            "mark": mark,
            "dossiers": country_dossiers[code],
        })

    return {
        "as_of": end.date().isoformat(),
        "min": min_dt.date().isoformat() if min_dt else None,
        "max": max_dt.date().isoformat() if max_dt else None,
        "window_days": WINDOW_DAYS,
        "countries": country_rows,
        "arcs": arcs,
        "signals": signals,
        "blocs": blocs,
        "chokepoints": chokepoints,
        "forecasts": forecasts,
        "overview": overview,
        "empty": not forecasts,
        "doctrine": "horizon_v2",
    }


def _prepared_key(date_iso: str, use_llm: bool) -> str:
    return f"horizon:v2:{date_iso}:{'llm' if use_llm else 'fast'}"


def build(db: Session, as_of: datetime | None = None, refresh: bool = False) -> dict:
    latest = (
        db.query(Article.published_at)
        .filter(Article.published_at.isnot(None))
        .order_by(Article.published_at.desc())
        .limit(1)
        .scalar()
    )
    if latest is None:
        return _empty()

    end = as_of or latest
    if end > latest:
        end = latest
    is_live = abs((latest - end).total_seconds()) < 86400
    date_iso = end.date().isoformat()
    uid = current_user_id() or 0
    loc = get_locale() or "fr"
    cache_key = f"{uid}:{loc}:{_prepared_key(date_iso, is_live)}"

    now = time.time()
    if not refresh and cache_key in _mem_cache:
        ts, cached = _mem_cache[cache_key]
        if now - ts < CACHE_TTL:
            return cached

    # Vérifie le cache persistant PreparedView en base pour la vue courante (évite tout appel LLM répété)
    pkey = _prepared_key(date_iso, is_live)
    if not refresh and is_live:
        persisted = prepared.load(db, pkey)
        if isinstance(persisted, dict) and persisted.get("doctrine") == "horizon_v2":
            _mem_cache[cache_key] = (now, persisted)
            return persisted

    raw_dossiers, min_dt, max_dt = _compute_dossiers(db, end)
    if not raw_dossiers:
        empty = _empty(min_dt, max_dt, date_iso)
        _mem_cache[cache_key] = (now, empty)
        return empty

    if is_live:
        briefs, overview = _synthesize_executive_briefs(db, raw_dossiers, locale=loc)
    else:
        # En replay historique (slider), réponse instantanée 0$ sans latence LLM
        briefs = {c["id"]: _fallback_brief(c) for c in raw_dossiers}
        overview = {
            "fr": " ".join(briefs[c["id"]]["call_fr"] for c in raw_dossiers[:3]),
            "en": " ".join(briefs[c["id"]]["call_en"] for c in raw_dossiers[:3]),
        }

    payload = _assemble_payload(raw_dossiers, briefs, overview, end, min_dt, max_dt)
    _mem_cache[cache_key] = (now, payload)
    if is_live and uid:
        try:
            prepared.put(db, pkey, payload, locales=(loc,))
        except Exception as exc:  # noqa: BLE001
            log.warning("Could not persist Horizon PreparedView: %s", exc)
    return payload


def _empty(min_dt: datetime | None = None, max_dt: datetime | None = None, as_of: str | None = None) -> dict:
    return {
        "as_of": as_of,
        "min": min_dt.date().isoformat() if min_dt else None,
        "max": max_dt.date().isoformat() if max_dt else None,
        "window_days": WINDOW_DAYS,
        "countries": [], "arcs": [], "signals": [], "blocs": [],
        "chokepoints": [], "forecasts": [],
        "overview": {"fr": "", "en": ""},
        "doctrine": "horizon_v2",
        "empty": True,
    }
