"""Append-only audit-event helper; callers must pass pre-redacted payloads."""

from __future__ import annotations

from uuid import uuid4

from sqlalchemy.orm import Session

from app.models import AuditEvent
from app.security import redact_mapping


def record_audit(
    db: Session,
    *,
    event_type: str,
    actor: str,
    payload: dict[str, object],
    environment: str | None = None,
    correlation_id: str | None = None,
) -> AuditEvent:
    event = AuditEvent(
        environment=environment,
        event_type=event_type,
        actor=actor,
        correlation_id=correlation_id or str(uuid4()),
        payload_json=redact_mapping(payload),
    )
    db.add(event)
    return event
