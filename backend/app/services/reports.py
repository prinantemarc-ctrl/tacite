"""Générateur de rapports PDF (design Gorgone).

Chaîne : collecte de faits via les outils de l'agent → rédaction par le LLM contrainte aux faits
(JSON de sections) → HTML avec graphiques SVG → PDF (Playwright) → Artifact.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from collections import Counter
from datetime import datetime

from sqlalchemy.orm import Session

from .. import geo
from ..constants import AXES
from ..i18n import axis_labels, axis_poles_map, get_locale
from ..models import Artifact, Journalist, Outlet, Report
from ..settings_store import get_setting
from . import agent_tools as T, files, llm

log = logging.getLogger("tacite.reports")

KINDS_FR = {
    "outlet": ("Note média", "Ligne éditoriale déclarée et mesurée, écarts, influence, journalistes clés, réseau."),
    "journalist": ("Dossier journaliste", "Profil, fixations, biais, sources, accessibilité, divergence avec son média, angles d'approche."),
    "client": ("Brief client", "Position des médias vis-à-vis du client, mouvements, recommandations, actions en cours."),
    "landscape": ("Panorama du paysage", "Positions par axe, blocs, meneurs et suiveurs, entités clivantes, angles morts. Filtre pays optionnel."),
    "country": ("Panorama pays", "Médias suivis d'un pays : positions, influence, meneurs, thèmes, journalistes, flux transfrontaliers."),
    "topic": ("Note thématique", "Mini executive summary du sujet, traitement par les médias suivis, cadrages, meneurs, contexte web. Filtre pays optionnel."),
    "theme": ("Brief de fond", "Mini executive summary de la famille et de chaque affaire, opinion et tons, cadrages, meneurs."),
}
KINDS_EN = {
    "outlet": ("Outlet note", "Declared and measured editorial line, gaps, influence, key journalists, network."),
    "journalist": ("Journalist file", "Profile, fixations, biases, sources, accessibility, divergence from the outlet, approach angles."),
    "client": ("Client brief", "Outlet stance toward the client, movements, recommendations, actions in progress."),
    "landscape": ("Landscape panorama", "Positions by axis, blocs, leaders and followers, polarising entities, blind spots. Optional country filter."),
    "country": ("Country panorama", "Followed outlets in a country: positions, influence, leaders, topics, journalists, cross-border flows."),
    "topic": ("Topic note", "Mini executive summary of the subject, how followed outlets treat it, framings, leaders, web context. Optional country filter."),
    "theme": ("Background brief", "Mini executive summary of the family and of each story, article opinion and tones, framings, leaders."),
}
KINDS = KINDS_FR


def _kinds() -> dict[str, tuple[str, str]]:
    return KINDS_EN if get_locale() == "en" else KINDS_FR


def _tr(fr: str, en: str) -> str:
    return en if get_locale() == "en" else fr


WRITER_SYSTEM_FR = """Vous rédigez des notes de renseignement presse (Press Intelligence) pour Tacite. Français sobre, direct, analytique ; aucune emphase.
Vous ne disposez QUE des FAITS fournis (JSON). Chaque chiffre ou nom que vous écrivez doit y figurer ; n'inventez rien, ne complétez pas de mémoire. Si une donnée manque, dites-le en une phrase.

DOCTRINE ANALYTIQUE TACITE (3 PILIERS) :
1. Analyse du discours (McCombs & Shaw, 1972 ; Entman, 1993) : distinguez l'événement du cadrage (définition du problème, responsabilité causale, remède proposé) et la position (stance) de la simple émotion (sentiment). Soulignez les anomalies éditoriales (média s'écartant de ≥ 0,22 de sa ligne mesurée habituelle ou de > 0,30 de sa ligne déclarée).
2. Tradecraft du renseignement (ODNI ICD 203 ; Heuer, 1999) : séparez explicitement l'information rapportée (« Les publications rapportent que… »), l'inférence (« Cela suggère que… ») et le jugement analytique (« Tacite évalue que… »). Évaluez la dépendance des sources (plusieurs articles citant la même source unique ne constituent pas une corroboration indépendante), exprimez le niveau de confiance (élevée / modérée / faible ; faible < 10 articles) et mentionnez, quand pertinent, une hypothèse alternative plausible et les indicateurs à surveiller.
3. Dynamique de l'environnement informationnel (OTAN ABCDE : Actor, Behaviour, Content, Degree, Effect) : identifiez les rôles (Originator / meneur d'agenda, Amplifier à forte influence, Interpreter), distinguez le volume brut du poids d'influence, et séparez les effets observés, probables et potentiels.
Si le rapport est national (un pays dans CIBLE), restez dans ce pays : les médias d'ailleurs n'apparaissent que s'ils figurent dans les faits (flux transfrontaliers).

Répondez en JSON : {"title": str, "subtitle": str, "summary": str, "sections": [{"heading": str, "markdown": str}], "sources": [str]}
- summary : 4 phrases maximum. Ce qui est établi (ou « non établi dans les faits »). Le cadrage des rédactions mesurées. Le jugement, limité à cet échantillon. La confiance et sa raison.
- Exactement 4 sections, titres courts, chacune un paragraphe ou trois puces :
  1. Cadrages — le cadrage mesuré et ceux déjà écrits ailleurs. Ne pas les présenter comme le cadrage du pays.
  2. Preuves — information rapportée, qui a ouvert et qui a repris, puis l'hypothèse qui peut annuler le jugement.
  3. Effets — effets observés seulement s'ils sont établis ; deux ou trois indicateurs politiques.
  4. Levier — une phrase sur l'exposition et le média qui fixe le cadre, puis un tableau Markdown des journalistes présents dans les faits (intelligence_brief.influence_targets, sinon journalists, sinon les journalistes du média) : nom, média, articles, accessibilité, action, contact. L'absence de dossier client n'est pas une raison d'omettre le tableau. Si targets_basis vaut newsroom, préciser que ce ne sont pas des signatures. Si la liste est vide : aucune signature et aucune fiche. Ne pas écrire qu'une liste serait fausse.
- Pas de section Méthode : le gabarit l'ajoute. Pas de nom de cadre dans le corps.
- Si « story_summaries[].brief » est présent, une puce par affaire dans Cadrages, pas une section de plus.
- sources : références internes et URL web utilisées."""

WRITER_SYSTEM_EN = """You write Press Intelligence notes for Tacite. Plain, direct, analytical English; no emphasis, no empty formulas.
You have ONLY the supplied FACTS (JSON). Every figure or name you write must appear there; invent nothing, do not fill from memory. If a datum is missing, say so in one sentence.

TACITE ANALYTICAL DOCTRINE (3 PILLARS):
1. Academic Media Analysis (McCombs & Shaw, 1972; Entman, 1993): distinguish the event from the frame (problem definition, causal attribution, treatment) and stance from sentiment. Highlight editorial anomalies (outlets deviating by ≥ 0.22 from their usual measured line or > 0.30 from their stated line).
2. Intelligence Tradecraft (ODNI ICD 203; Heuer, 1999): strictly separate reported information (“Reporting indicates…”), analytical inference (“This suggests…”) and analytical judgment (“Tacite assesses…”). Evaluate source dependency, state confidence (High / Moderate / Low; low below 10 articles), and include a plausible alternative hypothesis and observable indicators to monitor when relevant.
3. Information Environment Analysis (NATO ABCDE: Actor, Behaviour, Content, Degree, Effect): identify Actor roles (Originator, High-reach Amplifier, Interpreter), distinguish raw volume from influence weight, and separate Observed, Likely and Potential effects.
If the report is national (a country in TARGET), stay in that country: outlets from elsewhere appear only if they are in the facts (cross-border flows).

Reply in JSON: {"title": str, "subtitle": str, "summary": str, "sections": [{"heading": str, "markdown": str}], "sources": [str]}
- summary: 4 sentences maximum. What is established (or “not established in the facts”). The frame in the measured outlets. The judgment, limited to that sample. Confidence and its reason.
- Exactly 4 sections, short titles, each one paragraph or three bullets:
  1. Frames — the measured frame and frames already written elsewhere. Do not present them as the country’s frame.
  2. Evidence — reported information, who opened and who repeated, then the hypothesis that could overturn the judgment.
  3. Effects — observed effects only if established; two or three political indicators.
  4. Lever — one sentence on the exposure and the outlet that sets the frame, then a Markdown table of the journalists present in the facts (intelligence_brief.influence_targets, else journalists, else the outlet's journalists): name, outlet, articles, accessibility, action, contact. A missing client file is not a reason to omit the table. If targets_basis is newsroom, say these are not bylines. If the list is empty: no byline and no file. Do not write that a list would be false.
- No Method section: the template adds it. No framework names in the body.
- If “story_summaries[].brief” is present, one bullet per story inside Frames, not an extra section.
- sources: internal references and web URLs used."""

WRITER_SYSTEM = WRITER_SYSTEM_FR


def _bid() -> str:
    return uuid.uuid4().hex[:10]


def journalist_rows_from_facts(facts: dict) -> list[dict]:
    """Cibles du sujet, sinon journalistes déjà collectés, sinon la rédaction du média."""
    brief = facts.get("intelligence_brief") or {}
    raw = list(brief.get("influence_targets") or [])
    if not raw:
        raw = list(facts.get("journalists") or [])
    if not raw:
        raw = list((facts.get("outlet") or {}).get("journalists") or [])
    if not raw:
        for rec in ((facts.get("client") or {}).get("recommendations") or [])[:12]:
            if isinstance(rec, dict) and rec.get("journalist"):
                raw.append(rec)
    return files.journalist_rows(raw)


def _is_lever(heading: str) -> bool:
    h = re.sub(r"\s+", "", (heading or "").casefold())
    return h in {"levier", "lever"}


def attach_journalists(doc: dict, rows: list[dict]) -> dict:
    """Ajoute le tableau au bloc Levier et retire la phrase qui refuse la liste."""
    if not rows:
        return doc
    table = files.journalist_markdown(rows)
    sections = doc.setdefault("sections", [])
    target = next((s for s in sections if _is_lever(s.get("heading") or "")), None)
    if target is None and sections:
        target = sections[-1]
    if target is None:
        sections.append({"heading": _tr("Levier", "Lever"), "markdown": table})
        return doc
    md = files.strip_list_refusal(target.get("markdown") or "")
    names = [r["name"] for r in rows if r.get("name")]
    if names and not any(n in md for n in names[:3]):
        md = (md.rstrip() + "\n\n" + table).strip()
    target["markdown"] = md
    return doc


def _complete_json_streamed(db: Session, model: str, system: str, user: str) -> dict:
    """Rédige le JSON du rapport via aleria-fast (sans raisonnement caché bloquant) avec repli sur model."""
    models_to_try = ["aleria-fast", model] if model == "aleria" else [model, "aleria-fast"]
    last_err = None
    for m_name in models_to_try:
        buf: list[str] = []
        usage = None
        try:
            stream = llm.get_client().chat.completions.create(
                model=m_name,
                temperature=0.3,
                max_tokens=4000,
                response_format={"type": "json_object"},
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user}],
                stream=True,
                stream_options={"include_usage": True},
                timeout=90,
            )
            for chunk in stream:
                u = getattr(chunk, "usage", None)
                if u:
                    usage = u
                choices = getattr(chunk, "choices", None) or []
                if choices and choices[0].delta and choices[0].delta.content:
                    buf.append(choices[0].delta.content)
            raw = "".join(buf).strip()
            if not raw:
                continue
            if usage:
                llm._track_usage(db, m_name, "report", usage)
            try:
                return json.loads(raw)
            except json.JSONDecodeError:
                import re as _re
                m = _re.search(r"\{.*\}", raw, _re.S)
                if m:
                    return json.loads(m.group(0))
        except Exception as e:  # noqa: BLE001
            last_err = e
            continue
    if last_err:
        raise last_err
    return {}


def compose(db: Session, kind: str, target: str | None, notes: str | None = None, weeks: int = 8, conversation_id: int | None = None, country: str | None = None) -> Report:
    """Collecte + rédaction → brouillon éditable. Pas de PDF."""
    if kind not in KINDS:
        raise ValueError("unknown report type" if get_locale() == "en" else "type de rapport inconnu")
    facts, charts, stats, label = _collect(db, kind, target, weeks, country)
    kind_row = _kinds()[kind]
    model = get_setting(db, "llm_agent_model") or "aleria"
    user = (
        f"TYPE: {kind_row[0]} — {kind_row[1]}\nTARGET: {label}\nNOTES: {notes or ('none' if get_locale() == 'en' else 'aucune')}\n\nFACTS:\n{json.dumps(facts, ensure_ascii=False, default=str)[:24000]}"
        if get_locale() == "en"
        else f"TYPE : {kind_row[0]} — {kind_row[1]}\nCIBLE : {label}\nCONSIGNES : {notes or 'aucune'}\n\nFAITS :\n{json.dumps(facts, ensure_ascii=False, default=str)[:24000]}"
    )
    writer = WRITER_SYSTEM_EN if get_locale() == "en" else WRITER_SYSTEM_FR
    doc = _complete_json_streamed(db, model, writer, user)
    attach_journalists(doc, journalist_rows_from_facts(facts))
    catalog = [{"widget": "chart", "title": t, "caption": cap, "svg": svg} for t, svg, cap in charts]
    blocks = blocks_from_doc(doc, stats, catalog, highlight=facts.get("brief"), story_briefs=facts.get("story_summaries"))
    now = datetime.utcnow()
    report = Report(
        kind=kind, target=label, country=(country or "").upper() or None, weeks=weeks, notes=notes,
        locale=get_locale(), title=doc.get("title") or f"{kind_row[0]} — {label}",
        subtitle=doc.get("subtitle") or "", status="draft",
        body={"kicker": f"Tacite · {kind_row[0]}", "blocks": blocks},
        catalog=catalog, conversation_id=conversation_id, created_at=now, updated_at=now,
    )
    db.add(report)
    db.commit()
    db.refresh(report)
    return report


def generate(db: Session, kind: str, target: str | None, notes: str | None = None, weeks: int = 8, conversation_id: int | None = None, country: str | None = None) -> Artifact:
    """Rédige un brouillon puis exporte le PDF (assistant, rétrocompat)."""
    report = compose(db, kind, target, notes=notes, weeks=weeks, conversation_id=conversation_id, country=country)
    return export_pdf(db, report)


def blocks_from_doc(doc: dict, stats, catalog: list, highlight: str | None = None, story_briefs: list | None = None) -> list[dict]:
    """Assemble les blocs initiaux : chiffres, essentiel, sections, widgets, sources."""
    blocks: list[dict] = []
    if stats:
        blocks.append({"id": _bid(), "type": "stats", "items": [{"label": l, "value": v, "sub": s} for l, v, s in stats]})
    if highlight:
        blocks.append({"id": _bid(), "type": "callout", "label": _tr("Lecture", "Read"), "markdown": highlight})
    elif doc.get("summary"):
        blocks.append({"id": _bid(), "type": "callout", "label": _tr("Lecture", "Read"), "markdown": doc["summary"]})
    kids = [s for s in (story_briefs or []) if (s.get("brief") or "").strip() and s.get("label")]
    if len(kids) > 1:
        blocks.append({
            "id": _bid(), "type": "stories",
            "heading": _tr("Affaires — mini briefs", "Stories — mini briefs"),
            "items": [{"label": s.get("label") or "", "brief": s["brief"]} for s in kids],
        })
    sections = doc.get("sections") or []
    chart_i = 0
    for i, s in enumerate(sections):
        blocks.append({"id": _bid(), "type": "section", "heading": s.get("heading") or "", "markdown": s.get("markdown") or ""})
        if chart_i < len(catalog) and (i == 0 or i % 2 == 1):
            w = catalog[chart_i]
            blocks.append({"id": _bid(), "type": "widget", "widget": w.get("widget") or "chart", "title": w.get("title") or "", "caption": w.get("caption") or "", "svg": w.get("svg") or ""})
            chart_i += 1
    while chart_i < len(catalog):
        w = catalog[chart_i]
        blocks.append({"id": _bid(), "type": "widget", "widget": w.get("widget") or "chart", "title": w.get("title") or "", "caption": w.get("caption") or "", "svg": w.get("svg") or ""})
        chart_i += 1
    if doc.get("sources"):
        blocks.append({"id": _bid(), "type": "sources", "items": [str(x) for x in doc["sources"][:20]]})
    blocks.append({"id": _bid(), "type": "method"})
    return blocks


def export_pdf(db: Session, report: Report) -> Artifact:
    html = render_blocks(report.title or "", report.subtitle or "", (report.body or {}).get("kicker") or "Tacite", (report.body or {}).get("blocks") or [])
    pdf = files.pdf_from_html(html)
    fname = f"{report.title or report.kind}".replace("/", "-")
    meta = {"report_kind": report.kind, "target": report.target, "report_id": report.id, "sections": [b.get("heading") for b in (report.body or {}).get("blocks") or [] if b.get("type") == "section"]}
    art = files.save_artifact(db, "pdf", fname, pdf, title=report.title, conversation_id=report.conversation_id, meta=meta)
    html_art = files.save_artifact(db, "html", fname, html.encode("utf-8"), title=(report.title or "") + " (HTML)", conversation_id=report.conversation_id, meta={"report_kind": report.kind, "pdf_id": art.id, "report_id": report.id})
    report.pdf_artifact_id = art.id
    report.html_artifact_id = html_art.id
    report.status = "exported"
    report.updated_at = datetime.utcnow()
    db.commit()
    return art


def public_report(r: Report) -> dict:
    from ..models import row_to_dict
    d = row_to_dict(r)
    d["edit_url"] = f"/reports/{r.id}"
    d["pdf_url"] = f"/api/artifacts/{r.pdf_artifact_id}/download" if r.pdf_artifact_id else None
    d["html_url"] = f"/api/artifacts/{r.html_artifact_id}/download" if r.html_artifact_id else None
    return d


def apply_patch(report: Report, data: dict) -> Report:
    from sqlalchemy.orm.attributes import flag_modified
    if "title" in data and data["title"] is not None:
        report.title = str(data["title"])
    if "subtitle" in data and data["subtitle"] is not None:
        report.subtitle = str(data["subtitle"])
    if "body" in data and isinstance(data["body"], dict):
        report.body = data["body"]
        flag_modified(report, "body")
    if "blocks" in data and isinstance(data["blocks"], list):
        body = dict(report.body or {})
        body["blocks"] = data["blocks"]
        report.body = body
        flag_modified(report, "body")
    report.updated_at = datetime.utcnow()
    report.status = "draft"
    return report


# ───────────────────────────────────────────── collecte

def _iso2(value: str | None) -> str | None:
    """Code ISO-2, ou nom anglais exact du jeu interne (ex. France → FR)."""
    if not value:
        return None
    v = value.strip()
    if geo.is_valid(v):
        return v.upper()
    needle = v.casefold()
    for c in geo.all_countries():
        if (c.get("name_en") or "").casefold() == needle:
            return c["code"]
    raise ValueError(f"pays inconnu : {value} (utilisez un code ISO-2, ex. FR)")


def _country_label(code: str) -> str:
    c = geo.country(code)
    return (c or {}).get("name_en") or code


def _collect(db: Session, kind: str, target: str | None, weeks: int, country: str | None = None):
    ctx: dict = {}
    charts: list[tuple[str, str, str]] = []  # (titre, svg, légende)
    stats: list[tuple[str, str, str]] = []   # (label, valeur, sous-titre)
    if kind == "outlet":
        o = T.get_outlet(db, {"outlet": target}, ctx)
        if o.get("error"):
            raise ValueError(o["error"])
        declared = {r["axis"]: r["declared"] for r in o["axes"]}
        measured = {r["axis"]: r["measured"] for r in o["axes"]}
        arts = T.list_articles(db, {"outlet": o["name"], "status": "analyzed", "limit": 25}, ctx)
        ll = T.leadlag(db, {"days": 30}, ctx)
        me = [r for r in ll["ranking"] if r["outlet_id"] == o["id"]]
        facts = {"outlet": o, "recent_articles": arts["articles"], "leadlag": me[0] if me else None, "pairs": [p for p in ll["pairs"] if p["leader"] == o["id"] or p["follower"] == o["id"]][:10]}
        charts.append((_tr("Ligne déclarée et ligne mesurée", "Declared and measured line"), files.svg_radar(declared, measured), _tr("pointillé = déclaré · bronze = mesuré", "dashed = declared · bronze = measured")))
        charts.append((_tr("Positions par axe", "Positions by axis"), files.svg_axis_bars(declared, measured), _tr("cercle creux = déclaré · point plein = mesuré", "hollow circle = declared · filled point = measured")))
        gaps = sorted(((axis_labels()[a], (measured.get(a) or 0) - (declared.get(a) or 0)) for a in AXES), key=lambda x: -abs(x[1]))[:6]
        charts.append((_tr("Écarts les plus forts (mesuré − déclaré)", "Strongest gaps (measured − declared)"), files.svg_hbars(gaps, 1.0, fmt="{:+.2f}"), ""))
        stats = [(_tr("Influence", "Influence"), f"{o.get('influence') or 0:.0f}", f"{_tr('rang', 'rank')} {o.get('influence_rank') or '—'}"), (_tr("Articles / semaine", "Articles / week"), str(o.get("articles_week") or 0), f"{_tr('confiance', 'confidence')} {o.get('confidence', '—')}"),
                 (_tr("Écart max.", "Max. gap"), f"{(o.get('max_gap') or {}).get('value', 0):+.2f}", (o.get("max_gap") or {}).get("label") or (o.get("max_gap") or {}).get("axis", "")), (_tr("Journalistes", "Journalists"), str(len(o.get("journalists") or [])), _tr("documentés", "documented"))]
        return facts, charts, stats, o["name"]
    if kind == "journalist":
        j = T.get_journalist(db, {"journalist": target}, ctx)
        if j.get("error"):
            raise ValueError(j["error"])
        facts = {"journalist": j}
        if j.get("measured_framing"):
            p = T.get_outlet(db, {"outlet": str(j["outlet_id"])}, ctx)
            outlet_measured = {r["axis"]: r["measured"] for r in p["axes"]}
            charts.append((_tr("Cadrage du journaliste (bronze) vs ligne mesurée de son média (pointillé)", "Journalist framing (bronze) vs outlet measured line (dashed)"), files.svg_radar(outlet_measured, j["measured_framing"]), ""))
            facts["outlet_measured"] = outlet_measured
        stats = [(_tr("Accessibilité", "Accessibility"), f"{j.get('accessibility') or 0:.0f}", "0–100"), (_tr("Articles analysés", "Articles analysed"), str(j.get("n_analyzed") or 0), ""),
                 (_tr("Divergence", "Divergence"), f"{((j.get('divergence_axis') or {}).get('delta') or 0):+.2f}", (j.get("divergence_axis") or {}).get("axis", "—")), (_tr("Ton", "Tone"), (j.get("profile") or {}).get("tone") or "—", "")]
        return facts, charts, stats, f"{j['name']} ({j.get('outlet')})"
    if kind == "client":
        c = T.get_client(db, {"client": target}, ctx)
        if c.get("error"):
            raise ValueError(c["error"])
        dash = T.dashboard(db, {}, ctx)
        facts = {"client": c, "landscape_movements": dash.get("movements"), "week_topics": dash.get("topics")}
        sm = sorted(c["stance_map"], key=lambda p: p["stance"])
        charts.append((_tr("Position vis-à-vis du client (− hostile · + favorable), médias les plus influents", "Stance toward the client (− hostile · + favourable), most influential outlets"), files.svg_hbars([(p["outlet_name"], p["stance"]) for p in sorted(c["stance_map"], key=lambda p: -p["influence"])[:16]], 1.0, fmt="{:+.2f}"), ""))
        hostile = sum(1 for p in sm if p["stance"] < -0.15)
        fav = sum(1 for p in sm if p["stance"] > 0.15)
        stats = [(_tr("Médias hostiles", "Hostile outlets"), str(hostile), "< −0.15"), (_tr("Favorables", "Favourable"), str(fav), "> +0.15"), (_tr("Recommandations", "Recommendations"), str(len(c["recommendations"])), f"{sum(1 for r in c['recommendations'] if r['status'] == 'proposed')} {_tr('proposées', 'proposed')}"),
                 (_tr("Actions évaluées", "Actions scored"), str(len(c["history"])), "")]
        return facts, charts, stats, c["name"]
    if kind in ("landscape", "country"):
        code = _iso2((target or country) if kind == "country" else country)
        if kind == "country" and not code:
            raise ValueError(_tr("pays requis (code ISO-2, ex. FR)", "country required (ISO-2 code, e.g. FR)"))
        return _panorama(db, weeks, code, charts, stats, ctx)
    if kind == "theme":
        return _theme_brief(db, target, weeks, country, charts, stats, ctx)
    # topic
    if not target:
        raise ValueError("sujet requis")
    code = _iso2(country)
    q = {"query": target, "days": 60, "limit": 40}
    if code:
        q["country"] = code
    arts = T.search_articles(db, q, ctx)
    gn_args = {"query": target, "limit": 12}
    if code:
        gn_args["country"] = code
    gn = T.google_news(db, gn_args, ctx)
    ents = T.entities(db, {"days": 60, "name": target.split()[0] if target else None, "limit": 10}, ctx)
    by_outlet: dict[str, list] = {}
    for a in arts["articles"]:
        by_outlet.setdefault(a["outlet"], []).append(a)
    per_outlet = []
    for name, lst in by_outlet.items():
        fr = {ax: round(sum(float(a["framing"].get(ax, 0) or 0) for a in lst if a["framing"].get(ax)) / max(1, sum(1 for a in lst if a["framing"].get(ax))), 2) for ax in AXES}
        per_outlet.append({"outlet": name, "articles": len(lst), "framing": fr, "tones": sorted({a["tone"] for a in lst if a.get("tone")})})
    per_outlet.sort(key=lambda x: -x["articles"])
    tb = T.topic_brief(db, {"topic": target, "days": 60, "country": code}, ctx)
    facts = {"topic": target, "country": code, "country_label": _country_label(code) if code else None,
             "targets_basis": tb.get("targets_basis"),
             "journalists": tb.get("influence_targets") or [],
             "intelligence_brief": tb,
             "articles": arts["articles"][:25], "coverage_by_outlet": per_outlet, "google_news": gn.get("results"), "entities": ents.get("entities")}
    from . import topics as topics_svc
    members = [{"title": a.get("title"), "outlet": a.get("outlet"), "date": a.get("published_at"), "tone": a.get("tone")} for a in arts["articles"]]
    first = min(arts["articles"], key=lambda a: a.get("published_at") or "9999") if arts["articles"] else {}
    facts["brief"] = topics_svc.brief_coverage(db, {
        "label": target,
        "members": members,
        "lead": {"outlet": first.get("outlet"), "date": first.get("published_at"), "title": first.get("title")} if first else {},
        "entities": [{"name": e.get("name") or e.get("entity")} for e in (ents.get("entities") or [])],
        "opinion": topics_svc._opinion_from_counts(
            Counter(a.get("tone") for a in arts["articles"] if a.get("tone")),
            Counter(a.get("angle") for a in arts["articles"] if a.get("angle")),
            len(arts["articles"]),
        ),
    })
    charts.append((_tr("Volume de couverture par média (articles proches du sujet, 60 jours)", "Coverage volume by outlet (articles close to the topic, 60 days)"), files.svg_hbars([(p["outlet"], p["articles"]) for p in per_outlet[:14]]), ""))
    if per_outlet:
        spread_axis = max(AXES, key=lambda ax: (max(p["framing"][ax] for p in per_outlet) - min(p["framing"][ax] for p in per_outlet)))
        neg, pos = axis_poles_map()[spread_axis]
        charts.append((f"{_tr('Cadrage du sujet', 'Topic framing')} — {axis_labels()[spread_axis]} ({neg} − ↔ {pos} +)", files.svg_hbars(sorted(((p["outlet"], p["framing"][spread_axis]) for p in per_outlet[:14]), key=lambda x: x[1]), 1.0, fmt="{:+.2f}"), _tr("moyenne des articles proches du sujet", "mean of articles close to the topic")))
    stats = [(_tr("Articles proches", "Close articles"), str(len(arts["articles"])), _tr("60 jours", "60 days")), (_tr("Médias", "Outlets"), str(len(per_outlet)), _country_label(code) if code else ""),
             (_tr("Résultats web", "Web results"), str(len(gn.get("results") or [])), "Google News"), (_tr("Entités", "Entities"), str(len(ents.get("entities") or [])), "")]
    label = f"{target} — {_country_label(code)}" if code else target
    return facts, charts, stats, label


def _theme_brief(db: Session, target: str | None, weeks: int, country: str | None, charts, stats, ctx: dict):
    from . import topics as topics_svc
    if not target:
        raise ValueError(_tr("famille requise", "family required"))
    code = _iso2(country)
    days = max(1, min(int(weeks or 1) * 7, 90))
    d = topics_svc.agenda(db, days=days, country=code, briefs=True)
    needle = target.strip().casefold()
    theme = None
    for th in d.get("themes") or []:
        labels = [th.get("label"), *(th.get("aliases") or [])]
        if any((lab or "").casefold() == needle for lab in labels):
            theme = th
            break
    if not theme:
        # La famille a pu changer de nom : on retombe sur une note thématique.
        return _collect(db, "topic", target, weeks, country)
    stories = [c for c in (d.get("clusters") or []) if c.get("id") in set(theme.get("story_ids") or [])]
    gn_args = {"query": theme["label"], "limit": 12}
    if code:
        gn_args["country"] = code
    gn = T.google_news(db, gn_args, ctx)
    opinion = theme.get("opinion") or {}
    per_outlet = []
    for o in (theme.get("outlets_detail") or [])[:16]:
        row = next((x for x in (opinion.get("by_outlet") or []) if x.get("id") == o.get("id")), None)
        per_outlet.append({
            "outlet": o.get("name"), "articles": o.get("n"),
            "tone": (row or {}).get("tone"),
        })
    facts = {
        "family": theme["label"], "aliases": theme.get("aliases") or [],
        "brief": theme.get("brief") or "",
        "country": code, "country_label": _country_label(code) if code else None,
        "days": days, "articles": theme.get("articles"), "stories": theme.get("stories"),
        "story_summaries": theme.get("story_summaries") or [{"label": s.get("label"), "articles": s.get("articles"), "outlets": s.get("outlets"), "heat": s.get("heat"), "polarization": s.get("polarization")} for s in stories],
        "opinion": opinion, "spread": theme.get("spread"), "polarization": theme.get("polarization"),
        "heat": theme.get("heat"), "lead": theme.get("lead"),
        "entities": theme.get("entities"), "coverage_by_outlet": per_outlet,
        "journalists": (theme.get("journalists_detail") or [])[:12],
        "recent_articles": (theme.get("members") or [])[:25],
        "google_news": gn.get("results"),
    }
    charts.append((_tr("Volume de couverture par média (famille, fenêtre courante)", "Coverage volume by outlet (family, current window)"), files.svg_hbars([(p["outlet"], p["articles"]) for p in per_outlet if p.get("outlet")]), ""))
    story_bars = [(s.get("label") or "—", s.get("articles") or 0) for s in (theme.get("story_summaries") or stories)][:12]
    if len(story_bars) >= 2:
        charts.append((_tr("Affaires de la famille (articles)", "Stories in the family (articles)"), files.svg_hbars(story_bars), ""))
    stats = [
        (_tr("Articles", "Articles"), str(theme.get("articles") or 0), f"{days} {_tr('jours', 'days')}"),
        (_tr("Affaires", "Stories"), str(theme.get("stories") or len(stories)), ""),
        (_tr("Médias", "Outlets"), str(theme.get("outlets") or 0), _country_label(code) if code else ""),
        (_tr("Polarisation", "Polarisation"), f"{(theme.get('polarization') or 0):.2f}", (theme.get("spread") or {}).get("label") or _tr("consensus", "consensus")),
    ]
    label = f"{theme['label']} — {_country_label(code)}" if code else theme["label"]
    return facts, charts, stats, label


def _panorama(db: Session, weeks: int, country: str | None, charts, stats, ctx: dict):
    land_args: dict = {"weeks": weeks}
    if country:
        land_args["country"] = country
    land = T.landscape(db, land_args, ctx)
    listed = T.list_outlets(db, {"country": country} if country else {}, ctx)
    if country and not listed["count"]:
        raise ValueError(_tr(f"aucun média suivi dans {_country_label(country)} ({country})", f"no outlet followed in {_country_label(country)} ({country})"))
    ids = {o["id"] for o in listed["outlets"]} if country else set()
    ll = T.leadlag(db, {"days": 30}, ctx)
    ranking = [r for r in ll["ranking"] if not ids or r.get("outlet_id") in ids]
    pairs = [p for p in ll["pairs"] if not ids or p.get("leader") in ids or p.get("follower") in ids]
    ents = T.entities(db, {"days": 30, "limit": 80}, ctx)
    ents_f = []
    for e in ents.get("entities") or []:
        cells = e.get("cells") or []
        if ids:
            cells = [c for c in cells if c.get("outlet_id") in ids]
            if not cells:
                continue
            e = {**e, "cells": cells[:8], "outlets": len(cells), "mentions": sum(c.get("mentions") or 0 for c in cells)}
        else:
            e = {**e, "cells": cells[:8]}
        ents_f.append(e)
        if len(ents_f) >= 15:
            break
    tp_args: dict = {"days": 14}
    if country:
        tp_args["country"] = country
    tp = T.topics(db, tp_args, ctx)
    world_row, flows, journalists = None, None, None
    if country:
        w = T.world(db, {"days": 30}, ctx)
        world_row = next((c for c in (w.get("countries") or []) if (c.get("code") or "").upper() == country), None)
        flows = [f for f in (w.get("flows") or []) if (f.get("source") or "").upper() == country or (f.get("target") or "").upper() == country][:12]
        rows = (
            db.query(Journalist, Outlet.name)
            .join(Outlet, Outlet.id == Journalist.outlet_id)
            .filter(Outlet.country == country)
            .order_by(Journalist.accessibility_score.desc())
            .limit(20).all()
        )
        journalists = [{"id": j.id, "name": j.name, "outlet": oname, "role": j.role, "beat": getattr(j, "beat", None),
                        "accessibility": round(j.accessibility_score or 0)} for j, oname in rows]
    facts = {
        "country": country, "country_label": _country_label(country) if country else None,
        "landscape": land, "followed_outlets": listed["outlets"][:40] if country else None,
        "leadlag": {"events": ll["events"], "ranking": ranking[:12], "pairs": pairs[:10]},
        "entities": ents_f, "topics": tp, "country_stats": world_row,
        "citation_flows": flows, "journalists": journalists,
    }
    outs = [o for o in land["outlets"] if o.get("confidence") != "low"] or list(land["outlets"])
    for a in [k for k, v in axis_labels().items() if v in (land.get("most_dividing_axes") or [])[:3]]:
        items = sorted(((o["name"], o["measured"].get(a) or 0) for o in outs), key=lambda x: x[1])
        if not items:
            continue
        neg, pos = axis_poles_map()[a]
        charts.append((f"{axis_labels()[a]} — {neg} (−) ↔ {pos} (+)", files.svg_hbars(items, 1.0, fmt="{:+.2f}"), _tr("ligne mesurée, médias documentés", "measured line, documented outlets")))
    if country and listed["outlets"]:
        charts.append((_tr("Influence des médias suivis", "Influence of followed outlets"), files.svg_hbars([(o["name"], o.get("influence") or 0) for o in listed["outlets"][:16]]), "0–100"))
    clivant = (land.get("most_dividing_axes") or ["—"])[0]
    if country:
        stats.extend([
            (_tr("Médias suivis", "Outlets followed"), str(listed["count"]), _country_label(country)),
            (_tr("Documentés", "Documented"), str(len(outs)), _tr("≥ 10 articles", "≥ 10 articles")),
            (_tr("Axe le plus clivant", "Most dividing axis"), clivant, ""),
            (_tr("Journalistes", "Journalists"), str((world_row or {}).get("journalists") or len(journalists or [])), ""),
        ])
        label = f"{_country_label(country)} · {weeks} {_tr('semaines', 'weeks')}"
    else:
        stats.extend([
            (_tr("Médias documentés", "Documented outlets"), str(len(outs)), _tr("≥ 10 articles", "≥ 10 articles")),
            (_tr("Axe le plus clivant", "Most dividing axis"), clivant, ""),
            (_tr("Événements multi-médias", "Multi-outlet events"), str(ll["events"]), _tr("30 jours", "30 days")),
            (_tr("Blocs", "Blocs"), str(len(land.get("clusters") or [])), ""),
        ])
        label = f"{weeks} {_tr('semaines', 'weeks')}"
    return facts, charts, stats, label


# ───────────────────────────────────────────── rendu


def render_blocks(title: str, subtitle: str, kicker: str, blocks: list) -> str:
    esc = files._esc
    body = []
    for b in blocks or []:
        typ = b.get("type")
        if typ == "stats" and b.get("items"):
            body.append('<div class="stats">' + "".join(
                f'<div class="stat"><div class="lbl">{esc(i.get("label"))}</div><div class="val">{esc(i.get("value"))}</div><p class="sub">{esc(i.get("sub"))}</p></div>'
                for i in b["items"]
            ) + "</div>")
        elif typ == "callout":
            md = b.get("markdown") or ""
            inner = files.md_to_html_fragment(md) if md else ""
            body.append(f'<div class="callout"><div class="lbl">{esc(b.get("label") or "")}</div>{inner}</div>')
        elif typ == "stories" and b.get("items"):
            items = "".join(
                f'<li><strong>{esc(s.get("label") or "")}</strong><p>{esc(s.get("brief") or "")}</p></li>'
                for s in b["items"]
            )
            body.append(f'<h2>{esc(b.get("heading") or "")}</h2><ul class="sources">{items}</ul>')
        elif typ == "section":
            body.append(f"<h2>{esc(b.get('heading') or '')}</h2>")
            body.append(files.md_to_html_fragment(b.get("markdown") or ""))
        elif typ == "widget":
            t, svg, cap = b.get("title") or "", b.get("svg") or "", b.get("caption") or ""
            if svg:
                body.append(f'<div class="chart"><h3>{esc(t)}</h3>{svg}{f"<div class=cap>{esc(cap)}</div>" if cap else ""}</div>')
        elif typ == "sources" and b.get("items"):
            body.append(f"<h2>{esc(_tr('Sources', 'Sources'))}</h2><ul class=\"sources\">" + "".join(f"<li>{esc(x)}</li>" for x in b["items"]) + "</ul>")
        elif typ == "method":
            body.append(
                f'<div class="callout"><div class="lbl">{esc(_tr("Méthode", "Method"))}</div>'
                + _tr(
                    "Événement et cadrage sont tenus à part. Confiance selon la solidité des sources, pas selon le ton. Ligne déclarée : orientation annoncée, fixée. Ligne mesurée : moyenne des cadrages sur la période. Écart notable au-delà de 0,30. Influence 0–100.",
                    "Event and frame are kept apart. Confidence follows the strength of the sources, not the tone. Declared line: announced orientation, fixed. Measured line: mean framing over the period. Gap notable beyond 0.30. Influence 0–100.",
                )
                + "</div>"
            )
    date_fmt = "%d/%m/%Y" if get_locale() == "fr" else "%Y-%m-%d"
    return files.html_document(title, "\n".join(body), kicker=kicker or "Tacite", subtitle=subtitle or "", date_str=datetime.now().strftime(date_fmt))


def _render(doc: dict, kind: str, label: str, stats, charts, highlight: str | None = None, story_briefs: list | None = None) -> str:
    catalog = [{"widget": "chart", "title": t, "caption": cap, "svg": svg} for t, svg, cap in charts]
    blocks = blocks_from_doc(doc, stats, catalog, highlight=highlight, story_briefs=story_briefs)
    kind_row = _kinds()[kind]
    return render_blocks(doc.get("title") or f"{kind_row[0]} — {label}", doc.get("subtitle") or "", f"Tacite · {kind_row[0]}", blocks)
