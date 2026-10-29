from typing import Any, Optional

from pydantic import BaseModel


class OutletIn(BaseModel):
    name: str
    country: str = "FR"
    language: str = "fr"
    website_url: Optional[str] = None
    rss_url: Optional[str] = None
    declared_orientation: Optional[str] = None
    official_classification: dict[str, float] = {}
    meta: dict[str, Any] = {}


class OutletUpdate(BaseModel):
    name: Optional[str] = None
    country: Optional[str] = None
    language: Optional[str] = None
    website_url: Optional[str] = None
    rss_url: Optional[str] = None
    declared_orientation: Optional[str] = None
    official_classification: Optional[dict[str, float]] = None
    meta: Optional[dict[str, Any]] = None
    collect_enabled: Optional[int] = None


class JournalistIn(BaseModel):
    name: str
    outlet_id: int
    role: str = "Journaliste"
    twitter_handle: Optional[str] = None
    linkedin_url: Optional[str] = None
    bio: Optional[str] = None
    beat: Optional[str] = None


class JournalistUpdate(BaseModel):
    name: Optional[str] = None
    outlet_id: Optional[int] = None
    role: Optional[str] = None
    twitter_handle: Optional[str] = None
    linkedin_url: Optional[str] = None
    bio: Optional[str] = None
    beat: Optional[str] = None


class ArticleSearchIn(BaseModel):
    query: str
    limit: int = 20
    days: Optional[int] = 60
    analyzed_only: bool = False
    outlet_id: Optional[int] = None


class ClientIn(BaseModel):
    name: str
    sector: Optional[str] = None
    type: str = "corporate"
    exposure: str = "medium"
    risk_tolerance: str = "medium"
    budget_level: str = "medium"
    objectives: dict[str, Any] = {}
    narratives_push: list[str] = []
    narratives_counter: list[str] = []
    sensitive_topics: list[str] = []


class ClientUpdate(BaseModel):
    name: Optional[str] = None
    sector: Optional[str] = None
    type: Optional[str] = None
    exposure: Optional[str] = None
    risk_tolerance: Optional[str] = None
    budget_level: Optional[str] = None
    objectives: Optional[dict[str, Any]] = None
    narratives_push: Optional[list[str]] = None
    narratives_counter: Optional[list[str]] = None
    sensitive_topics: Optional[list[str]] = None


class ContactIn(BaseModel):
    journalist_id: int
    quality: str = "medium"
    notes: Optional[str] = None


class BlacklistIn(BaseModel):
    outlet_id: int
    reason: Optional[str] = None


class RecommendationUpdate(BaseModel):
    status: Optional[str] = None
    action_type: Optional[str] = None
    journalist_id: Optional[int] = None
    plan: Optional[list[Any]] = None
    variant: Optional[str] = None


class OutcomeIn(BaseModel):
    outcome: str  # success/partial/failure
    impact_metrics: dict[str, Any] = {}
    lessons_learned: Optional[str] = None


class SettingsUpdate(BaseModel):
    values: dict[str, Any]
