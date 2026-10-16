from collections.abc import Callable
from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy.orm import Session

from supplymesh.persistence.orm_models import AgentMessageLogRecord, AuditEventRecord


class AuditRepository:
    """Append-only message and material business-event audit writes."""

    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def log_message(
        self,
        *,
        workflow_id: UUID,
        message_id: UUID,
        sender: str,
        recipient: str,
        message_type: str,
        payload_hash: str,
        status: str,
        sent_at: datetime,
        received_at: datetime | None = None,
    ) -> UUID:
        record_id = uuid4()
        with self.session_factory() as session, session.begin():
            session.add(
                AgentMessageLogRecord(
                    id=record_id,
                    workflow_id=workflow_id,
                    message_id=message_id,
                    sender=sender,
                    recipient=recipient,
                    message_type=message_type,
                    payload_hash=payload_hash,
                    status=status,
                    sent_at=sent_at,
                    received_at=received_at,
                )
            )
        return record_id

    def append_event(
        self,
        *,
        workflow_id: UUID,
        actor_type: str,
        actor_id: str,
        action: str,
        entity_type: str,
        entity_id: str,
        before: dict[str, Any] | None,
        after: dict[str, Any] | None,
    ) -> UUID:
        event_id = uuid4()
        with self.session_factory() as session, session.begin():
            session.add(
                AuditEventRecord(
                    id=event_id,
                    workflow_id=workflow_id,
                    actor_type=actor_type,
                    actor_id=actor_id,
                    action=action,
                    entity_type=entity_type,
                    entity_id=entity_id,
                    before_json=before,
                    after_json=after,
                )
            )
        return event_id
