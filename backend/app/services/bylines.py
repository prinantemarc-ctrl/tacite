"""Signatures : extraction des auteurs depuis le HTML des articles (JSON-LD, rel=author, meta).

Sert à l'ingestion (quand le flux RSS ne donne pas l'auteur) et au rattrapage des articles déjà
en base sans journaliste. Renvoie aussi l'URL de la page auteur quand elle existe : c'est une
source de contacts.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime

from sqlalchemy.orm import Session

from ..models import Article, ArticleJournalist, Journalist, JournalistContact, Outlet

log = logging.getLogger("tacite.bylines")

_JSONLD_RE = re.compile(r'<script[^>]+type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)
_REL_AUTHOR_RE = re.compile(r'<a\b[^>]*\brel=["\'][^"\']*\bauthor\b[^"\']*["\'][^>]*>(.*?)</a>', re.I | re.S)
_HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.I)
_META_AUTHOR_RE = re.compile(r'<meta\b[^>]+(?:name|property)=["\'](?:author|article:author|dc\.creator|parsely-author|sailthru\.author|byl)["\'][^>]*\bcontent=["\']([^"\']+)["\']', re.I)
_META_AUTHOR_RE2 = re.compile(r'<meta\b[^>]+\bcontent=["\']([^"\']+)["\'][^>]+(?:name|property)=["\'](?:author|article:author|dc\.creator|parsely-author)["\']', re.I)
_BYLINE_CLASS_RE = re.compile(r'<(?:a|span|div|p)\b[^>]*class=["\'][^"\']*(?:byline|author|signature|autor|auteur|firma)[^"\']*["\'][^>]*>(.*?)</(?:a|span|div|p)>', re.I | re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _text(s: str) -> str:
    s = _TAG_RE.sub(" ", s or "")
    s = re.sub(r"&nbsp;|&#160;", " ", s)
    s = re.sub(r"&amp;", "&", s)
    s = re.sub(r"&#39;|&apos;", "'", s)
    return re.sub(r"\s+", " ", s).strip()


def _iter_jsonld(html: str):
    for m in _JSONLD_RE.finditer(html):
        raw = m.group(1).strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            try:
                data = json.loads(re.sub(r",\s*([}\]])", r"\1", raw))
            except json.JSONDecodeError:
                continue
        stack = data if isinstance(data, list) else [data]
        while stack:
            d = stack.pop()
            if isinstance(d, dict):
                yield d
                if isinstance(d.get("@graph"), list):
                    stack.extend(d["@graph"])
                for k in ("mainEntity", "mainEntityOfPage"):
                    if isinstance(d.get(k), dict):
                        stack.append(d[k])


def extract_authors(html: str | None) -> list[dict]:
    """[{name, url, same_as:[...], email}] — Person uniquement (les Organization sont ignorées)."""
    if not html:
        return []
    out: list[dict] = []
    seen: set[str] = set()

    def add(name: str | None, url: str | None = None, same_as=None, email=None):
        name = _text(name or "")
        if not name or len(name) > 80:
            return
        k = name.lower()
        if k in seen:
            return
        seen.add(k)
        out.append({"name": name, "url": url, "same_as": [s for s in (same_as or []) if isinstance(s, str)], "email": email})

    for d in _iter_jsonld(html):
        t = d.get("@type")
        types = t if isinstance(t, list) else [t]
        if any(x in ("NewsArticle", "Article", "ReportageNewsArticle", "AnalysisNewsArticle", "OpinionNewsArticle", "BlogPosting", "LiveBlogPosting") for x in types):
            authors = d.get("author") or d.get("creator")
            if authors is None:
                continue
            for a in (authors if isinstance(authors, list) else [authors]):
                if isinstance(a, str):
                    add(a)
                elif isinstance(a, dict):
                    at = a.get("@type")
                    ats = at if isinstance(at, list) else [at]
                    if any(x in ("Organization", "NewsMediaOrganization") for x in ats):
                        continue
                    url = a.get("url") or a.get("@id")
                    url = url if isinstance(url, str) and url.startswith("http") and "#" not in url else None
                    sa = a.get("sameAs")
                    sa = sa if isinstance(sa, list) else ([sa] if isinstance(sa, str) else [])
                    email = a.get("email") if isinstance(a.get("email"), str) else None
                    add(a.get("name"), url, sa, email)
    if not out:
        for m in _REL_AUTHOR_RE.finditer(html):
            href = _HREF_RE.search(m.group(0))
            add(m.group(1), href.group(1) if href else None)
    if not out:
        for rx in (_META_AUTHOR_RE, _META_AUTHOR_RE2):
            for m in rx.finditer(html):
                v = m.group(1)
                if v and not v.startswith("http"):
                    for part in re.split(r",| et | and | y | und ", v):
                        add(part)
                if out:
                    break
    if not out:
        for m in _BYLINE_CLASS_RE.finditer(html[:400_000]):
            t = _text(m.group(1))
            if 4 <= len(t) <= 60 and " " in t and not re.search(r"\d{2}", t):
                href = _HREF_RE.search(m.group(0))
                add(t, href.group(1) if href else None)
                if len(out) >= 2:
                    break
    return out


def attach_from_html(db: Session, article: Article, outlet: Outlet, html: str | None) -> Journalist | None:
    """Rattache l'article à tous les auteurs personnes trouvés ; le premier devient journalist_id."""
    from .rss import _match_or_create_journalist
    authors = extract_authors(html)
    attached: list[tuple[int, dict, int]] = []
    for i, a in enumerate(authors):
        jid = _match_or_create_journalist(db, outlet, a["name"])
        if not jid:
            continue
        attached.append((jid, a, i))
    if not attached:
        return None
    article.journalist_id = attached[0][0]
    for jid, a, i in attached:
        db.merge(ArticleJournalist(article_id=article.id, journalist_id=jid, position=i))
        j = db.get(Journalist, jid)
        if j:
            _record_author_sources(db, j, a, article.url)
    return db.get(Journalist, attached[0][0])


def _record_author_sources(db: Session, j: Journalist, a: dict, source_url: str) -> None:
    from . import contacts
    found = []
    if a.get("url") and a["url"].startswith("http"):
        found.append({"kind": "author_page", "value": a["url"], "confidence": "verified", "method": "jsonld"})
    if a.get("email") and "@" in a["email"]:
        found.append({"kind": "email", "value": a["email"].strip().lower(), "confidence": "verified", "method": "jsonld"})
    for s in a.get("same_as") or []:
        c = contacts.classify_url(s)
        if c:
            found.append({**c, "confidence": "verified", "method": "jsonld"})
    if found:
        contacts.upsert_many(db, j.id, found, source_url)


def backfill(db: Session, limit: int | None = None, only_outlet_id: int | None = None) -> dict:
    """Rattrape les articles sans journaliste dont on a le HTML (hors pages Google News)."""
    q = db.query(Article.id).filter(Article.journalist_id.is_(None), Article.raw_html.isnot(None), ~Article.url.like("%news.google.com%"))
    if only_outlet_id:
        q = q.filter(Article.outlet_id == only_outlet_id)
    ids = [r[0] for r in q.order_by(Article.id.desc()).all()]
    if limit:
        ids = ids[:limit]
    outlets = {o.id: o for o in db.query(Outlet).all()}
    stats = {"scanned": 0, "attached": 0, "created": 0}
    before = db.query(Journalist).count()
    for i, id_ in enumerate(ids):
        a = db.get(Article, id_)
        if not a or not a.raw_html:
            continue
        stats["scanned"] += 1
        try:
            j = attach_from_html(db, a, outlets[a.outlet_id], a.raw_html)
            if j:
                stats["attached"] += 1
            db.commit()
        except Exception as e:  # noqa: BLE001
            db.rollback()
            log.debug("byline backfill %s: %s", id_, e)
        db.expunge(a)  # libère le HTML
        if (i + 1) % 200 == 0:
            log.info("bylines backfill %d/%d %s", i + 1, len(ids), stats)
    stats["created"] = db.query(Journalist).count() - before
    return stats
