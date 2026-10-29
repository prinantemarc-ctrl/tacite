"""Suggestion de médias par pays — le modèle propose, le code vérifie.

Rien n'entre en base sans preuve : chaque candidat est contrôlé (site joignable, flux RSS
réellement parsables) avant d'être proposé à l'utilisateur. Statuts :
- verified      : au moins un flux RSS fonctionnel → collecte directe (15 min) ;
- site_only     : site joignable, pas de flux → collecte indirecte (Google News, GDELT, scraping) ;
- robot_blocked : le site existe mais bloque les robots (HTTP 403/429) → collecte par navigateur ;
- unreachable   : échec, avec la raison précise (domaine introuvable, délai, erreur serveur…) ;
- already       : un média du même nom ou du même domaine est déjà suivi.
"""

from __future__ import annotations

import json
import logging
import re
import threading
import time
from datetime import datetime, timedelta
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urljoin, urlparse

import feedparser
import httpx
from sqlalchemy.orm import Session

from ..models import Outlet
from ..settings_store import get_setting, set_setting
from ..tenant import current_user_id
from .. import geo
from . import extract, llm

log = logging.getLogger("tacite.suggest")

CACHE_TTL = 3 * 24 * 3600  # les paysages médiatiques nationaux bougent peu
_cache: dict[str, tuple[float, list[dict]]] = {}
_lock = threading.Lock()

FEED_LINK_RE = re.compile(
    r'<link\b[^>]*type=["\']application/(?:rss|atom)\+xml["\'][^>]*>', re.I)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
COMMON_FEED_PATHS = ["/rss", "/feed", "/feeds", "/rss.xml", "/feed.xml", "/atom.xml", "/index.rss", "/rss/une.xml", "/arc/outboundfeeds/rss/"]

SUGGEST_PROMPT = """List the {n} most influential news media of {country} for political and current-affairs coverage (national dailies, weeklies, public and private broadcasters with strong online news, major pure players). Give their EXACT official website URL.

For each, give:
- name: exact current name
- website_url: official homepage (https://…)
- language: main ISO 639-1 code
- type: one of "quotidien", "hebdomadaire", "télévision", "radio", "pure player", "agence"
- declared_orientation: publicly known editorial line, short, in French (e.g. "centre-gauche, social-démocrate"; "service public, généraliste" if none)
- audience: "high" | "medium" | "low" within the country

Only real, currently active news media. No aggregators, no state gazettes without newsroom.
Respond with JSON only: {{"media": [{{"name": …, "website_url": …, "language": …, "type": …, "declared_orientation": …, "audience": …}}]}}"""


# ───────────────────────────────────────────── fetch avec diagnostic

def fetch_diag(url: str, timeout: float = 12.0) -> tuple[str | None, str | None, str | None]:
    """(html, code_erreur, raison_lisible). Contrairement à extract.fetch_html, on garde la cause de l'échec."""
    try:
        with httpx.Client(headers=extract.HEADERS, follow_redirects=True, timeout=timeout, cookies=extract.CONSENT_COOKIES) as c:
            r = c.get(url)
        if r.status_code in (401, 403, 429):
            return None, "robot", f"le site existe mais bloque les robots (HTTP {r.status_code})"
        if r.status_code == 404:
            return None, "notfound", "page introuvable (HTTP 404) — l'adresse est peut-être fausse"
        if r.status_code >= 500:
            return None, "server", f"erreur du serveur (HTTP {r.status_code}) — souvent transitoire"
        if r.status_code != 200:
            return None, "http", f"réponse inattendue (HTTP {r.status_code})"
        ct = r.headers.get("content-type", "text/html")
        if "html" not in ct:
            return None, "not_html", f"l'adresse ne renvoie pas une page web ({ct.split(';')[0]})"
        return r.text, None, None
    except httpx.TimeoutException:
        return None, "timeout", f"pas de réponse en {timeout:.0f} s — site lent ou inaccessible depuis le serveur"
    except httpx.ConnectError as e:
        msg = str(e)
        if re.search(r"getaddrinfo|Name or service|nodename|No address", msg, re.I):
            return None, "dns", "domaine introuvable — le média n'existe peut-être plus à cette adresse"
        if re.search(r"ssl|tls|certificate", msg, re.I):
            return None, "tls", "certificat du site invalide"
        return None, "connect", "connexion refusée par le site"
    except Exception as e:  # noqa: BLE001
        return None, "other", f"erreur inattendue ({type(e).__name__})"


# ───────────────────────────────────────────── découverte et test de flux

def discover_feeds(website_url: str, max_feeds: int = 3, timeout: float = 12.0, html: str | None = None) -> list[str]:
    """Flux RSS/Atom fonctionnels d'un site : balises <link> de la page d'accueil + chemins usuels, chacun testé."""
    if html is None:
        html = extract.fetch_html(website_url, timeout=timeout)
    candidates: list[str] = []
    if html:
        for m in FEED_LINK_RE.finditer(html[:300_000]):
            h = HREF_RE.search(m.group(0))
            if h:
                candidates.append(urljoin(website_url, h.group(1)))
    base = website_url.rstrip("/")
    candidates += [base + p for p in COMMON_FEED_PATHS]
    seen: set[str] = set()
    working: list[str] = []
    for url in candidates:
        u = url.split("#")[0]
        if u in seen or len(working) >= max_feeds:
            continue
        seen.add(u)
        if _feed_works(u, timeout):
            working.append(u)
    return working


def _feed_works(url: str, timeout: float = 12.0) -> bool:
    try:
        with httpx.Client(headers=extract.HEADERS, follow_redirects=True, timeout=timeout) as c:
            r = c.get(url)
        if r.status_code != 200:
            return False
        head = r.content[:2000].lstrip()
        if not (head.startswith(b"<?xml") or b"<rss" in head or b"<feed" in head):
            return False
        f = feedparser.parse(r.content)
        return bool(f.entries)
    except Exception:  # noqa: BLE001
        return False


def _domain(url: str | None) -> str:
    try:
        return urlparse(url or "").netloc.lower().replace("www.", "")
    except ValueError:
        return ""


# ───────────────────────────────────────────── vérification d'un candidat

def _verify(cand: dict, existing_names: set[str], existing_domains: set[str]) -> dict:
    orientation = (cand.get("declared_orientation") or "").strip()
    if re.search(r"ligne éditoriale|editorial line|en français", orientation, re.I):  # le modèle a recopié la consigne
        orientation = ""
    out = {
        "name": (cand.get("name") or "").strip(),
        "website_url": (cand.get("website_url") or "").strip(),
        "language": (cand.get("language") or "").strip().lower()[:2],
        "type": cand.get("type"),
        "declared_orientation": orientation or None,
        "audience": cand.get("audience"),
        "feeds": [],
        "status": "unreachable",
        "reason": None,
        "error": None,
    }
    if not out["name"] or not out["website_url"].startswith("http"):
        out["status"] = "invalid"
        return out
    dom = _domain(out["website_url"])
    if out["name"].lower() in existing_names or (dom and dom in existing_domains):
        out["status"] = "already"
        return out
    html, err, reason = fetch_diag(out["website_url"], timeout=12)
    if html:
        out["feeds"] = discover_feeds(out["website_url"], html=html)
        out["status"] = "verified" if out["feeds"] else "site_only"
        return out
    # Page d'accueil en échec : les chemins de flux usuels sont parfois servis par une autre infrastructure.
    if err in ("robot", "server", "timeout", "http"):
        base = out["website_url"].rstrip("/")
        out["feeds"] = [base + p for p in COMMON_FEED_PATHS[:5] if _feed_works(base + p, timeout=8)][:3]
        if out["feeds"]:
            out["status"] = "verified"
            out["reason"] = "page d'accueil bloquée, mais flux RSS accessibles"
            return out
    if err == "robot":
        out["status"] = "robot_blocked"
        out["reason"] = reason
        out["error"] = err
    else:
        out["status"] = "unreachable"
        out["reason"] = reason
        out["error"] = err
    return out


def _existing(db: Session) -> tuple[set[str], set[str]]:
    rows = db.query(Outlet.name, Outlet.website_url).all()
    return {n.strip().lower() for n, _ in rows}, {_domain(w) for _, w in rows if w} - {""}


# ───────────────────────────────────────────── génération LLM

def _complete_json(db: Session, model: str, prompt: str, purpose: str) -> str:
    resp = llm.get_client().chat.completions.create(
        model=model,
        messages=[{"role": "user", "content": prompt}],
        response_format={"type": "json_object"},
        temperature=0.2,
    )
    llm._track_usage(db, model, purpose, resp.usage)
    return resp.choices[0].message.content or ""


def _parse_json(text: str):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        m = re.search(r"\{.*\}", text, re.S)
        if not m:
            raise
        return json.loads(m.group(0))


def _llm_candidates(db: Session, country_code: str, n: int = 14) -> list[dict]:
    c = geo.country(country_code)
    country_name = (c or {}).get("name_en") or country_code
    model = get_setting(db, "llm_agent_model") or "aleria"
    text = _complete_json(db, model, SUGGEST_PROMPT.format(n=n, country=country_name), "suggest")
    data = _parse_json(text)
    rows = data.get("media") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise ValueError("réponse du modèle sans JSON")
    return [d for d in rows if isinstance(d, dict)][:n + 4]


# ───────────────────────────────────────────── API du service

def cached_suggestions(db: Session, country_code: str) -> list[dict] | None:
    """Résultat en cache s'il existe (gratuit, instantané), sinon None — la recherche ne se lance pas."""
    code = country_code.upper()
    with _lock:
        hit = _cache.get(code)
    if hit and time.time() - hit[0] < CACHE_TTL:
        return _refresh_already(db, hit[1])
    return None


def suggest(db: Session, country_code: str, force: bool = False) -> list[dict]:
    """Liste vérifiée des médias suggérés pour un pays (mise en cache 3 jours)."""
    code = country_code.upper()
    if not geo.is_valid(code):
        raise ValueError(f"code pays inconnu : {code}")
    with _lock:
        hit = _cache.get(code)
        if hit and not force and time.time() - hit[0] < CACHE_TTL:
            return _refresh_already(db, hit[1])
    candidates = _llm_candidates(db, code)
    names_seen: set[str] = set()
    deduped = []
    for c in candidates:
        k = (c.get("name") or "").strip().lower()
        if k and k not in names_seen:
            names_seen.add(k)
            deduped.append(c)
    ex_names, ex_domains = _existing(db)
    with ThreadPoolExecutor(max_workers=6) as pool:
        results = list(pool.map(lambda c: _verify(c, ex_names, ex_domains), deduped))
    results = [r for r in results if r["status"] != "invalid"]
    order = {"verified": 0, "site_only": 1, "robot_blocked": 2, "already": 3, "unreachable": 4}
    aud = {"high": 0, "medium": 1, "low": 2}
    results.sort(key=lambda r: (order.get(r["status"], 9), aud.get(r.get("audience"), 3)))
    with _lock:
        _cache[code] = (time.time(), results)
    remember_unreachable(db, code, results)
    return results


def _refresh_already(db: Session, results: list[dict]) -> list[dict]:
    """Sur un résultat en cache, remet à jour le statut « déjà suivi » (des ajouts ont pu avoir lieu)."""
    ex_names, ex_domains = _existing(db)
    out = []
    for r in results:
        r = dict(r)
        if r["status"] in ("verified", "site_only", "robot_blocked", "already"):
            known = r["name"].lower() in ex_names or _domain(r["website_url"]) in ex_domains
            if known:
                r["status"] = "already"
            elif r["status"] == "already":
                r["status"] = "verified" if r.get("feeds") else "site_only"
        out.append(r)
    return out


def reverify(db: Session, country_code: str, item: dict) -> dict:
    """Re-vérifie un candidat (bouton « Réessayer ») et met à jour l'entrée en cache."""
    ex_names, ex_domains = _existing(db)
    r = _verify(item, ex_names, ex_domains)
    code = country_code.upper()
    with _lock:
        hit = _cache.get(code)
        if hit:
            _cache[code] = (hit[0], [r if s["name"].lower() == r["name"].lower() else s for s in hit[1]])
    return r


RESOLVE_PROMPT = """Find the official website of the news media "{name}" ({country}).
Respond with JSON only, all values filled with real information (never echo these instructions):
{{"name": "exact current name", "website_url": "https://…", "language": "ISO 639-1", "type": "quotidien|hebdomadaire|télévision|radio|pure player|agence", "declared_orientation": "its publicly known editorial line, in French, e.g. 'centriste, libéral'", "audience": "high|medium|low"}}
If this media does not exist or is not a news media, respond {{"not_found": true, "reason": "…"}}."""


def resolve(db: Session, name: str, country_code: str) -> dict:
    """Résout un nom saisi librement : site officiel via recherche web, puis vérification complète."""
    code = country_code.upper()
    c = geo.country(code)
    model = get_setting(db, "llm_agent_model") or "aleria"
    prompt = RESOLVE_PROMPT.format(name=name.strip(), country=(c or {}).get("name_en") or code)
    try:
        data = _parse_json(_complete_json(db, model, prompt, "suggest"))
    except (json.JSONDecodeError, ValueError):
        return {"status": "not_found", "name": name, "reason": "réponse du modèle illisible"}
    if not isinstance(data, dict):
        return {"status": "not_found", "name": name, "reason": "réponse du modèle illisible"}
    if data.get("not_found"):
        return {"status": "not_found", "name": name, "reason": data.get("reason")}
    ex_names, ex_domains = _existing(db)
    return _verify(data, ex_names, ex_domains)


def create_from_suggestions(db: Session, country_code: str, items: list[dict]) -> dict:
    """Crée les médias sélectionnés : fiche + flux vérifiés + estimation LLM de la ligne déclarée."""
    from ..main import _complete_outlet
    from ..models import OutletFeed
    code = country_code.upper()
    ex_names, ex_domains = _existing(db)
    created, skipped, errors = [], [], []
    for it in items:
        name = (it.get("name") or "").strip()
        if not name:
            continue
        if name.lower() in ex_names or _domain(it.get("website_url")) in ex_domains:
            skipped.append(name)
            continue
        feeds = [f for f in (it.get("feeds") or []) if isinstance(f, str) and f.startswith("http")]
        o = Outlet(
            name=name, country=code, language=(it.get("language") or "en")[:2],
            website_url=it.get("website_url") or None, rss_url=feeds[0] if feeds else None,
            declared_orientation=it.get("declared_orientation") or None,
            official_classification={}, meta={},
        )
        db.add(o)
        db.flush()
        for i, f in enumerate(feeds):
            db.add(OutletFeed(outlet_id=o.id, url=f, label="une" if i == 0 else f"flux {i + 1}", feed_type="rss"))
        try:
            _complete_outlet(db, o)
        except Exception as e:  # noqa: BLE001
            errors.append(f"{name}: estimation LLM impossible ({e})")
        ex_names.add(name.lower())
        created.append({"id": o.id, "name": o.name, "feeds": len(feeds)})
    db.commit()
    forget_unreachable(db, code, [c["name"] for c in created])
    from . import cartography
    cartography.invalidate()
    return {"created": created, "skipped": skipped, "errors": errors}


# ───────────────────────────────────────────── injoignables : on y revient

_QUEUE = "unreachable_outlets"
_TRANSIENT = {"timeout", "server", "connect", "tls", "http", "other", "not_html"}
_DEAD_URL = {"dns", "notfound"}
_JOINABLE = {"verified", "site_only", "robot_blocked"}
_BACKOFF_HOURS = (6, 24, 48, 72, 168)
_MAX_ATTEMPTS = 5
_SKIP_DOMAINS = ("google.com", "gstatic.com", "youtube.com", "facebook.com", "instagram.com", "twitter.com", "wikipedia.org", "tiktok.com", "linkedin.com")


def _queue(db: Session) -> list[dict]:
    raw = get_setting(db, _QUEUE)
    return list(raw) if isinstance(raw, list) else []


def _key(country: str, name: str) -> tuple[str, str]:
    return (country.upper(), (name or "").strip().lower())


def remember_unreachable(db: Session, country: str, items: list[dict]) -> None:
    """Garde les médias dont le site n'a pas répondu, pour les rejoindre plus tard."""
    if current_user_id() is None:
        return
    country = country.upper()
    queued = _queue(db)
    by_key = {_key(x.get("country", ""), x.get("name", "")): x for x in queued}
    now = datetime.utcnow()
    changed = False
    for it in items:
        if it.get("status") != "unreachable":
            continue
        url = (it.get("website_url") or "").strip()
        name = (it.get("name") or "").strip()
        if not name or not url.startswith("http"):
            continue
        prev = by_key.get(_key(country, name))
        if prev:
            if prev.get("website_url") != url:
                prev["attempts"] = 0
                prev["next_try"] = (now + timedelta(hours=_BACKOFF_HOURS[0])).isoformat()
            prev["website_url"] = url
            prev["reason"] = it.get("reason")
            prev["error"] = it.get("error")
            changed = True
            continue
        row = {
            "name": name,
            "country": country,
            "website_url": url,
            "language": (it.get("language") or "")[:2],
            "type": it.get("type"),
            "declared_orientation": it.get("declared_orientation"),
            "audience": it.get("audience"),
            "error": it.get("error"),
            "reason": it.get("reason"),
            "attempts": 0,
            "resolved_once": False,
            "since": now.isoformat(),
            "next_try": (now + timedelta(hours=_BACKOFF_HOURS[0])).isoformat(),
        }
        by_key[_key(country, name)] = row
        changed = True
    if changed:
        set_setting(db, _QUEUE, list(by_key.values()))


def forget_unreachable(db: Session, country: str, names: list[str]) -> None:
    if not names or current_user_id() is None:
        return
    drop = {_key(country, n) for n in names}
    queued = [x for x in _queue(db) if _key(x.get("country", ""), x.get("name", "")) not in drop]
    set_setting(db, _QUEUE, queued)


def _platform_domain(dom: str) -> bool:
    host = dom.lower().removeprefix("www.")
    if host in {"x.com", "t.co"}:
        return True
    return any(host == stem or host.endswith("." + stem) for stem in _SKIP_DOMAINS)


def domains_from_news_entries(entries: list[dict]) -> list[str]:
    """Domaines les plus cités comme source dans un flux Google News, hors plateformes."""
    counts: dict[str, int] = {}
    for entry in entries:
        src = entry.get("source") or {}
        href = src.get("href") if isinstance(src, dict) else None
        dom = _domain(href)
        if not dom or _platform_domain(dom):
            continue
        counts[dom] = counts.get(dom, 0) + 1
    return [d for d, _ in sorted(counts.items(), key=lambda kv: -kv[1])[:3]]


def _news_domains(name: str, language: str, country: str) -> list[str]:
    lang = language or "en"
    gl = (country or "US").upper()
    url = f"https://news.google.com/rss/search?q={quote(name)}&hl={lang}&gl={gl}&ceid={gl}:{lang}"
    try:
        with httpx.Client(headers=extract.HEADERS, follow_redirects=True, timeout=15, cookies=extract.CONSENT_COOKIES) as c:
            resp = c.get(url)
        if resp.status_code != 200:
            return []
        return domains_from_news_entries(feedparser.parse(resp.content).entries)
    except Exception as e:  # noqa: BLE001
        log.info("news lookup failed for %s: %s", name, e)
        return []


def _due(row: dict, now: datetime) -> bool:
    if int(row.get("attempts") or 0) >= _MAX_ATTEMPTS:
        return False
    raw = row.get("next_try")
    if not raw:
        return True
    try:
        when = datetime.fromisoformat(raw)
    except ValueError:
        return True
    return when <= now


def _schedule(row: dict, now: datetime) -> None:
    row["attempts"] = int(row.get("attempts") or 0) + 1
    hours = _BACKOFF_HOURS[min(row["attempts"], len(_BACKOFF_HOURS) - 1)]
    row["next_try"] = (now + timedelta(hours=hours)).isoformat()


def retry_unreachable(db: Session, limit: int = 8) -> dict:
    """Reprend les médias injoignables. Crée la fiche seulement quand le test passe."""
    if current_user_id() is None:
        return {"tried": 0, "joined": 0}
    now = datetime.utcnow()
    queued = _queue(db)
    due = [r for r in queued if _due(r, now)][:limit]
    if not due:
        return {"tried": 0, "joined": 0}
    joined: list[str] = []
    for row in due:
        candidate = dict(row)
        error = row.get("error") or ""
        found = None
        if error in _DEAD_URL:
            for dom in _news_domains(row["name"], row.get("language") or "", row["country"]):
                if dom == _domain(row.get("website_url")):
                    continue
                alt = _verify({**candidate, "website_url": f"https://{dom}"}, *_existing(db))
                if alt.get("status") in _JOINABLE:
                    found = alt
                    break
            if found is None and not row.get("resolved_once"):
                row["resolved_once"] = True
                alt = resolve(db, row["name"], row["country"])
                if alt.get("status") in _JOINABLE:
                    found = alt
        if found is None:
            found = _verify(candidate, *_existing(db))
        if found.get("status") in _JOINABLE:
            res = create_from_suggestions(db, row["country"], [found])
            if res["created"] or res["skipped"]:
                joined.append(row["name"])
                continue
        row["error"] = found.get("error") or error
        row["reason"] = found.get("reason")
        if found.get("website_url"):
            row["website_url"] = found["website_url"]
        _schedule(row, now)
    kept = [r for r in queued if r.get("name") not in joined]
    set_setting(db, _QUEUE, kept)
    if joined:
        log.info("Injoignables rejoints : %s", ", ".join(joined))
    return {"tried": len(due), "joined": len(joined)}
