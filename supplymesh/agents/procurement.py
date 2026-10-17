import asyncio
from typing import Protocol

from pydantic import ValidationError
from uagents import Context
from uagents import Protocol as AgentProtocol

from supplymesh.agents.transport import (
    AcknowledgmentReceivedTransport,
    ChangeOrderSubmittedTransport,
    ChangeResponseReceivedTransport,
    CounterproposalExecutionTransport,
    PurchaseOrderExecutionTransport,
    PurchaseOrderSubmittedTransport,
    SpecialistFailureTransport,
)
from supplymesh.domain.procurement import (
    ApprovalRecord,
    ChangeTransactionStatus,
    PurchaseOrder,
    SupplierTransactionAccepted,
    SupplierTransactionStatus,
)
from supplymesh.protocols.procurement import (
    AcknowledgmentReceived,
    ChangeOrderSubmitted,
    ChangeResponseReceived,
    CounterproposalExecutionRequest,
    PurchaseOrderExecutionRequest,
    PurchaseOrderSubmitted,
)
from supplymesh.services.counterproposal_service import ChangeOrderGateway, execute_counterproposal
from supplymesh.services.procurement_service import (
    PurchaseOrderGateway,
    SideEffectJournal,
    execute_purchase_order,
)


class ProcurementGateway(PurchaseOrderGateway, ChangeOrderGateway, Protocol):
    async def get_purchase_order_status(
        self, supplier_id: str, transaction_id: str, *, correlation_id: str
    ) -> SupplierTransactionStatus: ...

    async def get_change_order_status(
        self, supplier_id: str, transaction_id: str, *, correlation_id: str
    ) -> ChangeTransactionStatus: ...


class ProcurementState(Protocol):
    def get_approval(self, approval_id: str) -> ApprovalRecord: ...

    def save_approved_purchase_order(self, po: PurchaseOrder) -> None: ...

    def record_submission(
        self,
        po: PurchaseOrder,
        *,
        external_transaction_id: str,
        poll_url: str,
    ) -> None: ...


class ProcurementAgentService:
    name = "procurement-execution"

    def __init__(
        self,
        gateway: ProcurementGateway,
        journal: SideEffectJournal,
        state: ProcurementState,
        *,
        poll_interval_seconds: float = 2,
        poll_timeout_seconds: float = 45,
    ) -> None:
        self.gateway = gateway
        self.journal = journal
        self.state = state
        self.poll_interval_seconds = poll_interval_seconds
        self.poll_timeout_seconds = poll_timeout_seconds

    async def execute_purchase_orders(
        self, request: PurchaseOrderExecutionRequest
    ) -> tuple[tuple[PurchaseOrderSubmitted, AcknowledgmentReceived], ...]:
        approval_ids = request.approval_ids or (request.approval_id,)
        if len(approval_ids) != len(request.purchase_orders):
            raise ValueError("each purchase order requires its own approval record")
        results: list[tuple[PurchaseOrderSubmitted, AcknowledgmentReceived]] = []
        for po, approval_id in zip(request.purchase_orders, approval_ids, strict=True):
            approval = self.state.get_approval(approval_id)
            self.state.save_approved_purchase_order(po)
            accepted = await execute_purchase_order(
                po,
                approval,
                self.gateway,
                self.journal,
                correlation_id=str(request.correlation_id),
            )
            self.state.record_submission(
                po,
                external_transaction_id=accepted.supplier_transaction_id,
                poll_url=accepted.poll_url,
            )
            submitted = PurchaseOrderSubmitted(
                correlation_id=request.correlation_id,
                workflow_id=request.workflow_id,
                sender_agent=self.name,
                reply_to=str(request.message_id),
                po_id=str(po.po_id),
                supplier_transaction_id=accepted.supplier_transaction_id,
                poll_url=accepted.poll_url,
            )
            status = await self._poll_purchase_order(po, accepted, request)
            results.append(
                (
                    submitted,
                    AcknowledgmentReceived(
                        correlation_id=request.correlation_id,
                        workflow_id=request.workflow_id,
                        sender_agent=self.name,
                        reply_to=str(submitted.message_id),
                        po_id=str(po.po_id),
                        po_version=po.version,
                        raw_x12=status.x12 or "",
                    ),
                )
            )
        return tuple(results)

    async def execute_counterproposal(
        self, request: CounterproposalExecutionRequest
    ) -> tuple[ChangeOrderSubmitted, ChangeResponseReceived]:
        approval = self.state.get_approval(request.approval_id)
        accepted = await execute_counterproposal(
            request.counterproposal,
            approval,
            self.gateway,
            self.journal,
            correlation_id=str(request.correlation_id),
        )
        submitted = ChangeOrderSubmitted(
            correlation_id=request.correlation_id,
            workflow_id=request.workflow_id,
            sender_agent=self.name,
            reply_to=str(request.message_id),
            po_id=str(request.counterproposal.po_id),
            change_version=request.counterproposal.change_version,
            supplier_transaction_id=accepted.supplier_transaction_id,
        )
        status = await self._poll_change_order(request, accepted)
        return submitted, ChangeResponseReceived(
            correlation_id=request.correlation_id,
            workflow_id=request.workflow_id,
            sender_agent=self.name,
            reply_to=str(submitted.message_id),
            po_id=str(request.counterproposal.po_id),
            po_version=request.counterproposal.change_version,
            raw_x12=status.x12 or "",
        )

    async def _poll_purchase_order(
        self,
        po: PurchaseOrder,
        accepted: SupplierTransactionAccepted,
        request: PurchaseOrderExecutionRequest,
    ) -> SupplierTransactionStatus:
        attempts = self._attempt_limit()
        for attempt in range(attempts):
            status = await self.gateway.get_purchase_order_status(
                po.supplier_id,
                accepted.supplier_transaction_id,
                correlation_id=str(request.correlation_id),
            )
            if status.status == "ACKNOWLEDGED" and status.document_type == "855" and status.x12:
                return status
            if attempt + 1 < attempts:
                await asyncio.sleep(status.retry_after_seconds or self.poll_interval_seconds)
        raise RuntimeError("supplier acknowledgment polling timed out")

    async def _poll_change_order(
        self,
        request: CounterproposalExecutionRequest,
        accepted: SupplierTransactionAccepted,
    ) -> ChangeTransactionStatus:
        attempts = self._attempt_limit()
        for attempt in range(attempts):
            status = await self.gateway.get_change_order_status(
                request.counterproposal.supplier_id,
                accepted.supplier_transaction_id,
                correlation_id=str(request.correlation_id),
            )
            if status.status == "ACKNOWLEDGED" and status.document_type == "865" and status.x12:
                return status
            if attempt + 1 < attempts:
                await asyncio.sleep(status.retry_after_seconds or self.poll_interval_seconds)
        raise RuntimeError("supplier change-response polling timed out")

    def _attempt_limit(self) -> int:
        return max(1, int(self.poll_timeout_seconds / self.poll_interval_seconds) + 1)


def build_procurement_protocol(service: ProcurementAgentService) -> AgentProtocol:
    protocol = AgentProtocol(name="SupplyMeshProcurementExecution", version="1.0.0")

    @protocol.on_message(
        PurchaseOrderExecutionTransport,
        replies={
            PurchaseOrderSubmittedTransport,
            AcknowledgmentReceivedTransport,
            SpecialistFailureTransport,
        },
    )
    async def handle_purchase_orders(
        ctx: Context, sender: str, msg: PurchaseOrderExecutionTransport
    ) -> None:
        try:
            request = msg.to_domain()
            for submitted, acknowledgment in await service.execute_purchase_orders(request):
                await ctx.send(sender, PurchaseOrderSubmittedTransport.from_domain(submitted))
                await ctx.send(sender, AcknowledgmentReceivedTransport.from_domain(acknowledgment))
        except (ValidationError, ValueError, RuntimeError):
            await _send_failure(ctx, sender, msg, service.name, "PURCHASE_ORDER_EXECUTION")
        except Exception:
            ctx.logger.exception("purchase-order transport execution failed")
            await _send_failure(ctx, sender, msg, service.name, "PURCHASE_ORDER_EXECUTION")

    @protocol.on_message(
        CounterproposalExecutionTransport,
        replies={
            ChangeOrderSubmittedTransport,
            ChangeResponseReceivedTransport,
            SpecialistFailureTransport,
        },
    )
    async def handle_counterproposal(
        ctx: Context, sender: str, msg: CounterproposalExecutionTransport
    ) -> None:
        try:
            request = msg.to_domain()
            submitted, response = await service.execute_counterproposal(request)
            await ctx.send(sender, ChangeOrderSubmittedTransport.from_domain(submitted))
            await ctx.send(sender, ChangeResponseReceivedTransport.from_domain(response))
        except (ValidationError, ValueError, RuntimeError):
            await _send_failure(ctx, sender, msg, service.name, "COUNTERPROPOSAL_EXECUTION")
        except Exception:
            ctx.logger.exception("counterproposal transport execution failed")
            await _send_failure(ctx, sender, msg, service.name, "COUNTERPROPOSAL_EXECUTION")

    return protocol


async def _send_failure(
    ctx: Context,
    sender: str,
    msg: PurchaseOrderExecutionTransport | CounterproposalExecutionTransport,
    agent_name: str,
    operation: str,
) -> None:
    await ctx.send(
        sender,
        SpecialistFailureTransport(
            correlation_id=msg.correlation_id,
            workflow_id=msg.workflow_id,
            reply_to=msg.message_id,
            sender_agent=agent_name,
            operation=operation,
            code="PROCUREMENT_EXECUTION_FAILED",
            message="Approved procurement execution could not be completed safely.",
            retryable=True,
        ),
    )
