"""Normalized news abstraction. Providers may inform or block setups but cannot submit orders."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol


@dataclass(frozen=True)
class NormalizedNewsEvent:
    event_id: str
    source: str
    published_at: datetime
    received_at: datetime
    affected_instruments: list[str]
    event_type: str
    sentiment: str
    impact: str
    freshness_seconds: int
    duplicate_group: str | None
    confidence: float


class NewsProvider(Protocol):
    def fetch(self, instruments: list[str], max_age_seconds: int) -> list[NormalizedNewsEvent]: ...


class AlpacaNewsProvider:
    """Normalize official Alpaca News API responses without fabricating sentiment or impact."""

    def __init__(self, adapter: Any) -> None:
        self._adapter = adapter

    def fetch(
        self, instruments: list[str], max_age_seconds: int = 1800
    ) -> list[NormalizedNewsEvent]:
        now = datetime.now(UTC)
        rows = self._adapter.get_news(instruments, now - timedelta(seconds=max_age_seconds))
        events: list[NormalizedNewsEvent] = []
        for row in rows:
            published = _parse_timestamp(row.get("created_at") or row.get("updated_at"))
            # Unknown timestamps are treated as newly received, so they trigger a conservative blackout.
            if published is None:
                published = now
            headline = str(row.get("headline", ""))
            symbols = row.get("symbols", [])
            if not isinstance(symbols, list):
                symbols = []
            duplicate_group = (
                hashlib.sha256(" ".join(headline.casefold().split()).encode()).hexdigest()
                if headline
                else None
            )
            events.append(
                NormalizedNewsEvent(
                    event_id=str(row.get("id") or duplicate_group or "unknown"),
                    source="alpaca_news",
                    published_at=published,
                    received_at=now,
                    affected_instruments=[str(symbol).upper() for symbol in symbols],
                    event_type="company",
                    sentiment="unknown",
                    impact="unknown",
                    freshness_seconds=max(0, int((now - published).total_seconds())),
                    duplicate_group=duplicate_group,
                    confidence=0.0,
                )
            )
        return deduplicate(events)


def _parse_timestamp(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.replace(tzinfo=UTC) if parsed.tzinfo is None else parsed.astimezone(UTC)


def is_fresh(event: NormalizedNewsEvent, max_age_seconds: int, now: datetime | None = None) -> bool:
    reference = now or datetime.now(UTC)
    age = (reference - event.published_at).total_seconds()
    return 0 <= age <= max_age_seconds and event.freshness_seconds <= max_age_seconds


def deduplicate(events: list[NormalizedNewsEvent]) -> list[NormalizedNewsEvent]:
    seen: set[str] = set()
    result: list[NormalizedNewsEvent] = []
    for event in sorted(events, key=lambda item: item.received_at, reverse=True):
        key = event.duplicate_group or event.event_id
        if key not in seen:
            seen.add(key)
            result.append(event)
    return result
