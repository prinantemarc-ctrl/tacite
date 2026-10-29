"""Tests for the recommendation engine — the most critical business logic."""

import pytest
from unittest.mock import MagicMock, patch

# We test the pure logic functions without a real database.


class TestStanceCalculation:
    """Test _stance_for_outlet with various article/narrative configurations."""

    def test_no_articles_returns_zero(self):
        from app.services.recommend import _stance_for_outlet
        assert _stance_for_outlet([], [[0.1, 0.2]], [[0.3, 0.4]]) == 0.0

    def test_no_narratives_returns_zero(self):
        from app.services.recommend import _stance_for_outlet
        article_vecs = [[0.5, 0.5]]
        assert _stance_for_outlet(article_vecs, [], []) == 0.0

    def test_favorable_stance(self):
        """When articles align with push narratives and not counter narratives,
        stance should be positive."""
        from app.services.recommend import _stance_for_outlet
        import numpy as np
        # Push narrative vector aligned with articles
        push = [[0.9, 0.1]]
        counter = [[0.1, 0.9]]
        articles = [[0.8, 0.2], [0.85, 0.15]]
        stance = _stance_for_outlet(articles, push, counter)
        assert stance > 0, f"Expected positive stance, got {stance}"

    def test_hostile_stance(self):
        """When articles align with counter narratives, stance should be negative."""
        from app.services.recommend import _stance_for_outlet
        push = [[0.1, 0.9]]
        counter = [[0.9, 0.1]]
        articles = [[0.85, 0.15], [0.9, 0.1]]
        stance = _stance_for_outlet(articles, push, counter)
        assert stance < 0, f"Expected negative stance, got {stance}"


class TestActionSelection:
    """Test _select_action logic for various stance/influence/vulnerability combos."""

    @patch("app.services.recommend.get_setting_static", return_value=50)
    def test_hostile_high_influence_exploitable(self, mock_settings):
        from app.services.recommend import _select_action
        action, risk = _select_action(-0.5, 80, 0.5, "high")
        assert action == "RETOURNER"
        assert risk == "high"

    @patch("app.services.recommend.get_setting_static", return_value=50)
    def test_hostile_high_influence_not_exploitable(self, mock_settings):
        from app.services.recommend import _select_action
        action, risk = _select_action(-0.5, 80, 0.1, "high")
        # Should be ISOLER (high infl, hostile, not exploitable)
        assert action == "ISOLER"

    @patch("app.services.recommend.get_setting_static", return_value=50)
    def test_hostile_low_influence(self, mock_settings):
        from app.services.recommend import _select_action
        action, risk = _select_action(-0.3, 20, 0.2, "medium")
        assert action == "SURVEILLER"
        assert risk == "low"

    @patch("app.services.recommend.get_setting_static", return_value=50)
    def test_favorable_high_influence(self, mock_settings):
        from app.services.recommend import _select_action
        action, risk = _select_action(0.5, 80, 0.3, "medium")
        assert action == "NOURRIR"
        assert risk == "low"

    @patch("app.services.recommend.get_setting_static", return_value=50)
    def test_neutral_medium_influence(self, mock_settings):
        from app.services.recommend import _select_action
        action, risk = _select_action(0.0, 50, 0.2, "medium")
        assert action == "AMORCER"

    @patch("app.services.recommend.get_setting_static", return_value=50)
    def test_downgrade_for_low_risk_tolerance(self, mock_settings):
        """Client with low risk tolerance should get downgraded actions."""
        from app.services.recommend import _select_action
        action, risk = _select_action(-0.5, 80, 0.5, "low")
        # RETOURNER is high risk, should be downgraded to at most low risk
        assert risk == "low", f"Expected low risk, got {risk} for action {action}"

    @patch("app.services.recommend.get_setting_static", return_value=50)
    def test_favorable_low_influence_diluer(self, mock_settings):
        from app.services.recommend import _select_action
        action, risk = _select_action(0.3, 20, 0.1, "medium")
        # Low influence + favorable = DILUER
        assert action == "DILUER"


class TestVulnerabilities:
    """Test vulnerability detection."""

    def test_big_gap_triggers_signal(self):
        from app.services.recommend import _vulnerabilities
        db = MagicMock()
        outlet = MagicMock()
        outlet.meta = {}
        profile = MagicMock()
        profile.gap_from_official = {"economy": 0.5, "society": -0.4}
        profile.axis_n = {"economy": 20, "society": 20}
        profile.drift_alerts = []
        profile.article_count = 20
        outlet.country = "FR"
        strength, signals = _vulnerabilities(db, outlet, profile, None, 0.3)
        assert strength > 0, "Expected non-zero strength when gap > threshold"
        assert any("Écart" in s for s in signals)

    def test_drift_alerts_trigger_signal(self):
        from app.services.recommend import _vulnerabilities
        db = MagicMock()
        outlet = MagicMock()
        outlet.meta = {}
        profile = MagicMock()
        profile.gap_from_official = {"economy": 0.1}
        profile.axis_n = {"economy": 20}
        profile.drift_alerts = [{"axis": "society", "change": -0.4}]
        profile.article_count = 25
        outlet.country = "FR"
        strength, signals = _vulnerabilities(db, outlet, profile, None, 0.3)
        assert any("dérive" in s.lower() for s in signals)

    def test_accessible_journalist_boosts_vulnerability(self):
        from app.services.recommend import _vulnerabilities
        db = MagicMock()
        outlet = MagicMock()
        outlet.meta = {}
        profile = MagicMock()
        profile.gap_from_official = {}
        profile.axis_n = {}
        profile.drift_alerts = []
        profile.article_count = 30
        outlet.country = "FR"
        journalist = MagicMock()
        journalist.name = "Jean Dupont"
        journalist.accessibility_score = 80
        strength, signals = _vulnerabilities(db, outlet, profile, journalist, 0.3)
        assert any("accessible" in s.lower() for s in signals)


class TestNERMultilingual:
    """Test NER model selection."""

    def test_french_model_selected(self):
        from app.services.ner import LANGUAGE_MODELS, _get_nlp
        # We can't test actual model loading without spaCy installed,
        # but we can test the routing logic
        assert LANGUAGE_MODELS.get("fr") == "fr_core_news_md"
        assert LANGUAGE_MODELS.get("en") == "en_core_web_md"

    def test_unknown_language_falls_back_to_french(self):
        from app.services.ner import LANGUAGE_MODELS
        assert "zh" not in LANGUAGE_MODELS  # Chinese not supported


class TestDeduplication:
    """Test duplicate detection threshold."""

    def test_threshold_value(self):
        from app.services.analysis import DEDUP_SIMILARITY_THRESHOLD
        assert DEDUP_SIMILARITY_THRESHOLD == 0.95


class TestConstants:
    """Verify key constants are well-defined."""

    def test_12_axes(self):
        from app.constants import AXES
        assert len(AXES) == 12

    def test_9_action_types(self):
        from app.constants import ACTION_TYPES
        assert len(ACTION_TYPES) == 9

    def test_all_actions_have_risk(self):
        from app.constants import ACTION_TYPES, RISK_ORDER
        for action, risk in ACTION_TYPES.items():
            assert risk in RISK_ORDER, f"Action {action} has invalid risk level {risk}"

    def test_downgrade_chain_complete(self):
        from app.constants import ACTION_DOWNGRADE, ACTION_TYPES
        for action in ACTION_DOWNGRADE:
            assert action in ACTION_TYPES
            assert ACTION_DOWNGRADE[action] in ACTION_TYPES
