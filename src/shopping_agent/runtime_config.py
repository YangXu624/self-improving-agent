"""Runtime configuration model, validated presets, and operational limits.

Provides explicit, validated configuration across the agent execution path:
- LLM parameters (calls per turn, timeout, max tokens, spending cap)
- Shopping & search parameters (searches per turn, candidate limit, BM25 mode, fallback)
- User memory parameters (enabled, similarity threshold, top-k, recency weighting)
- Procedural memory parameters (enabled, confidence threshold, top-k)
- Evaluation parameters (max turns, mode, spending cap, shopper type)

Security and catalogue verification safeguards remain strictly immutable.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Literal


class ConfigurationError(ValueError):
    """Raised when runtime configuration violates operational bounds."""


@dataclass
class RuntimeConfig:
    # 1. LLM Settings
    agent_max_calls: int = 3
    max_retries: int = 0
    timeout: float = 25.0
    max_tokens: int = 2000
    model: str = "deepseek-flash"
    session_api_cost_ceiling_usd: float = 2.00

    # 2. Shopping & Search Settings
    agent_max_searches: int = 2
    candidate_retrieval_limit: int = 5
    bm25_matching_mode: Literal["all", "any"] = "all"
    search_fallback: bool = True
    max_conversation_turns: int = 6
    context_budget: int = 8000
    cards_profile: str = "baseline"
    memory_format: Literal["compact", "legacy"] = "legacy"

    # 3. User Memory Settings
    user_memory_enabled: bool = True
    user_memory_similarity_threshold: float = 0.45
    user_memory_top_k: int = 5
    user_memory_context_budget: int = 1500
    user_memory_recency_weighting: float = 0.95

    # 4. Procedural Memory Settings
    procedural_memory_enabled: bool = False
    procedural_confidence_threshold: float = 0.70
    procedural_top_k: int = 2
    procedural_context_budget: int = 800

    # 5. Evaluation Settings
    eval_max_agent_turns: int = 6
    eval_mode: Literal["target_item", "preference"] = "target_item"
    eval_per_run_spending_cap_usd: float = 2.00
    eval_shopper_type: Literal["scripted", "ollama", "deepseek"] = "scripted"

    def __post_init__(self) -> None:
        self.validate()

    def validate(self) -> None:
        """Validate all operational limits against safe bounds."""
        # LLM bounds
        if not 1 <= self.agent_max_calls <= 6:
            raise ConfigurationError("agent_max_calls must be between 1 and 6")
        if not 0 <= self.max_retries <= 3:
            raise ConfigurationError("max_retries must be between 0 and 3")
        if not 5.0 <= self.timeout <= 120.0:
            raise ConfigurationError("timeout must be between 5.0 and 120.0 seconds")
        if not 200 <= self.max_tokens <= 4000:
            raise ConfigurationError("max_tokens must be between 200 and 4000")
        if not 0.10 <= self.session_api_cost_ceiling_usd <= 50.0:
            raise ConfigurationError(
                "session_api_cost_ceiling_usd must be between $0.10 and $50.00"
            )

        # Shopping & search bounds
        if not 1 <= self.agent_max_searches <= 3:
            raise ConfigurationError("agent_max_searches must be between 1 and 3")
        if not 1 <= self.candidate_retrieval_limit <= 10:
            raise ConfigurationError(
                "candidate_retrieval_limit must be between 1 and 10"
            )
        if self.bm25_matching_mode not in {"all", "any"}:
            raise ConfigurationError("bm25_matching_mode must be 'all' or 'any'")
        if not 1 <= self.max_conversation_turns <= 20:
            raise ConfigurationError("max_conversation_turns must be between 1 and 20")
        if not 1000 <= self.context_budget <= 16000:
            raise ConfigurationError("context_budget must be between 1000 and 16000")
        if self.memory_format not in {"compact", "legacy"}:
            raise ConfigurationError("memory_format must be 'compact' or 'legacy'")

        # User memory bounds
        if not 0.10 <= self.user_memory_similarity_threshold <= 0.90:
            raise ConfigurationError(
                "user_memory_similarity_threshold must be between 0.10 and 0.90"
            )
        if not 1 <= self.user_memory_top_k <= 10:
            raise ConfigurationError("user_memory_top_k must be between 1 and 10")
        if not 0.0 <= self.user_memory_recency_weighting <= 1.0:
            raise ConfigurationError(
                "user_memory_recency_weighting must be between 0.0 and 1.0"
            )

        # Procedural memory bounds
        if not 0.10 <= self.procedural_confidence_threshold <= 1.0:
            raise ConfigurationError(
                "procedural_confidence_threshold must be between 0.10 and 1.0"
            )
        if not 1 <= self.procedural_top_k <= 5:
            raise ConfigurationError("procedural_top_k must be between 1 and 5")

        # Evaluation bounds
        if not 1 <= self.eval_max_agent_turns <= 12:
            raise ConfigurationError("eval_max_agent_turns must be between 1 and 12")
        if self.eval_mode not in {"target_item", "preference"}:
            raise ConfigurationError("eval_mode must be 'target_item' or 'preference'")
        if not 0.10 <= self.eval_per_run_spending_cap_usd <= 20.0:
            raise ConfigurationError(
                "eval_per_run_spending_cap_usd must be between $0.10 and $20.00"
            )
        if self.eval_shopper_type not in {"scripted", "ollama", "deepseek"}:
            raise ConfigurationError(
                "eval_shopper_type must be 'scripted', 'ollama', or 'deepseek'"
            )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RuntimeConfig:
        fields = cls.__dataclass_fields__
        clean = {k: v for k, v in data.items() if k in fields}
        return cls(**clean)

    @classmethod
    def from_json(cls, text: str) -> RuntimeConfig:
        return cls.from_dict(json.loads(text))

    def copy(self, **overrides: Any) -> RuntimeConfig:
        d = self.to_dict()
        d.update(overrides)
        return RuntimeConfig.from_dict(d)

    def diff_from(self, other: RuntimeConfig) -> dict[str, dict[str, Any]]:
        """Return dict of differing keys with their values in other and self."""
        diffs = {}
        for k, v in self.to_dict().items():
            other_v = getattr(other, k, None)
            if v != other_v:
                diffs[k] = {"configured": v, "reference": other_v}
        return diffs


# -----------------------------------------------------------------------------
# Configuration Presets
# -----------------------------------------------------------------------------

DEFAULT_CONFIG = RuntimeConfig()

DEMO_PRESET = RuntimeConfig(
    agent_max_calls=4,
    agent_max_searches=3,
    timeout=35.0,
    max_conversation_turns=10,
    candidate_retrieval_limit=6,
    search_fallback=True,
    user_memory_enabled=True,
    user_memory_similarity_threshold=0.40,
    user_memory_top_k=5,
    procedural_memory_enabled=False,
    session_api_cost_ceiling_usd=3.00,
)

EVALUATION_PRESET = RuntimeConfig(
    agent_max_calls=3,
    agent_max_searches=2,
    timeout=25.0,
    max_conversation_turns=6,
    candidate_retrieval_limit=5,
    search_fallback=True,
    user_memory_enabled=True,
    user_memory_similarity_threshold=0.45,
    user_memory_top_k=5,
    procedural_memory_enabled=False,
    session_api_cost_ceiling_usd=2.00,
)

PRESETS: dict[str, RuntimeConfig] = {
    "Demo (Interactive)": DEMO_PRESET,
    "Evaluation (Standard Benchmark)": EVALUATION_PRESET,
}

# Documentation and metadata about configurable settings
PARAMETER_METADATA: dict[str, dict[str, Any]] = {
    "agent_max_calls": {
        "label": "Max Model Calls / Turn",
        "category": "LLM",
        "description": "Maximum reasoning attempts or tool iterations per customer message.",
        "bounds": (1, 6),
        "type": "int",
        "default": DEFAULT_CONFIG.agent_max_calls,
    },
    "timeout": {
        "label": "HTTP Request Timeout (s)",
        "category": "LLM",
        "description": "Per-call HTTP socket timeout in seconds for DeepSeek chat completions.",
        "bounds": (5.0, 120.0),
        "type": "float",
        "default": DEFAULT_CONFIG.timeout,
    },
    "max_tokens": {
        "label": "Max Output Tokens",
        "category": "LLM",
        "description": "Output token ceiling requested per model response.",
        "bounds": (200, 4000),
        "type": "int",
        "default": DEFAULT_CONFIG.max_tokens,
    },
    "session_api_cost_ceiling_usd": {
        "label": "Session API Spending Cap ($)",
        "category": "LLM",
        "description": "Hard dollar cost ceiling per session before halting agent execution.",
        "bounds": (0.10, 20.00),
        "type": "float",
        "default": DEFAULT_CONFIG.session_api_cost_ceiling_usd,
    },
    "agent_max_searches": {
        "label": "Max Product Searches / Turn",
        "category": "Shopping & Search",
        "description": "Maximum SQLite FTS product search tool calls permitted in one turn.",
        "bounds": (1, 3),
        "type": "int",
        "default": DEFAULT_CONFIG.agent_max_searches,
    },
    "candidate_retrieval_limit": {
        "label": "Candidate Retrieval Limit",
        "category": "Shopping & Search",
        "description": "Maximum candidate product records returned by search tool.",
        "bounds": (1, 10),
        "type": "int",
        "default": DEFAULT_CONFIG.candidate_retrieval_limit,
    },
    "bm25_matching_mode": {
        "label": "BM25 Matching Mode",
        "category": "Shopping & Search",
        "description": "'all' (conjunction AND of terms) or 'any' (disjunction OR).",
        "options": ["all", "any"],
        "type": "choice",
        "default": DEFAULT_CONFIG.bm25_matching_mode,
    },
    "search_fallback": {
        "label": "Search Fallback Strategy",
        "category": "Shopping & Search",
        "description": "Automatically relax over-constrained query terms or mode if zero candidates found.",
        "type": "bool",
        "default": DEFAULT_CONFIG.search_fallback,
    },
    "max_conversation_turns": {
        "label": "Max Conversation Turns",
        "category": "Shopping & Search",
        "description": "Maximum customer-agent message rounds allowed before session closure.",
        "bounds": (1, 20),
        "type": "int",
        "default": DEFAULT_CONFIG.max_conversation_turns,
    },
    "user_memory_enabled": {
        "label": "User Memory Enabled",
        "category": "User Memory",
        "description": "Enable cross-session preference retrieval, injection, and consolidation.",
        "type": "bool",
        "default": DEFAULT_CONFIG.user_memory_enabled,
    },
    "user_memory_similarity_threshold": {
        "label": "Memory Similarity Threshold",
        "category": "User Memory",
        "description": "Minimum embedding cosine similarity + lexical bonus for memory injection.",
        "bounds": (0.10, 0.90),
        "type": "float",
        "default": DEFAULT_CONFIG.user_memory_similarity_threshold,
    },
    "user_memory_top_k": {
        "label": "Top-K Retrieved Memories",
        "category": "User Memory",
        "description": "Maximum user preference records injected into prompt context.",
        "bounds": (1, 10),
        "type": "int",
        "default": DEFAULT_CONFIG.user_memory_top_k,
    },
    "user_memory_recency_weighting": {
        "label": "Memory Recency Weighting",
        "category": "User Memory",
        "description": "Decay factor applied to older memories (1.0 = no decay).",
        "bounds": (0.0, 1.0),
        "type": "float",
        "default": DEFAULT_CONFIG.user_memory_recency_weighting,
    },
    "procedural_memory_enabled": {
        "label": "Procedural Memory Enabled",
        "category": "Procedural Memory",
        "description": "Retrieve centralized procedural lessons and rules into decision context.",
        "type": "bool",
        "default": DEFAULT_CONFIG.procedural_memory_enabled,
    },
    "procedural_confidence_threshold": {
        "label": "Lesson Confidence Threshold",
        "category": "Procedural Memory",
        "description": "Minimum confidence required to inject a procedural lesson directive.",
        "bounds": (0.10, 1.0),
        "type": "float",
        "default": DEFAULT_CONFIG.procedural_confidence_threshold,
    },
    "procedural_top_k": {
        "label": "Top-K Procedural Lessons",
        "category": "Procedural Memory",
        "description": "Maximum number of procedural directives injected per decision.",
        "bounds": (1, 5),
        "type": "int",
        "default": DEFAULT_CONFIG.procedural_top_k,
    },
    "eval_max_agent_turns": {
        "label": "Evaluation Max Turns",
        "category": "Evaluation",
        "description": "Turn limit per evaluation visit before scoring target success.",
        "bounds": (1, 12),
        "type": "int",
        "default": DEFAULT_CONFIG.eval_max_agent_turns,
    },
    "eval_mode": {
        "label": "Evaluation Mode",
        "category": "Evaluation",
        "description": "'target_item' scoring (Target Success@N) or 'preference' satisfaction scoring.",
        "options": ["target_item", "preference"],
        "type": "choice",
        "default": DEFAULT_CONFIG.eval_mode,
    },
    "eval_per_run_spending_cap_usd": {
        "label": "Evaluation Spending Cap ($)",
        "category": "Evaluation",
        "description": "Hard dollar cost cap for an evaluation run.",
        "bounds": (0.10, 10.00),
        "type": "float",
        "default": DEFAULT_CONFIG.eval_per_run_spending_cap_usd,
    },
}
