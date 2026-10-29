"""Appels LLM vers Aleria (API chat compatible) : sorties structurées et suivi des coûts."""

import json
import logging
import re
from datetime import date

from sqlalchemy.orm import Session

from ..config import LLM_API_KEY, LLM_BASE_URL
from ..constants import JOURNALISTIC_ANGLES, MODEL_PRICING, SOURCE_TYPES
from ..kits import extract_axes_for_country, kit_for_country
from ..models import LLMUsage

log = logging.getLogger("tacite.llm")

_client = None


def get_client():
    global _client
    if _client is None:
        from openai import OpenAI

        kwargs = {"api_key": LLM_API_KEY, "timeout": 60.0, "max_retries": 1}
        if LLM_BASE_URL:
            kwargs["base_url"] = LLM_BASE_URL
        _client = OpenAI(**kwargs)
    return _client


def _track_usage(db: Session, model: str, purpose: str, usage) -> None:
    if usage is None:
        return
    pin, pout = MODEL_PRICING.get(model, (0.5, 1.5))
    cost = (usage.prompt_tokens * pin + usage.completion_tokens * pout) / 1_000_000
    db.add(
        LLMUsage(
            date=date.today(),
            model=model,
            purpose=purpose,
            prompt_tokens=usage.prompt_tokens,
            completion_tokens=usage.completion_tokens,
            cost_usd=cost,
        )
    )
    db.commit()


def _framing_schema(axis_ids: list[str]):
    return {
        "type": "object",
        "properties": {a: {"type": "number"} for a in axis_ids},
        "required": list(axis_ids),
        "additionalProperties": False,
    }


def _extraction_schema(axis_ids: list[str]) -> dict:
    return {
        "name": "article_extraction",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "topics": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "label": {"type": "string"},
                            "framing": _framing_schema(axis_ids),
                        },
                        "required": ["label", "framing"],
                        "additionalProperties": False,
                    },
                },
                "sources": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "name": {"type": "string"},
                            "type": {"type": "string", "enum": SOURCE_TYPES},
                        },
                        "required": ["name", "type"],
                        "additionalProperties": False,
                    },
                },
                "tone": {"type": "string"},
                "angle": {"type": "string", "enum": JOURNALISTIC_ANGLES},
                "entities": {
                    "type": "object",
                    "properties": {
                        "people": {"type": "array", "items": {"type": "string"}},
                        "organizations": {"type": "array", "items": {"type": "string"}},
                        "locations": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["people", "organizations", "locations"],
                    "additionalProperties": False,
                },
            },
            "required": ["topics", "sources", "tone", "angle", "entities"],
            "additionalProperties": False,
        },
    }


def _axis_lines(axes: list[dict]) -> str:
    lines = []
    for a in axes:
        extra = f". {a['hint_en']}" if a.get("hint_en") else ""
        lines.append(f"- {a['id']}: {a.get('neg_en', '−')} (−1) to {a.get('pos_en', '+')} (+1){extra}")
    return "\n".join(lines)


def _extraction_system(axes: list[dict], kit) -> str:
    if kit:
        kit_block = (
            f"\nLocal political space — {kit.get('label_en') or kit['id']}:\n"
            f"{kit.get('prompt_en') or ''}\n"
            "Score ONLY the axes listed. Do not import Western left/right, EU federalism, "
            "or French laïcité unless they appear in the list.\n"
        )
    else:
        kit_block = (
            "\nNo local political kit: score only the structural axes. "
            "Do not force left/right, EU, or laïcité onto this landscape.\n"
        )
    return f"""You are a media analysis engine. Analyze the press article and extract structured intelligence.

Framing axes (score each from -1 to +1) as expressed BY THE ARTICLE (angle, vocabulary, sources), not the topic itself:
{_axis_lines(axes)}
{kit_block}
Rules:
- Extract at most 3 main topics, each with framing on every listed axis.
- Each topic "label" MUST be a concise, natural-language headline topic in the SAME language as the article (3 to 6 words max, e.g. "Entrée de Nvidia dans Doctolib", "Revalorisation des retraites Agirc-Arrco", "Mobilisation dans les lycées"). NEVER use snake_case, NEVER add parenthetical details "(...)", and NEVER write full sentences as topic labels.
- Subtle or implicit framings MUST be scored with non-zero values. Most political articles have framings on at least 3–5 axes. Do NOT default to 0 unless the axis is truly silent. When in doubt, assign ±0.1 or ±0.2.
- Sports, entertainment, lifestyle or weather with NO political/social dimension: all axes 0, topic label "Non-political".
- tone: one lowercase English word (anger, fear, hope, neutral, indignation, irony).
- List every named source cited, with its type.
- Extract all named entities."""


def _official_system(axes: list[dict], kit) -> str:
    space = ""
    if kit:
        space = f"\nPolitical space: {kit.get('label_en') or kit['id']}. {kit.get('prompt_en') or ''}\n"
    listed = ", ".join(f"{a['id']} (−1 {a.get('neg_en')}, +1 {a.get('pos_en')})" for a in axes)
    return f"""You are a media analyst. Given a news outlet, estimate its DECLARED / publicly perceived editorial line on these axes, each from -1 to +1:
{listed}
{space}
Also estimate audience_score, elite_score, network_score, longevity_score (0-100) for influence weighting.
Respond with JSON only: {{"official_classification": {{axis: value}}, "meta": {{"audience_score": n, "elite_score": n, "network_score": n, "longevity_score": n}}}}"""


def estimate_official_classification(db: Session, model: str, name: str, country: str, language: str, orientation: str) -> dict | None:
    """Estimate declared classification + influence meta for a newly added outlet."""
    axes = extract_axes_for_country(country, db)
    axis_ids = [a["id"] for a in axes]
    kit = kit_for_country(country, db)
    content = f"Outlet: {name}\nCountry: {country}\nLanguage: {language}\nDeclared orientation: {orientation or 'unknown'}"
    try:
        resp = get_client().chat.completions.create(
            model=model,
            messages=[{"role": "system", "content": _official_system(axes, kit)}, {"role": "user", "content": content}],
            response_format={"type": "json_object"},
            temperature=0.2,
        )
        _track_usage(db, model, "profile", resp.usage)
        data = json.loads(resp.choices[0].message.content)
        oc = {a: max(-1.0, min(1.0, float((data.get("official_classification") or {}).get(a, 0) or 0))) for a in axis_ids}
        meta = {k: int(max(0, min(100, float(v)))) for k, v in (data.get("meta") or {}).items() if isinstance(v, (int, float))}
        return {"official_classification": oc, "meta": meta, "kit": kit["id"] if kit else "_structural"}
    except Exception as e:  # noqa: BLE001
        log.warning("official classification estimate failed for %s: %s", name, e)
        return None


def extract_article(db: Session, model: str, title: str, text: str, country: str | None = None, coverage: str = "body") -> dict | None:
    """Extraction LLM. coverage='excerpt' : titre et chapô seulement, axes silencieux à 0."""
    axes = extract_axes_for_country(country, db)
    axis_ids = [a["id"] for a in axes]
    kit = kit_for_country(country, db)
    system = _extraction_system(axes, kit)
    if coverage == "excerpt":
        system += (
            "\n\nEXCEPTION — this is a headline and a lead, not the full article. "
            "Score an axis only when the lead itself expresses it; leave every silent axis at 0. "
            "Do not invent sources, quotations or entities that are not written in the lead."
        )
    content = f"TITLE: {title}\n\nARTICLE:\n{text[:8000]}"
    # Libère la transaction avant l'appel réseau : sinon la session reste
    # « idle in transaction » pendant toute la latence du modèle.
    db.commit()
    try:
        resp = get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": content},
            ],
            response_format={"type": "json_schema", "json_schema": _extraction_schema(axis_ids)},
            temperature=0.1,
            timeout=60,
        )
        _track_usage(db, model, "extraction", resp.usage)
        data = json.loads(resp.choices[0].message.content)
        topics = data.get("topics", [])[:3]
        framing = {}
        for axis in axis_ids:
            vals = [t.get("framing", {}).get(axis, 0) for t in topics]
            nonzero = [v for v in vals if v]
            framing[axis] = round(sum(nonzero) / len(nonzero), 3) if nonzero else 0.0
        data["framing"] = framing
        data["topics"] = topics
        data["kit"] = kit["id"] if kit else "_structural"
        return data
    except Exception as e:  # noqa: BLE001
        log.warning("LLM extraction failed: %s", e)
        return None


PROFILE_SYSTEM = """You are an intelligence analyst profiling a journalist for influence operations.
Based on their recent articles (topics, framings, tones, sources), return a JSON object with:
- "themes": array of {"label": str, "count": int} — their fixations, most frequent first (max 6)
- "biases": array of strings in French — recurring biases you detect (max 5)
- "preferred_sources": array of {"type": str, "count": int}
- "tone": dominant tone, one French word
- "vulnerabilities": array of {"label": str, "explanation": str} in French — exploitable traits
  (e.g. "en quête de reconnaissance", "réactif aux angles exclusifs", "en recherche de sujet")
- "accessibility_score": number 0-100 — how receptive this journalist would be to a pitch
  (higher if productive, generalist, uses varied/corporate sources; lower if investigative, elite sources)
- "summary": 2-3 sentence synthesis in French
Respond with JSON only."""


def synthesize_journalist_profile(db: Session, model: str, name: str, outlet: str, articles_digest: list[dict]) -> dict | None:
    try:
        resp = get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": PROFILE_SYSTEM},
                {
                    "role": "user",
                    "content": f"Journalist: {name} ({outlet})\n\nRecent articles (7 days):\n"
                    + json.dumps(articles_digest, ensure_ascii=False)[:12000],
                },
            ],
            response_format={"type": "json_object"},
            temperature=0.3,
        )
        _track_usage(db, model, "profile", resp.usage)
        return json.loads(resp.choices[0].message.content)
    except Exception as e:  # noqa: BLE001
        log.warning("LLM profile synthesis failed: %s", e)
        return None


PLAN_SYSTEM = """You are an influence operations planner. Produce a multi-week action plan for the given action type.
Return a JSON object: {"phases": [{"phase": str, "weeks": str, "actions": [str], "tools": [str]}]}
- 2 to 4 phases, weeks as ranges like "S1-S2".
- "actions": concrete steps in French.
- "tools": text references to external suite tools, e.g. "Génération de contenu pour X", "Amplification pour Y".
Action type meanings:
NOURRIR=feed exclusive info to a journalist; AMORCER=seed a narrative angle; SURVEILLER=monitor only;
COOPTER=turn a journalist via access; CONTOURNER=bypass a hostile outlet via others; DILUER=flood a hostile narrative;
RETOURNER=flip an outlet's position on an axis; DIVISER=exploit newsroom fractures; ISOLER=cut an outlet's re-citations.
Respond with JSON only."""


def generate_plan(db: Session, model: str, context: dict) -> list[dict]:
    try:
        resp = get_client().chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": PLAN_SYSTEM},
                {"role": "user", "content": json.dumps(context, ensure_ascii=False)},
            ],
            response_format={"type": "json_object"},
            temperature=0.4,
        )
        _track_usage(db, model, "plan", resp.usage)
        data = json.loads(resp.choices[0].message.content)
        phases = data.get("phases", [])
        if isinstance(phases, list) and phases:
            return phases
    except Exception as e:  # noqa: BLE001
        log.warning("LLM plan generation failed: %s", e)
    # Fallback template
    action = context.get("action_type", "SURVEILLER")
    return [
        {"phase": "Préparation", "weeks": "S1-S2", "actions": [f"Cartographier les angles pertinents pour {action}"], "tools": ["Veille approfondie"]},
        {"phase": "Exécution", "weeks": "S3-S6", "actions": ["Dérouler l'action auprès de la cible"], "tools": ["Génération de contenu"]},
        {"phase": "Évaluation", "weeks": "S7-S8", "actions": ["Mesurer l'impact et ajuster"], "tools": ["Suivi des retombées"]},
    ]


BRIEF_SYSTEM_FR = """Vous rédigez des mini executive summaries pour Tacite (intelligence presse).
Le lecteur ne doit pas avoir besoin d'ouvrir les articles pour comprendre LE SUJET : quoi, où, qui, quel enjeu, comment la presse le traite.
Règles :
- 3 ou 4 phrases. Prose. Pas de puces, pas de titre.
- Partez des titres et des acteurs fournis. N'inventez aucun fait.
- Interdit : nombres d'articles ou de médias, pourcentages, « ton dominant », « premier titre », « ouvre le », « acteurs les plus cités », polarisation, listes d'affaires (« 2 stories: A ; B »).
- N'ouvrez pas par le libellé du cluster. Ne recitez pas les libellés LLM.
- Une seule citation de titre, seulement si elle nomme l'événement.
- Si les titres mélangent des événements distincts, dites-le en une proposition puis tenez-vous au fil dominant.
- Langue : français sobre.
Répondez en JSON : {"briefs": [{"id": str, "brief": str}]} — un objet par id fourni, rien d'autre."""

BRIEF_SYSTEM_EN = """You write mini executive summaries for Tacite (press intelligence).
The reader must understand THE SUBJECT without opening the articles: what, where, who, the stake, how the press treats it.
Rules:
- 3 or 4 sentences. Prose. No bullets, no heading.
- Use only the supplied headlines and actors. Invent nothing.
- Forbidden: article or outlet counts, percentages, “dominant tone”, “opens on”, “most cited actors”, polarisation, catalogues of story labels (“2 stories: A ; B”).
- Do not open with the cluster label. Do not recite LLM labels.
- Quote at most one headline, and only if it names the event.
- If the headlines mix distinct events, say so in one clause, then stay with the dominant thread.
- Language: plain, direct English.
Reply in JSON: {"briefs": [{"id": str, "brief": str}]} — one object per supplied id, nothing else."""


def synthesize_topic_briefs(db: Session, model: str, items: list[dict], locale: str = "fr") -> dict[str, str]:
    """Rédige un mini-brief par item (id -> texte). Échec → dict vide."""
    if not items:
        return {}
    if not LLM_API_KEY:
        return {}
    out: dict[str, str] = {}
    system = BRIEF_SYSTEM_EN if locale == "en" else BRIEF_SYSTEM_FR
    chunk: list[dict] = []
    size = 0
    batches: list[list[dict]] = []
    for it in items:
        blob = json.dumps(it, ensure_ascii=False)
        if chunk and size + len(blob) > 18000:
            batches.append(chunk)
            chunk, size = [], 0
        chunk.append(it)
        size += len(blob)
    if chunk:
        batches.append(chunk)
    for batch in batches:
        try:
            resp = get_client().chat.completions.create(
                model=model,
                temperature=0.2,
                timeout=90,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": json.dumps({"items": batch}, ensure_ascii=False)},
                ],
            )
            _track_usage(db, model, "topic_brief", resp.usage)
            data = json.loads(resp.choices[0].message.content or "{}")
            out.update(_parse_brief_map(data))
        except Exception as e:  # noqa: BLE001
            log.warning("LLM topic briefs failed (%s items): %s", len(batch), e)
    return out


def _parse_brief_map(data) -> dict[str, str]:
    raw = data.get("briefs") if isinstance(data, dict) else None
    rows: list = []
    if isinstance(raw, dict):
        rows = [{"id": k, "brief": v} for k, v in raw.items()]
    elif isinstance(raw, list):
        rows = raw
    out: dict[str, str] = {}
    for it in rows:
        if not isinstance(it, dict):
            continue
        i = str(it.get("id") or "").strip()
        b = re.sub(r"\s+", " ", str(it.get("brief") or "")).strip().strip("\"'")
        if not i or len(b) < 40:
            continue
        if len(b) > 900:
            cut = b[:900]
            dot = cut.rfind(".")
            b = cut[: dot + 1] if dot > 200 else cut.rstrip() + "…"
        out[i] = b
    return out
