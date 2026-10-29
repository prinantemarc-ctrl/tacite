"""Fetch article pages and extract clean text."""

import json
import logging
import re
import threading
import time

import httpx
import trafilatura

log = logging.getLogger("tacite.extract")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
}
# Cookies qui évitent le mur de consentement Google (consent.google.com) sur les redirections.
CONSENT_COOKIES = {"CONSENT": "YES+cb", "SOCS": "CAISHAgBEhJnd3NfMjAyMzA4MTAtMF9SQzIaAmZyIAEaBgiA_LyaBg"}

# ─────────────────────────────────────────────── texte parasite (bandeaux, murs de consentement)

# Lexique multilingue des bandeaux cookies / politiques de confidentialité.
_CONSENT_TERMS = [
    "cookie", "cookies", "consent", "consentement", "traceurs", "données personnelles", "personal data",
    "vie privée", "privacy", "confidentialité", "partenaires", "partners", "publicités personnalisées",
    "personalised ads", "personalized ads", "mesure d'audience", "audience measurement", "paramètres de confidentialité",
    "privacy settings", "accepter", "refuser", "tout accepter", "accept all", "reject all", "gérer mes choix",
    "einwilligung", "datenschutz", "zustimmen", "ablehnen", "personenbezogene daten",
    "privacidad", "consentimiento", "aceptar", "rechazar", "datos personales",
    "privacy policy", "informativa", "consenso", "accetta", "rifiuta", "dati personali",
    "privacybeleid", "toestemming", "accepteren", "weigeren", "persoonsgegevens",
]
_CONSENT_MARKERS = [
    "g.co/privacytools", "consent.google", "toutes les langues", "afrikaans\n", "azərbaycan", "isizulu",
    "politique de confidentialité", "privacy policy", "cookie policy", "politique cookies",
    "gérer mes cookies", "manage cookies", "cookie-einstellungen", "cookie settings",
]
_CONSENT_RE = re.compile("|".join(re.escape(t) for t in _CONSENT_TERMS), re.I)


def is_boilerplate(text: str | None, title: str | None = None) -> bool:
    """True si le texte est un bandeau cookies, un mur de consentement, une liste de langues
    ou une page de politique de confidentialité — et non un article."""
    if not text:
        return True
    t = text.lower()
    head = t[:2500]
    if any(m in head for m in _CONSENT_MARKERS[:6]):  # marqueurs Google / listes de langues
        return True
    words = max(1, len(head.split()))
    hits = len(_CONSENT_RE.findall(head))
    # Un article normal contient rarement plus de 1 % de vocabulaire « consentement » en ouverture.
    if hits >= 6 and hits / words > 0.012:
        return True
    ttl = (title or "").lower()
    if any(m in ttl for m in ("politique de confidentialité", "privacy policy", "cookie policy", "datenschutz", "politique cookies")):
        return True
    # Liste de langues (menu) : beaucoup de lignes très courtes commençant par « - »
    lines = [l for l in text[:1500].splitlines() if l.strip()]
    if len(lines) >= 15 and sum(1 for l in lines if l.startswith("- ") and len(l) < 30) / len(lines) > 0.7:
        return True
    return False


def strip_boilerplate(text: str) -> str:
    """Retire les paragraphes parasites (bandeau cookies en tête ou en pied) d'un texte d'article."""
    paras = [p for p in re.split(r"\n{2,}|\n", text) if p.strip()]
    keep = []
    for p in paras:
        w = max(1, len(p.split()))
        h = len(_CONSENT_RE.findall(p))
        if h >= 3 and h / w > 0.06:
            continue
        keep.append(p)
    return "\n".join(keep)


# ─────────────────────────────────────────────── Google News


def is_google_news_url(url: str) -> bool:
    return "news.google.com/" in url and "/articles/" in url


class GoogleRateLimited(Exception):
    """Google a répondu 429 : il faut ralentir, l'URL n'est pas décodable pour l'instant."""


# Google limite vite les requêtes : on sérialise et on espace les appels au décodeur.
_g_lock = threading.Lock()
_g_next_ok = 0.0
_g_blocked_until = 0.0
GOOGLE_MIN_INTERVAL = 1.5   # secondes entre deux décodages
GOOGLE_BACKOFF = 300.0      # après un 429, on laisse Google tranquille 5 min


def google_blocked() -> bool:
    return time.time() < _g_blocked_until


def google_backoff_remaining() -> float:
    return max(0.0, _g_blocked_until - time.time())


def resolve_google_news_url(url: str, timeout: float = 20.0) -> str | None:
    """Décode un lien news.google.com/rss/articles/… vers l'URL réelle de l'article.
    La page Google News est une application JS : on récupère la signature et l'horodatage
    dans le HTML, puis on interroge l'endpoint interne batchexecute.
    Lève GoogleRateLimited si Google renvoie 429 (ou si un 429 récent impose une pause)."""
    global _g_next_ok, _g_blocked_until
    m = re.search(r"/articles/([^?/]+)", url)
    if not m:
        return None
    b64 = m.group(1)
    with _g_lock:
        if google_blocked():
            raise GoogleRateLimited()
        wait = _g_next_ok - time.time()
        if wait > 0:
            time.sleep(wait)
        _g_next_ok = time.time() + GOOGLE_MIN_INTERVAL
        try:
            with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=timeout, cookies=CONSENT_COOKIES) as c:
                r = c.get(f"https://news.google.com/articles/{b64}")
                if r.status_code == 429 or "google.com/sorry" in str(r.url):
                    _g_blocked_until = time.time() + GOOGLE_BACKOFF
                    log.warning("Google News: 429, pause de %.0f s", GOOGLE_BACKOFF)
                    raise GoogleRateLimited()
                sg = re.search(r'data-n-a-sg="([^"]+)"', r.text)
                ts = re.search(r'data-n-a-ts="([^"]+)"', r.text)
                if not (sg and ts):
                    return None
                return _batchexecute(c, b64, int(ts.group(1)), sg.group(1))
        except GoogleRateLimited:
            raise
        except Exception as e:  # noqa: BLE001
            log.debug("google news decode failed %s: %s", url, e)
            return None


def _batchexecute(c: httpx.Client, b64: str, ts: int, sg: str) -> str | None:
    try:
        inner = json.dumps([
            "garturlreq",
            [["X", "X", ["X", "X"], None, None, 1, 1, "US:en", None, 1, None, None, None, None, None, 0, 1],
             "X", "X", 1, [1, 1, 1], 1, 1, None, 0, 0, None, 0],
            b64, ts, sg,
        ])
        payload = json.dumps([[["Fbv4je", inner, None, "generic"]]])
        r2 = c.post(
            "https://news.google.com/_/DotsSplashUi/data/batchexecute",
            data={"f.req": payload},
            headers={"content-type": "application/x-www-form-urlencoded;charset=UTF-8"},
        )
        if r2.status_code == 429:
            raise GoogleRateLimited()
        parts = r2.text.split("\n\n")
        data = json.loads(parts[1])
        real = json.loads(data[0][2])[1]
        return real if isinstance(real, str) and real.startswith("http") else None
    except GoogleRateLimited:
        raise
    except Exception as e:  # noqa: BLE001
        log.debug("google news batchexecute failed: %s", e)
        return None


def fetch_html(url: str, timeout: float = 20.0) -> str | None:
    try:
        with httpx.Client(headers=HEADERS, follow_redirects=True, timeout=timeout, cookies=CONSENT_COOKIES) as client:
            resp = client.get(url)
            if resp.status_code == 200 and "text/html" in resp.headers.get("content-type", "text/html"):
                return resp.text
    except Exception as e:  # noqa: BLE001
        log.debug("fetch failed %s: %s", url, e)
    return None


EXCERPT_MIN = 40
BODY_MIN = 100

_DESC_META = (
    re.compile(
        r'<meta\b[^>]*(?:property|name)=["\'](?:og:description|twitter:description|description)["\'][^>]*\bcontent=["\']([^"\']+)["\']',
        re.I,
    ),
    re.compile(
        r'<meta\b[^>]*\bcontent=["\']([^"\']+)["\'][^>]*(?:property|name)=["\'](?:og:description|twitter:description|description)["\']',
        re.I,
    ),
)
_JSON_DESC = re.compile(r'"description"\s*:\s*"((?:\\.|[^"\\]){40,800})"', re.I)


def _clean_lead(raw: str) -> str:
    import html as html_lib

    raw = html_lib.unescape(raw or "")
    raw = raw.replace("\\n", " ").replace('\\"', '"').replace("\\/", "/")
    return re.sub(r"\s+", " ", raw).strip()


def lead_from_html(html: str | None) -> str | None:
    """Chapô présent dans l'en-tête (og:description, meta, JSON-LD), sans le corps."""
    if not html:
        return None
    head = html[:200_000]
    found: list[str] = []
    for rx in _DESC_META:
        for match in rx.finditer(head):
            found.append(_clean_lead(match.group(1)))
    for match in _JSON_DESC.finditer(head):
        found.append(_clean_lead(match.group(1)))
    usable = [c for c in found if len(c) >= EXCERPT_MIN and not is_boilerplate(c)]
    if not usable:
        return None
    return max(usable, key=len)[:2000]


def choose_coverage(body: str | None, excerpt: str | None, title: str | None = None) -> tuple[str | None, str | None]:
    """(texte, 'body'|'excerpt'). Le corps gagne dès qu'il est exploitable. Sinon le chapô."""
    body = (body or "").strip()
    excerpt = (excerpt or "").strip()
    if len(body) >= BODY_MIN and not is_boilerplate(body, title):
        return body, "body"
    if len(excerpt) >= EXCERPT_MIN and not is_boilerplate(excerpt, title):
        return excerpt, "excerpt"
    return None, None


def extract_text(html: str) -> str | None:
    try:
        text = trafilatura.extract(html, include_comments=False, include_tables=False)
        if not text:
            return None
        if is_boilerplate(text):
            return None
        return strip_boilerplate(text)
    except Exception:  # noqa: BLE001
        return None


def fetch_article(url: str) -> tuple[str | None, str | None, str]:
    """Returns (raw_html, extracted_text, final_url). final_url = URL réelle après résolution Google News."""
    final = url
    if is_google_news_url(url):
        try:
            real = resolve_google_news_url(url)
        except GoogleRateLimited:
            real = None
        if not real:
            return None, None, url
        final = real
    html = fetch_html(final)
    if not html:
        return None, None, final
    return html, extract_text(html), final


def detect_language(text: str, fallback: str = "fr") -> str:
    try:
        from langdetect import detect

        return detect(text[:2000])
    except Exception:  # noqa: BLE001
        return fallback
