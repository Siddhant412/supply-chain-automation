from dataclasses import dataclass

from uagents import Agent

from supplymesh.agents.orchestrator import build_orchestrator_agent


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


def _specialist(name: str, seed: str, description: str, publish: bool) -> Agent:
    return Agent(
        name=name,
        seed=seed,
        publish_agent_details=publish,
        description=description,
    )


def build_company_agents(
    seeds: AgentSeeds, *, publish_agent_details: bool = False
) -> tuple[Agent, ...]:
    seeds.validate()
    return (
        build_orchestrator_agent(
            seed=seeds.orchestrator,
            port=None,
            mailbox=False,
            publish_agent_details=publish_agent_details,
        ),
        _specialist(
            "supplymesh-inventory-bom",
            seeds.inventory,
            "Deterministically expands BOMs, protects reservations, and calculates shortages.",
            publish_agent_details,
        ),
        _specialist(
            "supplymesh-sourcing-optimization",
            seeds.sourcing,
            "Collects supplier REST quotes and creates constrained OR-Tools procurement plans.",
            publish_agent_details,
        ),
        _specialist(
            "supplymesh-procurement-execution",
            seeds.procurement,
            "Executes approved, version-matched, idempotent X12 purchase and change orders.",
            publish_agent_details,
        ),
        _specialist(
            "supplymesh-acknowledgment-exception",
            seeds.acknowledgment,
            "Parses X12 acknowledgments and deterministically classifies supplier discrepancies.",
            publish_agent_details,
        ),
    )
