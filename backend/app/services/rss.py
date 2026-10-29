"""RSS/Atom ingestion, sitemap fallback, homepage scraping, multi-feed support."""

import logging
import re
import time
from datetime import datetime, timedelta
from urllib.parse import urljoin, urlparse

import feedparser
import httpx
from sqlalchemy.orm import Session

from ..models import Article, ArticleJournalist, IngestionLog, Journalist, Outlet, OutletFeed
from .sitemap import article_excerpt, google_article_id, parse_sitemap, rank_sitemap_children, select_sitemap_articles
from .extract import (
    EXCERPT_MIN, HEADERS, choose_coverage, detect_language, extract_text, fetch_article,
    fetch_html, google_blocked, is_boilerplate, is_google_news_url, lead_from_html,
    resolve_google_news_url, GoogleRateLimited,
)

log = logging.getLogger("tacite.rss")

MAX_NEW_PER_RUN = 30
MAX_NEW_PER_RUN_GOOGLE = 10  # chaque lien Google News coûte deux requêtes espacées : on reste discret


def _log(db: Session, outlet_id: int, feed_type: str, status: str, count: int = 0, error: str | None = None):
    db.add(IngestionLog(outlet_id=outlet_id, feed_type=feed_type, status=status,
                        articles_captured=count, error_message=error))
    db.commit()


_GENERIC_AUTHOR_RE = re.compile(
    r"\b(agence|agency|presse|press|rédaction|redaction|redazione|redacción|redactie|"
    r"staff|stagiaire|service|desk|regions?|équipe|team|correspondants?|envoyés?|"
    r"édito|editorial|newsroom|news|sport|économie|politique|culture|société|international)\b",
    re.I,
)

_MEDIA_NAMES = {
    "the guardian", "guardian sport", "guardian staff", "guardian",
    "el país", "el mundo", "la croix", "corriere", "abc",
    "press association", "associated press", "australian associated press",
    "agencias", "agencias .", "redazione online", "redazione economia",
    "reuters", "afp", "ap", "dpa", "epa", "sda", "ats", "ansa",
    "words", "presented", "corriere della sera", "la repubblica",
    "der spiegel", "die welt", "süddeutsche zeitung", "faz",
    "le monde", "le figaro", "libération", "les échos", "france info",
    "médiasport", "rtl", "le parisien", "l'opinion", "courrier international",
    "valeurs actuelles", "bbc news", "bbc", "the times", "nzz",
    "le soir", "la libre belgique", "de standaard", "hln",
    "il giornale", "the daily telegraph", "the telegraph",
    "belga", "belga belga", "afp -", "afp belga", "keystone-ats", "keystone ats", "adnkronos", "agi", "efe", "europa press", "servimedia",
    "pa media", "reuters staff", "bloomberg", "la libre", "le soir", "rtbf", "france télévisions", "franceinfo", "franceinfo avec afp",
    "le monde avec afp", "le figaro avec afp", "libération avec afp", "afp/le monde", "with agencies", "agencies",
}

# Byline prefixes: "Recueilli par Emmanuel Pellat" → "Emmanuel Pellat"
_PREFIX_RE = re.compile(
    r"^(propos recueillis par|recueilli[s]? par|entretien avec|interview de|presented by|hosted by|"
    r"live animé par|animé par|texte de|texte :|photos? de|written by|words by|photographs? by|par|by|von|door|di|de)\s+", re.I
)
# Datelines pris pour des signatures (presse espagnole / italienne)
_DATELINE = {
    "santiago de compostela", "palma de mallorca", "san sebastián", "san sebastian", "las palmas", "ciudad de méxico", "ciudad de mexico",
    "buenos aires", "nueva york", "new york", "los angeles", "città del vaticano", "reggio emilia", "reggio calabria", "la spezia", "santa cruz de tenerife",
}
# Role keyword: everything from here to the end is a job title
_ROLE_RE = re.compile(
    r"\s+(editor|correspondent|reporter|columnist|writer|critic|commentator|analyst|"
    r"journalist|presenter|producer|photographer|head of\b|"
    r"rédacteur|rédactrice|chroniqueu(?:r|se)|correspondant[e]?|envoyé[e]?\s+spécial[e]?|"
    r"grand reporter|éditorialiste|redattore|redattrice|redactor[a]?|redakteur(?:in)?|"
    r"korrespondent(?:in)?)\b.*$",
    re.I,
)
# Words that qualify a role and may precede the role keyword ("Senior political", "Economics")
_ROLE_MODIFIERS = {
    "senior", "chief", "deputy", "associate", "assistant", "executive", "special", "global",
    "political", "politics", "economics", "economic", "business", "financial", "finance", "money",
    "education", "health", "science", "technology", "tech", "consumer", "digital", "data",
    "diplomatic", "foreign", "home", "social", "affairs", "indigenous", "environment", "energy",
    "climate", "transport", "housing", "policy", "legal", "justice", "crime", "defence", "defense",
    "security", "media", "arts", "culture", "music", "film", "tv", "books", "travel", "food",
    "fashion", "wine", "motoring", "property", "sports", "sport", "football", "rugby", "cricket",
    "city", "north", "south", "east", "west", "europe", "european", "uk", "us", "ireland",
    "scotland", "wales", "africa", "asia", "latin", "america", "middle", "international",
    "world", "national", "industrial", "investigations", "community", "religion", "personal",
    "washington", "brussels", "paris", "berlin", "rome", "madrid", "moscow", "beijing",
    "midlands", "london", "yorkshire", "westminster", "whitehall", "sydney", "melbourne",
    "canberra", "australia", "pacific", "scandinavia", "balkans", "caucasus", "sahel",
    "économie", "politique", "société", "culture", "international", "justice", "éducation",
    "santé", "environnement", "sciences", "médias", "sports",
}


# Particules et connecteurs admis en minuscules à l'intérieur d'un nom
_PARTICLES = {
    "de", "du", "des", "della", "delle", "del", "dell", "di", "da", "dos", "das", "la", "le", "les", "van", "von", "der", "den", "ten", "ter",
    "y", "e", "d", "l", "al", "bin", "ibn", "mac", "mc", "st", "saint", "zu", "zur", "af", "av", "genannt", "dit", "dite", "of", "the",
}
# Mots qui ne peuvent pas faire partie d'un nom de personne (signatures-phrases, rubriques, fonctions)
_NOT_NAME_WORDS = {
    "article", "rédigé", "redige", "rédigée", "écrit", "ecrit", "publié", "publie", "par", "avec", "pour", "sur", "dans", "mis", "à", "jour",
    "propos", "recueillis", "texte", "photo", "photos", "vidéo", "video", "live", "direct", "édition", "edition", "service", "rubrique",
    "envoyé", "envoyée", "spécial", "spéciale", "correspondant", "correspondante", "reporter", "journaliste", "journalist", "editor", "staff",
    "team", "desk", "news", "info", "infos", "rédaction", "redaction", "and", "with", "by", "from", "for", "our", "at", "on", "this", "that",
    "story", "report", "analysis", "opinion", "update", "updated", "breaking", "exclusive", "exclusif", "dossier", "enquête", "enquete",
    "chronique", "tribune", "interview", "entretien", "portrait", "reportage", "décryptage", "decryptage", "analyse", "éditorial", "editorial",
    "podcast", "newsletter", "abonnés", "abonnes", "lecteurs", "source", "sources", "agence", "agency", "agences", "presse", "press", "média",
    "media", "group", "groupe", "rédacteur", "rédactrice", "chef", "cheffe", "adjoint", "adjointe", "directeur", "directrice", "bureau",
    "international", "politique", "économie", "société", "societe", "culture", "sport", "sports", "monde", "europe", "région", "régions", "regions",
    "réalisation", "realisation", "montage", "images", "son", "sœur", "soeur", "frère", "père", "mgr", "dr", "pr", "expat", "réseau", "reseau",
    "communiqué", "publi", "sponsorisé", "partenaire", "ici", "una", "uno", "por", "para", "como", "degli", "dei", "gli",
    "und", "mit", "für", "fur", "nach", "aus", "het", "een", "met", "voor", "door", "op", "aan", "days", "ago", "hours", "minutes",
}


def looks_like_person_name(name: str) -> tuple[bool, str | None]:
    """(ok, nom normalisé). Forme d'un nom de personne : 2 à 5 mots, chacun capitalisé (ou particule, ou initiale),
    aucun mot de phrase/rubrique, au moins un mot de 3 lettres. Alphabets non latins acceptés tels quels."""
    name = re.sub(r"[\u200b\u200c\u200d\ufeff*]+", "", name or "").strip(" -–—:|/*")
    toks = [t for t in re.split(r"\s+", name) if t]
    if not 2 <= len(toks) <= 5:
        return False, None
    latin = any(re.search(r"[A-Za-zÀ-ÿ]", t) for t in toks)
    out: list[str] = []
    core = 0
    for t in toks:
        raw = t.strip("'’.,")
        low = raw.lower()
        if re.search(r"\d", t) or re.search(r"[|/${}<>=@#]", t):
            return False, None
        if re.fullmatch(r"[A-ZÀ-Ý]\.?", raw):        # initiale « J. »
            out.append(raw.rstrip(".") + ".")
            continue
        if re.fullmatch(r"(?:[A-ZÀ-Ý]\.){2,3}", t.strip(",")):   # « M.C. »
            out.append(t.strip(","))
            continue
        if low in _PARTICLES:
            out.append(raw if len(out) else raw.capitalize())   # on garde la casse d'origine (« Di Feo », « de Gaulle »)
            continue
        if low in _NOT_NAME_WORDS:
            return False, None
        if latin:
            if not raw[:1].isalpha():
                return False, None
            # « d'Ormesson », « O'Brien » : la majuscule est après l'apostrophe
            if raw[:1].islower() and not (len(raw) > 2 and raw[1] in "'’" and raw[2:3].isupper()):
                raw = raw.capitalize()                # bylines en minuscules (presse espagnole), prénom composé mal saisi
            elif raw.isupper() and len(raw) > 3:      # « DUPONT » → « Dupont »
                raw = raw.capitalize()
        if len(raw) >= 3:
            core += 1
        out.append(raw)
    if core == 0:
        return False, None
    return True, " ".join(out)


def clean_author_name(author: str | None) -> str | None:
    """Normalise a raw byline into a plausible person name, or return None if it isn't one.

    Shared by the RSS parser and the /api/journalists/cleanup endpoint so both agree.
    """
    if not author:
        return None
    author = re.sub(r"[\u200b\u200c\u200d\ufeff]", "", author)
    author = re.sub(r"\(.*?\)", "", author).strip()            # parenthetical info
    author = re.sub(r"^(réalisation|realisation|montage|texte|photos?|vidéo|video|images|son|illustration)\s*:\s*", "", author, flags=re.I)
    author = _PREFIX_RE.sub("", author.strip())
    author = re.split(r",", author)[0].strip()   # « Name, Senior correspondent »
    author = _PREFIX_RE.sub("", author)
    author = re.sub(r"\s+(in|from|for|à|en|a|da|aus)\s+[A-ZÀ-Ý]\w*.*$", "", author)  # "X in Berlin", "X for MetDesk"
    role_hit = _ROLE_RE.search(author)
    if role_hit:
        author = author[: role_hit.start()]
    author = author.strip().rstrip(".-–—:").strip()

    tokens = author.split()
    if len(tokens) == 2 and tokens[0].lower() == tokens[1].lower():   # « Belga Belga »
        return None
    # "Peter Walker Senior political" → drop trailing role modifiers while a 2-token name remains.
    # Lowercase trailing words are only dropped when a role keyword was actually found.
    while len(tokens) > 2 and (
        tokens[-1].lower() in _ROLE_MODIFIERS or (role_hit and tokens[-1].islower())
    ):
        tokens.pop()
    author = " ".join(tokens)

    if not author or len(author) < 3 or len(author) > 60 or "@" in author:
        return None
    lower = author.lower()
    if lower in _MEDIA_NAMES or lower in _DATELINE:
        return None
    if lower.startswith(("la rédaction", "le service", "la libre", "le figaro", "guardian ",
                         "redaction", "rédaction", "agencia", "servizio", "sezione", "rubrica")):
        return None
    if _GENERIC_AUTHOR_RE.search(author):                          # "Agence France-Presse", "VA Regions"
        return None
    if re.match(r"^(à|a|au|aux|le|la|les|the|il|el|die|der|das|de|het)\s", lower):  # "À l'air libre"
        return None
    if " " not in author and len(author) < 15:                     # single word
        return None
    if author.isupper() and len(author) > 10:                      # media name in caps
        return None
    if re.match(r"^[\d.\s]+$", author):
        return None
    ok, normalized = looks_like_person_name(author)                # dernière ligne de défense : la forme d'un nom
    if not ok:
        return None
    return normalized


_AUTHOR_SPLIT = re.compile(r"\s*(?:;|·|&|\||/| et | and | with | avec | y | und )\s*", re.I)


def split_author_names(raw: str | None) -> list[str]:
    """Tous les noms de personnes d'une byline, déjà normalisés."""
    if not raw:
        return []
    seen: set[str] = set()
    out: list[str] = []
    for part in _AUTHOR_SPLIT.split(raw):
        name = clean_author_name(part)
        if name and name.lower() not in seen:
            seen.add(name.lower())
            out.append(name)
    return out


def _match_or_create_journalist(db: Session, outlet: Outlet, author: str | None) -> int | None:
    author = clean_author_name(author)
    if not author:
        return None
    existing = (
        db.query(Journalist)
        .filter(Journalist.outlet_id == outlet.id, Journalist.name.ilike(author))
        .first()
    )
    if existing:
        return existing.id
    j = Journalist(name=author, outlet_id=outlet.id, role="Journaliste")
    db.add(j)
    db.commit()
    return j.id


def _clean_title(title: str | None, outlet: Outlet) -> str | None:
    """Retire le suffixe « - Nom du média » des titres Google News ; rejette les titres vides."""
    if not title:
        return None
    t = title.strip()
    t = re.sub(r"\s+[-–|]\s+[^-–|]{2,40}$", "", t) if len(t) > 45 else t
    t = t.strip(" -–|")
    return t[:500] if len(t) >= 8 else None


def _by_url(db: Session, url: str) -> Article | None:
    return db.query(Article).filter(Article.url == url).first()


def _attach_bylines(db: Session, art: Article, outlet: Outlet, raw_html: str | None) -> None:
    if art.journalist_id or not raw_html:
        return
    try:
        from . import bylines
        if bylines.attach_from_html(db, art, outlet, raw_html):
            db.commit()
    except Exception as e:  # noqa: BLE001
        db.rollback()
        log.debug("byline from html failed %s: %s", art.url, e)


def _usable_lead(text: str | None, title: str | None) -> str | None:
    text = (text or "").strip()
    if len(text) >= EXCERPT_MIN and not is_boilerplate(text, title):
        return text
    return None


def _insert_article(db: Session, outlet: Outlet, url: str, title: str, published: datetime | None,
                    author: str | None, text: str, raw_html: str | None, coverage: str) -> bool:
    names = split_author_names(author)
    ids = [_match_or_create_journalist(db, outlet, n) for n in names]
    ids = [i for i in ids if i]
    art = Article(
        outlet_id=outlet.id,
        journalist_id=ids[0] if ids else None,
        url=url,
        title=_clean_title(title, outlet) or url,
        text=text,
        raw_html=raw_html,
        language=detect_language(text, outlet.language or "fr"),
        published_at=published or datetime.utcnow(),
        analysis_status="pending",
        text_coverage=coverage,
    )
    db.add(art)
    db.commit()
    for i, jid in enumerate(ids):
        db.merge(ArticleJournalist(article_id=art.id, journalist_id=jid, position=i))
    if ids:
        db.commit()
    _attach_bylines(db, art, outlet, raw_html)
    return True


def _save_article(db: Session, outlet: Outlet, url: str, title: str,
                  published: datetime | None, author: str | None,
                  fallback_text: str | None = None) -> bool:
    """Pose le chapô du flux tout de suite. La page n'est lue que pour obtenir un corps,
    ou quand le flux n'a pas de chapô. Un chapô déjà stocké est remplacé si le corps arrive.
    """
    existing = _by_url(db, url)
    if existing and existing.text_coverage != "excerpt":
        return False
    lead = _usable_lead(fallback_text, title)
    if existing is None and lead and not is_google_news_url(url):
        return _insert_article(db, outlet, url, title, published, author, lead, None, "excerpt")
    if existing is None and lead and is_google_news_url(url):
        try:
            resolved = resolve_google_news_url(url)
        except GoogleRateLimited:
            resolved = None
        if resolved:
            other = _by_url(db, resolved)
            if other and other.text_coverage != "excerpt":
                return False
            if other is None:
                return _insert_article(db, outlet, resolved, title, published, author, lead, None, "excerpt")
            existing = other
    db.commit()
    raw_html, text, final_url = fetch_article(url)
    if final_url != url:
        other = _by_url(db, final_url)
        if other and other is not existing:
            if other.text_coverage != "excerpt":
                return False
            existing = other
    lead = _usable_lead(fallback_text, title)
    meta = lead_from_html(raw_html)
    if meta and (not lead or len(meta) > len(lead)):
        lead = meta
    body = text if text and not is_boilerplate(text, title) else None
    chosen, coverage = choose_coverage(body, lead, title)
    if not chosen:
        return False
    clean_title = _clean_title(title, outlet) or final_url
    if existing:
        if coverage != "body":
            return False
        existing.url = final_url
        existing.text = chosen
        existing.raw_html = raw_html or existing.raw_html
        existing.text_coverage = "body"
        existing.language = detect_language(chosen, outlet.language or "fr")
        existing.analysis_status = "pending"
        existing.embedding = None
        existing.extracted_data = None
        existing.duplicate_of_id = None
        if clean_title and existing.title == existing.url:
            existing.title = clean_title
        db.commit()
        _attach_bylines(db, existing, outlet, raw_html)
        return True
    if is_google_news_url(final_url):
        return False
    return _insert_article(db, outlet, final_url, title, published, author, chosen, raw_html, coverage)


def _ingest_feed(db: Session, outlet: Outlet, feed_url: str, feed_type: str = "rss") -> int:
    """Core RSS ingestion for a single feed URL."""
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20) as client:
            resp = client.get(feed_url)
            resp.raise_for_status()
        feed = feedparser.parse(resp.content)
        if feed.bozo and not feed.entries:
            raise ValueError(f"invalid feed: {feed.bozo_exception}")
        count = 0
        per_run = MAX_NEW_PER_RUN_GOOGLE if feed_type == "google_news" else MAX_NEW_PER_RUN
        for entry in feed.entries[:per_run]:
            url = entry.get("link")
            if not url:
                continue
            if feed_type == "google_news" and google_blocked():
                log.info("Google News limite les requêtes : %s, reste du flux ignoré pour ce cycle", outlet.name)
                break
            published = None
            for key in ("published_parsed", "updated_parsed"):
                if entry.get(key):
                    published = datetime.fromtimestamp(time.mktime(entry[key]))
                    break
            summary = entry.get("summary", "")
            summary_text = re.sub(r"<[^>]+>", " ", summary)
            summary_text = re.sub(r"\s+", " ", summary_text).strip() if summary else ""
            if not summary_text or "news.google.com" in summary_text or summary_text.startswith("http"):
                summary_text = ""
            lead = summary_text if len(summary_text) >= 40 else article_excerpt(entry.get("title", ""), None, url)
            if _save_article(db, outlet, url, entry.get("title", ""), published,
                             entry.get("author"), fallback_text=lead):
                count += 1
        _log(db, outlet.id, feed_type, "ok", count)
        return count
    except Exception as e:  # noqa: BLE001
        log.warning("Feed ingestion failed for %s (%s): %s", outlet.name, feed_url, e)
        _log(db, outlet.id, feed_type, "error", 0, str(e)[:500])
        return 0


def collection_suspended(outlet: Outlet) -> bool:
    return getattr(outlet, "collect_enabled", 1) == 0


def recover_feeds(db: Session, outlet: Outlet) -> int:
    """Donne un flux à un média dont le RSS n'a rien donné depuis 24 h.

    Réactive un flux coupé s'il répond encore. Sinon cherche une autre adresse
    sur le site. Une tentative par média et par jour.
    """
    if collection_suspended(outlet) or not outlet.website_url:
        return 0
    since = datetime.utcnow() - timedelta(hours=24)
    tried = (
        db.query(IngestionLog.id)
        .filter(IngestionLog.outlet_id == outlet.id, IngestionLog.feed_type == "feed_discover",
                IngestionLog.timestamp >= since)
        .first()
    )
    if tried:
        return 0
    from .suggest import _feed_works, discover_feeds

    gained = 0
    disabled = db.query(OutletFeed).filter(
        OutletFeed.outlet_id == outlet.id, OutletFeed.enabled == 0, OutletFeed.feed_type == "rss",
    ).all()
    for feed in disabled:
        try:
            if _feed_works(feed.url, timeout=8):
                feed.enabled = 1
                gained += 1
        except Exception:  # noqa: BLE001
            continue
    if gained:
        _log(db, outlet.id, "feed_discover", "ok", gained)
        return gained
    known = {f.url for f in db.query(OutletFeed).filter(OutletFeed.outlet_id == outlet.id).all()}
    if outlet.rss_url:
        known.add(outlet.rss_url)
    try:
        found = discover_feeds(outlet.website_url, max_feeds=2, timeout=8)
    except Exception as e:  # noqa: BLE001
        log.warning("feed discovery failed for %s: %s", outlet.name, e)
        found = []
    for url in found:
        if url in known:
            continue
        db.add(OutletFeed(outlet_id=outlet.id, url=url, label="découvert", feed_type="rss", enabled=1))
        known.add(url)
        gained += 1
    _log(db, outlet.id, "feed_discover", "ok", gained)
    return gained


def ingest_outlet_rss(db: Session, outlet: Outlet) -> int:
    """Ingest all RSS feeds for an outlet (multi-feed support)."""
    if collection_suspended(outlet):
        return 0
    total = 0
    # 1) Use outlet_feeds if available
    feeds = db.query(OutletFeed).filter(
        OutletFeed.outlet_id == outlet.id,
        OutletFeed.enabled == 1,
        OutletFeed.feed_type == "rss",
    ).all()

    if feeds:
        for feed in feeds:
            total += _ingest_feed(db, outlet, feed.url, f"rss:{feed.label}")
    elif outlet.rss_url:
        # 2) Fallback to the single rss_url field
        total += _ingest_feed(db, outlet, outlet.rss_url, "rss")

    return total


# ------------------------------------------------------------------- Google News RSS

def _rss_healthy(db: Session, outlet: Outlet) -> bool:
    """True si un flux RSS a réussi dans les 24 h."""
    since = datetime.utcnow() - timedelta(hours=24)
    row = (
        db.query(IngestionLog)
        .filter(IngestionLog.outlet_id == outlet.id, IngestionLog.status == "ok",
                IngestionLog.timestamp >= since, IngestionLog.feed_type.like("rss%"))
        .first()
    )
    return row is not None


def _source_healthy(db: Session, outlet: Outlet) -> bool:
    """True si un flux RSS ou un sitemap a déjà fourni des articles dans les 24 h."""
    since = datetime.utcnow() - timedelta(hours=24)
    row = (
        db.query(IngestionLog)
        .filter(IngestionLog.outlet_id == outlet.id, IngestionLog.status == "ok",
                IngestionLog.timestamp >= since, IngestionLog.articles_captured > 0,
                (IngestionLog.feed_type.like("rss%")) | (IngestionLog.feed_type == "sitemap"))
        .first()
    )
    return row is not None


def _known_urls(db: Session, urls: list[str]) -> set[str]:
    found: set[str] = set()
    for i in range(0, len(urls), 400):
        chunk = urls[i:i + 400]
        if not chunk:
            continue
        found.update(row[0] for row in db.query(Article.url).filter(Article.url.in_(chunk)).all())
    return found


def _google_feed_url(outlet: Outlet) -> str:
    from urllib.parse import quote
    domain = urlparse(outlet.website_url).netloc.replace("www.", "")
    query = quote(f"site:{domain}")
    lang = outlet.language or "fr"
    country = outlet.country or "FR"
    return f"https://news.google.com/rss/search?q={query}&hl={lang}&gl={country}&ceid={country}:{lang}"


def _google_entries(outlet: Outlet) -> list:
    with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20) as client:
        resp = client.get(_google_feed_url(outlet))
        resp.raise_for_status()
    feed = feedparser.parse(resp.content)
    if feed.bozo and not feed.entries:
        raise ValueError(f"invalid feed: {feed.bozo_exception}")
    return list(feed.entries)


def _capture_google_entry(db: Session, outlet: Outlet, entry) -> str:
    """'saved', 'skipped' ou 'rate_limited'. Un titre déjà décodé n'est pas redemandé à Google."""
    from .extract import GoogleRateLimited, resolve_google_news_url

    link = entry.get("link") or ""
    title = entry.get("title") or ""
    published = None
    for key in ("published_parsed", "updated_parsed"):
        if entry.get(key):
            published = datetime.fromtimestamp(time.mktime(entry[key]))
            break
    summary = re.sub(r"<[^>]+>", " ", entry.get("summary") or "")
    summary = re.sub(r"\s+", " ", summary).strip()
    if "news.google.com" in summary or summary.startswith("http"):
        summary = ""
    lead = summary if len(summary) >= 40 else article_excerpt(title, None, link)
    try:
        resolved = resolve_google_news_url(link)
    except GoogleRateLimited:
        return "rate_limited"
    if not resolved:
        return "skipped"
    if _save_article(db, outlet, resolved, title, published, entry.get("author")):
        return "saved"
    if lead and _save_article(db, outlet, resolved, title, published, entry.get("author"), fallback_text=lead):
        return "saved"
    return "skipped"


def drain_google_news(db: Session, budget_s: float = 10 * 60, only_id: int | None = None) -> int:
    """Décode les articles Google News encore inconnus, les plus récents d'abord, à tour de rôle.

    Un média dont le flux ou le sitemap a déjà fourni des articles est laissé de côté.
    Au premier refus de Google, on s'arrête sans marquer le titre comme vu : le cycle suivant reprend.
    """
    from .extract import google_blocked

    if google_blocked():
        return 0
    deadline = time.time() + budget_s
    outlets = [
        outlet for outlet in db.query(Outlet).all()
        if outlet.website_url and not collection_suspended(outlet) and not _source_healthy(db, outlet)
        and (only_id is None or outlet.id == only_id)
    ]
    queues = []
    for outlet in outlets:
        try:
            entries = _google_entries(outlet)
        except Exception as e:  # noqa: BLE001
            log.warning("Google News list failed for %s: %s", outlet.name, e)
            _log(db, outlet.id, "google_news", "error", 0, str(e)[:500])
            continue
        seen = list((outlet.meta or {}).get("google_seen") or [])
        seen_set = set(seen)
        pending = []
        for entry in entries:
            token = google_article_id(entry.get("link") or "")
            if token and token in seen_set:
                continue
            pending.append(entry)
        queues.append({"outlet": outlet, "pending": pending, "seen": seen, "gained": 0, "dirty": False})
    saved = 0
    while time.time() < deadline and not google_blocked():
        progressed = False
        for queue in queues:
            if time.time() >= deadline or google_blocked():
                break
            if not queue["pending"]:
                continue
            entry = queue["pending"].pop(0)
            token = google_article_id(entry.get("link") or "")
            try:
                result = _capture_google_entry(db, queue["outlet"], entry)
            except Exception as e:  # noqa: BLE001
                log.warning("Google News entry failed for %s: %s", queue["outlet"].name, e)
                result = "skipped"
            if result == "rate_limited":
                queue["pending"].insert(0, entry)
                progressed = False
                break
            if token:
                queue["seen"].append(token)
                queue["dirty"] = True
            if result == "saved":
                queue["gained"] += 1
                saved += 1
            progressed = True
        if not progressed:
            break
    for queue in queues:
        if not queue["dirty"] and queue["gained"] == 0:
            continue
        outlet = queue["outlet"]
        meta = dict(outlet.meta or {})
        meta["google_seen"] = queue["seen"][-500:]
        outlet.meta = meta
        db.commit()
        if queue["gained"]:
            _log(db, outlet.id, "google_news", "ok", queue["gained"])
    return saved


def ingest_google_news(db: Session, outlet: Outlet) -> int:
    """Un média : toute la liste Google News encore inconnue, dans la limite de trois minutes."""
    if not outlet.website_url or collection_suspended(outlet) or _source_healthy(db, outlet):
        return 0
    return drain_google_news(db, budget_s=180, only_id=outlet.id)


# ------------------------------------------------------------------- GDELT API

_gdelt_blocked_until = 0.0
_last_gdelt_call = 0.0
GDELT_CALL_INTERVAL = 5.5  # GDELT public API rate-limits faster than 1 req / 5s


def ingest_gdelt(db: Session, outlet: Outlet) -> int:
    """Ingest recent articles from GDELT API for a given outlet.
    GDELT provides free access to global news coverage."""
    global _gdelt_blocked_until, _last_gdelt_call
    if not outlet.website_url or collection_suspended(outlet):
        return 0
    if time.time() < _gdelt_blocked_until:
        return 0
    try:
        from urllib.parse import urlparse, quote
        domain = urlparse(outlet.website_url).netloc.replace("www.", "")
        db.commit()
        elapsed = time.time() - _last_gdelt_call
        if elapsed < GDELT_CALL_INTERVAL:
            time.sleep(GDELT_CALL_INTERVAL - elapsed)
        _last_gdelt_call = time.time()
        # GDELT API: search for articles from this domain
        url = f"https://api.gdeltproject.org/api/v2/doc/doc?query=domain:{quote(domain)}&mode=artlist&maxrecords={MAX_NEW_PER_RUN}&format=json&timespan=7d"
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=20) as client:
            resp = client.get(url)
            if resp.status_code == 429:
                _gdelt_blocked_until = time.time() + 900
                log.info("GDELT rate limit (429) on %s, pausing GDELT for 15 min", outlet.name)
                return 0
            if resp.status_code != 200:
                _log(db, outlet.id, "gdelt", "error", 0, f"HTTP {resp.status_code}")
                return 0
            data = resp.json()

        articles = data.get("articles", [])
        count = 0
        for art in articles:
            art_url = art.get("url")
            if not art_url:
                continue
            title = art.get("title", "")
            published_str = art.get("seendate", "")
            published = None
            try:
                # GDELT format: 20260906T123000Z
                published = datetime.strptime(published_str, "%Y%m%dT%H%M%SZ")
            except (ValueError, TypeError):
                pass
            if _save_article(db, outlet, art_url, title, published, None):
                count += 1
        _log(db, outlet.id, "gdelt", "ok", count)
        return count
    except Exception as e:  # noqa: BLE001
        log.warning("GDELT ingestion failed for %s: %s", outlet.name, e)
        _log(db, outlet.id, "gdelt", "error", 0, str(e)[:500])
        return 0


# ------------------------------------------------------------------- Sitemap

def _get_bytes(url: str, timeout: float = 15.0, limit: int = 2_000_000) -> bytes | None:
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=timeout) as client:
            with client.stream("GET", url) as resp:
                if resp.status_code != 200:
                    return None
                chunks: list[bytes] = []
                size = 0
                for chunk in resp.iter_bytes():
                    chunks.append(chunk)
                    size += len(chunk)
                    if size >= limit:
                        break
                return b"".join(chunks)
    except Exception:  # noqa: BLE001
        return None


def _sitemap_candidates(website: str, known: str | None) -> list[str]:
    found: list[str] = []
    if known:
        found.append(known)
    robots = _get_bytes(urljoin(website, "/robots.txt"), timeout=8)
    if robots:
        for line in robots.decode("utf-8", "replace").splitlines():
            if line.lower().startswith("sitemap:"):
                url = line.split(":", 1)[1].strip()
                if url and url not in found:
                    found.append(url)
    origin = f"{urlparse(website).scheme}://{urlparse(website).netloc}"
    for path in ("/sitemap.xml", "/news-sitemap.xml", "/sitemap-news.xml"):
        url = origin + path
        if url not in found:
            found.append(url)
    return found


def _remember_sitemap(db: Session, outlet: Outlet, url: str) -> None:
    meta = dict(outlet.meta or {})
    if meta.get("sitemap_url") == url:
        return
    meta["sitemap_url"] = url
    outlet.meta = meta
    db.commit()


def ingest_sitemap(db: Session, outlet: Outlet) -> int:
    """Articles récents listés dans le sitemap, pour un média sans flux RSS utilisable."""
    if not outlet.website_url or collection_suspended(outlet) or _rss_healthy(db, outlet):
        return 0
    known = (outlet.meta or {}).get("sitemap_url")
    try:
        entries: list[dict] = []
        used = None
        for candidate in _sitemap_candidates(outlet.website_url, known):
            body = _get_bytes(candidate)
            if not body:
                continue
            kind, items = parse_sitemap(body)
            if kind == "urlset" and items:
                entries = items
                used = candidate
                break
            if kind == "index" and items:
                for child in rank_sitemap_children(items):
                    child_body = _get_bytes(child["loc"])
                    if not child_body:
                        continue
                    child_kind, child_items = parse_sitemap(child_body)
                    if child_kind == "urlset" and child_items:
                        entries.extend(child_items)
                        used = used or child["loc"]
                if entries:
                    break
        articles = select_sitemap_articles(entries, outlet.website_url)
        known_urls = _known_urls(db, [article["url"] for article in articles])
        count = 0
        for article in articles:
            if article["url"] in known_urls:
                continue
            lead = article_excerpt(article.get("title"), article.get("caption"), article["url"])
            saved = _save_article(db, outlet, article["url"], article["title"], article["published"], None)
            if not saved and lead:
                saved = _save_article(
                    db, outlet, article["url"], article["title"], article["published"], None, fallback_text=lead,
                )
            if saved:
                count += 1
        if used:
            _remember_sitemap(db, outlet, used)
        _log(db, outlet.id, "sitemap", "ok", count)
        return count
    except Exception as e:  # noqa: BLE001
        log.warning("Sitemap ingestion failed for %s: %s", outlet.name, e)
        _log(db, outlet.id, "sitemap", "error", 0, str(e)[:500])
        return 0


# ------------------------------------------------------------------- Scraping

ARTICLE_PATH_RE = re.compile(
    r"/(article|actu|20\d{2}|politique|economie|societe|international|monde|info|"
    r"story|news|politik|wirtschaft|gesellschaft|berlin|welt|cultura|opinioni|"
    r"opinion|deportes|economia|sociedad|internacional|actualite|planete|sciences|culture)",
    re.I,
)


def ingest_outlet_scrape(db: Session, outlet: Outlet) -> int:
    """Fallback: scrape the homepage for article links (outlets without RSS)."""
    if not outlet.website_url or collection_suspended(outlet):
        return 0
    try:
        from lxml import html as lxml_html

        page = fetch_html(outlet.website_url)
        if not page:
            raise ValueError("homepage unreachable")
        tree = lxml_html.fromstring(page)
        base_host = urlparse(outlet.website_url).netloc
        seen, candidates = set(), []
        for href in tree.xpath("//a/@href"):
            url = urljoin(outlet.website_url, href.split("#")[0])
            parsed = urlparse(url)
            if parsed.netloc != base_host or url in seen:
                continue
            seen.add(url)
            # Heuristic: either matches known patterns OR has a date-like segment
            if (ARTICLE_PATH_RE.search(parsed.path) and len(parsed.path) > 25) or \
               re.search(r"/\d{4}/\d{2}/", parsed.path):
                candidates.append(url)
        count = 0
        for url in candidates[:MAX_NEW_PER_RUN]:
            if db.query(Article.id).filter(Article.url == url).first():
                continue
            raw_html, text, _ = fetch_article(url)
            if not text or len(text) < 300:
                continue
            title = ""
            try:
                t = lxml_html.fromstring(raw_html).xpath("//title/text()")
                title = t[0].strip() if t else url
            except Exception:  # noqa: BLE001
                title = url
            if _save_article(db, outlet, url, title, None, None, fallback_text=text):
                count += 1
        _log(db, outlet.id, "scrape", "ok", count)
        return count
    except Exception as e:  # noqa: BLE001
        log.warning("Scraping failed for %s: %s", outlet.name, e)
        _log(db, outlet.id, "scrape", "error", 0, str(e)[:500])
        return 0


# ------------------------------------------------------------------- Main ingestion

def ingest_all(db: Session, feed_type: str = "all") -> dict:
    """Ingest all outlets using all available methods.
    feed_type: 'rss', 'sitemap', 'scrape', 'google_news', 'gdelt', or 'all'."""
    results = {}
    outlets = db.query(Outlet).all()
    for outlet in outlets:
        count = 0
        try:
            if feed_type in ("rss", "all"):
                count += ingest_outlet_rss(db, outlet)
                if not _rss_healthy(db, outlet) and recover_feeds(db, outlet):
                    count += ingest_outlet_rss(db, outlet)
            if feed_type in ("sitemap", "all") and not _rss_healthy(db, outlet):
                count += ingest_sitemap(db, outlet)
            if feed_type in ("gdelt", "all"):
                count += ingest_gdelt(db, outlet)
            if feed_type in ("scrape", "all") and not _source_healthy(db, outlet):
                count += ingest_outlet_scrape(db, outlet)
            results[outlet.name] = count
        except Exception as e:  # noqa: BLE001
            log.warning("Ingestion error for %s: %s", outlet.name, e)
            db.rollback()
    if feed_type in ("google_news", "all"):
        try:
            results["google_news"] = drain_google_news(db, budget_s=10 * 60)
        except Exception as e:  # noqa: BLE001
            log.warning("Google News drain failed: %s", e)
            db.rollback()
    return results
