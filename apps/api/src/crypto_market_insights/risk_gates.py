"""Hard risk gates and explicit No Trade decisions."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

RISK_GATE_STRATEGY_VERSION = "risk-gates-v1"


class RiskGatePolicy(BaseModel):
    """Configurable thresholds for unsafe or low-quality setups."""

    model_config = ConfigDict(frozen=True)

    strategy_version: str = Field(default=RISK_GATE_STRATEGY_VERSION, min_length=1)
    max_candle_age: timedelta = timedelta(hours=26)
    min_quote_volume: Decimal = Field(default=Decimal("10000000"), ge=0)
    min_liquidity_score: Decimal = Field(default=Decimal(60), ge=0, le=100)
    max_atr_to_close: Decimal = Field(default=Decimal("0.20"), gt=0)
    min_post_cost_reward_risk: Decimal = Field(default=Decimal("1.50"), gt=0)
    setup_expiry: timedelta = timedelta(hours=24)

    @field_validator("setup_expiry")
    @classmethod
    def positive_expiry(cls, value: timedelta) -> timedelta:
        if value <= timedelta(0):
            raise ValueError("setup_expiry must be positive.")
        return value


class RiskGateReason(BaseModel):
    """Machine-readable gate failure with a human-readable explanation."""

    model_config = ConfigDict(frozen=True)

    code: str = Field(min_length=1)
    message: str = Field(min_length=1)


class RiskGateInput(BaseModel):
    """Point-in-time facts required to approve or reject one candidate setup."""

    model_config = ConfigDict(frozen=True)

    candidate_asset_id: str = Field(min_length=1)
    venue: str = Field(min_length=1)
    venue_pair: str | None
    pair_mapping_status: Literal["resolved", "uncertain", "unsupported"]
    evaluated_at: datetime
    latest_completed_close_time: datetime | None
    latest_completed_candle_count: int = Field(ge=0)
    required_candle_count: int = Field(ge=1)
    quote_volume: Decimal | None = Field(default=None, ge=0)
    liquidity_score: Decimal | None = Field(default=None, ge=0, le=100)
    close_price: Decimal | None = Field(default=None, gt=0)
    atr: Decimal | None = Field(default=None, ge=0)
    gross_reward_risk: Decimal | None = Field(default=None, ge=0)
    fee_bps: Decimal = Field(default=Decimal(0), ge=0)
    slippage_bps: Decimal = Field(default=Decimal(0), ge=0)
    severe_event_status: Literal["none", "resolved", "unresolved"] = "none"
    positive_sentiment_score: Decimal = Field(default=Decimal(0), ge=0, le=100)
    timeframes_aligned: bool
    invalidation_price: Decimal | None = Field(default=None, gt=0)
    setup_expiry: datetime | None = None

    @field_validator("evaluated_at", "latest_completed_close_time", "setup_expiry")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Timestamp must include a timezone.")
            return value.astimezone(UTC)
        return value

    @field_validator("venue")
    @classmethod
    def normalize_venue(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("Venue cannot be empty.")
        return normalized


class RiskGateResult(BaseModel):
    """Persistable candidate outcome and explicit blocking reasons."""

    model_config = ConfigDict(frozen=True)

    candidate_asset_id: str
    strategy_version: str
    outcome: Literal["TRADE", "NO_TRADE"]
    approved: bool
    reasons: tuple[RiskGateReason, ...]
    evaluated_at: datetime
    expires_at: datetime
    post_cost_reward_risk: Decimal | None


class RiskGateEvaluator:
    """Apply independent deterministic hard vetoes."""

    def __init__(self, policy: RiskGatePolicy | None = None) -> None:
        self.policy = policy or RiskGatePolicy()

    def evaluate(self, inputs: RiskGateInput) -> RiskGateResult:
        reasons: list[RiskGateReason] = []

        if inputs.latest_completed_close_time is None:
            reasons.append(
                RiskGateReason(
                    code="missing_completed_candle",
                    message="No completed candle is available for this candidate.",
                )
            )
        else:
            age = inputs.evaluated_at - inputs.latest_completed_close_time
            if age < timedelta(0):
                reasons.append(
                    RiskGateReason(
                        code="future_candle",
                        message="The latest completed candle closes after the evaluation time.",
                    )
                )
            elif age > self.policy.max_candle_age:
                reasons.append(
                    RiskGateReason(
                        code="stale_candle",
                        message=(
                            f"The latest completed candle is {age} old; "
                            f"the maximum allowed age is {self.policy.max_candle_age}."
                        ),
                    )
                )

        if inputs.latest_completed_candle_count < inputs.required_candle_count:
            reasons.append(
                RiskGateReason(
                    code="missing_candle_history",
                    message=(
                        f"Only {inputs.latest_completed_candle_count} completed candles are "
                        f"available; {inputs.required_candle_count} are required."
                    ),
                )
            )

        if (
            inputs.pair_mapping_status != "resolved"
            or inputs.venue_pair is None
            or not inputs.venue_pair.strip()
        ):
            reasons.append(
                RiskGateReason(
                    code="uncertain_pair_mapping",
                    message=(
                        "The venue/pair mapping is unresolved or unsupported; "
                        "no substitute pair will be used."
                    ),
                )
            )

        if (
            inputs.quote_volume is None
            or inputs.liquidity_score is None
            or inputs.quote_volume < self.policy.min_quote_volume
            or inputs.liquidity_score < self.policy.min_liquidity_score
        ):
            reasons.append(
                RiskGateReason(
                    code="poor_liquidity",
                    message=("Quote volume or liquidity quality is below the configured minimum."),
                )
            )

        if inputs.close_price is None or inputs.atr is None:
            reasons.append(
                RiskGateReason(
                    code="volatility_input_missing",
                    message=(
                        "Close price or ATR is missing, so volatility safety cannot be verified."
                    ),
                )
            )
        else:
            atr_fraction = inputs.atr / inputs.close_price
            if atr_fraction > self.policy.max_atr_to_close:
                reasons.append(
                    RiskGateReason(
                        code="abnormal_volatility",
                        message=(
                            f"ATR is {atr_fraction:.2%} of close price, above the "
                            f"{self.policy.max_atr_to_close:.2%} limit."
                        ),
                    )
                )

        post_cost_rr = self._post_cost_reward_risk(inputs)
        if post_cost_rr is None:
            reasons.append(
                RiskGateReason(
                    code="reward_risk_input_missing",
                    message="Gross reward/risk is missing, so post-cost reward/risk is unknown.",
                )
            )
        elif post_cost_rr < self.policy.min_post_cost_reward_risk:
            reasons.append(
                RiskGateReason(
                    code="poor_post_cost_reward_risk",
                    message=(
                        f"Post-cost reward/risk is {post_cost_rr:.2f}, below the "
                        f"{self.policy.min_post_cost_reward_risk:.2f} minimum."
                    ),
                )
            )

        if inputs.severe_event_status == "unresolved":
            reasons.append(
                RiskGateReason(
                    code="unresolved_severe_event",
                    message=(
                        "A severe event remains unresolved. Positive sentiment cannot override "
                        "this hard gate."
                    ),
                )
            )

        if not inputs.timeframes_aligned:
            reasons.append(
                RiskGateReason(
                    code="timeframes_misaligned",
                    message="Required market-data timeframes materially conflict.",
                )
            )

        if inputs.invalidation_price is None:
            reasons.append(
                RiskGateReason(
                    code="undefined_invalidation",
                    message="No thesis invalidation/invalidation price is defined.",
                )
            )

        expires_at = inputs.setup_expiry or (inputs.evaluated_at + self.policy.setup_expiry)
        if expires_at <= inputs.evaluated_at:
            reasons.append(
                RiskGateReason(
                    code="invalid_setup_expiry",
                    message="The setup expires at or before the evaluation time.",
                )
            )

        unique_reasons = tuple(dict((reason.code, reason) for reason in reasons).values())
        approved = not unique_reasons
        return RiskGateResult(
            candidate_asset_id=inputs.candidate_asset_id,
            strategy_version=self.policy.strategy_version,
            outcome="TRADE" if approved else "NO_TRADE",
            approved=approved,
            reasons=unique_reasons,
            evaluated_at=inputs.evaluated_at,
            expires_at=expires_at,
            post_cost_reward_risk=post_cost_rr,
        )

    @staticmethod
    def _post_cost_reward_risk(inputs: RiskGateInput) -> Decimal | None:
        if inputs.gross_reward_risk is None:
            return None
        cost_fraction = (inputs.fee_bps + inputs.slippage_bps) / Decimal(10000)
        return inputs.gross_reward_risk * (Decimal(1) - cost_fraction)
