"""Sitemap : extraire les articles récents d'un média sans flux RSS."""

from datetime import datetime

from app.services.sitemap import (
    article_excerpt, google_article_id, parse_sitemap, rank_sitemap_children, select_sitemap_articles,
)

NEWS = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"
        xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">
  <url>
    <loc>https://www.example.com/politique/budget-2026</loc>
    <news:news>
      <news:publication_date>2026-10-28T08:00:00Z</news:publication_date>
      <news:title>Le budget est adopté</news:title>
    </news:news>
  </url>
  <url>
    <loc>https://autre-site.com/politique/pas-nous</loc>
    <news:news><news:title>Hors site</news:title></news:news>
  </url>
</urlset>
""".encode()

INDEX = b"""<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.example.com/sitemap-images.xml</loc></sitemap>
  <sitemap><loc>https://www.example.com/sitemap-news.xml</loc><lastmod>2026-10-29</lastmod></sitemap>
</sitemapindex>
"""

GENERIC = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.example.com/tag/politique</loc></url>
  <url><loc>https://www.example.com/photo.jpg</loc></url>
  <url><loc>https://www.example.com/monde/2026/10/29/entretien-long</loc><lastmod>2026-10-29T10:00:00Z</lastmod></url>
  <url><loc>https://www.example.com/archives/2020/01/01/vieux-sujet</loc><lastmod>2020-01-01T00:00:00Z</lastmod></url>
</urlset>
"""


def test_news_sitemap_keeps_title_and_same_site():
    kind, items = parse_sitemap(NEWS)
    assert kind == "urlset"
    chosen = select_sitemap_articles(items, "https://www.example.com", datetime(2026, 10, 29))
    assert len(chosen) == 1
    assert chosen[0]["url"].endswith("/budget-2026")
    assert chosen[0]["title"] == "Le budget est adopté"
    assert chosen[0]["published"] == datetime(2026, 10, 28, 8, 0)


def test_index_prefers_news_sitemap():
    kind, items = parse_sitemap(INDEX)
    assert kind == "index"
    chosen = rank_sitemap_children(items)
    assert chosen[0]["loc"].endswith("sitemap-news.xml")
    assert all("images" not in item["loc"] for item in chosen)


def test_blocked_page_keeps_headline_and_caption():
    text = article_excerpt(
        "Christine Lagarde annonce son départ de la BCE",
        "Christine Lagarde quitte la BCE en anticipant de près de dix mois la fin de son mandat de huit ans.",
        "https://www.example.com/a",
    )
    assert text.startswith("Christine Lagarde annonce")
    assert "dix mois" in text
    assert article_excerpt("https://www.example.com/a", None, "https://www.example.com/a") is None


def test_sitemap_keeps_the_whole_recent_list():
    rows = []
    for i in range(40):
        rows.append(
            f"<url><loc>https://www.example.com/news/2026/10/29/sujet-{i}-assez-long</loc>"
            f"<news:news><news:title>Sujet numéro {i} du jour assez long pour être gardé</news:title></news:news></url>"
        )
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9" '
        'xmlns:news="http://www.google.com/schemas/sitemap-news/0.9">'
        + "".join(rows) + "</urlset>"
    ).encode()
    _, items = parse_sitemap(body)
    chosen = select_sitemap_articles(items, "https://example.com", datetime(2026, 10, 29))
    assert len(chosen) == 40


def test_google_article_id_is_stable():
    url = "https://news.google.com/rss/articles/CBMiabc123?oc=5"
    assert google_article_id(url) == "CBMiabc123"
    assert google_article_id("https://www.lemonde.fr/a") is None


def test_generic_sitemap_skips_tags_images_and_old_urls():
    _, items = parse_sitemap(GENERIC)
    chosen = select_sitemap_articles(items, "https://example.com", datetime(2026, 10, 29))
    assert [item["url"] for item in chosen] == ["https://www.example.com/monde/2026/10/29/entretien-long"]
