from dataclasses import dataclass

from sqlalchemy.orm import Session
from uagents import Agent

from supplymesh.agents.connectivity import FetchConnectivityCoordinator
from supplymesh.agents.inventory import build_inventory_protocol
from supplymesh.agents.orchestrator import build_orchestrator_agent
from supplymesh.persistence.database import get_engine
from supplymesh.persistence.planning_repository import PlanningRequestRepository
from supplymesh.persistence.workflow_repository import WorkflowRepository


@dataclass(frozen=True)
class AgentSeeds:
    orchestrator: str
    inventory: str
    sourcing: str
    procurement: str
    acknowledgment: str

    def validate(self) -> None:
        values = tuple(vars(self).values())
        if any(not value.strip() for value in values):
            raise ValueError("all five agent seeds must be configured")
        if len(set(values)) != 5:
            raise ValueError("each company agent must have a unique seed")


def _specialist(
    name: str, seed: str, description: str, publish: bool, *, mailbox: bool = False
) -> Agent:
    return Agent(
        name=name,
        seed=seed,
        mailbox=mailbox,
        publish_agent_details=publish,
        description=description,
    )


def _session_factory() -> Session:
    return Session(get_engine())


def build_company_agents(
    seeds: AgentSeeds,
    *,
    publish_agent_details: bool = False,
    mailbox: bool = False,
    publish_manifests: bool = True,
) -> tuple[Agent, ...]:
    seeds.validate()
    inventory = _specialist(
        "supplymesh-inventory-bom",
        seeds.inventory,
        "Deterministically expands BOMs, protects reservations, and calculates shortages.",
        publish_agent_details,
        mailbox=mailbox,
    )
    inventory.include(build_inventory_protocol(), publish_manifest=publish_manifests)
    coordinator = FetchConnectivityCoordinator(
        inventory_address=inventory.address,
        requests=PlanningRequestRepository(_session_factory),
        workflows=WorkflowRepository(_session_factory),
    )
    return (
        build_orchestrator_agent(
            seed=seeds.orchestrator,
            port=None,
            mailbox=mailbox,
            publish_agent_details=publish_agent_details,
            coordinator=coordinator,
            publish_manifests=publish_manifests,
        ),
        inventory,
        _specialist(
            "supplymesh-sourcing-optimization",
            seeds.sourcing,
            "Collects supplier REST quotes and creates constrained OR-Tools procurement plans.",
            publish_agent_details,
            mailbox=mailbox,
        ),
        _specialist(
            "supplymesh-procurement-execution",
            seeds.procurement,
            "Executes approved, version-matched, idempotent X12 purchase and change orders.",
            publish_agent_details,
            mailbox=mailbox,
        ),
        _specialist(
            "supplymesh-acknowledgment-exception",
            seeds.acknowledgment,
            "Parses X12 acknowledgments and deterministically classifies supplier discrepancies.",
            publish_agent_details,
            mailbox=mailbox,
        ),
    )
