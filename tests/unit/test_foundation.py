from datetime import UTC
from uuid import uuid4

from fastapi.testclient import TestClient

from apps.agent_host.health import app as agent_app
from apps.supplier_simulator.main import create_app
from supplymesh.protocols.common import MessageEnvelope


def test_agent_health() -> None:
    response = TestClient(agent_app).get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "service": "agent-host"}


def test_supplier_health_and_readiness() -> None:
    client = TestClient(create_app(api_key="test-api-key", admin_api_key="test-admin-key"))
    assert client.get("/health").json()["status"] == "ok"
    assert client.get("/ready").json() == {"status": "ready"}


def test_message_envelope_has_utc_identity_fields() -> None:
    envelope = MessageEnvelope(
        correlation_id=uuid4(), workflow_id=uuid4(), sender_agent="orchestrator"
    )
    assert envelope.schema_version == "1.0"
    assert envelope.sent_at.tzinfo == UTC
    assert envelope.message_id
