"""Point-in-time asset eligibility and deterministic candidate ranking."""

import re
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from types import MappingProxyType
from typing import ClassVar, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from crypto_market_insights.config import Settings
from crypto_market_insights.kraken import INTERVAL_MINUTES
from crypto_market_insights.market_metadata import AssetMarketMetadata

UNIVERSE_STRATEGY_VERSION = "universe-v1"
RANKING_STRATEGY_VERSION = "ranking-v1"
LEVERAGED_SYMBOL_PATTERN = re.compile(r"(?:[2-9]|[1-9]\d+)[LS]$")
KNOWN_ASSET_TYPES = frozenset({"stablecoin", "wrapped", "bridged", "leveraged", "synthetic"})


class UniversePolicy(BaseModel):
    """Configurable initial requirements for universe membership."""

    model_config = ConfigDict(frozen=True)

    size: int = Field(default=10, ge=1, le=250)
    quote_currency: str = Field(default="USD", min_length=2, max_length=20)
    history_timeframe: str = "1d"
    min_market_cap: Decimal = Field(default=Decimal("100000000"), ge=0)
    min_quote_volume: Decimal = Field(default=Decimal("10000000"), ge=0)
    min_history_candles: int = Field(default=200, ge=1)
    max_metadata_age: timedelta = timedelta(hours=24)
    max_history_age: timedelta = timedelta(hours=26)
    min_data_quality: Decimal = Field(default=Decimal(90), ge=0, le=100)
    universe_version: str = Field(default=UNIVERSE_STRATEGY_VERSION, min_length=1)
    stablecoin_symbols: frozenset[str] = frozenset(
        {
            "BUSD",
            "DAI",
            "FDUSD",
            "FRAX",
            "GUSD",
            "LUSD",
            "PYUSD",
            "TUSD",
            "USDC",
            "USDD",
            "USDE",
            "USDP",
            "USDT",
            "USDS",
            "UST",
        }
    )
    wrapped_symbols: frozenset[str] = frozenset(
        {"CBBTC", "CBETH", "RETH", "STETH", "WBTC", "WETH", "WSTETH"}
    )
    leveraged_symbols: frozenset[str] = frozenset(
        {
            "ADABULL",
            "ADABEAR",
            "BTCDOWN",
            "BTCUP",
            "ETHBEAR",
            "ETHBULL",
            "ETHDOWN",
            "ETHUP",
            "SOLBULL",
            "SOLBEAR",
        }
    )
    excluded_provider_asset_ids: frozenset[str] = frozenset()
    canonical_asset_overrides: dict[str, str] = Field(default_factory=dict)

    @field_validator("quote_currency")
    @classmethod
    def normalize_quote_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("quote_currency cannot be empty.")
        return normalized

    @field_validator("stablecoin_symbols", "wrapped_symbols", "leveraged_symbols")
    @classmethod
    def normalize_symbol_set(cls, value: frozenset[str]) -> frozenset[str]:
        return frozenset(symbol.strip().upper() for symbol in value if symbol.strip())

    @field_validator("canonical_asset_overrides")
    @classmethod
    def normalize_canonical_overrides(cls, value: dict[str, str]) -> dict[str, str]:
        normalized = {
            asset_id.strip().casefold(): canonical_id.strip()
            for asset_id, canonical_id in value.items()
        }
        if any(not asset_id or not canonical_id for asset_id, canonical_id in normalized.items()):
            raise ValueError("Canonical asset overrides cannot contain empty IDs.")
        return normalized

    @model_validator(mode="after")
    def validate_ages(self) -> "UniversePolicy":
        if self.max_metadata_age <= timedelta(0) or self.max_history_age <= timedelta(0):
            raise ValueError("Metadata and history age limits must be positive.")
        if self.history_timeframe not in INTERVAL_MINUTES:
            raise ValueError(f"Unsupported history timeframe: {self.history_timeframe}")
        return self

    @classmethod
    def from_settings(cls, settings: Settings) -> "UniversePolicy":
        """Create policy from the corresponding runtime settings."""
        return cls(
            size=settings.universe_size,
            quote_currency=settings.default_quote_currency,
            history_timeframe=settings.universe_history_timeframe,
            min_market_cap=settings.universe_min_market_cap,
            min_quote_volume=settings.universe_min_quote_volume,
            min_history_candles=settings.universe_min_history_candles,
            max_metadata_age=timedelta(hours=settings.universe_max_metadata_age_hours),
            max_history_age=timedelta(hours=settings.universe_max_history_age_hours),
            min_data_quality=settings.universe_min_data_quality,
        )


class UniverseObservation(BaseModel):
    """Point-in-time metadata, venue resolution, history, and quality for one asset."""

    model_config = ConfigDict(frozen=True)

    metadata: AssetMarketMetadata
    venue: str = Field(min_length=1, max_length=40)
    quote_currency: str = Field(min_length=2, max_length=20)
    history_timeframe: str = Field(min_length=1, max_length=16)
    venue_pair: str | None
    asset_types: frozenset[str] = frozenset()
    history_candle_count: int = Field(ge=0)
    history_as_of: datetime | None
    data_quality_score: Decimal | None = Field(default=None, ge=0, le=100)

    @field_validator("venue")
    @classmethod
    def normalize_venue(cls, value: str) -> str:
        normalized = value.strip().lower()
        if not normalized:
            raise ValueError("venue cannot be empty.")
        return normalized

    @field_validator("history_as_of")
    @classmethod
    def normalize_history_timestamp(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("history_as_of must include a timezone.")
            return value.astimezone(UTC)
        return value

    @field_validator("venue_pair")
    @classmethod
    def normalize_venue_pair(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None

    @field_validator("asset_types")
    @classmethod
    def validate_asset_types(cls, value: frozenset[str]) -> frozenset[str]:
        normalized = frozenset(asset_type.strip().lower() for asset_type in value)
        unknown = normalized - KNOWN_ASSET_TYPES
        if unknown:
            raise ValueError(f"Unsupported asset type tags: {', '.join(sorted(unknown))}.")
        return normalized

    @field_validator("quote_currency")
    @classmethod
    def normalize_quote_currency(cls, value: str) -> str:
        normalized = value.strip().upper()
        if not normalized:
            raise ValueError("quote_currency cannot be empty.")
        return normalized


class UniverseCandidate(BaseModel):
    """Eligibility decision and temporal membership for one evaluated asset."""

    model_config = ConfigDict(frozen=True)

    provider_asset_id: str
    canonical_asset_id: str
    symbol: str
    name: str
    venue_pair: str | None
    asset_types: frozenset[str]
    history_timeframe: str
    market_cap: Decimal | None
    quote_volume: Decimal | None
    metadata_source_timestamp: datetime
    metadata_retrieved_at: datetime
    history_candle_count: int
    history_as_of: datetime | None
    data_quality_score: Decimal | None
    eligible: bool
    selected: bool
    selection_rank: int | None
    effective_from: datetime | None
    exclusion_reasons: tuple[str, ...]


class UniverseSelection(BaseModel):
    """A reproducible, point-in-time universe decision including excluded candidates."""

    model_config = ConfigDict(frozen=True)

    evaluated_at: datetime
    venue: str
    quote_currency: str
    metadata_provider: str
    universe_version: str
    requested_size: int
    candidates: tuple[UniverseCandidate, ...]
    selected_asset_ids: tuple[str, ...]

    @property
    def selected(self) -> tuple[UniverseCandidate, ...]:
        return tuple(candidate for candidate in self.candidates if candidate.selected)


class RankingComponents(BaseModel):
    """Normalized 0–100 inputs for the six versioned ranking components."""

    model_config = ConfigDict(frozen=True)

    trend_alignment: Decimal = Field(ge=0, le=100)
    momentum_relative_strength: Decimal = Field(ge=0, le=100)
    volume_confirmation: Decimal = Field(ge=0, le=100)
    setup_quality: Decimal = Field(ge=0, le=100)
    liquidity_quality: Decimal = Field(ge=0, le=100)
    news_context: Decimal = Field(ge=0, le=100)


class RankingEvidence(BaseModel):
    """Normalized component values and any hard gates from deterministic analysis."""

    model_config = ConfigDict(frozen=True)

    components: RankingComponents
    gate_failures: tuple[str, ...] = ()

    @field_validator("gate_failures")
    @classmethod
    def validate_gate_failures(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        normalized = tuple(failure.strip() for failure in value)
        if any(not failure for failure in normalized):
            raise ValueError("Gate failure codes cannot be empty.")
        return tuple(dict.fromkeys(normalized))


class RankingEntry(BaseModel):
    """Component-level rank output; gated or missing evidence cannot receive a rank."""

    model_config = ConfigDict(frozen=True)

    provider_asset_id: str
    canonical_asset_id: str
    symbol: str
    venue_pair: str
    component_scores: RankingComponents | None
    total_score: Decimal | None
    rank: int | None
    strategy_version: str
    gate_failures: tuple[str, ...]


class RankingResult(BaseModel):
    """Versioned ranking output, including an explicit no-trade outcome."""

    model_config = ConfigDict(frozen=True)

    evaluated_at: datetime
    strategy_version: str
    weights: dict[str, Decimal]
    entries: tuple[RankingEntry, ...]
    no_trade: bool


class UniverseRepositoryProtocol(Protocol):
    """Persistence boundary used by the point-in-time selection service."""

    def persist(
        self,
        selection: UniverseSelection,
        ranking: RankingResult,
    ) -> UUID: ...


class RankingStrategy:
    """Weighted six-component score; weights are an explicit versioned hypothesis."""

    COMPONENT_WEIGHTS: ClassVar[Mapping[str, Decimal]] = MappingProxyType(
        {
            "trend_alignment": Decimal("0.25"),
            "momentum_relative_strength": Decimal("0.20"),
            "volume_confirmation": Decimal("0.15"),
            "setup_quality": Decimal("0.20"),
            "liquidity_quality": Decimal("0.10"),
            "news_context": Decimal("0.10"),
        }
    )

    def __init__(self, version: str = RANKING_STRATEGY_VERSION) -> None:
        if not version.strip():
            raise ValueError("Ranking strategy version cannot be empty.")
        if sum(self.COMPONENT_WEIGHTS.values(), Decimal(0)) != Decimal(1):
            raise RuntimeError("Ranking component weights must sum to 1.")
        self.version = version.strip()

    def score(self, components: RankingComponents) -> Decimal:
        weighted_score = sum(
            (getattr(components, name) * weight for name, weight in self.COMPONENT_WEIGHTS.items()),
            Decimal(0),
        )
        return weighted_score.quantize(Decimal("0.01"))


def select_universe(
    observations: list[UniverseObservation],
    *,
    venue: str,
    quote_currency: str,
    evaluated_at: datetime,
    policy: UniversePolicy | None = None,
) -> UniverseSelection:
    """Select eligible assets using only observations available at ``evaluated_at``."""
    if evaluated_at.tzinfo is None or evaluated_at.utcoffset() is None:
        raise ValueError("evaluated_at must include a timezone.")
    if not venue.strip():
        raise ValueError("venue cannot be empty.")
    policy = policy or UniversePolicy()
    effective_at = evaluated_at.astimezone(UTC)
    normalized_quote = quote_currency.strip().upper()
    if normalized_quote != policy.quote_currency:
        raise ValueError(
            f"Requested quote currency {normalized_quote!r} does not match the "
            f"universe policy {policy.quote_currency!r}."
        )

    normalized_venue = venue.strip().lower()
    providers = {observation.metadata.provider for observation in observations}
    if len(providers) > 1:
        raise ValueError("All universe observations must use the same metadata provider.")
    ids = [observation.metadata.provider_asset_id for observation in observations]
    if len(ids) != len(set(ids)):
        raise ValueError("Each provider asset may appear only once in a universe evaluation.")

    candidates: list[UniverseCandidate] = []
    eligible_observations: list[tuple[UniverseObservation, str]] = []
    for observation in observations:
        if observation.venue != normalized_venue:
            raise ValueError(
                f"Observation {observation.metadata.provider_asset_id!r} is for venue "
                f"{observation.venue!r}, expected {normalized_venue!r}."
            )
        if observation.quote_currency != normalized_quote:
            raise ValueError(
                f"Observation {observation.metadata.provider_asset_id!r} uses quote "
                f"{observation.quote_currency!r}, expected {normalized_quote!r}."
            )
        reasons = _eligibility_reasons(
            observation,
            evaluated_at=effective_at,
            policy=policy,
        )
        canonical_id = _canonical_asset_id(observation.metadata, policy)
        if not reasons:
            eligible_observations.append((observation, canonical_id))
        candidates.append(
            _candidate(
                observation,
                canonical_id=canonical_id,
                evaluated_at=effective_at,
                reasons=reasons,
                eligible=not reasons,
                selected=False,
                selection_rank=None,
                effective_from=None,
            )
        )

    eligible_observations.sort(
        key=lambda item: (
            -(item[0].metadata.market_cap or Decimal(0)),
            item[0].metadata.market_cap_rank or 2**31,
            item[0].metadata.provider_asset_id,
        )
    )
    seen_exposures: dict[str, str] = {}
    selected_ids: list[str] = []
    selected_ranks: dict[str, int] = {}
    duplicates: dict[str, str] = {}
    for observation, canonical_id in eligible_observations:
        prior_asset_id = seen_exposures.get(canonical_id.casefold())
        asset_id = observation.metadata.provider_asset_id
        if prior_asset_id is not None:
            duplicates[asset_id] = prior_asset_id
            continue
        seen_exposures[canonical_id.casefold()] = asset_id
        if len(selected_ids) < policy.size:
            selected_ids.append(asset_id)
            selected_ranks[asset_id] = len(selected_ids)

    updated: list[UniverseCandidate] = []
    for candidate in candidates:
        if candidate.provider_asset_id in duplicates:
            updated.append(
                candidate.model_copy(
                    update={
                        "eligible": False,
                        "exclusion_reasons": (
                            f"duplicate_exposure:{duplicates[candidate.provider_asset_id]}",
                        ),
                    }
                )
            )
            continue
        selected_rank = selected_ranks.get(candidate.provider_asset_id)
        updated.append(
            candidate.model_copy(
                update={
                    "selected": selected_rank is not None,
                    "selection_rank": selected_rank,
                    "effective_from": effective_at if selected_rank is not None else None,
                }
            )
        )

    updated.sort(
        key=lambda candidate: (
            candidate.selection_rank is None,
            candidate.selection_rank or 0,
            candidate.provider_asset_id,
        )
    )
    return UniverseSelection(
        evaluated_at=effective_at,
        venue=normalized_venue,
        quote_currency=normalized_quote,
        metadata_provider=observations[0].metadata.provider if observations else "unknown",
        universe_version=policy.universe_version,
        requested_size=policy.size,
        candidates=tuple(updated),
        selected_asset_ids=tuple(selected_ids),
    )


def _eligibility_reasons(
    observation: UniverseObservation,
    *,
    evaluated_at: datetime,
    policy: UniversePolicy,
) -> tuple[str, ...]:
    metadata = observation.metadata
    symbol = metadata.symbol.strip().upper()
    asset_id = metadata.provider_asset_id.strip().casefold()
    reasons: list[str] = []

    if asset_id in {value.strip().casefold() for value in policy.excluded_provider_asset_ids}:
        reasons.append("explicitly_excluded")
    if "stablecoin" in observation.asset_types or symbol in policy.stablecoin_symbols:
        reasons.append("stablecoin")
    if (
        observation.asset_types.intersection({"wrapped", "bridged"})
        or symbol in policy.wrapped_symbols
    ):
        reasons.append("wrapped_or_bridged_asset")
    if (
        "leveraged" in observation.asset_types
        or symbol in policy.leveraged_symbols
        or LEVERAGED_SYMBOL_PATTERN.search(symbol)
    ):
        reasons.append("leveraged_token")
    if "synthetic" in observation.asset_types:
        reasons.append("synthetic_asset")
    if metadata.market_cap is None or metadata.market_cap < policy.min_market_cap:
        reasons.append("market_cap_below_minimum")
    if metadata.total_volume is None or metadata.total_volume < policy.min_quote_volume:
        reasons.append("quote_volume_below_minimum")
    if metadata.current_price is None:
        reasons.append("missing_current_price")
    if observation.venue_pair is None:
        reasons.append("unsupported_venue_pair")
    if observation.history_candle_count < policy.min_history_candles:
        reasons.append("insufficient_history")
    if observation.history_timeframe != policy.history_timeframe:
        reasons.append("history_timeframe_mismatch")
    if observation.data_quality_score is None:
        reasons.append("missing_data_quality")
    elif observation.data_quality_score < policy.min_data_quality:
        reasons.append("data_quality_below_minimum")

    source_time = metadata.source_timestamp
    retrieved_time = metadata.retrieved_at
    if source_time > evaluated_at or retrieved_time > evaluated_at:
        reasons.append("metadata_from_future")
    elif (
        evaluated_at - source_time > policy.max_metadata_age
        or evaluated_at - retrieved_time > policy.max_metadata_age
    ):
        reasons.append("stale_metadata")

    history_time = observation.history_as_of
    if history_time is None:
        reasons.append("missing_history_timestamp")
    elif history_time > evaluated_at:
        reasons.append("history_from_future")
    elif evaluated_at - history_time > policy.max_history_age:
        reasons.append("stale_history")
    return tuple(dict.fromkeys(reasons))


def _canonical_asset_id(metadata: AssetMarketMetadata, policy: UniversePolicy) -> str:
    canonical_id = policy.canonical_asset_overrides.get(
        metadata.provider_asset_id.strip().casefold(),
        metadata.canonical_asset_id,
    )
    if not canonical_id.strip():
        raise ValueError("Canonical asset IDs cannot be empty.")
    return canonical_id.strip()


def _candidate(
    observation: UniverseObservation,
    *,
    canonical_id: str,
    evaluated_at: datetime,
    reasons: tuple[str, ...],
    eligible: bool,
    selected: bool,
    selection_rank: int | None,
    effective_from: datetime | None,
) -> UniverseCandidate:
    metadata = observation.metadata
    return UniverseCandidate(
        provider_asset_id=metadata.provider_asset_id,
        canonical_asset_id=canonical_id,
        symbol=metadata.symbol,
        name=metadata.name,
        venue_pair=observation.venue_pair,
        asset_types=observation.asset_types,
        history_timeframe=observation.history_timeframe,
        market_cap=metadata.market_cap,
        quote_volume=metadata.total_volume,
        metadata_source_timestamp=metadata.source_timestamp,
        metadata_retrieved_at=metadata.retrieved_at,
        history_candle_count=observation.history_candle_count,
        history_as_of=observation.history_as_of,
        data_quality_score=observation.data_quality_score,
        eligible=eligible,
        selected=selected,
        selection_rank=selection_rank,
        effective_from=effective_from,
        exclusion_reasons=reasons,
    )


def rank_candidates(
    selection: UniverseSelection,
    evidence_by_asset_id: dict[str, RankingEvidence],
    *,
    strategy: RankingStrategy | None = None,
) -> RankingResult:
    """Score selected universe members and apply explicit hard-gate vetoes."""
    strategy = strategy or RankingStrategy()
    selected_ids = set(selection.selected_asset_ids)
    unknown_ids = set(evidence_by_asset_id) - selected_ids
    if unknown_ids:
        raise ValueError(
            "Ranking evidence contains assets outside the selected universe: "
            + ", ".join(sorted(unknown_ids))
        )

    ranked: list[tuple[UniverseCandidate, Decimal]] = []
    entries_by_id: dict[str, RankingEntry] = {}
    for candidate in selection.selected:
        evidence = evidence_by_asset_id.get(candidate.provider_asset_id)
        if evidence is None:
            entries_by_id[candidate.provider_asset_id] = RankingEntry(
                provider_asset_id=candidate.provider_asset_id,
                canonical_asset_id=candidate.canonical_asset_id,
                symbol=candidate.symbol,
                venue_pair=candidate.venue_pair or "",
                component_scores=None,
                total_score=None,
                rank=None,
                strategy_version=strategy.version,
                gate_failures=("missing_ranking_evidence",),
            )
            continue
        score = strategy.score(evidence.components)
        if not evidence.gate_failures:
            ranked.append((candidate, score))
        entries_by_id[candidate.provider_asset_id] = RankingEntry(
            provider_asset_id=candidate.provider_asset_id,
            canonical_asset_id=candidate.canonical_asset_id,
            symbol=candidate.symbol,
            venue_pair=candidate.venue_pair or "",
            component_scores=evidence.components,
            total_score=score,
            rank=None,
            strategy_version=strategy.version,
            gate_failures=evidence.gate_failures,
        )

    ranked.sort(
        key=lambda item: (
            -item[1],
            item[0].canonical_asset_id.casefold(),
            item[0].provider_asset_id.casefold(),
        )
    )
    for rank, (candidate, _) in enumerate(ranked, start=1):
        entries_by_id[candidate.provider_asset_id] = entries_by_id[
            candidate.provider_asset_id
        ].model_copy(update={"rank": rank})

    ordered_entries = tuple(
        entries_by_id[candidate.provider_asset_id] for candidate in selection.selected
    )
    return RankingResult(
        evaluated_at=selection.evaluated_at,
        strategy_version=strategy.version,
        weights=dict(strategy.COMPONENT_WEIGHTS),
        entries=ordered_entries,
        no_trade=not ranked,
    )


class UniverseEvaluation(BaseModel):
    """Selection, ranking, and persistent run identifier for one evaluation."""

    model_config = ConfigDict(frozen=True)

    run_id: UUID
    selection: UniverseSelection
    ranking: RankingResult


class UniverseService:
    """Select, score, and persist one point-in-time candidate universe."""

    def __init__(
        self,
        repository: UniverseRepositoryProtocol,
        *,
        strategy: RankingStrategy | None = None,
    ) -> None:
        self._repository = repository
        self._strategy = strategy or RankingStrategy()

    def evaluate(
        self,
        observations: list[UniverseObservation],
        evidence_by_asset_id: dict[str, RankingEvidence],
        *,
        venue: str,
        quote_currency: str,
        evaluated_at: datetime,
        policy: UniversePolicy | None = None,
    ) -> UniverseEvaluation:
        selection = select_universe(
            observations,
            venue=venue,
            quote_currency=quote_currency,
            evaluated_at=evaluated_at,
            policy=policy,
        )
        ranking = rank_candidates(
            selection,
            evidence_by_asset_id,
            strategy=self._strategy,
        )
        run_id = self._repository.persist(selection, ranking)
        return UniverseEvaluation(run_id=run_id, selection=selection, ranking=ranking)
