"""Temporal aggregation for risk assessment over sliding windows.

Instead of reacting to single-frame noise, this module tracks risk state
over a configurable time window and requires sustained signals before
escalating -- critical for avoiding false alarms in real deployments.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

_RISK_LEVELS: dict[str, int] = {
    "NORMAL": 0,
    "WATCH": 1,
    "WARNING_CANDIDATE": 2,
    "UNKNOWN": -1,
}


class TemporalRiskError(ValueError):
    """Raised when temporal risk aggregation input is invalid."""


@dataclass(frozen=True)
class TemporalConfig:
    """Configuration for temporal risk aggregation."""

    window_minutes: int = 10
    watch_sustained_minutes: int = 3
    warning_sustained_minutes: int = 5
    min_samples: int = 3

    def __post_init__(self) -> None:
        if self.window_minutes < 1:
            raise TemporalRiskError("window_minutes must be at least 1")
        if self.min_samples < 1:
            raise TemporalRiskError("min_samples must be at least 1")


@dataclass
class _Sample:
    timestamp: datetime
    risk_state: str
    confidence: float
    water_ratio: float


@dataclass
class TemporalWindow:
    """Sliding window of risk assessments."""

    config: TemporalConfig
    _samples: deque[_Sample] = field(default_factory=deque)

    def add_sample(
        self,
        risk_state: str,
        confidence: float,
        water_ratio: float,
        *,
        timestamp: datetime | None = None,
    ) -> None:
        ts = timestamp or datetime.now(tz=UTC)
        self._samples.append(
            _Sample(
                timestamp=ts,
                risk_state=risk_state,
                confidence=confidence,
                water_ratio=water_ratio,
            )
        )
        self._evict_old(ts)

    def _evict_old(self, now: datetime) -> None:
        cutoff = now - timedelta(minutes=self.config.window_minutes)
        while self._samples and self._samples[0].timestamp < cutoff:
            self._samples.popleft()

    @property
    def sample_count(self) -> int:
        return len(self._samples)

    def evaluate(self, *, timestamp: datetime | None = None) -> dict[str, object]:
        """Evaluate the temporal risk state across the window.

        Returns a V1 record with the sustained risk state.
        """

        now = timestamp or datetime.now(tz=UTC)
        self._evict_old(now)

        if len(self._samples) < self.config.min_samples:
            return _build_record(
                risk_state="UNKNOWN",
                confidence=0.0,
                reason="Insufficient samples for temporal analysis",
                sample_count=len(self._samples),
                window_minutes=self.config.window_minutes,
                avg_water_ratio=0.0,
                timestamp=now,
            )

        warning_count = 0
        watch_count = 0
        total_confidence = 0.0
        total_water = 0.0

        for sample in self._samples:
            level = _RISK_LEVELS.get(sample.risk_state, -1)
            if level >= 2:
                warning_count += 1
            if level >= 1:
                watch_count += 1
            total_confidence += sample.confidence
            total_water += sample.water_ratio

        n = len(self._samples)
        avg_confidence = total_confidence / n
        avg_water = total_water / n

        warning_minutes = self._sustained_minutes("WARNING_CANDIDATE")
        watch_minutes = self._sustained_minutes("WATCH")

        if (
            warning_minutes >= self.config.warning_sustained_minutes
            and warning_count >= self.config.min_samples
        ):
            return _build_record(
                risk_state="WARNING_CANDIDATE",
                confidence=avg_confidence,
                reason=(
                    f"Warning-level risk sustained for {warning_minutes} minutes "
                    f"({warning_count}/{n} samples)"
                ),
                sample_count=n,
                window_minutes=self.config.window_minutes,
                avg_water_ratio=avg_water,
                timestamp=now,
            )

        if (
            watch_minutes >= self.config.watch_sustained_minutes
            and watch_count >= self.config.min_samples
        ):
            return _build_record(
                risk_state="WATCH",
                confidence=avg_confidence,
                reason=(
                    f"Watch-level risk sustained for {watch_minutes} minutes "
                    f"({watch_count}/{n} samples)"
                ),
                sample_count=n,
                window_minutes=self.config.window_minutes,
                avg_water_ratio=avg_water,
                timestamp=now,
            )

        return _build_record(
            risk_state="NORMAL",
            confidence=avg_confidence,
            reason=f"No sustained risk detected ({n} samples in window)",
            sample_count=n,
            window_minutes=self.config.window_minutes,
            avg_water_ratio=avg_water,
            timestamp=now,
        )

    def _sustained_minutes(self, min_state: str) -> int:
        """Count consecutive minutes the risk has been at or above min_state."""

        min_level = _RISK_LEVELS.get(min_state, 0)
        if not self._samples:
            return 0

        sustained_from: datetime | None = None
        for sample in reversed(self._samples):
            level = _RISK_LEVELS.get(sample.risk_state, -1)
            if level >= min_level:
                sustained_from = sample.timestamp
            else:
                break

        if sustained_from is None:
            return 0

        latest = self._samples[-1].timestamp
        delta = latest - sustained_from
        return int(delta.total_seconds() / 60)


def _build_record(
    *,
    risk_state: str,
    confidence: float,
    reason: str,
    sample_count: int,
    window_minutes: int,
    avg_water_ratio: float,
    timestamp: datetime,
) -> dict[str, object]:
    return {
        "contract_version": "v1",
        "record_id": f"temporal-risk-{uuid4()}",
        "record_type": "temporal_risk_output",
        "timestamp": timestamp.isoformat(),
        "temporal_risk_state": risk_state,
        "confidence": round(min(max(confidence, 0.0), 1.0), 4),
        "reason": reason,
        "sample_count": sample_count,
        "window_minutes": window_minutes,
        "avg_water_ratio": round(avg_water_ratio, 6),
    }
