"""Database models package."""

from .base import TimestampMixin
from .conversation_theme import ConversationTheme, ThemeType
from .deep_insight import DeepInsight, InsightAction, InsightType
from .economic import EconomicIndicator
from .indicator import TechnicalIndicator
from .insight import Insight, InsightAnnotation
from .insight_conversation import (
    ContentType,
    ConversationStatus,
    FollowUpResearch,
    InsightConversation,
    InsightConversationMessage,
    InsightModification,
    MessageRole,
    ModificationStatus,
    ModificationType,
    ResearchStatus,
    ResearchType,
)
from .insight_outcome import InsightOutcome, OutcomeCategory, TrackingStatus
from .insight_research_context import InsightResearchContext
from .knowledge_pattern import KnowledgePattern, PatternType
from .portfolio import Portfolio, PortfolioHolding
from .price import PriceHistory
from .settings import UserSettings
from .analysis_task import AnalysisTask, AnalysisTaskStatus, PHASE_PROGRESS, PHASE_NAMES
from .alpha_engine import AnalysisRun, AnalysisRunStatus, CandidateIdea, MarketSnapshot, SecuritySignal
from .statistical_feature import StatisticalFeature, StatisticalFeatureType
from .stock import Stock
from .thematic_insight import LifecycleState, ThematicInsight
from .thematic_outcome import ThematicOutcome

__all__ = [
    "TimestampMixin",
    "Stock",
    "PriceHistory",
    "TechnicalIndicator",
    "Insight",
    "InsightAnnotation",
    "EconomicIndicator",
    "UserSettings",
    "DeepInsight",
    "InsightAction",
    "InsightType",
    "InsightResearchContext",
    # Insight conversation models
    "InsightConversation",
    "InsightConversationMessage",
    "InsightModification",
    "FollowUpResearch",
    "ConversationStatus",
    "MessageRole",
    "ContentType",
    "ModificationType",
    "ModificationStatus",
    "ResearchType",
    "ResearchStatus",
    # Conversation theme models
    "ConversationTheme",
    "ThemeType",
    # Knowledge pattern models
    "KnowledgePattern",
    "PatternType",
    # Statistical feature models
    "StatisticalFeature",
    "StatisticalFeatureType",
    # Insight outcome models
    "InsightOutcome",
    "OutcomeCategory",
    "TrackingStatus",
    # Analysis task models
    "AnalysisTask",
    "AnalysisTaskStatus",
    "PHASE_PROGRESS",
    "PHASE_NAMES",
    # Alpha engine models
    "AnalysisRun",
    "AnalysisRunStatus",
    "MarketSnapshot",
    "SecuritySignal",
    "CandidateIdea",
    # Portfolio models
    "Portfolio",
    "PortfolioHolding",
    # Thematic insight models
    "ThematicInsight",
    "LifecycleState",
    "ThematicOutcome",
]
