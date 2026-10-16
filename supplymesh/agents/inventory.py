from supplymesh.protocols.planning import DemandPlanningRequest, InventoryShortageReport
from supplymesh.services.inventory_service import assess_inventory, tentative_reservations


class InventoryAgentService:
    """Pure typed handler used by the Inventory uAgent transport adapter."""

    name = "inventory-and-bom"

    def handle(self, request: DemandPlanningRequest) -> InventoryShortageReport:
        assessment = assess_inventory(request.demand, request.bom, request.inventory_positions)
        reservations = tentative_reservations(request.demand, assessment)
        return InventoryShortageReport(
            correlation_id=request.correlation_id,
            workflow_id=request.workflow_id,
            sender_agent=self.name,
            reply_to=str(request.message_id),
            assessment=assessment,
            tentative_reservations=reservations,
        )
