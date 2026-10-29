"""Contacts journalistes — détection fondée sur des preuves, jamais sur des suppositions du LLM.

Sources, par fiabilité décroissante :
1. HTML des articles signés (déjà en base) : JSON-LD Person (sameAs, email), liens du bloc signature, mailto.
2. Page auteur du média (rel=author / JSON-LD url) : bio, réseaux, mail.
3. Texte des articles : « prenom.nom@lemonde.fr », « @handle », Signal.
4. Motif d'adresse du média : dès que ≥ 2 mails vérifiés suivent le même motif, on propose l'adresse
   des autres journalistes (confiance « guess », jamais plus).
5. Recherche publique Bluesky (API publique, sans clé) : profil dont la bio cite le média (« probable »).

Chaque contact garde sa source, sa méthode et sa confiance ; l'utilisateur peut marquer invalide.
"""

from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from collections import Counter
from datetime import datetime
from urllib.parse import urlparse

import httpx
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..models import Article, ContactScan, Journalist, JournalistContact, Outlet
from . import extract
from .bylines import _iter_jsonld, _REL_AUTHOR_RE, _HREF_RE, _text

log = logging.getLogger("tacite.contacts")

KINDS = ["email", "x", "bluesky", "mastodon", "linkedin", "instagram", "threads", "facebook", "author_page", "website", "wikipedia", "phone", "signal", "other"]
KIND_LABELS_FR = {"email": "E-mail", "x": "X", "bluesky": "Bluesky", "mastodon": "Mastodon", "linkedin": "LinkedIn", "instagram": "Instagram", "threads": "Threads",
                  "facebook": "Facebook", "author_page": "Page auteur", "website": "Site", "wikipedia": "Wikipédia", "phone": "Téléphone", "signal": "Signal", "other": "Autre"}
# Canaux qui comptent comme un contact joignable (page auteur / Wikipédia = traces, pas un canal).
REACHABLE_KINDS = frozenset(k for k in KINDS if k not in ("author_page", "wikipedia"))


def journalist_has_contact(kinds: list[str] | None) -> bool:
    return any(k in REACHABLE_KINDS for k in (kinds or []))
SOCIAL_HOSTS = {
    "twitter.com": "x", "x.com": "x", "mobile.twitter.com": "x", "bsky.app": "bluesky", "linkedin.com": "linkedin", "instagram.com": "instagram",
    "threads.net": "threads", "facebook.com": "facebook", "wikipedia.org": "wikipedia",
}
MASTODON_RE = re.compile(r"^https?://([a-z0-9.-]+)/@([A-Za-z0-9_]+)/?$", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
HANDLE_RE = re.compile(r"(?<![\w@/])@([A-Za-z0-9_]{3,30})\b")
STATE: dict = {"running": False, "total": 0, "done": 0, "stats": None, "started_at": None, "finished_at": None}
_lock = threading.Lock()


# ───────────────────────────────────────────── normalisation

def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def _name_parts(name: str) -> tuple[str, str]:
    parts = _norm(name).split()
    if len(parts) < 2:
        return (parts[0] if parts else "", "")
    return parts[0], parts[-1]


def classify_url(url: str) -> dict | None:
    """URL → {kind, value} ou None si ce n'est pas un canal reconnu (les liens de partage sont écartés)."""
    if not url or not url.startswith("http"):
        return None
    try:
        p = urlparse(url)
    except ValueError:
        return None
    host = p.netloc.lower().replace("www.", "")
    path = p.path.strip("/")
    if re.search(r"intent/|/share|sharer|/status/|/posts/|/p/|/reel", url):
        return None
    for h, kind in SOCIAL_HOSTS.items():
        if host == h or host.endswith("." + h):
            if kind == "x":
                handle = path.split("/")[0].lstrip("@")
                if not handle or handle.lower() in ("home", "search", "hashtag", "i", "explore", "share", "intent") or not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
                    return None
                return {"kind": "x", "value": "@" + handle}
            if kind == "bluesky":
                m = re.match(r"profile/([^/]+)", path)
                return {"kind": "bluesky", "value": "@" + m.group(1)} if m else None
            if kind == "linkedin":
                return {"kind": "linkedin", "value": f"https://www.linkedin.com/{path}"} if path.startswith(("in/", "pub/")) else None
            if kind == "instagram":
                h2 = path.split("/")[0]
                return {"kind": "instagram", "value": "@" + h2} if h2 and h2 not in ("explore", "p", "reel", "accounts") else None
            if kind == "threads":
                h2 = path.split("/")[0].lstrip("@")
                return {"kind": "threads", "value": "@" + h2} if h2 else None
            if kind == "facebook":
                h2 = path.split("/")[0]
                return {"kind": "facebook", "value": f"https://www.facebook.com/{h2}"} if h2 and h2 not in ("sharer.php", "share", "dialog", "plugins") else None
            if kind == "wikipedia":
                return {"kind": "wikipedia", "value": url}
    m = MASTODON_RE.match(url)
    if m:
        return {"kind": "mastodon", "value": f"@{m.group(2)}@{m.group(1)}"}
    return None


def _outlet_domain(o: Outlet) -> str:
    try:
        return urlparse(o.website_url or "").netloc.lower().replace("www.", "")
    except ValueError:
        return ""


def _is_outlet_account(value: str, outlet: Outlet | None) -> bool:
    """@el_pais, facebook.com/elpais, @Le_Figaro… : comptes du média, pas d'une personne."""
    if not outlet:
        return False
    v = re.sub(r"[^a-z0-9]", "", _norm(value.split("/")[-1] if value.startswith("http") else value))
    keys = {re.sub(r"[^a-z0-9]", "", _norm(outlet.name)), re.sub(r"[^a-z0-9]", "", _outlet_domain(outlet).split(".")[0])} - {""}
    return any(k and (v == k or v.startswith(k) and len(v) - len(k) <= 4 or k in v and len(k) >= 6) for k in keys)


def _looks_like_person_handle(value: str, name: str) -> bool:
    """@handle plausible pour la personne : contient le nom, ou l'initiale + nom, ou le prénom + nom."""
    first, last = _name_parts(name)
    v = _norm(value.split("@")[1] if value.startswith("@") and value.count("@") == 1 else value.lstrip("@").split("@")[0]).replace(" ", "")
    if not last:
        return False
    return last in v or (first and (first[0] + last) in v) or (first and (first + last) in v) or (first and last[:5] in v and first[:3] in v)


def _email_matches(email: str, name: str) -> bool:
    first, last = _name_parts(name)
    local = _norm(email.split("@")[0]).replace(" ", "")
    if not last or len(last) < 3:
        return False
    return last in local or (first and (first[0] + last) in local) or (first and (first[:3] in local and last[:4] in local))


def _generic_mailbox(email: str) -> bool:
    return bool(re.match(r"^(info|contact|redaction|redazione|redaccion|newsdesk|news|press|presse|hello|support|abonnement|service|webmaster|noreply|no-reply|lecteurs|courrier|esperto)", email.split("@")[0].lower()))


# ───────────────────────────────────────────── stockage

def upsert_many(db: Session, journalist_id: int, found: list[dict], source_url: str | None) -> int:
    """Insère ou met à jour (last_seen) ; ne rétrograde jamais la confiance. Renvoie le nombre de nouveaux."""
    rank = {"guess": 0, "probable": 1, "verified": 2}
    existing = {(c.kind, c.value.lower()): c for c in db.query(JournalistContact).filter(JournalistContact.journalist_id == journalist_id).all()}
    new = 0
    for f in found:
        kind, value = f["kind"], (f["value"] or "").strip()
        if not value or kind not in KINDS:
            continue
        key = (kind, value.lower())
        if key in existing:
            c = existing[key]
            c.last_seen = datetime.utcnow()
            if rank.get(f.get("confidence", "probable"), 1) > rank.get(c.confidence or "probable", 1):
                c.confidence, c.method, c.source_url = f.get("confidence"), f.get("method"), source_url or c.source_url
            continue
        c = JournalistContact(journalist_id=journalist_id, kind=kind, value=value, confidence=f.get("confidence", "probable"), method=f.get("method"),
                              source_url=source_url, note=f.get("note"))
        db.add(c)
        existing[key] = c
        new += 1
    db.commit()
    _refresh_denormalized(db, journalist_id)
    return new


def _refresh_denormalized(db: Session, journalist_id: int) -> None:
    """Journalist.twitter_handle / linkedin_url = meilleur contact vérifié ou probable (jamais un guess)."""
    j = db.get(Journalist, journalist_id)
    if not j:
        return
    rows = db.query(JournalistContact).filter(JournalistContact.journalist_id == journalist_id, JournalistContact.invalid == 0,
                                              JournalistContact.confidence.in_(["verified", "probable"])).all()
    x = next((c.value for c in sorted(rows, key=lambda c: c.confidence != "verified") if c.kind == "x"), None)
    li = next((c.value for c in sorted(rows, key=lambda c: c.confidence != "verified") if c.kind == "linkedin"), None)
    j.twitter_handle, j.linkedin_url = x, li
    db.commit()


def list_for(db: Session, journalist_id: int, include_invalid: bool = False) -> list[dict]:
    q = db.query(JournalistContact).filter(JournalistContact.journalist_id == journalist_id)
    if not include_invalid:
        q = q.filter(JournalistContact.invalid == 0)
    order = {"verified": 0, "probable": 1, "guess": 2}
    kind_order = {k: i for i, k in enumerate(KINDS)}
    rows = sorted(q.all(), key=lambda c: (order.get(c.confidence, 3), kind_order.get(c.kind, 99)))
    return [{"id": c.id, "kind": c.kind, "label": KIND_LABELS_FR.get(c.kind, c.kind), "value": c.value, "confidence": c.confidence, "method": c.method,
             "source_url": c.source_url, "note": c.note, "invalid": bool(c.invalid), "first_seen": c.first_seen.isoformat() if c.first_seen else None,
             "url": contact_url(c.kind, c.value)} for c in rows]


def contact_url(kind: str, value: str) -> str | None:
    if kind == "email":
        return f"mailto:{value}"
    if kind == "x":
        return f"https://x.com/{value.lstrip('@')}"
    if kind == "bluesky":
        return f"https://bsky.app/profile/{value.lstrip('@')}"
    if kind == "mastodon":
        m = re.match(r"^@([^@]+)@(.+)$", value)
        return f"https://{m.group(2)}/@{m.group(1)}" if m else None
    if kind == "instagram":
        return f"https://www.instagram.com/{value.lstrip('@')}/"
    if kind == "threads":
        return f"https://www.threads.net/@{value.lstrip('@')}"
    if value.startswith("http"):
        return value
    return None


def summary_for_many(db: Session, journalist_ids: list[int]) -> dict[int, dict]:
    """{jid: {kinds: [...], best: {...}, n, has_contact}} pour les listes."""
    if not journalist_ids:
        return {}
    rows = db.query(JournalistContact).filter(JournalistContact.journalist_id.in_(journalist_ids), JournalistContact.invalid == 0).all()
    out: dict[int, dict] = {}
    order = {"verified": 0, "probable": 1, "guess": 2}
    for c in sorted(rows, key=lambda c: order.get(c.confidence, 3)):
        d = out.setdefault(c.journalist_id, {"kinds": [], "best": None, "n": 0, "has_contact": False})
        if c.kind not in d["kinds"]:
            d["kinds"].append(c.kind)
        d["n"] += 1
        if d["best"] is None and c.kind in ("email", "x", "bluesky", "mastodon", "linkedin"):
            d["best"] = {"kind": c.kind, "value": c.value, "confidence": c.confidence}
    for d in out.values():
        d["has_contact"] = journalist_has_contact(d["kinds"])
    return out


# ───────────────────────────────────────────── extraction

def _site_wide_links(db: Session, outlet: Outlet) -> set[str]:
    """Liens sociaux présents sur plusieurs pages du média (pied de page) : comptes du média, pas des journalistes."""
    rows = db.query(Article.raw_html).filter(Article.outlet_id == outlet.id, Article.raw_html.isnot(None), ~Article.url.like("%news.google.com%")).order_by(Article.id.desc()).limit(6).all()
    counts: Counter = Counter()
    for (html,) in rows:
        links = set()
        for m in _HREF_RE.finditer(html or ""):
            c = classify_url(m.group(1))
            if c:
                links.add((c["kind"], c["value"].lower()))
        counts.update(links)
    return {f"{k}:{v}" for (k, v), n in counts.items() if n >= 2}


def extract_from_html(html: str, name: str, outlet_domain: str, exclude: set[str], outlet: Outlet | None = None) -> list[dict]:
    found: list[dict] = []
    if not html:
        return found
    first, last = _name_parts(name)
    # 1. JSON-LD Person correspondant au nom
    for d in _iter_jsonld(html):
        t = d.get("@type")
        types = t if isinstance(t, list) else [t]
        cands = []
        if "Person" in types:
            cands.append(d)
        for k in ("author", "creator"):
            v = d.get(k)
            for a in (v if isinstance(v, list) else [v]):
                if isinstance(a, dict):
                    cands.append(a)
        for a in cands:
            if _norm(str(a.get("name") or "")) != _norm(name):
                continue
            url = a.get("url") or a.get("@id")
            if isinstance(url, str) and url.startswith("http") and "#" not in url:
                found.append({"kind": "author_page", "value": url, "confidence": "verified", "method": "jsonld"})
            email = a.get("email")
            if isinstance(email, str) and "@" in email:
                found.append({"kind": "email", "value": email.strip().lower(), "confidence": "verified", "method": "jsonld"})
            sa = a.get("sameAs")
            for s in (sa if isinstance(sa, list) else [sa] if isinstance(sa, str) else []):
                c = classify_url(s)
                if c and f"{c['kind']}:{c['value'].lower()}" not in exclude and not _is_outlet_account(c["value"], outlet):
                    found.append({**c, "confidence": "verified", "method": "jsonld"})
    # 2. bloc signature : ancre rel=author (ou contenant le nom) → liens sociaux / mailto dans un voisinage de 1 500 caractères
    for m in re.finditer(r'<a\b[^>]*>(?:(?!</a>).){0,120}</a>', html, re.I | re.S):
        txt = _norm(_text(m.group(0)))
        if not last or last not in txt or (first and first not in txt):
            continue
        href = _HREF_RE.search(m.group(0))
        if href and outlet_domain and outlet_domain in href.group(1) and re.search(r"/(auteur|author|autor|autori|journalist|redaktion|redaction|profil|people|staff|firma)", href.group(1), re.I):
            found.append({"kind": "author_page", "value": href.group(1) if href.group(1).startswith("http") else f"https://{outlet_domain}{href.group(1)}", "confidence": "verified", "method": "byline_link"})
        window = html[max(0, m.start() - 800): m.end() + 800]
        for h in _HREF_RE.finditer(window):
            u = h.group(1)
            if u.startswith("mailto:"):
                em = u[7:].split("?")[0].strip().lower()
                if EMAIL_RE.fullmatch(em) and not _generic_mailbox(em) and _email_matches(em, name):
                    found.append({"kind": "email", "value": em, "confidence": "verified", "method": "byline_link"})
                continue
            c = classify_url(u)
            if c and f"{c['kind']}:{c['value'].lower()}" not in exclude and (c["kind"] in ("linkedin", "wikipedia") or _looks_like_person_handle(c["value"], name)) and not _is_outlet_account(c["value"], outlet):
                found.append({**c, "confidence": "verified", "method": "byline_link"})
    # 3. mailto au nom du journaliste n'importe où dans la page
    for m in re.finditer(r'mailto:([^"\'?>\s]+)', html, re.I):
        em = m.group(1).strip().lower()
        if EMAIL_RE.fullmatch(em) and not _generic_mailbox(em) and _email_matches(em, name):
            found.append({"kind": "email", "value": em, "confidence": "verified", "method": "byline_link"})
    return _dedupe(found)


def extract_from_text(text: str, name: str) -> list[dict]:
    found: list[dict] = []
    if not text:
        return found
    for em in EMAIL_RE.findall(text):
        em = em.lower().rstrip(".")
        if not _generic_mailbox(em) and _email_matches(em, name):
            found.append({"kind": "email", "value": em, "confidence": "probable", "method": "article_text"})
    for h in HANDLE_RE.findall(text):
        if _looks_like_person_handle("@" + h, name) and len(h) >= 5:
            found.append({"kind": "x", "value": "@" + h, "confidence": "probable", "method": "article_text", "note": "handle cité dans le texte ; réseau présumé X"})
    m = re.search(r"signal\s*[:：]\s*(\+?[\d .]{9,18}|@?[A-Za-z0-9_.]{3,32})", text, re.I)
    if m:
        found.append({"kind": "signal", "value": m.group(1).strip(), "confidence": "probable", "method": "article_text"})
    return _dedupe(found)


def extract_from_author_page(html: str, name: str, outlet_domain: str, exclude: set[str], outlet: Outlet | None = None) -> list[dict]:
    """Sur une page auteur, les liens sociaux non génériques du média sont attribués au journaliste.
    Les e-mails doivent porter son nom (les boîtes de service ne sont pas des contacts)."""
    found = extract_from_html(html, name, outlet_domain, exclude, outlet)
    socials: list[dict] = []
    for h in _HREF_RE.finditer(html or ""):
        u = h.group(1)
        if u.startswith("mailto:"):
            em = u[7:].split("?")[0].strip().lower()
            if EMAIL_RE.fullmatch(em) and not _generic_mailbox(em) and _email_matches(em, name):
                found.append({"kind": "email", "value": em, "confidence": "verified", "method": "author_page"})
            continue
        c = classify_url(u)
        if c and f"{c['kind']}:{c['value'].lower()}" not in exclude and c["kind"] != "wikipedia" and not _is_outlet_account(c["value"], outlet):
            socials.append(c)
    # Une page auteur qui liste plus de 3 comptes du même réseau est une page d'index, pas un profil.
    from collections import Counter as _C
    per_kind = _C(s["kind"] for s in socials)
    for c in socials:
        if per_kind[c["kind"]] > 3:
            continue
        found.append({**c, "confidence": "verified" if (c["kind"] == "linkedin" or _looks_like_person_handle(c["value"], name)) else "probable", "method": "author_page"})
    return _dedupe(found)


def _dedupe(found: list[dict]) -> list[dict]:
    rank = {"guess": 0, "probable": 1, "verified": 2}
    best: dict[tuple, dict] = {}
    for f in found:
        k = (f["kind"], f["value"].lower())
        if k not in best or rank[f["confidence"]] > rank[best[k]["confidence"]]:
            best[k] = f
    return list(best.values())


# ───────────────────────────────────────────── recherche publique Bluesky

def bluesky_lookup(name: str, outlet: Outlet) -> list[dict]:
    try:
        with httpx.Client(timeout=10, headers={"User-Agent": "Tacite/1.0"}) as c:
            r = c.get("https://public.api.bsky.app/xrpc/app.bsky.actor.searchActors", params={"q": name, "limit": 8})
        if r.status_code != 200:
            return []
        actors = r.json().get("actors", [])
    except Exception:  # noqa: BLE001
        return []
    keys = {_norm(outlet.name), _outlet_domain(outlet).split(".")[0]} - {""}
    first, last = _name_parts(name)
    out = []
    for a in actors:
        dn, desc = _norm(a.get("displayName") or ""), _norm(a.get("description") or "")
        hd = _norm(a.get("handle") or "").replace(" ", "")
        # le nom affiché doit porter le nom ET le prénom (ou son initiale) ; un simple nom de famille ne suffit pas
        full_ok = _norm(name) in dn or (last and last in dn and first and (first in dn or dn.startswith(first[0])))
        handle_ok = last and first and (first + last) in hd
        if not (full_ok or handle_ok):
            continue
        if any(k and (k in desc or k in _norm(a.get("handle", ""))) for k in keys):
            out.append({"kind": "bluesky", "value": "@" + a["handle"], "confidence": "probable", "method": "bluesky_search", "note": (a.get("description") or "")[:160]})
    return out


# ───────────────────────────────────────────── motifs d'adresse

PATTERNS = {
    "first.last": lambda f, l: f"{f}.{l}", "flast": lambda f, l: f"{f[0]}{l}", "f.last": lambda f, l: f"{f[0]}.{l}", "firstlast": lambda f, l: f"{f}{l}",
    "last": lambda f, l: l, "first_last": lambda f, l: f"{f}_{l}", "first-last": lambda f, l: f"{f}-{l}", "lastfirst": lambda f, l: f"{l}{f}", "last.first": lambda f, l: f"{l}.{f}",
}


def infer_pattern(db: Session, outlet: Outlet) -> tuple[str, str] | None:
    """(pattern, domaine) si ≥ 2 mails vérifiés de journalistes du média suivent le même motif."""
    rows = (db.query(JournalistContact, Journalist).join(Journalist, Journalist.id == JournalistContact.journalist_id)
            .filter(Journalist.outlet_id == outlet.id, JournalistContact.kind == "email", JournalistContact.confidence == "verified", JournalistContact.invalid == 0).all())
    votes: Counter = Counter()
    for c, j in rows:
        f, l = _name_parts(j.name)
        local, _, dom = c.value.partition("@")
        for name, fn in PATTERNS.items():
            if f and l and fn(f, l) == _norm(local).replace(" ", ""):
                votes[(name, dom)] += 1
    if not votes:
        return None
    (pat, dom), n = votes.most_common(1)[0]
    return (pat, dom) if n >= 2 else None


def apply_pattern(db: Session, outlet: Outlet) -> int:
    p = infer_pattern(db, outlet)
    if not p:
        return 0
    pat, dom = p
    have = {c.journalist_id for c in db.query(JournalistContact.journalist_id).filter(JournalistContact.kind == "email").join(Journalist, Journalist.id == JournalistContact.journalist_id).filter(Journalist.outlet_id == outlet.id).all()}
    n = 0
    for j in db.query(Journalist).filter(Journalist.outlet_id == outlet.id).all():
        if j.id in have:
            continue
        f, l = _name_parts(j.name)
        if not f or not l or len(l) < 3:
            continue
        addr = f"{PATTERNS[pat](f, l)}@{dom}"
        n += upsert_many(db, j.id, [{"kind": "email", "value": addr, "confidence": "guess", "method": "pattern", "note": f"motif {pat}@{dom} observé sur ≥ 2 adresses vérifiées du média"}], None)
    return n


# ───────────────────────────────────────────── passe par journaliste

def discover(db: Session, j: Journalist, fetch_pages: bool = True, bluesky: bool = True) -> dict:
    outlet = db.get(Outlet, j.outlet_id)
    dom = _outlet_domain(outlet) if outlet else ""
    exclude = _site_wide_links(db, outlet) if outlet else set()
    found: list[dict] = []
    src = None
    arts = db.query(Article.id, Article.url).filter(Article.journalist_id == j.id, ~Article.url.like("%news.google.com%")).order_by(Article.published_at.desc()).limit(8).all()
    for aid, url in arts:
        a = db.get(Article, aid)
        if a.raw_html:
            f = extract_from_html(a.raw_html, j.name, dom, exclude, outlet)
            if f:
                upsert_many(db, j.id, f, url)
                found += f
        f2 = extract_from_text(a.text or "", j.name)
        if f2:
            upsert_many(db, j.id, f2, url)
            found += f2
        db.expunge(a)
    pages = 0
    if fetch_pages:
        author_pages = [c.value for c in db.query(JournalistContact).filter(JournalistContact.journalist_id == j.id, JournalistContact.kind == "author_page", JournalistContact.invalid == 0).all()]
        for url in author_pages[:2]:
            html = extract.fetch_html(url)
            pages += 1
            if html:
                f = extract_from_author_page(html, j.name, dom, exclude, outlet)
                if f:
                    upsert_many(db, j.id, f, url)
                    found += f
    if bluesky and outlet and not any(f["kind"] == "bluesky" for f in found):
        f = bluesky_lookup(j.name, outlet)
        if f:
            upsert_many(db, j.id, f, "https://bsky.app")
            found += f
    scan = db.get(ContactScan, j.id) or ContactScan(journalist_id=j.id)
    scan.scanned_at, scan.found, scan.pages_fetched = datetime.utcnow(), len(_dedupe(found)), pages
    db.add(scan)
    db.commit()
    return {"journalist_id": j.id, "found": len(_dedupe(found)), "pages": pages}


def run_discovery(db: Session, limit: int = 100, fetch_pages: bool = True, bluesky: bool = True, rescan_days: int = 30) -> dict:
    """Journalistes jamais scannés (ou anciens), les plus productifs d'abord."""
    from datetime import timedelta
    cutoff = datetime.utcnow() - timedelta(days=rescan_days)
    counts = db.query(Article.journalist_id, func.count(Article.id).label("n")).filter(Article.journalist_id.isnot(None)).group_by(Article.journalist_id).subquery()
    q = (db.query(Journalist).join(counts, counts.c.journalist_id == Journalist.id).outerjoin(ContactScan, ContactScan.journalist_id == Journalist.id)
         .filter((ContactScan.scanned_at.is_(None)) | (ContactScan.scanned_at < cutoff)).order_by(counts.c.n.desc()).limit(limit))
    js = q.all()
    stats = {"journalists": len(js), "with_new_contacts": 0, "contacts": 0, "pattern_guesses": 0}
    with _lock:
        STATE.update(running=True, total=len(js), done=0, stats=stats, started_at=time.time(), finished_at=None)
    try:
        for i, j in enumerate(js):
            try:
                r = discover(db, j, fetch_pages=fetch_pages, bluesky=bluesky)
                if r["found"]:
                    stats["with_new_contacts"] += 1
                    stats["contacts"] += r["found"]
            except Exception as e:  # noqa: BLE001
                db.rollback()
                log.warning("contacts discover %s: %s", j.name, e)
            STATE["done"] = i + 1
        for o in db.query(Outlet).all():
            try:
                stats["pattern_guesses"] += apply_pattern(db, o)
            except Exception as e:  # noqa: BLE001
                db.rollback()
                log.warning("pattern %s: %s", o.name, e)
    finally:
        with _lock:
            STATE.update(running=False, finished_at=time.time())
    return stats


def start_background(limit: int = 300, fetch_pages: bool = True) -> bool:
    with _lock:
        if STATE["running"]:
            return False
        STATE["running"] = True

    def _run():
        from ..database import SessionLocal
        s = SessionLocal()
        try:
            run_discovery(s, limit=limit, fetch_pages=fetch_pages)
        finally:
            s.close()

    from contextvars import copy_context
    threading.Thread(target=copy_context().run, args=(_run,), name="contacts", daemon=True).start()
    return True


def purge_bad_contacts(db: Session) -> int:
    """Nettoyage après durcissement des règles : boîtes de service, comptes du média, handles mal formés."""
    n = 0
    outlets = {o.id: o for o in db.query(Outlet).all()}
    for c, j in db.query(JournalistContact, Journalist).join(Journalist, Journalist.id == JournalistContact.journalist_id).filter(JournalistContact.method != "manual").all():
        bad = False
        if c.kind == "email" and (c.method in ("author_page", "article_text") and not _email_matches(c.value, j.name) or _generic_mailbox(c.value)):
            bad = True
        if c.kind in ("x", "bluesky", "instagram", "threads", "facebook", "mastodon") and _is_outlet_account(c.value, outlets.get(j.outlet_id)):
            bad = True
        if c.kind == "x" and not re.fullmatch(r"@[A-Za-z0-9_]{1,15}", c.value):
            fixed = "@" + c.value.lstrip("@")
            if re.fullmatch(r"@[A-Za-z0-9_]{1,15}", fixed):
                c.value = fixed
            else:
                bad = True
        if c.kind == "bluesky" and c.method == "bluesky_search":
            first, last = _name_parts(j.name)
            hd = _norm(c.value).replace(" ", "")
            if not (last and last in hd) and not (first and first in hd):
                bad = True
        if bad:
            db.delete(c)
            n += 1
    db.commit()
    return n


def purge_unsourced_handles(db: Session) -> int:
    """Retire les handles X / LinkedIn devinés par le LLM (aucun contact ne les étaye)."""
    n = 0
    for j in db.query(Journalist).filter((Journalist.twitter_handle.isnot(None)) | (Journalist.linkedin_url.isnot(None))).all():
        kinds = {c.kind for c in db.query(JournalistContact.kind).filter(JournalistContact.journalist_id == j.id, JournalistContact.invalid == 0, JournalistContact.confidence.in_(["verified", "probable"])).all()}
        changed = False
        if j.twitter_handle and "x" not in kinds:
            j.twitter_handle, changed = None, True
        if j.linkedin_url and "linkedin" not in kinds:
            j.linkedin_url, changed = None, True
        n += changed
    db.commit()
    return n


def stats(db: Session) -> dict:
    total_j = db.query(func.count(Journalist.id)).scalar() or 0
    with_any = db.query(func.count(func.distinct(JournalistContact.journalist_id))).filter(JournalistContact.invalid == 0).scalar() or 0
    direct = db.query(func.count(func.distinct(JournalistContact.journalist_id))).filter(JournalistContact.invalid == 0, JournalistContact.kind.in_(["email", "x", "bluesky", "mastodon", "linkedin"]), JournalistContact.confidence.in_(["verified", "probable"])).scalar() or 0
    by_kind = dict(db.query(JournalistContact.kind, func.count()).filter(JournalistContact.invalid == 0).group_by(JournalistContact.kind).all())
    scanned = db.query(func.count(ContactScan.journalist_id)).scalar() or 0
    return {"journalists": total_j, "with_contacts": with_any, "directly_reachable": direct, "by_kind": by_kind, "scanned": scanned, "job": STATE}
