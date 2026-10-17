from datetime import UTC, date, datetime
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from supplymesh.domain.procurement import ApprovalRecord, PurchaseOrder, PurchaseOrderLine
from supplymesh.persistence.orm_models import (
    ApprovalDecisionRecord,
    PurchaseOrderLineRecord,
    PurchaseOrderRecord,
    SupplierTransactionRecord,
)
from supplymesh.persistence.procurement_repository import ProcurementRepository
from supplymesh.services.approval_service import approval_payload_hash


def test_procurement_repository_persists_approval_po_and_supplier_transaction() -> None:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for table in (
        ApprovalDecisionRecord.__table__,
        PurchaseOrderRecord.__table__,
        PurchaseOrderLineRecord.__table__,
        SupplierTransactionRecord.__table__,
    ):
        table.create(engine)

    def sessions() -> Session:
        return Session(engine)

    po = PurchaseOrder(
        po_id=uuid4(),
        po_number="PO-REPO-1",
        workflow_id=uuid4(),
        supplier_id="supplier-alpha",
        version=1,
        currency="USD",
        lines=(
            PurchaseOrderLine(
                line_number=1,
                component_sku="ENGINE-001",
                quantity=Decimal("75"),
                unit_price=Decimal("10"),
                requested_date=date(2026, 12, 1),
            ),
        ),
        total=Decimal("750"),
    )
    approval = ApprovalRecord(
        approval_id=uuid4(),
        workflow_id=po.workflow_id,
        decision_type="SEND_PURCHASE_ORDER",
        target_type="purchase_order",
        target_id=str(po.po_id),
        target_version=po.version,
        decision="APPROVED",
        actor="manager",
        payload_hash=approval_payload_hash(po),
        decided_at=datetime(2026, 10, 16, tzinfo=UTC),
    )
    with sessions() as session, session.begin():
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
                payload_hash=approval.payload_hash,
                decided_at=approval.decided_at,
            )
        )

    repository = ProcurementRepository(sessions)
    loaded_approval = repository.get_approval(str(approval.approval_id))
    assert loaded_approval.approval_id == approval.approval_id
    assert loaded_approval.payload_hash == approval.payload_hash
    assert loaded_approval.target_id == approval.target_id
    repository.save_approved_purchase_order(po)
    repository.save_approved_purchase_order(po)
    assert repository.get_purchase_order(str(po.po_id)) == po
    repository.record_submission(
        po, external_transaction_id="TX-REPO-1", poll_url="/purchase-orders/TX-REPO-1"
    )
    repository.record_submission(
        po, external_transaction_id="TX-REPO-1", poll_url="/purchase-orders/TX-REPO-1"
    )

    with sessions() as session:
        row = session.get(PurchaseOrderRecord, po.po_id)
        transactions = tuple(session.scalars(select(SupplierTransactionRecord)))
        assert row is not None
        assert row.status == "SUBMITTED"
        assert len(transactions) == 1

    altered = po.model_copy(update={"total": Decimal("999")})
    with pytest.raises(ValueError, match="different content"):
        repository.save_approved_purchase_order(altered)
    engine.dispose()
