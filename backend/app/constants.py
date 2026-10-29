"""Shared domain constants: framing axes, action types, default settings."""

from .kits import (  # noqa: F401
    AXIS_CATALOG,
    FR_AXIS_ZONE,
    FR_SPECIFIC_AXES,
    STRUCTURAL_IDS,
    all_axis_ids,
    axes_for_country,
    axis_labels_for,
    axis_poles_for,
)

# Union of structural + all builtin kit axes (extraction schema / legacy loops).
AXES = all_axis_ids()
AXIS_LABELS_FR = axis_labels_for("fr")
AXIS_LABELS_EN = axis_labels_for("en")
AXIS_POLES_FR = axis_poles_for("fr")
AXIS_POLES_EN = axis_poles_for("en")

# Valence approximative des tons extraits par le LLM (anglais, minuscules).
TONE_VALENCE = {
    "neutral": 0.0, "hope": 1.0, "optimism": 1.0, "pride": 0.7, "relief": 0.6, "admiration": 0.8,
    "indignation": -1.0, "anger": -1.0, "outrage": -1.0, "fear": -0.8, "concern": -0.5, "worry": -0.5,
    "tension": -0.5, "sad": -0.5, "sadness": -0.5, "grief": -0.6, "irony": -0.4, "sarcasm": -0.6,
    "skepticism": -0.4, "nostalgia": 0.1, "curiosity": 0.2, "surprise": 0.0, "alarm": -0.8,
}

# Action types by risk level.
ACTION_TYPES = {
    "NOURRIR": "low",
    "AMORCER": "low",
    "SURVEILLER": "low",
    "COOPTER": "medium",
    "CONTOURNER": "medium",
    "DILUER": "medium",
    "RETOURNER": "high",
    "DIVISER": "high",
    "ISOLER": "high",
}

RISK_ORDER = {"low": 0, "medium": 1, "high": 2}

# Downgrade chain when an action exceeds the client's risk tolerance.
ACTION_DOWNGRADE = {
    "RETOURNER": "COOPTER",
    "DIVISER": "CONTOURNER",
    "ISOLER": "DILUER",
    "COOPTER": "NOURRIR",
    "CONTOURNER": "AMORCER",
    "DILUER": "SURVEILLER",
}

JOURNALISTIC_ANGLES = [
    "investigation", "editorial", "brief", "analysis", "opinion", "reaction",
]

SOURCE_TYPES = [
    "government", "anonymous", "expert", "ngo", "corporate",
    "judicial", "union", "political_party", "citizen", "media", "other",
]

DEFAULT_SETTINGS = {
    "rss_interval_minutes": 15,
    "scrape_interval_minutes": 60,
    "analysis_batch_size": 50,
    "min_text_length_for_llm": 400,
    "llm_model": "aleria",
    "llm_profile_model": "aleria",
    "llm_agent_model": "aleria",           # assistant : usage d'outils et rédaction
    "agent_web_search": False,             # outil de recherche hébergé indisponible chez Aleria
    "agent_confirm_writes": True,          # demander confirmation avant toute écriture
    "drift_threshold": 0.3,
    "influence_weights": {
        "audience": 0.20,
        "citation": 0.25,
        "agenda": 0.20,
        "elite": 0.15,
        "network": 0.10,
        "longevity": 0.10,
    },
    "influence_high_threshold": 60,
    "influence_medium_threshold": 35,
    "stance_hostile_threshold": -0.15,
    "stance_favorable_threshold": 0.15,
    "accessibility_pitch_threshold": 55,
    "recommendation_interval_days": 7,
    "max_daily_cost_usd": 0,  # 0 = no cap
    "gap_exploitable_threshold": 0.35,
    "google_news_interval_minutes": 15,
    "gdelt_interval_minutes": 360,
    "contacts_interval_minutes": 60,
    "bylines_interval_minutes": 360,
}

# USD per 1M tokens (input, output) — used for cost estimation.
MODEL_PRICING = {
    "aleria": (0.075, 0.25),
    "glm51": (0.075, 0.25),
    "z-ai/glm-5.3-flash": (0.075, 0.25),
    "aleria-fast": (1.08, 3.30),
    "deepseek-v4-flash": (1.08, 3.30),
    "aleria-experimental": (1.50, 6.15),
    "z-ai/glm-5.3": (1.50, 6.15),
    "glm52-1m": (1.50, 6.15),
}
WEB_SEARCH_CALL_USD = 0.0
