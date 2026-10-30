"""Headless browser scraping via Playwright — for sites that require JS rendering."""

import logging
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

from sqlalchemy.orm import Session

from ..models import Article, IngestionLog, Journalist, Outlet
from .extract import choose_coverage, detect_language, is_boilerplate, strip_boilerplate
from .rss import _match_or_create_journalist, _save_article

log = logging.getLogger("tacite.scraping")

MAX_NEW_PER_RUN = 100

# Playwright is optional — graceful fallback if not installed
_pw_available = False
try:
    from playwright.sync_api import sync_playwright
    _pw_available = True
except ImportError:
    pass


def _is_article_url(url: str, base_host: str) -> bool:
    parsed = urlparse(url)
    if parsed.netloc != base_host:
        return False
    path = parsed.path
    if len(path) < 20:
        return False
    # Must have a date-like segment OR known article patterns
    if re.search(r"/\d{4}/\d{2}/", path):
        return True
    if re.search(r"/(article|story|post|entry|bericht|articulo|articolo|actu)", path, re.I):
        return True
    # DPG (HLN, De Standaard…) : slug~a<hex> ou /123456.html
    if re.search(r"~a[0-9a-f]{5,}", path, re.I) or re.search(r"/\d{6,}\.html$", path):
        return True
    # Heuristic: paths with 3+ segments and no file extension are often articles
    segments = [s for s in path.split("/") if s]
    if len(segments) >= 3 and "." not in segments[-1]:
        return True
    return False


def scrape_with_playwright(db: Session, outlet: Outlet, start_url: str | None = None) -> int:
    """Scrape articles from a site using Playwright headless browser.
    Handles JS rendering, cookie consent banners, and lazy-loaded content."""
    if not _pw_available:
        log.warning("Playwright not installed — skipping headless scrape for %s", outlet.name)
        return 0

    url = start_url or outlet.website_url
    if not url or getattr(outlet, "collect_enabled", 1) == 0:
        return 0

    try:
        count = 0
        base_host = urlparse(url).netloc
        seen_urls = set()

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
                locale=outlet.language or "fr-FR",
            )
            page = context.new_page()

            # Load homepage (domcontentloaded avoids 30s timeouts on news sites with continuous ad/analytics beacons)
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1500)

            # Try to dismiss common cookie consent banners (y compris la porte DPG « Akkoord »)
            consent_selectors = [
                "button:has-text('Accept')", "button:has-text('Accepter')",
                "button:has-text('Accept All')", "button:has-text('Tout accepter')",
                "button:has-text('Akzeptieren')", "button:has-text('Aceptar')",
                "button:has-text('Accetta')", "button:has-text('Akkoord')",
                "button:has-text('Accepteren')", "button:has-text('Alles accepteren')",
                "[data-testid='cookie-accept']",
                "#didomi-notice-agree-button", ".cookie-accept", ".cc-accept",
            ]
            try:
                page.wait_for_selector(", ".join(consent_selectors[:8]), timeout=8000)
            except Exception:  # noqa: BLE001
                pass
            try:
                for selector in consent_selectors:
                    btn = page.query_selector(selector)
                    if not btn:
                        continue
                    try:
                        with page.expect_navigation(wait_until="domcontentloaded", timeout=15000):
                            btn.click()
                    except Exception:  # noqa: BLE001
                        page.wait_for_timeout(1000)
                    page.wait_for_timeout(800)
                    break
            except Exception:  # noqa: BLE001
                pass

            # Collect article links from the page
            links = page.eval_on_selector_all("a[href]", "els => els.map(a => a.href)")
            article_urls = []
            for href in links:
                full_url = urljoin(url, href.split("#")[0])
                if full_url in seen_urls:
                    continue
                seen_urls.add(full_url)
                if _is_article_url(full_url, base_host):
                    article_urls.append(full_url)

            # Visit each article URL and extract content
            for art_url in article_urls[:MAX_NEW_PER_RUN]:
                existing = db.query(Article).filter(Article.url == art_url).first()
                if existing and existing.text_coverage != "excerpt":
                    continue
                try:
                    page.goto(art_url, wait_until="domcontentloaded", timeout=15000)
                    page.wait_for_timeout(500)  # Let lazy content load

                    title = page.title()
                    # Extract article text: try article/main content first, fall back to body
                    text = None
                    for selector in ["article", "main", "[role='main']", ".article-body", ".post-content", "#article-body"]:
                        el = page.query_selector(selector)
                        if el:
                            text = el.inner_text()
                            if text and len(text) > 200:
                                break
                    if not text or len(text) < 200:
                        text = page.query_selector("body").inner_text() if page.query_selector("body") else None

                    if text:
                        text = strip_boilerplate(text)
                    desc = None
                    for desc_sel in ["meta[property='og:description']", "meta[name='description']", "meta[name='twitter:description']"]:
                        desc_el = page.query_selector(desc_sel)
                        if desc_el:
                            desc = desc_el.get_attribute("content")
                            if desc:
                                break
                    body = text if text and not is_boilerplate(text, title) else None
                    chosen, coverage = choose_coverage(body, desc, title)
                    if not chosen:
                        continue

                    # Try to get author from common meta tags
                    author = None
                    for meta_sel in [
                        "meta[name='author']", "meta[property='article:author']",
                        "meta[name='dc.creator']",
                    ]:
                        meta = page.query_selector(meta_sel)
                        if meta:
                            author = meta.get_attribute("content")
                            if author:
                                break

                    journalist_id = _match_or_create_journalist(db, outlet, author)
                    if existing and coverage == "body":
                        existing.text = chosen
                        existing.text_coverage = "body"
                        existing.language = detect_language(chosen, outlet.language or "fr")
                        existing.analysis_status = "pending"
                        existing.embedding = None
                        existing.extracted_data = None
                        existing.duplicate_of_id = None
                        if journalist_id and not existing.journalist_id:
                            existing.journalist_id = journalist_id
                        db.commit()
                        count += 1
                        continue
                    if existing:
                        continue

                    db.add(Article(
                        outlet_id=outlet.id,
                        journalist_id=journalist_id,
                        url=art_url,
                        title=title[:500] if title else art_url,
                        text=chosen,
                        raw_html=None,
                        language=detect_language(chosen, outlet.language or "fr"),
                        published_at=datetime.utcnow(),
                        analysis_status="pending",
                        text_coverage=coverage,
                    ))
                    db.commit()
                    count += 1
                except Exception as e:  # noqa: BLE001
                    log.debug("Failed to scrape article %s: %s", art_url, e)
                    db.rollback()
                    continue

            browser.close()

        _log_scrape(db, outlet.id, "playwright", "ok", count)
        return count
    except Exception as e:  # noqa: BLE001
        log.warning("Playwright scraping failed for %s: %s", outlet.name, e)
        _log_scrape(db, outlet.id, "playwright", "error", 0, str(e)[:500])
        return 0


def _log_scrape(db: Session, outlet_id: int, feed_type: str, status: str, count: int = 0, error: str | None = None):
    db.add(IngestionLog(outlet_id=outlet_id, feed_type=feed_type, status=status,
                        articles_captured=count, error_message=error))
    db.commit()
