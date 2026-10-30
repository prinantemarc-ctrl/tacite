"""Récap médias : sujets, écart max. signé, confiance."""

from app.constants import axes_for_country
from app.kits import axes_for_countries
from app.services.profiles import confidence_label, max_usable_gap, topics_from_extracted


class TestConfidence:
    def test_thresholds(self):
        assert confidence_label(0) == "faible"
        assert confidence_label(9) == "faible"
        assert confidence_label(10) == "moyenne"
        assert confidence_label(29) == "moyenne"
        assert confidence_label(30) == "élevée"


class TestMaxUsableGap:
    def test_picks_largest_signed(self):
        gaps = {"economy": 0.2, "immigration": -0.61, "society": 0.4}
        axis_n = {k: 20 for k in gaps}
        g = max_usable_gap("FR", gaps, axis_n)
        assert g["axis"] == "immigration"
        assert g["label"] == "Immigration"
        assert g["value"] == -0.61

    def test_skips_thin_axes(self):
        gaps = {"economy": 0.9, "immigration": 0.4}
        axis_n = {"economy": 3, "immigration": 20}
        g = max_usable_gap("FR", gaps, axis_n)
        assert g["axis"] == "immigration"

    def test_skips_fr_axes_outside_zone(self):
        gaps = {"secularism": 0.9, "economy": 0.3}
        axis_n = {k: 20 for k in gaps}
        assert "secularism" not in axes_for_country("DE")
        g = max_usable_gap("DE", gaps, axis_n)
        assert g["axis"] == "economy"

    def test_empty(self):
        assert max_usable_gap("FR", None, None) is None
        assert max_usable_gap("FR", {}, {}) is None


class TestTopics:
    def test_counts_and_skips_non_political(self):
        items = [
            {"topics": [{"label": "Retraites"}, {"label": "Non-political"}]},
            {"topics": [{"label": "retraites"}, {"label": "Gaza"}]},
            {"topics": [{"label": "Gaza"}]},
        ]
        top = topics_from_extracted(items, n=3)
        assert [t["label"] for t in top] == ["Retraites", "Gaza"]
        assert top[0]["count"] == 2
        assert top[1]["count"] == 2

    def test_accepts_raw_lists(self):
        top = topics_from_extracted([[{"label": "Ukraine"}]], n=1)
        assert top == [{"label": "Ukraine", "count": 1}]


class TestAxesBatch:
    def test_matches_single_country_lookup(self):
        batched = axes_for_countries(["FR", "DE", "US", "FR", ""])
        assert batched["FR"] == axes_for_country("FR")
        assert batched["DE"] == axes_for_country("DE")
        assert batched["US"] == axes_for_country("US")
        assert batched[""] == axes_for_country(None)

    def test_gap_uses_precomputed_axes(self):
        gaps = {"secularism": 0.9, "economy": 0.3}
        axis_n = {k: 20 for k in gaps}
        usable = axes_for_countries(["DE"])["DE"]
        g = max_usable_gap("DE", gaps, axis_n, usable=usable)
        assert g["axis"] == "economy"
