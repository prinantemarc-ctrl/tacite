"""Lecture des sitemaps : index, sitemap news, URLs d'articles récentes."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import urlparse
from xml.etree import ElementTree as ET

_SKIP_EXT = (".jpg", ".jpeg", ".png", ".gif", ".webp", ".pdf", ".xml", ".mp4", ".css", ".js", ".svg")
_SKIP_PARTS = {"tag", "tags", "author", "authors", "category", "categories", "login", "subscribe", "search", "newsletter"}


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _parse_when(value: str | None) -> datetime | None:
    if not value:
        return None
    raw = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
    return parsed


def parse_sitemap(body: bytes) -> tuple[str, list[dict]]:
    """('index'|'urlset'|'unknown', entrées).

    Un index donne loc et lastmod. Un urlset donne loc, title, published et news.
    """
    if body[:2] == b"\x1f\x8b":
        import gzip
        try:
            body = gzip.decompress(body)
        except OSError:
            return "unknown", []
    try:
        root = ET.fromstring(body)
    except ET.ParseError:
        return "unknown", []
    kind = _local(root.tag)
    if kind == "sitemapindex":
        items = []
        for node in root:
            if _local(node.tag) != "sitemap":
                continue
            loc = lastmod = None
            for child in node:
                name = _local(child.tag)
                if name == "loc":
                    loc = (child.text or "").strip()
                elif name == "lastmod":
                    lastmod = (child.text or "").strip()
            if loc:
                items.append({"loc": loc, "lastmod": lastmod})
        return "index", items
    if kind == "urlset":
        items = []
        for node in root:
            if _local(node.tag) != "url":
                continue
            loc = title = published = caption = None
            news = False
            for child in node:
                name = _local(child.tag)
                if name == "loc":
                    loc = (child.text or "").strip()
                elif name == "lastmod":
                    published = (child.text or "").strip()
                elif name == "image":
                    for sub in child:
                        if _local(sub.tag) == "caption" and sub.text:
                            caption = sub.text.strip()
                elif name == "news":
                    news = True
                    for sub in child:
                        sub_name = _local(sub.tag)
                        if sub_name == "title" and sub.text:
                            title = sub.text.strip()
                        elif sub_name == "publication_date" and sub.text:
                            published = sub.text.strip()
            if loc:
                items.append({"loc": loc, "title": title, "caption": caption, "published": published, "news": news})
        return "urlset", items
    return "unknown", []


def _same_site(article_url: str, website: str) -> bool:
    article_host = urlparse(article_url).netloc.lower().removeprefix("www.")
    site_host = urlparse(website).netloc.lower().removeprefix("www.")
    if not article_host or not site_host:
        return False
    return article_host == site_host or article_host.endswith("." + site_host)


def _is_article(url: str, news: bool) -> bool:
    if news:
        return True
    path = urlparse(url).path.lower()
    if path in ("", "/"):
        return False
    if path.endswith(_SKIP_EXT):
        return False
    parts = [part for part in path.split("/") if part]
    if parts and parts[0] in _SKIP_PARTS:
        return False
    return bool(re.search(r"/20\d{2}/", path) or len(path) > 30)


def select_sitemap_articles(entries: list[dict], website: str, now: datetime | None = None) -> list[dict]:
    """Garde les URLs d'articles du même site, y compris les archives."""
    chosen = []
    seen: set[str] = set()
    for entry in entries:
        url = entry.get("loc") or ""
        if not url.startswith("http") or url in seen or not _same_site(url, website):
            continue
        if not _is_article(url, bool(entry.get("news"))):
            continue
        seen.add(url)
        chosen.append({
            "url": url,
            "title": entry.get("title") or url,
            "caption": entry.get("caption"),
            "published": _parse_when(entry.get("published")),
        })
    return chosen


def _child_score(loc: str) -> int:
    low = loc.lower()
    score = 0
    if "news" in low:
        score += 5
    if "article" in low or "post" in low:
        score += 2
    if any(token in low for token in ("image", "video", "tag", "author", "categor")):
        score -= 5
    return score


def article_excerpt(title: str | None, caption: str | None, url: str = "") -> str | None:
    """Texte gardé quand la page elle-même ne se laisse pas lire : titre, et légende si elle fait phrase."""
    title = re.sub(r"\s+", " ", (title or "")).strip()
    caption = re.sub(r"\s+", " ", (caption or "")).strip()
    if title.startswith("http") or title == url:
        title = ""
    if caption.startswith("http"):
        caption = ""
    if len(caption) >= 60 and caption.lower() not in title.lower():
        if title and title.lower() not in caption.lower():
            return f"{title}. {caption}"[:2000]
        return caption[:2000]
    if len(title) >= 40:
        return title
    if len(caption) >= 40:
        return caption
    return None


def google_article_id(url: str) -> str | None:
    """Identifiant stable d'un lien news.google.com/rss/articles/…, sans rappeler Google."""
    if "news.google.com/" not in (url or ""):
        return None
    marker = "/articles/"
    i = url.find(marker)
    if i < 0:
        return None
    token = url[i + len(marker):].split("?")[0].split("#")[0].strip()
    return token or None


def rank_sitemap_children(items: list[dict]) -> list[dict]:
    """Sitemaps d'actualités d'abord, puis les archives. Les sitemaps d'images sont écartés."""
    ranked = sorted(items, key=lambda item: (_child_score(item["loc"]), item.get("lastmod") or ""), reverse=True)
    chosen = [item for item in ranked if _child_score(item["loc"]) >= 0]
    return chosen or ranked[:1]
