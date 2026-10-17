from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from supplymesh.domain.procurement import ApprovalRecord
from supplymesh.persistence.orm_models import ApprovalDecisionRecord, WorkflowRun
from supplymesh.services.approval_service import approval_payload_hash


@dataclass(frozen=True)
class ConnectivitySession:
    workflow_id: UUID
    conversation_id: str
    correlation_id: UUID
    request_message_id: UUID
    chat_message_id: UUID
    status: str
    currency: str = "USD"


@dataclass(frozen=True)
class WorkflowSnapshot:
    workflow_id: UUID
    conversation_id: str
    status: str
    checkpoint_version: int
    state: dict[str, Any]


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

    def find_active_by_conversation(self, conversation_id: str) -> WorkflowSnapshot | None:
        terminal = ("COMPLETED", "CANCELLED", "FAILED_REQUIRES_OPERATOR")
        with self.session_factory() as session:
            record = session.scalar(
                select(WorkflowRun)
                .where(
                    WorkflowRun.conversation_id == conversation_id,
                    WorkflowRun.status.not_in(terminal),
                )
                .order_by(WorkflowRun.started_at.desc())
                .limit(1)
            )
            return self._snapshot(record) if record is not None else None

    def snapshot(self, workflow_id: UUID) -> WorkflowSnapshot | None:
        with self.session_factory() as session:
            record = session.get(WorkflowRun, workflow_id)
            return self._snapshot(record) if record is not None else None

    def update(
        self,
        workflow_id: UUID,
        *,
        status: str | None = None,
        updates: dict[str, Any] | None = None,
        inbound_message_id: UUID | None = None,
    ) -> bool:
        """Atomically deduplicate an inbound message and persist its resulting state."""
        with self.session_factory() as session, session.begin():
            record = session.get(WorkflowRun, workflow_id, with_for_update=True)
            if record is None:
                raise ValueError("workflow was not found")
            state = dict(record.state)
            processed = list(state.get("processed_message_ids", []))
            if inbound_message_id is not None and str(inbound_message_id) in processed:
                return False
            if inbound_message_id is not None:
                processed.append(str(inbound_message_id))
                state["processed_message_ids"] = processed
            if updates:
                state.update(updates)
            record.state = state
            if status is not None:
                record.status = status
                if status in {"COMPLETED", "CANCELLED", "FAILED_REQUIRES_OPERATOR"}:
                    record.completed_at = datetime.now(UTC)
            record.checkpoint_version += 1
            return True

    def record_outbound(
        self,
        workflow_id: UUID,
        *,
        message_id: UUID,
        destination: str,
        message_type: str,
        status: str,
    ) -> None:
        with self.session_factory() as session, session.begin():
            record = session.get(WorkflowRun, workflow_id, with_for_update=True)
            if record is None:
                raise ValueError("workflow was not found")
            state = dict(record.state)
            outbound = dict(state.get("outbound_messages", {}))
            current = outbound.get(str(message_id))
            if current is not None and (
                current["destination"] != destination or current["message_type"] != message_type
            ):
                raise ValueError("message ID is already bound to a different outbound message")
            outbound[str(message_id)] = {
                "destination": destination,
                "message_type": message_type,
                "status": status,
            }
            state["outbound_messages"] = outbound
            record.state = state
            record.checkpoint_version += 1

    def save_approval(
        self,
        *,
        workflow_id: UUID,
        decision_type: Literal[
            "SELECT_PLAN", "SEND_PURCHASE_ORDER", "ACCEPT_EXCEPTION", "SEND_COUNTERPROPOSAL"
        ],
        target_type: str,
        target_id: str,
        target_version: int,
        actor: str,
        payload: BaseModel | dict[str, Any],
        reason: str | None = None,
    ) -> ApprovalRecord:
        payload_hash = approval_payload_hash(payload)
        approval_id = uuid5(
            workflow_id,
            f"{decision_type}:{target_id}:{target_version}:{actor}:{payload_hash}",
        )
        approval = ApprovalRecord(
            approval_id=approval_id,
            workflow_id=workflow_id,
            decision_type=decision_type,
            target_type=target_type,
            target_id=target_id,
            target_version=target_version,
            decision="APPROVED",
            actor=actor,
            reason=reason,
            payload_hash=payload_hash,
            decided_at=datetime.now(UTC),
        )
        with self.session_factory() as session, session.begin():
            existing = session.get(ApprovalDecisionRecord, approval_id)
            if existing is None:
                session.add(
                    ApprovalDecisionRecord(
                        id=approval.approval_id,
                        workflow_id=approval.workflow_id,
                        decision_type=approval.decision_type,
                        target_type=approval.target_type,
                        target_id=approval.target_id,
                        target_version=approval.target_version,
                        decision=approval.decision,
                        actor=approval.actor,
                        reason=approval.reason,
                        payload_hash=approval.payload_hash,
                        decided_at=approval.decided_at,
                    )
                )
        return approval

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
            "currency": session_state.currency,
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
            currency=state.get("currency", "USD"),
        )

    @staticmethod
    def _snapshot(record: WorkflowRun) -> WorkflowSnapshot:
        return WorkflowSnapshot(
            workflow_id=record.id,
            conversation_id=record.conversation_id,
            status=record.status,
            checkpoint_version=record.checkpoint_version,
            state=dict(record.state),
        )
