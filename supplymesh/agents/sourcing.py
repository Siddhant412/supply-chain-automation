from datetime import datetime
from decimal import Decimal

from supplymesh.protocols.sourcing import (
    ProcurementPlansReady,
    SourcingRequest,
    SupplierQuotesCollected,
)
from supplymesh.services.optimizer import optimize_plans
from supplymesh.services.sourcing_service import (
    SupplierGateway,
    collect_quotes,
    normalize_quotes,
)


class SourcingAgentService:
    name = "sourcing-and-optimization"

    def __init__(
        self,
        gateway: SupplierGateway,
        supplier_ids: tuple[str, ...],
        *,
        minimum_valid_quotes: int = 2,
    ) -> None:
        self.gateway = gateway
        self.supplier_ids = supplier_ids
        self.minimum_valid_quotes = minimum_valid_quotes

    async def collect(
        self, request: SourcingRequest, *, now: datetime | None = None
    ) -> SupplierQuotesCollected:
        return await collect_quotes(
            request,
            self.supplier_ids,
            self.gateway,
            minimum_valid_quotes=self.minimum_valid_quotes,
            now=now,
        )

    def plan(
        self,
        request: SourcingRequest,
        collected: SupplierQuotesCollected,
        *,
        fx_to_target: dict[str, Decimal],
    ) -> ProcurementPlansReady:
        lines = normalize_quotes(collected.quotes, request.required_by, fx_to_target)
        result = optimize_plans(request.shortages, lines, currency=request.currency)
        return ProcurementPlansReady(
            correlation_id=request.correlation_id,
            workflow_id=request.workflow_id,
            sender_agent=self.name,
            reply_to=str(collected.message_id),
            result=result,
        )
