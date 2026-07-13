"""Bounded, session-local scale learning for repeated template searches."""

from __future__ import annotations

import math
import re
import threading
from dataclasses import dataclass, field
from typing import Iterable


SCALE_MEMORY_TIERS = ("conservative", "balanced", "aggressive")
MAX_MANUAL_SCALES = 12
MIN_HISTORY_LIMIT = 8
MAX_HISTORY_LIMIT = 512
MAX_LEARNED_PREFERRED = 12


def normalize_scale(value) -> float:
    scale = float(value)
    if not math.isfinite(scale) or not 0.01 <= scale <= 5.0:
        raise ValueError("缩放倍率必须是 0.01 到 5.0 之间的有限数字")
    return float(round(scale, 8))


def format_scale(value) -> str:
    text = f"{float(value):.4f}".rstrip("0").rstrip(".")
    return text or "0"


def parse_manual_scales(value, *, maximum=MAX_MANUAL_SCALES) -> tuple[float, ...]:
    if isinstance(value, (list, tuple, set)):
        parts = list(value)
    else:
        text = str(value or "").strip()
        if not text:
            return ()
        parts = [part for part in re.split(r"[\s,，;；]+", text) if part]
    result = []
    for part in parts:
        scale = normalize_scale(part)
        if scale not in result:
            result.append(scale)
        if len(result) > int(maximum):
            raise ValueError(f"手动优先倍率最多允许 {maximum} 个")
    return tuple(result)


def format_manual_scales(scales: Iterable[float]) -> str:
    return ", ".join(format_scale(scale) for scale in scales)


@dataclass(frozen=True)
class ScaleMemoryPolicy:
    enabled: bool = True
    tier: str = "balanced"
    manual_scales: tuple[float, ...] = ()
    custom_enabled: bool = False
    preferred_limit: int = 3
    history_limit: int = 64

    def normalized(self) -> "ScaleMemoryPolicy":
        tier = self.tier if self.tier in SCALE_MEMORY_TIERS else "balanced"
        manual = parse_manual_scales(self.manual_scales)
        preferred_limit = max(
            1, min(MAX_LEARNED_PREFERRED, int(self.preferred_limit))
        )
        history_limit = max(
            MIN_HISTORY_LIMIT,
            min(MAX_HISTORY_LIMIT, int(self.history_limit)),
        )
        return ScaleMemoryPolicy(
            enabled=bool(self.enabled),
            tier=tier,
            manual_scales=manual,
            custom_enabled=bool(self.custom_enabled),
            preferred_limit=preferred_limit,
            history_limit=history_limit,
        )


@dataclass
class ScaleMemorySummary:
    label: str
    preferred_scales: tuple[float, ...]
    manual_scales: tuple[float, ...]
    learned_scales: tuple[float, ...]
    observed_count: int
    unique_count: int
    history_limit: int

    @property
    def signature(self):
        return (
            self.preferred_scales,
            self.history_limit,
        )

    def status_text(self) -> str:
        preferred = format_manual_scales(self.preferred_scales) or "暂无"
        return (
            f"{self.label}：已记录 {self.observed_count} 次、"
            f"{self.unique_count} 个倍率；当前优先 {len(self.preferred_scales)} 个 "
            f"[{preferred}]；历史上限 {self.history_limit}"
        )


@dataclass
class _ScaleMemoryEntry:
    label: str
    valid_scales: tuple[float, ...]
    generation: tuple | None = None
    history: list[tuple[float, float, int]] = field(default_factory=list)
    updated_sequence: int = 0
    last_logged_signature: tuple | None = None


class ScaleMemoryStore:
    """Thread-safe learning cache that intentionally lives only for this process."""

    def __init__(self, max_entries=256):
        self.max_entries = max(1, int(max_entries))
        self._entries: dict[tuple, _ScaleMemoryEntry] = {}
        self._sequence = 0
        self._lock = threading.RLock()

    @staticmethod
    def _snap_manual_scales(manual_scales, valid_scales):
        valid = tuple(sorted({normalize_scale(scale) for scale in valid_scales}))
        if not valid:
            return ()
        gaps = [b - a for a, b in zip(valid, valid[1:], strict=False) if b > a]
        tolerance = max(1e-7, (min(gaps) * 0.11) if gaps else 1e-7)
        snapped = []
        for requested in manual_scales:
            nearest = min(valid, key=lambda scale: abs(scale - requested))
            if abs(nearest - requested) <= tolerance and nearest not in snapped:
                snapped.append(nearest)
        return tuple(snapped)

    @staticmethod
    def _effective_history_limit(entry, policy):
        if policy.custom_enabled:
            return policy.history_limit
        scale_count = max(1, len(entry.valid_scales))
        unique_count = len({item[0] for item in entry.history})
        maturity = min(len(entry.history) // 4, scale_count * 2)
        base = 10 + scale_count * 2 + unique_count * 4 + maturity
        factor = {
            "conservative": 0.68,
            "balanced": 1.0,
            "aggressive": 1.48,
        }[policy.tier]
        return max(
            MIN_HISTORY_LIMIT,
            min(256, int(round(base * factor))),
        )

    @staticmethod
    def _ranked_scales(entry):
        scores: dict[float, float] = {}
        last_seen: dict[float, int] = {}
        for age, (scale, score, sequence) in enumerate(reversed(entry.history)):
            recency = math.pow(0.985, age)
            quality = 0.75 + 0.25 * max(0.0, min(1.0, float(score)))
            scores[scale] = scores.get(scale, 0.0) + recency * quality
            last_seen[scale] = max(last_seen.get(scale, 0), sequence)
        return sorted(
            scores,
            key=lambda scale: (-scores[scale], -last_seen[scale], scale),
        ), scores

    @staticmethod
    def _auto_preferred_limit(entry, policy, ranked, weights):
        if not ranked:
            return 0
        if policy.custom_enabled:
            return min(policy.preferred_limit, len(ranked))
        coverage = {
            "conservative": 0.68,
            "balanced": 0.84,
            "aggressive": 0.95,
        }[policy.tier]
        tendency = {
            "conservative": 0.7,
            "balanced": 1.0,
            "aggressive": 1.45,
        }[policy.tier]
        dynamic_cap = max(
            1,
            min(
                MAX_LEARNED_PREFERRED,
                int(math.ceil(math.sqrt(max(1, len(entry.valid_scales))) * tendency)),
            ),
        )
        total = sum(weights[scale] for scale in ranked)
        running = 0.0
        selected = 0
        for scale in ranked:
            running += weights[scale]
            selected += 1
            if total <= 0.0 or running / total >= coverage:
                break
        return min(max(1, selected), dynamic_cap, len(ranked))

    def _entry(self, key, label, valid_scales, generation=None):
        valid = tuple(sorted({normalize_scale(scale) for scale in valid_scales}))
        entry = self._entries.get(key)
        if entry is None:
            entry = _ScaleMemoryEntry(
                str(label or "图片"),
                valid,
                generation=generation,
            )
            self._entries[key] = entry
        else:
            entry.label = str(label or entry.label)
            if (
                generation is not None
                and entry.generation is not None
                and generation != entry.generation
            ):
                # The path still identifies the same logical template, but the
                # file contents changed. Old scale observations are no longer
                # trustworthy for the replacement image.
                entry.history.clear()
                entry.last_logged_signature = None
            if generation is not None:
                entry.generation = generation
            if valid and entry.valid_scales != valid:
                entry.valid_scales = valid
                allowed = set(valid)
                entry.history = [item for item in entry.history if item[0] in allowed]
        return entry

    def _summary(self, entry, policy):
        policy = policy.normalized()
        history_limit = self._effective_history_limit(entry, policy)
        if len(entry.history) > history_limit:
            del entry.history[:-history_limit]
        ranked, weights = self._ranked_scales(entry)
        learned_limit = self._auto_preferred_limit(
            entry, policy, ranked, weights
        )
        learned = tuple(ranked[:learned_limit])
        manual = self._snap_manual_scales(
            policy.manual_scales, entry.valid_scales
        )
        preferred = list(manual)
        for scale in learned:
            if scale not in preferred:
                preferred.append(scale)
        return ScaleMemorySummary(
            label=entry.label,
            preferred_scales=tuple(preferred),
            manual_scales=manual,
            learned_scales=learned,
            observed_count=len(entry.history),
            unique_count=len({item[0] for item in entry.history}),
            history_limit=history_limit,
        )

    def preferred_scales(
        self,
        key,
        label,
        valid_scales,
        policy,
        *,
        generation=None,
    ):
        policy = policy.normalized()
        if not policy.enabled:
            return (), None
        with self._lock:
            entry = self._entry(
                key,
                label,
                valid_scales,
                generation=generation,
            )
            summary = self._summary(entry, policy)
            return summary.preferred_scales, summary

    def record(
        self,
        key,
        label,
        valid_scales,
        scale,
        score,
        policy,
        *,
        generation=None,
    ):
        policy = policy.normalized()
        if not policy.enabled:
            return None, False
        scale = normalize_scale(scale)
        with self._lock:
            entry = self._entry(
                key,
                label,
                valid_scales,
                generation=generation,
            )
            if scale not in entry.valid_scales:
                return self._summary(entry, policy), False
            self._sequence += 1
            entry.updated_sequence = self._sequence
            entry.history.append((scale, float(score), self._sequence))
            summary = self._summary(entry, policy)
            changed = summary.signature != entry.last_logged_signature
            if changed:
                entry.last_logged_signature = summary.signature
            self._evict_old_entries()
            return summary, changed

    def _evict_old_entries(self):
        while len(self._entries) > self.max_entries:
            oldest_key = min(
                self._entries,
                key=lambda key: self._entries[key].updated_sequence,
            )
            del self._entries[oldest_key]

    def summaries(self, policy, maximum=8):
        policy = policy.normalized()
        with self._lock:
            entries = sorted(
                self._entries.values(),
                key=lambda entry: entry.updated_sequence,
                reverse=True,
            )
            return [
                self._summary(entry, policy)
                for entry in entries[: max(1, int(maximum))]
            ]

    def clear(self):
        with self._lock:
            self._entries.clear()
            self._sequence = 0
