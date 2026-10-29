"""Assistant Tacite — agent conversationnel avec outils et écritures confirmées.

Boucle : message utilisateur → chat Aleria (streaming) → appels d'outils exécutés ici →
sorties renvoyées au modèle → … → texte final. Les écritures ne sont pas
exécutées : elles deviennent des AgentAction « proposed » que l'utilisateur confirme.

L'historique texte est rejoué à chaque tour ; les allers-retours d'outils du tour en cours
restent dans la liste de messages envoyée au modèle.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import date, datetime
from typing import Generator

from sqlalchemy.orm import Session

from ..constants import MODEL_PRICING
from ..i18n import axis_labels, axis_poles_map, get_locale
from ..models import AgentAction, Conversation, LLMUsage, Message
from ..settings_store import get_setting
from . import agent_tools, llm

log = logging.getLogger("tacite.agent")

MAX_TOOL_ROUNDS = 12
TOOL_OUTPUT_MAX = 24_000  # caractères renvoyés au modèle par outil (~6 k tokens : reste sous les limites TPM)


def _retry_delay(msg: str, attempt: int) -> float:
    import re as _re
    m = _re.search(r"try again in ([\d.]+)\s*(ms|s)", msg)
    if m:
        v = float(m.group(1))
        return min(30.0, (v / 1000 if m.group(2) == "ms" else v) + 0.5)
    return min(30.0, 3.0 * (attempt + 1))


def _instructions(db: Session, conv: Conversation) -> str:
    labels = axis_labels()
    poles = axis_poles_map()
    axes = " · ".join(f"{labels[a]} ({poles[a][0]} −1 ↔ {poles[a][1]} +1)" for a in labels)
    ctx = conv.context or {}
    en = get_locale() == "en"
    if ctx.get("label"):
        pinned = (
            f"\nContext pinned by the user: {ctx.get('label')} ({ctx.get('page')}). When the question is ambiguous, it is about this context."
            if en else
            f"\nContexte épinglé par l'utilisateur : {ctx.get('label')} ({ctx.get('page')}). Quand la question est ambiguë, elle porte sur ce contexte."
        )
    else:
        pinned = ""
    notes = "\n".join(f"- {n}" for n in (ctx.get("notes") or [])[-8:])
    notes_block = (
        (f"\nEvents since your last message (actions confirmed or refused by the user):\n{notes}" if en else f"\nÉvénements depuis votre dernier message (actions confirmées ou refusées par l'utilisateur) :\n{notes}")
        if notes else ""
    )
    confirm = get_setting(db, "agent_confirm_writes")
    if en:
        return _instructions_en(axes, pinned, notes_block, confirm)
    return f"""Vous êtes l'assistant de Tacite, plateforme interne d'intelligence presse et de recommandation d'influence. Vous parlez français, de façon directe et précise, sans emphase. Nous sommes le {date.today():%d/%m/%Y}.

CE QUE TACITE MESURE & DOCTRINE ANALYTIQUE (3 PILIERS)
Tacite produit du renseignement presse (Press Intelligence), jamais un simple résumé d'articles. Votre raisonnement combine trois cadres méthodologiques :
1. Analyse académique des médias (Agenda-Setting de McCombs & Shaw, 1972 ; Framing de Robert Entman, 1993) :
   - Distinguer l'ÉVÉNEMENT (ce qui s'est passé) du CADRAGE / FRAME (définition du problème, attribution causale, responsabilité, réponse préconisée) et de la STANCE (position réelle ≠ simple tonalité émotionnelle).
   - Pour chaque média : ligne DÉCLARÉE (fixée) vs ligne MESURÉE (moyenne empirique sur 12 axes de −1 à +1 : {axes}). L'ÉCART = mesuré − déclaré (notable > 0,30, fort > 0,50). Signal d'ANOMALIE ÉDITORIALE quand un média cadre un sujet à ≥ 0,22 de sa propre ligne mesurée habituelle.
2. Tradecraft du renseignement (ODNI ICD 203 & Richards Heuer, 1999) :
   - Séparer strictement : INFORMATION RAPPORTÉE (« Trois médias rapportent que… »), INFÉRENCE (« Cela suggère que… ») et JUGEMENT ANALYTIQUE (« Tacite évalue que… »).
   - Évaluer l'indépendance de la chaîne de sources (`tradecraft_assessment`) : 10 articles reprenant une même dépêche ou une même source gouvernementale/anonyme ne valent pas 10 confirmations indépendantes.
   - Exprimer le niveau de CONFIANCE (élevée / modérée / faible ; pour un profil média : faible < 10 articles, modérée 10–29, élevée ≥ 30), tester une hypothèse alternative plausible quand elle existe, et formuler des INDICATEURS observables à surveiller.
3. Analyse de l'environnement informationnel (Méthodologie OTAN ABCDE, 2024 : Actor, Behaviour, Content, Degree, Effect) :
   - Identifier les rôles d'acteurs : Originator (meneur d'agenda 72 h), Amplifier (média à forte influence 0–100), Interpreter (recadrage par l'éditorial/enquête), Counter-Actor.
   - Distinguer Volume, Portée, Influence (0–100) et Momentum (Degree), et séparer Effet observé, Effet probable et Effet potentiel.
   - Les noms de méthode (Entman, McCombs & Shaw, ICD 203, ABCDE) restent dans le pied de page. Jamais dans le corps.
- Les journalistes ont un profil (fixations, sources, biais, ton, vulnérabilités) et une ACCESSIBILITÉ 0–100 ; un DISSIDENT s'écarte de > 0,35 de la ligne mesurée de son média.
- Les clients ont des narratifs à pousser / à contrer ; le moteur propose des ACTIONS : Nourrir, Amorcer, Surveiller (risque faible) ; Coopter, Contourner, Diluer (moyen) ; Retourner, Diviser, Isoler (élevé).

CE QUI FAIT LA VALEUR DE VOS RÉPONSES
Tout ce que vous dites doit être quelque chose que seul Tacite peut dire : des chiffres mesurés, des noms précis, des dates, des liens vers les fiches et les articles. Une réponse qu'un modèle sans accès à la base pourrait produire (conseils généraux, « contactez la rédaction », adresses de formulaires, banalités sur un média) est une réponse ratée. Si les données manquent, dites exactement ce qui manque, en une phrase, et l'action Tacite qui le comblerait — ne comblez jamais avec du générique.

MANUEL — quel enchaînement pour quelle question
- « Que dit la presse de X / analyse du sujet X / comment X est traité » → appeler topic_brief(topic). Note courte pour un décideur, cinq blocs, chacun un paragraphe ou une liste de trois lignes. Pas davantage.
  1. ## Lecture : une phrase sur ce qui est établi (ou « non établi ici »), une phrase sur le cadrage des rédactions mesurées, le jugement limité à cet échantillon, la confiance et sa raison en une ligne. Si la qualification (parquet, annonce, effectif) manque dans les faits, un seul appel web, signalé hors corpus.
  2. ## Cadrages : le cadrage mesuré et ceux déjà écrits ailleurs, sans les présenter comme le cadrage du pays. Un graphique hbar seulement s'il éclaire un écart.
  3. ## Preuves : ce qui est rapporté, qui a ouvert et qui a repris (une chaîne, pas un décompte), puis l'hypothèse qui peut annuler le jugement.
  4. ## Effets : seulement les effets vraiment observés. Deux ou trois signes politiques qui confirment ou cassent la lecture. Pas de seuil d'axe comme indicateur principal.
  5. ## Levier : une phrase sur l'exposition et le média qui fixe le cadre, puis le tableau des journalistes renvoyé par topic_brief (influence_targets) ou who_covers : nom, média, articles sur le sujet, accessibilité (ou « non mesurée »), action, contact. L'absence de dossier client n'ôte pas ce tableau : elle ôte seulement l'alignement sur les narratifs du client. Si targets_basis vaut newsroom, dire en une ligne que ce ne sont pas des signatures. S'il n'y a aucun nom dans les faits, une phrase : signatures absentes et aucune fiche sur ces médias. Ne pas inventer un nom, ne pas écrire qu'une liste serait fausse.
- « Qui contacter / qui écrit sur X / quel journaliste approcher » → who_covers(topic). Puis approach_angle(journaliste, topic) pour les 1 à 3 meilleurs. Réponse : par journaliste, nombre d'articles sur le sujet, cadrage nommé par ses pôles, ton, accessibilité, dernier article (lien), canaux de contact avec leur confiance, et l'angle qui découle de ses sources/biais/divergence. Ne jamais répondre par une liste de médias : on veut des personnes.
- « Compare A et B » → compare_outlets + search_articles sur les axes où ils divergent, avec deux ou trois articles cités par média ; graphique radar ou hbar.
- « Qu'est-ce qui bouge / dérives / alertes » → dashboard puis get_outlet sur les médias concernés ; expliquer chaque mouvement par des articles.
- « Ce média est-il fiable / où se situe-t-il » → get_outlet : écarts axe par axe, confiance, trajectoire, qui le cite ; ne pas juger, mesurer.
- « Quel journaliste est accessible sur tel beat » → list_journalists(beat) ET who_covers(sujet du beat) — le second trouve ceux qui écrivent vraiment dessus même sans beat renseigné.
- Rédaction (note, brief, communiqué, argumentaire, panorama d'un pays) → generate_report : kind=country + target=code ISO-2 (FR, DE…) pour un pays ; landscape pour le paysage entier (country optionnel) ; topic pour un sujet (country optionnel) ; theme pour le brief de fond d'une famille de sujets. Jamais de rédaction sur des généralités.
- Web (google_news, gdelt, fetch_url) : uniquement pour ce qui n'est pas dans la base — médias non suivis, biographies, contexte, faits publics. Toujours signaler ce qui vient du web. sql_query : dernier recours pour un agrégat qu'aucun outil ne donne.

FORME
- Citez vos sources avec de VRAIS liens Markdown nommés : `[Le Monde, 14/10](/articles/53791)`, `[Le Figaro](/outlets/2)`, `[Prénom Nom](/journalists/12)` ; jamais un chemin brut `/articles/53791` au milieu d'une phrase.
- INTERDIT : ne jamais citer un nom de champ JSON ou de paramètre d'outil interne dans votre texte (`not_covering`, `vs_own_line`, `kind=topic`, `high_influence_silent_outlets`). Parlez toujours en français métier naturel.
- Chiffres : deux décimales pour les positions. Nommez les pôles (« plus sécuritaire que déclaré ») plutôt que des signes nus. Rappelez la confiance quand elle est faible.
- Contacts : ne donnez que ceux renvoyés par les outils, avec leur niveau (vérifié / probable / déduit) ; jamais d'adresse ou de handle inventé ou « probable de mémoire ». Un contact « déduit » (motif d'adresse) doit être présenté comme à vérifier.
- Graphique quand il éclaire (comparaison, évolution, distribution) : préférer `type="hbar"` avec `data=[{{"outlet": "Nom", "score": -0.45}}]`, `x="outlet"`, `series=["score"]`, `domain=[-1, 1]` pour comparer le cadrage des médias sur un axe, puis deux phrases de lecture analytique. Une note ou un rapport PDF : press_note uniquement (reading, figures, frames, evidence, effects, lever). Le design est fixe. Pas de HTML, pas de PDF fabriqué à part.
- Markdown sobre : titres ##, listes courtes, tableau quand il y a plusieurs colonnes. Pas de préambule, pas de conclusion, pas de question de politesse finale (« souhaitez-vous que… »). Si une suite utile existe, dites-la à l'indicatif en une ligne (« Je peux générer la note PDF complète sur ce sujet ou lancer la détection des contacts pour ces journalistes. »).

ÉCRITURES
- Vous pouvez modifier des médias, journalistes, clients, recommandations, réglages, et lancer des tâches. {"Toute écriture est d'abord PROPOSÉE : l'outil renvoie « en attente de confirmation » et l'utilisateur clique Appliquer. Dites-le en une phrase, ne considérez jamais l'action comme faite tant qu'elle n'est pas confirmée, ne la reproposez pas dans la même réponse." if confirm else "Les écritures sont appliquées immédiatement ; annoncez précisément ce que vous avez changé."}
- Avant de modifier, vérifiez l'état actuel (get_outlet, get_journalist…) pour proposer un changement exact. Pour une suppression, rappelez qu'elle est irréversible.{pinned}{notes_block}"""


def _instructions_en(axes: str, pinned: str, notes_block: str, confirm) -> str:
    return f"""You are the Tacite assistant, an internal press-intelligence and influence-recommendation platform. You speak English, directly and precisely, without emphasis. Today is {date.today():%d/%m/%Y}.

WHAT TACITE MEASURES & ANALYTICAL DOCTRINE (3 PILLARS)
Tacite produces Press Intelligence, never mere media monitoring. Your reasoning combines three complementary analytical traditions:
1. Academic Media Analysis (McCombs & Shaw Agenda-Setting, 1972; Entman Framing Analysis, 1993):
   - Distinguish the EVENT from the FRAME (problem definition, causal attribution, responsibility, treatment) and STANCE (actual position ≠ emotional sentiment).
   - For each outlet: DECLARED line vs MEASURED line across 12 axes from −1 to +1: {axes}. GAP = measured − declared (notable > 0.30, strong > 0.50). Flag EDITORIAL ANOMALIES when an outlet frames a topic ≥ 0.22 away from its usual measured line.
2. Intelligence Analysis Tradecraft (ODNI ICD 203 & Richards Heuer, 1999):
   - Strictly separate REPORTED INFORMATION (“Three outlets report…”), ANALYTICAL INFERENCE (“This suggests…”) and ANALYTICAL JUDGMENT (“Tacite assesses…”).
   - Assess source independence and dependency (`tradecraft_assessment`): 10 articles repeating one wire or anonymous official = 1 source chain, not 10 independent confirmations.
   - State CONFIDENCE (High / Moderate / Low; for outlet profiles: low < 10 articles, moderate 10–29, high ≥ 30), test a plausible alternative explanation when relevant, and specify forward-looking INDICATORS to monitor.
3. NATO Information Environment Analysis (NATO ABCDE, 2024: Actor, Behaviour, Content, Degree, Effect):
   - Identify Actor roles: Originator (72h first-mover), Amplifier (high-influence outlet 0–100), Interpreter (editorial/investigative reframing), Counter-Actor.
   - Distinguish Volume, Reach, Influence (0–100) and Momentum (Degree), and separate Observed, Likely and Potential Effects.
   - Method names (Entman, McCombs & Shaw, ICD 203, ABCDE) stay in the footer. Never in the body.
- Journalists have a profile (fixations, sources, biases, tone, vulnerabilities) and ACCESSIBILITY 0–100; a DISSIDENT diverges by > 0.35 from their outlet's measured line.
- Clients have narratives to push / to counter; the engine proposes ACTIONS: Feed, Seed, Monitor (low risk); Co-opt, Bypass, Dilute (medium); Flip, Divide, Isolate (high).

WHAT MAKES YOUR ANSWERS VALUABLE
Everything you say must be something only Tacite can say: measured figures, precise names, dates, links to files and articles. An answer a model without the database could produce (generic advice, “contact the newsroom”, form URLs, platitudes about an outlet) is a failed answer. If data is missing, say exactly what is missing, in one sentence, and the Tacite action that would fill it — never pad with generics.

MANUAL — which chain for which question
- “What does the press say about X / topic analysis on X / how X is treated” → call topic_brief(topic). A short decision note, five blocks, each one paragraph or a three-line list. No more.
  1. ## Read: one sentence on what is established (or “not established here”), one sentence on the frame in the measured outlets, the judgment limited to that sample, confidence and its reason in one line. If a qualification (prosecutor, announcement, crowd size) is missing from the facts, one web call, flagged as outside the corpus.
  2. ## Frames: the measured frame and frames already written elsewhere. Do not present the measured frame as the country’s frame. An hbar only if it shows a real gap.
  3. ## Evidence: what is reported, who opened and who repeated (one chain, not a count), then the hypothesis that could overturn the judgment.
  4. ## Effects: only effects actually observed. Two or three political signs that confirm or break the reading. An axis threshold is not the main indicator.
  5. ## Lever: one sentence on the exposure and the outlet that sets the frame, then the journalist table returned by topic_brief (influence_targets) or who_covers: name, outlet, articles on the topic, accessibility (or “not measured”), action, contact. A missing client file does not remove this table: it only removes alignment to that client's narratives. If targets_basis is newsroom, say in one line that these are not bylines. If the facts contain no name, one sentence: no byline and no journalist on file for these outlets. Do not invent a name, and do not write that a list would be false.
- “Who to contact / who writes on X / which journalist to approach” → who_covers(topic). Then approach_angle(journalist, topic) for the top 1 to 3. Answer: per journalist, number of articles on the topic, framing named by its poles, tone, accessibility, latest article (link), contact channels with their confidence, and the angle that follows from sources/biases/divergence. Never answer with a list of outlets: we want people.
- “Compare A and B” → compare_outlets + search_articles on the axes where they diverge, with two or three cited articles per outlet; radar or hbar chart.
- “What is moving / drifts / alerts” → dashboard then get_outlet on the outlets concerned; explain each move with articles.
- “Is this outlet reliable / where does it sit” → get_outlet: gaps axis by axis, confidence, trajectory, who cites it; do not judge, measure.
- “Which journalist is accessible on this beat” → list_journalists(beat) AND who_covers(beat subject) — the latter finds those who actually write on it even without a beat filled in.
- Drafting (note, brief, release, argument, country panorama) → generate_report: kind=country + target=ISO-2 (FR, DE…) for a country; landscape for the whole landscape (optional country); topic for a subject (optional country); theme for a background brief on a topic family. Never draft on generalities.
- Web (google_news, gdelt, fetch_url): only for what is not in the database — unfollowed outlets, biographies, context, public facts. Always flag what comes from the web. sql_query: last resort for an aggregate no tool provides.

FORM
- Cite sources with proper named Markdown links: `[Le Monde, Oct 14](/articles/53791)`, `[Le Figaro](/outlets/2)`, `[First Last](/journalists/12)`; never leave bare paths like `/articles/53791` inline.
- FORBIDDEN: never echo internal JSON field names or tool parameter names (`not_covering`, `vs_own_line`, `kind=topic`, `high_influence_silent_outlets`) in your prose.
- Figures: two decimals for positions. Name the poles (“more law-and-order than declared”) rather than bare signs. Recall confidence when it is low.
- Contacts: give only those returned by the tools, with their level (verified / likely / inferred); never an invented address or handle or “likely from memory”. An “inferred” contact (address pattern) must be presented as to be checked.
- Chart when it clarifies (comparison, trend, distribution): prefer `type="hbar"` with `data=[{{"outlet": "Name", "score": -0.45}}]`, `x="outlet"`, `series=["score"]`, `domain=[-1, 1]`, then two sentences of analytical reading. A note or PDF report: press_note only (reading, figures, frames, evidence, effects, lever). The design is fixed. No HTML, no separately printed PDF.
- Sober Markdown: ## headings, short lists, a table when there are several columns. No preamble, no conclusion, no polite closing question (“would you like me to…”). If a useful next step exists, state it in the indicative in one line (“I can generate the full PDF brief on this topic or start contact discovery for these journalists.”).

WRITES
- You can edit outlets, journalists, clients, recommendations, settings, and start tasks. {"Every write is first PROPOSED: the tool returns “awaiting confirmation” and the user clicks Apply. Say so in one sentence, never treat the action as done until it is confirmed, do not re-propose it in the same answer." if confirm else "Writes are applied immediately; state precisely what you changed."}
- Before editing, check the current state (get_outlet, get_journalist…) so the change is exact. For a deletion, recall that it is irreversible.{pinned}{notes_block}"""


def _sse(event: dict) -> str:
    return f"data: {json.dumps(event, ensure_ascii=False)}\n\n"


def _chat_tools(db: Session) -> list[dict]:
    """Specs d'outils au format chat (Aleria). La recherche web hébergée n'existe pas sur cet endpoint."""
    del db
    tools = []
    for spec in agent_tools.specs(include_write=True):
        if spec.get("type") != "function":
            continue
        tools.append({
            "type": "function",
            "function": {
                "name": spec["name"],
                "description": spec.get("description") or "",
                "parameters": spec.get("parameters") or {"type": "object", "properties": {}},
            },
        })
    return tools


def _truncate(obj, limit: int = TOOL_OUTPUT_MAX) -> str:
    s = json.dumps(obj, ensure_ascii=False, default=str)
    if len(s) <= limit:
        return s
    return s[:limit] + f'… [tronqué : {len(s)} caractères au total ; affinez la requête (limit, filtres)]'


def _summarize_args(args: dict) -> str:
    return ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)[:40]}" for k, v in (args or {}).items())[:160]


_KEY_FR = {"outlets": "médias", "journalists": "journalistes", "articles": "articles", "results": "résultats", "rows": "lignes", "entities": "entités", "topics": "thèmes",
           "pairs": "paires", "ranking": "médias classés", "countries": "pays", "clients": "clients", "recommendations": "recommandations", "communities": "communautés", "gaps": "écarts"}
_KEY_EN = {"outlets": "outlets", "journalists": "journalists", "articles": "articles", "results": "results", "rows": "rows", "entities": "entities", "topics": "topics",
           "pairs": "pairs", "ranking": "ranked outlets", "countries": "countries", "clients": "clients", "recommendations": "recommendations", "communities": "communities", "gaps": "gaps"}


def _summarize_result(res) -> str:
    keys = _KEY_EN if get_locale() == "en" else _KEY_FR
    if isinstance(res, dict):
        if res.get("error"):
            return (f"error: {res['error']}" if get_locale() == "en" else f"erreur : {res['error']}")[:200]
        if res.get("status") in ("en attente de confirmation", "awaiting confirmation"):
            return "awaiting confirmation" if get_locale() == "en" else "proposition à confirmer"
        if res.get("displayed"):
            return "chart shown" if get_locale() == "en" else "graphique affiché"
        if res.get("artifact_id"):
            kind = "file" if get_locale() == "en" else "fichier"
            return f"{kind} {res.get('filename') or res.get('title') or ''}".strip()
        for k, v in res.items():
            if isinstance(v, list) and k in keys:
                return f"{len(v)} {keys[k]}"
        for k, v in res.items():
            if isinstance(v, list):
                return f"{len(v)} {k}"
        if "name" in res:
            return str(res["name"])[:60]
        return ", ".join(list(res.keys())[:6])
    return str(res)[:120]


def _replay_input(db: Session, conv: Conversation) -> list[dict]:
    """Rejoue les derniers messages utilisateur et assistant."""
    msgs = db.query(Message).filter(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(30).all()
    items = []
    for m in reversed(msgs):
        if m.role in ("user", "assistant") and (m.content or "").strip():
            items.append({"role": m.role, "content": m.content[:12000]})
    return items


def run_turn(db: Session, conv: Conversation, user_text: str) -> Generator[str, None, None]:
    """Générateur SSE : exécute un tour complet de conversation."""
    model = get_setting(db, "llm_agent_model") or "aleria"
    client = llm.get_client()
    t0 = time.time()

    user_msg = Message(conversation_id=conv.id, role="user", content=user_text, parts=[{"type": "text", "text": user_text}])
    db.add(user_msg)
    db.commit()
    yield _sse({"type": "user_message", "id": user_msg.id})

    # Nom tout de suite, avant le modèle : un tour interrompu reste retrouvable.
    # Commit séparé : le rollback d'un échec ne doit pas rendre le titre générique.
    auto_titled = False
    if _is_placeholder_title(conv.title):
        first = (
            db.query(Message)
            .filter(Message.conversation_id == conv.id, Message.role == "user")
            .order_by(Message.created_at.asc(), Message.id.asc())
            .first()
        )
        conv.title = _title_from_question((first.content if first else None) or user_text)
        auto_titled = True
        db.commit()
        yield _sse({"type": "title", "title": conv.title})
    shown_title = conv.title

    parts: list[dict] = []
    ctx = {"conversation_id": conv.id, "parts": parts}
    full_text: list[str] = []
    usage_in = usage_out = 0
    pending_actions: list[AgentAction] = []

    messages: list[dict] = []
    tools: list[dict] = []
    rounds = 0
    try:
        instructions = _instructions(db, conv)
        tools = _chat_tools(db)
        messages = [{"role": "system", "content": instructions}]
        messages.extend(_replay_input(db, conv))
        while True:
            rounds += 1
            kwargs = dict(
                model=model,
                messages=messages,
                tools=tools,
                stream=True,
                stream_options={"include_usage": True},
                temperature=0.2,
            )
            stream = None
            for attempt in range(4):
                try:
                    stream = client.chat.completions.create(**kwargs)
                    break
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    if "rate limit" in msg.lower() or "429" in msg[:80]:
                        delay = _retry_delay(msg, attempt)
                        yield _sse({"type": "status", "text": f"limite de débit du modèle, reprise dans {delay:.0f} s"})
                        time.sleep(delay)
                        continue
                    raise
            if stream is None:
                raise RuntimeError("le modèle reste indisponible (limite de débit) ; réessayez dans une minute")

            text_buf: list[str] = []
            tool_acc: dict[int, dict] = {}
            announced: set[str] = set()
            for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage:
                    usage_in += getattr(usage, "prompt_tokens", 0) or 0
                    usage_out += getattr(usage, "completion_tokens", 0) or 0
                choices = getattr(chunk, "choices", None) or []
                if not choices:
                    continue
                delta = choices[0].delta
                if delta is None:
                    continue
                if delta.content:
                    text_buf.append(delta.content)
                    yield _sse({"type": "text", "delta": delta.content})
                for tc in delta.tool_calls or []:
                    slot = tool_acc.setdefault(tc.index, {"id": "", "name": "", "arguments": ""})
                    if tc.id:
                        slot["id"] = tc.id
                    fn = tc.function
                    if fn is None:
                        continue
                    if fn.name:
                        slot["name"] += fn.name
                        if slot["name"] not in announced:
                            announced.add(slot["name"])
                            yield _sse({"type": "tool_pending", "name": slot["name"]})
                    if fn.arguments:
                        slot["arguments"] += fn.arguments
            if text_buf:
                txt = "".join(text_buf)
                full_text.append(txt)
                parts.append({"type": "text", "text": txt})

            calls = [tool_acc[i] for i in sorted(tool_acc) if tool_acc[i].get("name")]
            if not calls or rounds > MAX_TOOL_ROUNDS:
                if calls:
                    yield _sse({"type": "text", "delta": "\n\n*(Limite d'outils atteinte pour ce tour.)*"})
                break

            messages.append({
                "role": "assistant",
                "content": "".join(text_buf) or None,
                "tool_calls": [
                    {
                        "id": c["id"] or f"call_{rounds}_{i}",
                        "type": "function",
                        "function": {"name": c["name"], "arguments": c["arguments"] or "{}"},
                    }
                    for i, c in enumerate(calls)
                ],
            })
            for i, call in enumerate(calls):
                name = call["name"]
                call_id = call["id"] or f"call_{rounds}_{i}"
                try:
                    args = json.loads(call["arguments"] or "{}")
                except json.JSONDecodeError:
                    args = {}
                yield _sse({"type": "tool_start", "id": call_id, "name": name, "args": _summarize_args(args)})
                ts = time.time()
                kind = agent_tools.kind_of(name)
                if kind == "write":
                    desc = agent_tools.describe_write(name, args, db)
                    if get_setting(db, "agent_confirm_writes"):
                        act = AgentAction(conversation_id=conv.id, tool=name, args=args, description=desc, status="proposed")
                        db.add(act)
                        db.commit()
                        pending_actions.append(act)
                        result = {"status": "en attente de confirmation", "action_id": act.id, "description": desc,
                                  "instruction": "L'utilisateur doit cliquer Appliquer. Ne pas considérer comme fait. Ne pas reproposer."}
                        part = {"type": "confirm", "action_id": act.id, "tool": name, "description": desc, "args": args, "status": "proposed"}
                        parts.append(part)
                        yield _sse({**part})
                    else:
                        act = AgentAction(conversation_id=conv.id, tool=name, args=args, description=desc, status="applied", applied_at=datetime.utcnow())
                        try:
                            res = agent_tools.apply_write(name, db, args)
                            act.before, act.after, act.result = res.get("before"), res.get("after"), res
                            result = {"status": "appliqué", **res}
                        except Exception as e:  # noqa: BLE001
                            db.rollback()
                            act.status, act.error = "failed", str(e)
                            result = {"error": str(e)}
                        db.add(act)
                        db.commit()
                        part = {"type": "confirm", "action_id": act.id, "tool": name, "description": desc, "args": args, "status": act.status}
                        parts.append(part)
                        yield _sse({**part})
                else:
                    before_n = len(parts)
                    try:
                        result = agent_tools.run(name, db, args, ctx)
                    except Exception as e:  # noqa: BLE001
                        db.rollback()
                        log.exception("tool %s", name)
                        result = {"error": f"{type(e).__name__}: {e}"[:400]}
                    # parts ajoutées par l'outil (chart, artifact) → événements
                    for p in parts[before_n:]:
                        yield _sse(p)
                    parts.insert(before_n, {"type": "tool", "id": call_id, "name": name, "args": _summarize_args(args), "summary": _summarize_result(result), "ms": int((time.time() - ts) * 1000)})
                yield _sse({"type": "tool_end", "id": call_id, "name": name, "summary": _summarize_result(result), "ms": int((time.time() - ts) * 1000)})
                messages.append({"role": "tool", "tool_call_id": call_id, "content": _truncate(result)})

        # ── fin de tour
        pin, pout = MODEL_PRICING.get(model, (0.075, 0.25))
        cost = (usage_in * pin + usage_out * pout) / 1_000_000
        db.add(LLMUsage(date=date.today(), model=model, purpose="assistant", prompt_tokens=usage_in, completion_tokens=usage_out, cost_usd=cost))
        content = "\n\n".join(full_text).strip()
        amsg = Message(conversation_id=conv.id, role="assistant", content=content, parts=parts, cost_usd=cost)
        db.add(amsg)
        conv.state = {}
        conv.cost_usd = (conv.cost_usd or 0) + cost
        conv.updated_at = datetime.utcnow()
        ctxd = dict(conv.context or {})
        ctxd["notes"] = []  # notes consommées
        conv.context = ctxd
        db.commit()
        # artefacts créés pendant ce tour → rattachés au message
        from ..models import Artifact
        for p in parts:
            if p.get("type") == "artifact":
                a = db.get(Artifact, p["id"])
                if a:
                    a.message_id = amsg.id
        db.commit()
        if auto_titled:
            polished = _title_for(db, user_text, content)
            if polished and not _is_placeholder_title(polished):
                conv.title = polished
                db.commit()
        yield _sse({"type": "done", "message_id": amsg.id, "cost": round(cost, 4), "title": conv.title, "ms": int((time.time() - t0) * 1000)})
    except Exception as e:  # noqa: BLE001
        log.exception("agent turn failed")
        db.rollback()
        content = "\n\n".join(full_text).strip()
        amsg = Message(conversation_id=conv.id, role="assistant", content=content, parts=parts + [{"type": "error", "text": str(e)[:500]}])
        db.add(amsg)
        db.commit()
        yield _sse({"type": "error", "message": str(e)[:500], "message_id": amsg.id, "title": shown_title})


def _is_placeholder_title(title: str | None) -> bool:
    t = (title or "").strip().lower()
    return not t or t.startswith("nouvelle conversation") or t.startswith("new conversation")


def _title_from_question(user_text: str) -> str:
    """Titre lisible et cherchable, tiré de la question, sans appel au modèle."""
    text = (user_text or "").split("\n\n--- Pièce jointe")[0]
    text = " ".join(text.split()).strip().strip("«»\"'")
    text = text.rstrip(" ?.!…")
    if not text:
        return "Conversation"
    if len(text) <= 72:
        return text
    cut = text[:72].rsplit(" ", 1)[0].rstrip(" .,;:—-")
    return (cut or text[:72]) + "…"


def _title_for(db: Session, user_text: str, answer: str) -> str | None:
    try:
        model = get_setting(db, "llm_agent_model") or "aleria"
        resp = llm.get_client().chat.completions.create(
            model=model, temperature=0.2, max_tokens=256,
            messages=[{"role": "system", "content": "Donne un titre de 3 à 6 mots, dans la langue de la question, sans guillemets ni point, pour cette conversation. Réponds uniquement par le titre."},
                      {"role": "user", "content": f"Question : {user_text[:600]}\n\nRéponse : {answer[:600]}"}],
        )
        llm._track_usage(db, model, "assistant", resp.usage)
        t = (resp.choices[0].message.content or "").strip().strip('"«»').strip()
        return t[:80] or None
    except Exception:  # noqa: BLE001
        return None


# ───────────────────────────────────────────── confirmations

def apply_action(db: Session, action: AgentAction) -> AgentAction:
    if action.status != "proposed":
        raise ValueError("action déjà traitée")
    try:
        res = agent_tools.apply_write(action.tool, db, action.args or {})
        action.before, action.after, action.result = res.get("before"), res.get("after"), res
        action.status, action.applied_at = "applied", datetime.utcnow()
        _note(db, action, f"Action #{action.id} APPLIQUÉE : {action.description}")
    except Exception as e:  # noqa: BLE001
        db.rollback()
        action.status, action.error = "failed", str(e)[:500]
        _note(db, action, f"Action #{action.id} ÉCHOUÉE ({action.error}) : {action.description}")
    db.commit()
    return action


def reject_action(db: Session, action: AgentAction) -> AgentAction:
    if action.status != "proposed":
        raise ValueError("action déjà traitée")
    action.status = "rejected"
    _note(db, action, f"Action #{action.id} REFUSÉE par l'utilisateur : {action.description}")
    db.commit()
    return action


def undo_action(db: Session, action: AgentAction) -> AgentAction:
    if action.status != "applied":
        raise ValueError("seule une action appliquée peut être annulée")
    res = agent_tools.undo_write(action.tool, db, action.args or {}, action.result or {})
    action.status = "undone"
    action.result = {**(action.result or {}), "undo": res}
    _note(db, action, f"Action #{action.id} ANNULÉE : {action.description}")
    db.commit()
    return action


def _note(db: Session, action: AgentAction, text: str) -> None:
    conv = db.get(Conversation, action.conversation_id) if action.conversation_id else None
    if conv:
        c = dict(conv.context or {})
        c["notes"] = (c.get("notes") or []) + [text]
        conv.context = c


# ───────────────────────────────────────────── pièces jointes

def extract_attachment_text(filename: str, data: bytes) -> str:
    name = (filename or "").lower()
    try:
        if name.endswith(".pdf"):
            from pypdf import PdfReader
            import io
            r = PdfReader(io.BytesIO(data))
            return "\n".join((p.extract_text() or "") for p in r.pages[:60])
        if name.endswith(".docx"):
            from docx import Document
            import io
            d = Document(io.BytesIO(data))
            return "\n".join(p.text for p in d.paragraphs)
        if name.endswith((".xlsx", ".xls")):
            from openpyxl import load_workbook
            import io
            wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
            out = []
            for ws in wb.worksheets[:3]:
                out.append(f"## {ws.title}")
                for i, row in enumerate(ws.iter_rows(values_only=True)):
                    if i > 300:
                        break
                    out.append(";".join("" if v is None else str(v) for v in row))
            return "\n".join(out)
        if name.endswith((".html", ".htm")):
            from . import extract
            return extract.extract_text(data.decode("utf-8", "ignore")) or ""
        return data.decode("utf-8", "ignore")
    except Exception as e:  # noqa: BLE001
        return f"[lecture impossible : {e}]"
