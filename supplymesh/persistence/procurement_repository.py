from collections.abc import Callable
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from supplymesh.domain.procurement import ApprovalRecord, PurchaseOrder, PurchaseOrderLine
from supplymesh.persistence.orm_models import (
    ApprovalDecisionRecord,
    PurchaseOrderLineRecord,
    PurchaseOrderRecord,
    SupplierTransactionRecord,
)
from supplymesh.services.procurement_service import purchase_order_idempotency_key


class ProcurementRepository:
    def __init__(self, session_factory: Callable[[], Session]) -> None:
        self.session_factory = session_factory

    def get_approval(self, approval_id: str) -> ApprovalRecord:
        with self.session_factory() as session:
            row = session.get(ApprovalDecisionRecord, UUID(approval_id))
            if row is None:
                raise ValueError("approval record was not found")
            return ApprovalRecord(
                approval_id=row.id,
                workflow_id=row.workflow_id,
                decision_type=row.decision_type,
                target_type=row.target_type,
                target_id=row.target_id,
                target_version=row.target_version,
                decision=row.decision,
                actor=row.actor,
                reason=row.reason,
                payload_hash=row.payload_hash,
                decided_at=row.decided_at,
            )

    def save_approved_purchase_order(self, po: PurchaseOrder) -> None:
        key = purchase_order_idempotency_key(po)
        with self.session_factory() as session, session.begin():
            existing = session.get(PurchaseOrderRecord, po.po_id)
            if existing is not None:
                if self._to_domain(session, existing) != po:
                    raise ValueError("purchase order ID already exists with different content")
                return
            session.add(
                PurchaseOrderRecord(
                    id=po.po_id,
                    po_number=po.po_number,
                    workflow_id=po.workflow_id,
                    supplier_id=po.supplier_id,
                    version=po.version,
                    currency=po.currency,
                    status="APPROVED",
                    total=po.total,
                    idempotency_key=key,
                )
            )
            session.add_all(
                PurchaseOrderLineRecord(
                    po_id=po.po_id,
                    line_number=line.line_number,
                    component_sku=line.component_sku,
                    quantity=line.quantity,
                    unit_price=line.unit_price,
                    requested_date=line.requested_date,
                    unit=line.unit,
                )
                for line in po.lines
            )

    def record_submission(
        self,
        po: PurchaseOrder,
        *,
        external_transaction_id: str,
        poll_url: str,
    ) -> None:
        key = purchase_order_idempotency_key(po)
        with self.session_factory() as session, session.begin():
            record = session.get(PurchaseOrderRecord, po.po_id)
            if record is None:
                raise ValueError("purchase order must be persisted before supplier submission")
            record.status = "SUBMITTED"
            transaction = session.scalar(
                select(SupplierTransactionRecord).where(
                    SupplierTransactionRecord.supplier_id == po.supplier_id,
                    SupplierTransactionRecord.idempotency_key == key,
                )
            )
            if transaction is None:
                session.add(
                    SupplierTransactionRecord(
                        supplier_id=po.supplier_id,
                        transaction_type="PURCHASE_ORDER",
                        idempotency_key=key,
                        external_transaction_id=external_transaction_id,
                        status="PROCESSING",
                        poll_url=poll_url,
                        attempts=1,
                    )
                )
            elif transaction.external_transaction_id != external_transaction_id:
                raise ValueError("idempotent PO submission returned a different transaction")

    def get_purchase_order(self, po_id: str) -> PurchaseOrder:
        with self.session_factory() as session:
            row = session.get(PurchaseOrderRecord, UUID(po_id))
            if row is None:
                raise ValueError("purchase order was not found")
            return self._to_domain(session, row)

    @staticmethod
    def _to_domain(session: Session, row: PurchaseOrderRecord) -> PurchaseOrder:
        lines = tuple(
            PurchaseOrderLine(
                line_number=line.line_number,
                component_sku=line.component_sku,
                quantity=line.quantity,
                unit_price=line.unit_price,
                requested_date=line.requested_date,
                unit=line.unit,
            )
            for line in session.scalars(
                select(PurchaseOrderLineRecord)
                .where(PurchaseOrderLineRecord.po_id == row.id)
                .order_by(PurchaseOrderLineRecord.line_number)
            )
        )
        return PurchaseOrder(
            po_id=row.id,
            po_number=row.po_number,
            workflow_id=row.workflow_id,
            supplier_id=row.supplier_id,
            version=row.version,
            currency=row.currency,
            lines=lines,
            total=row.total,
        )
