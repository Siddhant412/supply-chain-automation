from uagents import Bureau

from apps.agent_host.settings import get_settings
from supplymesh.agents.factory import AgentSeeds, build_company_agents
from supplymesh.observability.logging import configure_logging
from supplymesh.observability.sentry import initialize_sentry


def main() -> None:
    settings = get_settings()
    configure_logging(settings.log_level)
    initialize_sentry(
        dsn=settings.sentry_dsn.get_secret_value() if settings.sentry_dsn else None,
        traces_sample_rate=settings.sentry_traces_sample_rate,
        profiles_sample_rate=settings.sentry_profiles_sample_rate,
    )
    configured = (
        settings.orchestrator_agent_seed,
        settings.inventory_agent_seed,
        settings.sourcing_agent_seed,
        settings.procurement_agent_seed,
        settings.acknowledgment_agent_seed,
    )
    if any(value is None for value in configured):
        raise RuntimeError("all five company agent seeds are required to start the Agentverse host")
    values = [value.get_secret_value() for value in configured if value is not None]
    agents = build_company_agents(
        AgentSeeds(*values),
        publish_agent_details=settings.publish_agent_details,
        mailbox=settings.agent_mailbox,
    )
    Bureau(agents=list(agents), port=settings.agent_host_port, network="testnet").run()


if __name__ == "__main__":
    main()
