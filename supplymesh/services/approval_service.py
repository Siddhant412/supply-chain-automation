import hashlib
import json
from typing import Any

from pydantic import BaseModel

from supplymesh.domain.procurement import ApprovalRecord


def approval_payload_hash(payload: BaseModel | dict[str, Any]) -> str:
    value = payload.model_dump(mode="json") if isinstance(payload, BaseModel) else payload
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def verify_approval(
    approval: ApprovalRecord,
    *,
    expected_decision_type: str,
    target_id: str,
    target_version: int,
    current_payload: BaseModel | dict[str, Any],
) -> None:
    if approval.decision != "APPROVED":
        raise ValueError("approval decision is not APPROVED")
    if approval.decision_type != expected_decision_type:
        raise ValueError("approval decision type does not authorize this action")
    if approval.target_id != target_id or approval.target_version != target_version:
        raise ValueError("approval target is stale or does not match")
    current_hash = approval_payload_hash(current_payload)
    if approval.payload_hash != current_hash:
        raise ValueError("approved payload changed after approval")
