from pathlib import Path

from sqlalchemy import select

from app.db import create_database_engine, create_session_factory, initialize_database
from app.models import AuditEvent, AutomationState, User
from app.worker import _disarm_paper_automation_on_start


def test_worker_restart_disarms_paper_automation_and_audits(tmp_path: Path) -> None:
    engine = create_database_engine(f"sqlite:///{tmp_path / 'worker.db'}")
    initialize_database(engine)
    session_factory = create_session_factory(engine)
    with session_factory() as db:
        owner = User(username="owner")
        db.add(owner)
        db.flush()
        automation = AutomationState(
            user_id=owner.id,
            environment="paper",
            enabled=True,
            reduce_only=False,
        )
        db.add(automation)
        db.commit()
        automation_id = automation.id

        _disarm_paper_automation_on_start(db)

        refreshed = db.get(AutomationState, automation_id)
        assert refreshed is not None
        assert refreshed.enabled is False
        assert refreshed.enabled_at is None
        audit = db.scalar(
            select(AuditEvent).where(
                AuditEvent.event_type == "PAPER_WORKER_RESTARTED_AUTOMATION_DISABLED"
            )
        )
        assert audit is not None
        assert audit.payload_json["explicit_reenable_required"] is True
    engine.dispose()
