from collections.abc import Callable
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from supplymesh.persistence.orm_models import WorkflowRun


@dataclass(frozen=True)
class ConnectivitySession:
    workflow_id: UUID
    conversation_id: str
    correlation_id: UUID
    request_message_id: UUID
    chat_message_id: UUID
    status: str


class WorkflowRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def start_inventory(self, session_state: ConnectivitySession) -> None:
        with self.session_factory() as session, session.begin():
            session.add(
                WorkflowRun(
                    id=session_state.workflow_id,
                    conversation_id=session_state.conversation_id,
                    status=session_state.status,
                    checkpoint_version=1,
                    state=self._state(session_state),
                )
            )

    def get(self, workflow_id: UUID) -> ConnectivitySession | None:
        with self.session_factory() as session:
            record = session.get(WorkflowRun, workflow_id)
            if record is None:
                return None
            return self._session(record)

    def find_by_chat_message(self, chat_message_id: UUID) -> ConnectivitySession | None:
        with self.session_factory() as session:
            record = session.scalar(
                select(WorkflowRun).where(
                    WorkflowRun.state["chat_message_id"].as_string() == str(chat_message_id)
                )
            )
            return self._session(record) if record is not None else None

    def record_inventory_result(self, workflow_id: UUID, result: dict[str, Any]) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(WorkflowRun, workflow_id)
            if record is None:
                raise ValueError("inventory result references an unknown workflow")
            state = dict(record.state)
            state["inventory_result"] = result
            record.state = state
            record.status = "SOURCING" if result["has_shortages"] else "COMPLETED"
            record.checkpoint_version += 1

    def record_failure(self, workflow_id: UUID, error: dict[str, Any]) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(WorkflowRun, workflow_id)
            if record is None:
                return
            state = dict(record.state)
            state["error"] = error
            record.state = state
            record.status = "FAILED_REQUIRES_OPERATOR"
            record.checkpoint_version += 1

    @staticmethod
    def _state(session_state: ConnectivitySession) -> dict[str, str]:
        return {
            "correlation_id": str(session_state.correlation_id),
            "request_message_id": str(session_state.request_message_id),
            "chat_message_id": str(session_state.chat_message_id),
        }

    @staticmethod
    def _session(record: WorkflowRun) -> ConnectivitySession:
        state = record.state
        return ConnectivitySession(
            workflow_id=record.id,
            conversation_id=record.conversation_id,
            correlation_id=UUID(state["correlation_id"]),
            request_message_id=UUID(state["request_message_id"]),
            chat_message_id=UUID(state["chat_message_id"]),
            status=record.status,
        )
