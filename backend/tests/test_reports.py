"""Rapports : résolution des codes pays, types connus, mise en page des notes."""

import pytest

from app.services.reports import KINDS, _country_label, _iso2, blocks_from_doc


class TestIso2:
    def test_code(self):
        assert _iso2("fr") == "FR"
        assert _iso2("DE") == "DE"

    def test_english_name(self):
        assert _iso2("France") == "FR"
        assert _iso2("germany") == "DE"

    def test_empty(self):
        assert _iso2(None) is None
        assert _iso2("") is None

    def test_unknown(self):
        with pytest.raises(ValueError, match="pays inconnu"):
            _iso2("XX")
        with pytest.raises(ValueError, match="pays inconnu"):
            _iso2("Narnia")


class TestCountryKind:
    def test_kinds_include_country(self):
        assert "country" in KINDS
        assert KINDS["country"][0] == "Panorama pays"
        assert "theme" in KINDS
        assert KINDS["theme"][0] == "Brief de fond"

    def test_label(self):
        assert _country_label("FR") == "France"
        assert _country_label("ZZ") == "ZZ"


class TestBlocksFromDoc:
    def test_order_and_widgets(self):
        doc = {
            "summary": "Essentiel.",
            "sections": [{"heading": "A", "markdown": "un"}, {"heading": "B", "markdown": "deux"}],
            "sources": ["Tacite"],
        }
        stats = [("Influence", "72", "rang 3")]
        catalog = [
            {"widget": "chart", "title": "Radar", "caption": "cap", "svg": "<svg></svg>"},
            {"widget": "chart", "title": "Écarts", "caption": "", "svg": "<svg></svg>"},
        ]
        blocks = blocks_from_doc(doc, stats, catalog)
        types = [b["type"] for b in blocks]
        assert types[0] == "stats"
        assert types[1] == "callout"
        assert "section" in types and "widget" in types and "sources" in types and types[-1] == "method"
        widgets = [b for b in blocks if b["type"] == "widget"]
        assert len(widgets) == 2
        assert widgets[0]["title"] == "Radar"
        assert blocks[1]["markdown"] == "Essentiel."

    def test_highlight_beats_summary(self):
        blocks = blocks_from_doc({"summary": "LLM"}, [], [], highlight="Brief collecté")
        call = next(b for b in blocks if b["type"] == "callout")
        assert call["markdown"] == "Brief collecté"


class TestNoteLayout:
    def test_kpi_table_becomes_stat_strip(self):
        from app.services.files import render_markdown_body, html_document

        md = (
            "Le jugement tient en une phrase.\n\n"
            "| Fenêtre | Carte |\n| --- | --- |\n| 21–28 octobre | 500 articles |\n\n"
            "## Évaluation\n\n"
            "Le détail.\n\n"
            "## Ce que l'on peut conclure de cette semaine trop longue\n\n"
            "Suite.\n"
        )
        body = render_markdown_body(md)
        assert 'class="stats cols-2"' in body
        assert ">500</div>" in body
        assert "articles" in body
        assert "<table>" not in body
        assert '<p class="lead">' in body
        assert '<h2 class="label">Évaluation</h2>' in body
        assert 'class="title"' in body
        html = html_document(
            "Une séquence",
            body,
            subtitle="Note de renseignement\nFrance · 21–28 octobre 2026\nConfiance modérée",
        )
        assert 'class="mast"' in html
        assert 'class="meta"' in html
        assert "Confiance modérée" in html
        assert "@font-face" in html


class TestJournalistLever:
    def test_refusal_is_removed_and_table_kept(self):
        from app.services.files import render_press_note, GORGONE_CSS

        lever = (
            "No client file is engaged, and this extract does not support a journalist target list. "
            "The ministry line travels through Emarat Al Youm and Gulf News."
        )
        html = render_press_note(
            "Note",
            reading="The frame is established in this extract.",
            frames="Frames.",
            evidence="Evidence.",
            effects="Effects.",
            lever=lever,
            journalists=[{
                "name": "Sara Khan",
                "outlet": "The National",
                "articles_on_topic": 4,
                "accessibility": None,
                "recommended_action": "SURVEILLER",
                "contacts": [{"kind": "email", "value": "sara@thenational.ae"}],
                "basis": "Aucune signature sur ce sujet dans l'échantillon.",
            }],
        )
        assert "does not support a journalist target list" not in html
        assert "No client file" not in html
        assert "The ministry line travels through Emarat Al Youm" in html
        assert "Sara Khan" in html
        assert "sara@thenational.ae" in html
        assert '<h2 class="label">Lever</h2>' in html
        assert "L EVI ER" not in html
        assert "letter-spacing: .14em" not in GORGONE_CSS
        assert "letter-spacing: .22em" not in GORGONE_CSS

    def test_french_heading_stays_levier(self):
        from app.services.files import render_press_note

        html = render_press_note(
            "Note",
            reading="Le cadrage est établi dans cet échantillon.",
            frames="Cadrages mesurés.",
            evidence="Preuves.",
            effects="Effets.",
            lever="La ligne passe par Emarat Al Youm.",
        )
        assert '<h2 class="label">Levier</h2>' in html

    def test_attach_journalists_on_spaced_heading(self):
        from app.services.reports import attach_journalists

        doc = {"sections": [{
            "heading": "L EVI ER",
            "markdown": "No client file is engaged, and this extract does not support a journalist target list. The ministry line holds.",
        }]}
        attach_journalists(doc, [{"name": "Sara Khan", "outlet": "The National", "articles": 4, "accessibility": "", "action": "SURVEILLER", "contact": "", "basis": ""}])
        md = doc["sections"][0]["markdown"]
        assert "Sara Khan" in md
        assert "does not support" not in md
        assert "The ministry line holds." in md

