from datetime import datetime, date

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    JSON,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import declared_attr, relationship

from .config import EMBEDDING_DIM
from .database import Base
from .tenant import HasTenant


def row_to_dict(obj, exclude=("embedding", "raw_html")):
    """Serialize an ORM row to a JSON-safe dict."""
    out = {}
    for col in obj.__table__.columns:
        if col.name in exclude:
            continue
        val = getattr(obj, col.name)
        if isinstance(val, (datetime, date)):
            val = val.isoformat()
        out[col.name] = val
    return out


class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True)
    username = Column(String, unique=True, nullable=False, index=True)
    password_hash = Column(String, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class AuthSession(Base):
    __tablename__ = "auth_sessions"
    token = Column(String, primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=False, index=True)


class Setting(HasTenant, Base):
    __tablename__ = "settings"

    @declared_attr
    def user_id(cls):  # noqa: N805
        return Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)

    key = Column(String, primary_key=True)
    value = Column(JSON)


class Outlet(HasTenant, Base):
    __tablename__ = "outlets"
    __table_args__ = (UniqueConstraint("user_id", "name", "country", name="outlets_user_name_country_key"),)
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    country = Column(String, default="FR")
    language = Column(String, default="fr")
    website_url = Column(String)
    rss_url = Column(String)  # Primary/default RSS feed (kept for backward compat)
    declared_orientation = Column(String)
    official_classification = Column(JSON, default=dict)  # {axis: -1..1}
    influence_score = Column(Float, default=0.0)
    influence_rank = Column(Integer)
    collect_enabled = Column(Integer, default=1)  # 0 = collecte suspendue (historique conservé)
    meta = Column(JSON, default=dict)  # audience_score, elite_score, network_score, longevity_score...
    created_at = Column(DateTime, default=datetime.utcnow)

    journalists = relationship("Journalist", back_populates="outlet")
    feeds = relationship("OutletFeed", back_populates="outlet", cascade="all, delete-orphan")


class OutletFeed(HasTenant, Base):
    """Multiple RSS/Atom feeds per outlet (one per section/rubric)."""
    __tablename__ = "outlet_feeds"
    id = Column(Integer, primary_key=True)
    outlet_id = Column(Integer, ForeignKey("outlets.id"), nullable=False, index=True)
    url = Column(String, nullable=False)
    label = Column(String, default="default")  # e.g. "une", "international", "economie"
    feed_type = Column(String, default="rss")  # rss/scrape/google_news/gdelt
    enabled = Column(Integer, default=1)  # 1=active, 0=disabled
    created_at = Column(DateTime, default=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="feeds")


class Journalist(HasTenant, Base):
    __tablename__ = "journalists"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    outlet_id = Column(Integer, ForeignKey("outlets.id"), nullable=False)
    role = Column(String, default="Journaliste")
    twitter_handle = Column(String)
    linkedin_url = Column(String)
    bio = Column(Text)
    beat = Column(String)
    accessibility_score = Column(Float, default=50.0)
    created_at = Column(DateTime, default=datetime.utcnow)

    outlet = relationship("Outlet", back_populates="journalists")


class Article(HasTenant, Base):
    __tablename__ = "articles"
    __table_args__ = (UniqueConstraint("user_id", "url", name="articles_user_url_key"),)
    id = Column(Integer, primary_key=True)
    outlet_id = Column(Integer, ForeignKey("outlets.id"), nullable=False)
    journalist_id = Column(Integer, ForeignKey("journalists.id"), nullable=True)
    url = Column(String, nullable=False, index=True)
    title = Column(String)
    text = Column(Text)
    raw_html = Column(Text)
    language = Column(String)
    published_at = Column(DateTime, index=True)
    extracted_data = Column(JSON)  # topics, framing, sources, tone, angle, entities
    embedding = Column(Vector(EMBEDDING_DIM), nullable=True)
    analysis_status = Column(String, default="pending", index=True)  # pending/analyzed/embedded_only/error/duplicate
    text_coverage = Column(String)  # body = texte intégral ; excerpt = titre, auteur et chapô
    duplicate_of_id = Column(Integer, ForeignKey("articles.id"), nullable=True)
    captured_at = Column(DateTime, default=datetime.utcnow)


class ArticleJournalist(HasTenant, Base):
    """Auteurs d'un article (position 0 = principal, aussi stocké sur articles.journalist_id)."""
    __tablename__ = "article_journalists"
    article_id = Column(Integer, ForeignKey("articles.id"), primary_key=True)
    journalist_id = Column(Integer, ForeignKey("journalists.id"), primary_key=True)
    position = Column(Integer, default=0)


class JournalistProfile(HasTenant, Base):
    __tablename__ = "journalist_profiles"
    id = Column(Integer, primary_key=True)
    journalist_id = Column(Integer, ForeignKey("journalists.id"), nullable=False, index=True)
    date = Column(Date, default=date.today, index=True)
    themes = Column(JSON, default=list)             # [{label, count}]
    biases = Column(JSON, default=list)             # [str]
    preferred_sources = Column(JSON, default=list)  # [{type, count}]
    tone = Column(String)
    productivity = Column(Float, default=0.0)       # articles / week
    vulnerabilities = Column(JSON, default=list)    # [{label, explanation}]
    accessibility_score = Column(Float, default=50.0)
    raw_summary = Column(Text)


class OutletProfile(HasTenant, Base):
    __tablename__ = "outlet_profiles"
    id = Column(Integer, primary_key=True)
    outlet_id = Column(Integer, ForeignKey("outlets.id"), nullable=False, index=True)
    week = Column(Date, default=date.today, index=True)  # monday of the week
    real_classification = Column(JSON, default=dict)     # {axis: -1..1}
    gap_from_official = Column(JSON, default=dict)       # {axis: real - official}
    drift_alerts = Column(JSON, default=list)            # [{axis, change, previous, current}]
    component_scores = Column(JSON, default=dict)        # {audience, citation, agenda, elite, network, longevity}
    article_count = Column(Integer, default=0)
    axis_n = Column(JSON, default=dict)                  # {axis: n articles non nuls} — confiance par axe


class Client(HasTenant, Base):
    __tablename__ = "clients"
    id = Column(Integer, primary_key=True)
    name = Column(String, nullable=False)
    sector = Column(String)
    type = Column(String, default="corporate")  # corporate/government/ngo/political
    exposure = Column(String, default="medium")  # high/medium/low
    risk_tolerance = Column(String, default="medium")  # low/medium/high
    budget_level = Column(String, default="medium")
    objectives = Column(JSON, default=dict)          # {primary, secondary, tertiary}
    narratives_push = Column(JSON, default=list)     # [str]
    narratives_counter = Column(JSON, default=list)  # [str]
    sensitive_topics = Column(JSON, default=list)    # [str]
    created_at = Column(DateTime, default=datetime.utcnow)


class ClientContact(HasTenant, Base):
    __tablename__ = "client_contacts"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    journalist_id = Column(Integer, ForeignKey("journalists.id"), nullable=False)
    quality = Column(String, default="medium")  # strong/medium/weak
    notes = Column(Text)


class ClientBlacklist(HasTenant, Base):
    __tablename__ = "client_blacklist"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    outlet_id = Column(Integer, ForeignKey("outlets.id"), nullable=False)
    reason = Column(Text)


class Recommendation(HasTenant, Base):
    __tablename__ = "recommendations"
    id = Column(Integer, primary_key=True)
    client_id = Column(Integer, ForeignKey("clients.id"), nullable=False, index=True)
    outlet_id = Column(Integer, ForeignKey("outlets.id"), nullable=False)
    journalist_id = Column(Integer, ForeignKey("journalists.id"), nullable=True)
    action_type = Column(String, nullable=False)
    variant = Column(String)
    priority = Column(Float, default=0.0)
    status = Column(String, default="proposed")  # proposed/accepted/in_progress/completed/cancelled
    plan = Column(JSON, default=list)            # [{phase, weeks, actions, tools}]
    risk_level = Column(String, default="low")
    budget_level = Column(String, default="low")
    justification = Column(JSON, default=dict)   # {stance, influence, vulnerabilities, summary}
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ActionHistory(HasTenant, Base):
    __tablename__ = "action_history"
    id = Column(Integer, primary_key=True)
    recommendation_id = Column(Integer, ForeignKey("recommendations.id"))
    client_id = Column(Integer, ForeignKey("clients.id"), index=True)
    outlet_id = Column(Integer, ForeignKey("outlets.id"))
    action_type = Column(String)
    outcome = Column(String)  # success/partial/failure
    impact_metrics = Column(JSON, default=dict)
    lessons_learned = Column(Text)
    started_at = Column(DateTime)
    completed_at = Column(DateTime, default=datetime.utcnow)


class IngestionLog(HasTenant, Base):
    __tablename__ = "ingestion_log"
    id = Column(Integer, primary_key=True)
    outlet_id = Column(Integer, ForeignKey("outlets.id"))
    feed_type = Column(String, default="rss")  # rss/scrape
    status = Column(String, default="ok")      # ok/error
    articles_captured = Column(Integer, default=0)
    error_message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)


class LLMUsage(HasTenant, Base):
    __tablename__ = "llm_usage"
    id = Column(Integer, primary_key=True)
    date = Column(Date, default=date.today, index=True)
    model = Column(String)
    purpose = Column(String)  # extraction/profile/plan
    prompt_tokens = Column(Integer, default=0)
    completion_tokens = Column(Integer, default=0)
    cost_usd = Column(Float, default=0.0)


class Citation(HasTenant, Base):
    __tablename__ = "citations"
    id = Column(Integer, primary_key=True)
    source_outlet_id = Column(Integer, ForeignKey("outlets.id"), nullable=False, index=True)
    target_outlet_id = Column(Integer, ForeignKey("outlets.id"), nullable=False, index=True)
    article_id = Column(Integer, ForeignKey("articles.id"), nullable=False)
    match_type = Column(String, default="entity")  # entity/url/name_variant
    timestamp = Column(DateTime, default=datetime.utcnow)


# ------------------------------------------------------------------ contacts

class JournalistContact(HasTenant, Base):
    """Canal de contact d'un journaliste, toujours avec sa preuve (source, méthode, confiance)."""
    __tablename__ = "journalist_contacts"
    id = Column(Integer, primary_key=True)
    journalist_id = Column(Integer, ForeignKey("journalists.id"), nullable=False, index=True)
    kind = Column(String, nullable=False)        # email / x / bluesky / mastodon / linkedin / instagram / threads / facebook / author_page / website / wikipedia / phone / signal / other
    value = Column(String, nullable=False)       # adresse, @handle, URL
    confidence = Column(String, default="verified")  # verified (lien attaché à la signature / page auteur) · probable (texte, recherche publique) · guess (motif d'adresse)
    method = Column(String)                      # jsonld / byline_link / author_page / article_text / meta / pattern / bluesky_search / manual
    source_url = Column(String)                  # page où le canal a été vu
    note = Column(Text)
    invalid = Column(Integer, default=0)         # 1 = marqué invalide par l'utilisateur
    first_seen = Column(DateTime, default=datetime.utcnow)
    last_seen = Column(DateTime, default=datetime.utcnow)


class ContactScan(HasTenant, Base):
    """Trace des journalistes déjà passés à la détection de contacts."""
    __tablename__ = "contact_scans"
    journalist_id = Column(Integer, ForeignKey("journalists.id"), primary_key=True)
    scanned_at = Column(DateTime, default=datetime.utcnow)
    found = Column(Integer, default=0)
    pages_fetched = Column(Integer, default=0)


# ------------------------------------------------------------------ assistant

class Conversation(HasTenant, Base):
    __tablename__ = "conversations"
    id = Column(Integer, primary_key=True)
    title = Column(String, default="Nouvelle conversation")
    context = Column(JSON, default=dict)      # {"page": "/outlets/3", "label": "Le Figaro"} épinglé
    state = Column(JSON, default=list)        # historique au format « input » de l'API Responses
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class Message(HasTenant, Base):
    __tablename__ = "messages"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=False, index=True)
    role = Column(String, nullable=False)     # user / assistant
    content = Column(Text, default="")        # texte final (markdown)
    parts = Column(JSON, default=list)        # [{type: text|tool|confirm|chart|artifact|citations, ...}] dans l'ordre d'affichage
    cost_usd = Column(Float, default=0.0)
    created_at = Column(DateTime, default=datetime.utcnow)


class Artifact(HasTenant, Base):
    __tablename__ = "artifacts"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)
    kind = Column(String, nullable=False)     # csv/xlsx/md/docx/pdf/html/png/report
    title = Column(String)
    filename = Column(String, nullable=False)
    path = Column(String, nullable=False)
    mime = Column(String, default="application/octet-stream")
    size = Column(Integer, default=0)
    meta = Column(JSON, default=dict)         # {report_kind, target_id, ...}
    created_at = Column(DateTime, default=datetime.utcnow)


class AgentAction(HasTenant, Base):
    __tablename__ = "agent_actions"
    id = Column(Integer, primary_key=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True, index=True)
    tool = Column(String, nullable=False)
    args = Column(JSON, default=dict)
    description = Column(Text)                # phrase lisible : « Passer l'accessibilité de X de 62 à 75 »
    status = Column(String, default="proposed")  # proposed / applied / rejected / undone / failed
    before = Column(JSON)                     # instantané avant écriture (pour annuler)
    after = Column(JSON)
    result = Column(JSON)
    error = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    applied_at = Column(DateTime)


class Report(HasTenant, Base):
    """Brouillon de note : blocs éditables, PDF à l'export."""
    __tablename__ = "reports"
    id = Column(Integer, primary_key=True)
    kind = Column(String, nullable=False)
    target = Column(String)
    country = Column(String)
    weeks = Column(Integer, default=8)
    notes = Column(Text)
    locale = Column(String, default="fr")
    title = Column(String)
    subtitle = Column(String)
    status = Column(String, default="draft")  # draft | exported
    body = Column(JSON, default=dict)          # {kicker, blocks}
    catalog = Column(JSON, default=list)       # widgets disponibles [{widget, title, caption, svg}]
    pdf_artifact_id = Column(Integer)
    html_artifact_id = Column(Integer)
    conversation_id = Column(Integer, ForeignKey("conversations.id"), nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


TENANT_MODELS = (
    Setting, Outlet, OutletFeed, Journalist, Article, ArticleJournalist,
    JournalistProfile, OutletProfile, Client, ClientContact, ClientBlacklist,
    Recommendation, ActionHistory, IngestionLog, LLMUsage, Citation,
    JournalistContact, ContactScan, Conversation, Message, Artifact,
    AgentAction, Report,
)

