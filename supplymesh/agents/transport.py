"""uAgents wire models for the Pydantic 2 planning contracts.

uAgents 0.25.x builds protocol schemas from its Pydantic-1-compatible ``Model``
base.  The application contracts remain Pydantic 2 models and are serialized at
this narrow boundary, then strictly revalidated by the receiver.
"""

from uagents import Model

from supplymesh.protocols.planning import DemandPlanningRequest, InventoryShortageReport


class DemandPlanningTransport(Model):
    schema_version: str
    message_id: str
    correlation_id: str
    workflow_id: str
    sender_agent: str
    payload_json: str

    @classmethod
    def from_domain(cls, request: DemandPlanningRequest) -> "DemandPlanningTransport":
        return cls(
            schema_version=request.schema_version,
            message_id=str(request.message_id),
            correlation_id=str(request.correlation_id),
            workflow_id=str(request.workflow_id),
            sender_agent=request.sender_agent,
            payload_json=request.model_dump_json(),
        )

    def to_domain(self) -> DemandPlanningRequest:
        request = DemandPlanningRequest.model_validate_json(self.payload_json)
        if (
            request.schema_version != self.schema_version
            or str(request.message_id) != self.message_id
            or str(request.correlation_id) != self.correlation_id
            or str(request.workflow_id) != self.workflow_id
            or request.sender_agent != self.sender_agent
        ):
            raise ValueError("planning transport envelope does not match its validated payload")
        return request


class InventoryShortageTransport(Model):
    schema_version: str
    message_id: str
    correlation_id: str
    workflow_id: str
    sender_agent: str
    reply_to: str
    payload_json: str

    @classmethod
    def from_domain(cls, report: InventoryShortageReport) -> "InventoryShortageTransport":
        if report.reply_to is None:
            raise ValueError("inventory report must identify the planning request it answers")
        return cls(
            schema_version=report.schema_version,
            message_id=str(report.message_id),
            correlation_id=str(report.correlation_id),
            workflow_id=str(report.workflow_id),
            sender_agent=report.sender_agent,
            reply_to=report.reply_to,
            payload_json=report.model_dump_json(),
        )

    def to_domain(self) -> InventoryShortageReport:
        report = InventoryShortageReport.model_validate_json(self.payload_json)
        if (
            report.schema_version != self.schema_version
            or str(report.message_id) != self.message_id
            or str(report.correlation_id) != self.correlation_id
            or str(report.workflow_id) != self.workflow_id
            or report.sender_agent != self.sender_agent
            or report.reply_to != self.reply_to
        ):
            raise ValueError("inventory transport envelope does not match its validated payload")
        return report


class PlanningFailureTransport(Model):
    schema_version: str = "1.0"
    correlation_id: str
    workflow_id: str
    reply_to: str
    code: str
    message: str
    retryable: bool = False
