"""Domain engines powering the eight product suites in Ryan Project Suites."""

from .accessibility import AccessibilityEngine
from .operator_os import OperatorOSEngine
from .brand_publishing import BrandPublishingEngine
from .production_house import ProductionHouseEngine
from .model_behavior import ModelBehaviorEngine
from .discovery_decision import DiscoveryDecisionEngine
from .agent_reliability import AgentReliabilityEngine
from .game_design import GameDesignEngine

ENGINES = {
    "accessibility": AccessibilityEngine,
    "operator-os": OperatorOSEngine,
    "brand-publishing": BrandPublishingEngine,
    "production-house": ProductionHouseEngine,
    "model-behavior-lab": ModelBehaviorEngine,
    "discovery-decision": DiscoveryDecisionEngine,
    "agent-reliability": AgentReliabilityEngine,
    "game-design": GameDesignEngine,
}

__all__ = [
    "ENGINES",
    "AccessibilityEngine",
    "OperatorOSEngine",
    "BrandPublishingEngine",
    "ProductionHouseEngine",
    "ModelBehaviorEngine",
    "DiscoveryDecisionEngine",
    "AgentReliabilityEngine",
    "GameDesignEngine",
]
