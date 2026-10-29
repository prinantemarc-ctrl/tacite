"""Chapô admissible, corps prioritaire."""

from app.services.analysis import _prompt_mode, _stored_coverage
from app.services.extract import choose_coverage, lead_from_html
from app.services.profiles import evidence_n


class _Art:
    def __init__(self, text, coverage=None):
        self.text = text
        self.text_coverage = coverage


def test_body_wins_over_lead():
    text, kind = choose_coverage("x" * 120, "Un chapô suffisamment long pour être gardé tel quel.")
    assert kind == "body"
    assert len(text) == 120


def test_lead_kept_when_body_missing():
    lead = "Le gouvernement reporte la réforme des retraites complémentaires."
    text, kind = choose_coverage("cookie consent " * 3, lead)
    assert kind == "excerpt"
    assert text == lead


def test_boilerplate_lead_dropped():
    wall = "cookie " * 40 + "accepter refuser tout accepter consentement données personnelles privacy"
    assert choose_coverage(None, wall) == (None, None)


def test_lead_from_meta():
    html = '<html><head><meta property="og:description" content="Les députés adoptent le texte sur les retraites en première lecture."></head></html>'
    assert "retraites" in lead_from_html(html)


def test_short_body_is_read_as_lead():
    art = _Art("x" * 80, coverage="body")
    assert _stored_coverage(art, 400) == "body"
    assert _prompt_mode("body", art.text, 400) == "excerpt"


def test_excerpt_column_stays_excerpt():
    art = _Art("x" * 800, coverage="excerpt")
    assert _prompt_mode(_stored_coverage(art, 400), art.text, 400) == "excerpt"


def test_news_domains_ignore_platforms():
    from app.services.suggest import domains_from_news_entries
    entries = [
        {"source": {"href": "https://www.lemonde.fr/article"}},
        {"source": {"href": "https://www.lemonde.fr/autre"}},
        {"source": {"href": "https://news.google.com/rss/articles/x"}},
        {"source": {"href": "https://www.lefigaro.fr/a"}},
    ]
    assert domains_from_news_entries(entries) == ["lemonde.fr", "lefigaro.fr"]


def test_evidence_falls_back_to_article_count():
    assert evidence_n(None, 12) == 12
    assert evidence_n({"economy": 4, "_evidence": 6.5}, 12) == 6.5
