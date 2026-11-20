"""Enumerations shared by all platform contracts.

Values are taken verbatim from the v2.1 baseline:
docs/plans/Shutu_AI_Trading_Lab_Codex_Execution_Plan_v2.1.md (正交状态定义)
and docs/plans/Shutu_AI_Trading_Lab_Architecture_and_Codex_Plan_v2.1.md §6.1/§4.6.
"""

from __future__ import annotations

from enum import StrEnum


class Environment(StrEnum):
    """Trading environment. A process is bound to exactly one at startup and
    can never switch (`docs/plans/...Architecture...v2.1.md` §6.3: 不得在一个
    进程里通过 paper=false 切换环境)."""

    PAPER = "PAPER"
    LIVE = "LIVE"


class OrderState(StrEnum):
    """Order lifecycle states (architecture §6.1 item 4).

    Monotonicity of legal transitions is enforced by the OMS (M2); M0 only
    fixes the vocabulary.
    """

    PREPARED = "PREPARED"
    SUBMITTING = "SUBMITTING"
    ACK = "ACK"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    CANCEL_PENDING = "CANCEL_PENDING"
    CANCELED = "CANCELED"
    REJECTED = "REJECTED"
    UNKNOWN = "UNKNOWN"


class EvidenceState(StrEnum):
    NOT_EVALUATED = "NOT_EVALUATED"
    HIST_OOS_SUPPORTED = "HIST_OOS_SUPPORTED"
    FORWARD_OBSERVING = "FORWARD_OBSERVING"
    FORWARD_SUPPORTED = "FORWARD_SUPPORTED"
    INCONCLUSIVE = "INCONCLUSIVE"
    FAILED = "FAILED"


class DeploymentState(StrEnum):
    NOT_DEPLOYED = "NOT_DEPLOYED"
    SHADOW_RUNNING = "SHADOW_RUNNING"
    PAPER_RUNNING = "PAPER_RUNNING"
    LIVE_RUNNING = "LIVE_RUNNING"
    PAUSED = "PAUSED"
    RETIRED = "RETIRED"


class StrategyRole(StrEnum):
    CANDIDATE = "CANDIDATE"
    CHALLENGER = "CHALLENGER"
    CHAMPION_PAPER = "CHAMPION_PAPER"
    CHAMPION_LIVE = "CHAMPION_LIVE"
    NONE = "NONE"


class FinalHoldoutStatus(StrEnum):
    SEALED = "SEALED"
    PASS = "PASS"
    FAILED = "FAILED"
    INCONCLUSIVE = "INCONCLUSIVE"
    INVALIDATED = "INVALIDATED"


class HaltState(StrEnum):
    """New-risk halt states used by the kill switch and (from M2) the risk
    engine. ``HALT_NEW_RISK`` always preserves the ability to run read-only
    queries and risk-reduction-only actions."""

    NORMAL = "NORMAL"
    HALT_NEW_RISK = "HALT_NEW_RISK"


class AdjustmentKind(StrEnum):
    """Price adjustment marker for MarketBar (contract §2.2 field
    ``adjustment``)."""

    RAW = "RAW"
    ADJUSTED = "ADJUSTED"
