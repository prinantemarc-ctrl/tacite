"""Confiance par axe et influence ancrée."""

from app.services.analysis import _is_likely_non_political
from app.services.profiles import _anchored_agenda, _anchored_citation, _real_classification


class _Art:
    def __init__(self, framing, coverage=None):
        self.extracted_data = {"framing": framing}
        if coverage:
            self.extracted_data["coverage"] = coverage
        self.text_coverage = coverage


class TestAxisConfidence:
    def test_counts_nonzero_per_axis(self):
        arts = [
            _Art({"economy": 0.4, "society": 0, "immigration": 0.2}),
            _Art({"economy": 0.6, "society": 0}),
        ]
        real, axis_n = _real_classification(arts)
        assert axis_n["economy"] == 2
        assert axis_n["society"] == 0
        assert axis_n["immigration"] == 1
        assert abs(real["economy"] - 0.5) < 1e-9
        assert real["society"] == 0
        assert axis_n["_evidence"] == 2

    def test_excerpt_weighs_half(self):
        arts = [
            _Art({"economy": 0.4}, coverage="excerpt"),
            _Art({"economy": 0.8}, coverage="body"),
        ]
        real, axis_n = _real_classification(arts)
        # (0.4 × 0.5 + 0.8 × 1) / 1.5
        assert abs(real["economy"] - 0.667) < 1e-9
        assert axis_n["economy"] == 1.5
        assert axis_n["_evidence"] == 1.5


class TestAnchoredInfluence:
    def test_citation_log_cap(self):
        assert _anchored_citation(0) == 0
        mid = _anchored_citation(5)
        assert 0 < mid < 100
        assert _anchored_citation(40) == 100
        assert _anchored_citation(400) == 100

    def test_agenda_percent(self):
        assert _anchored_agenda(0) == 0
        assert _anchored_agenda(0.5) == 50
        assert _anchored_agenda(1.2) == 100


class TestNonPoliticalFilter:
    def test_politics_with_match_not_skipped(self):
        assert _is_likely_non_political("Le match politique au Parlement", "Le débat à l'Assemblée.", "fr") is False

    def test_bylines_not_skipped(self):
        assert _is_likely_non_political("Article rédigé par Jean Dupont", "Un éditorial sur la réforme.", "fr") is False

    def test_unknown_language_not_filtered(self):
        assert _is_likely_non_political("Football match goal stadium", "trainer concert film", "es") is False
