"""Choose time-spaced evidence and describe gaps in local video coverage."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class SamplingSettings:
    """Prototype settings; these are not field-validated detection thresholds."""

    interval_seconds: float = 5.0
    max_samples: int = 120
    minimum_brightness: float = 5.0

    def __post_init__(self) -> None:
        if not math.isfinite(self.interval_seconds) or self.interval_seconds <= 0:
            raise ValueError("Sample interval must be finite and greater than zero")
        if isinstance(self.max_samples, bool) or not isinstance(self.max_samples, int):
            raise ValueError("Maximum samples must be an integer")
        if self.max_samples < 2:
            raise ValueError("Maximum samples must be at least two")
        if not math.isfinite(self.minimum_brightness) or not 0 <= self.minimum_brightness <= 255:
            raise ValueError("Minimum brightness must be between 0 and 255")


def frame_second(record: Mapping[str, object]) -> float:
    """Read a known numeric frame time."""

    value = record["video_time_seconds"]
    if not isinstance(value, int | float) or not math.isfinite(value):
        raise ValueError("Frame time must be finite")
    return float(value)


def window_evidence(
    metadata: Sequence[Mapping[str, object]],
    window: tuple[float, float],
    settings: SamplingSettings,
) -> dict[str, object]:
    """Describe usable coverage, including missing footage at either boundary."""

    start, end = window
    inside = [r for r in metadata if start <= frame_second(r) < end]
    usable = [r for r in inside if r.get("input_quality_state") == "USABLE"]
    times = [frame_second(r) for r in usable]
    reasons: dict[str, int] = {}
    for record in inside:
        if record.get("input_quality_state") != "USABLE":
            codes = record.get("reason_codes", [])
            for reason in codes if isinstance(codes, list) else []:
                key = str(reason)
                reasons[key] = reasons.get(key, 0) + 1
    # One frame period is expected between the final frame and the exclusive end.
    period = 0.0
    if metadata:
        fps = metadata[0].get("frame_rate")
        if isinstance(fps, int | float) and fps > 0:
            period = 1 / fps
    gaps = [b - a for a, b in zip(times, times[1:], strict=False)]
    if times:
        gaps += [times[0] - start, max(0.0, end - times[-1] - period)]
    largest_gap = max(gaps, default=end - start)
    usable_fraction = min(1.0, len(times) * period / (end - start))
    enough = (
        len(times) >= 2
        and largest_gap <= 2 * settings.interval_seconds + period
        and usable_fraction >= 0.8
    )
    reason = ""
    if len(times) < 2:
        reason = "Fewer than two usable frames in this period."
    elif largest_gap > 2 * settings.interval_seconds + period:
        reason = "A large gap in usable footage leaves this period poorly covered."
    elif not enough:
        reason = "Less than 80% of this period has usable footage."
    return {
        "usable_coverage_fraction": round(usable_fraction, 6),
        "time_window_seconds": [start, end],
        "usable_frame_count": len(usable),
        "unusable_frame_count": len(inside) - len(usable),
        "unusable_reasons": reasons,
        "first_usable_second": times[0] if times else None,
        "last_usable_second": times[-1] if times else None,
        "largest_gap_seconds": round(largest_gap, 6),
        "coverage_sufficient": enough,
        "coverage_reason": reason,
        "sample_interval_seconds": settings.interval_seconds,
        "max_samples": settings.max_samples,
        "minimum_brightness": settings.minimum_brightness,
    }


def sample_indices(
    metadata: Sequence[Mapping[str, object]],
    window: tuple[float, float],
    settings: SamplingSettings,
) -> list[int]:
    """Keep first/last usable frames and capped, evenly spaced time targets."""

    start, end = window
    candidates = [
        i
        for i, record in enumerate(metadata)
        if start <= frame_second(record) < end and record.get("input_quality_state") == "USABLE"
    ]
    if len(candidates) < 2:
        return candidates
    first, last = candidates[0], candidates[-1]
    first_time, last_time = frame_second(metadata[first]), frame_second(metadata[last])
    intervals = min(
        settings.max_samples - 1,
        max(1, math.ceil((last_time - first_time) / settings.interval_seconds)),
    )
    spacing = max(settings.interval_seconds, (last_time - first_time) / intervals)
    selected = [first]
    target = first_time + spacing
    for index in candidates[1:-1]:
        second = frame_second(metadata[index])
        if second >= target and len(selected) < settings.max_samples - 1:
            selected.append(index)
            target = first_time + (math.floor((second - first_time) / spacing) + 1) * spacing
    selected.append(last)
    return selected
