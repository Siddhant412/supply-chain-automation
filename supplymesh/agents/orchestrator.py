from datetime import UTC, datetime

from uagents import Agent, Context, Protocol
from uagents_core.contrib.protocols.chat import (
    ChatAcknowledgement,
    ChatMessage,
    MetadataContent,
    TextContent,
    chat_protocol_spec,
)

from supplymesh.cards.demand import demand_intake_card


def build_chat_protocol() -> Protocol:
    protocol = Protocol(spec=chat_protocol_spec)

    @protocol.on_message(ChatMessage)
    async def handle_message(ctx: Context, sender: str, msg: ChatMessage) -> None:
        await ctx.send(sender, ChatAcknowledgement(acknowledged_msg_id=msg.msg_id))
        card = demand_intake_card()
        await ctx.send(
            sender,
            ChatMessage(
                timestamp=datetime.now(UTC),
                content=[
                    TextContent(
                        text=(
                            "I can protect existing reservations, calculate shortages, source "
                            "parts, and prepare purchase orders. Confirm the demand to begin."
                        )
                    ),
                    MetadataContent(metadata=card.metadata()),
                ],
            ),
        )

    @protocol.on_message(ChatAcknowledgement)
    async def handle_acknowledgement(ctx: Context, sender: str, msg: ChatAcknowledgement) -> None:
        ctx.logger.info(
            "chat response acknowledged", extra={"message_id": str(msg.acknowledged_msg_id)}
        )

    return protocol


def build_orchestrator_agent(
    *,
    seed: str,
    port: int | None = 8000,
    mailbox: bool = True,
    publish_agent_details: bool = False,
) -> Agent:
    if not seed.strip():
        raise ValueError("ORCHESTRATOR_AGENT_SEED must be configured")
    agent = Agent(
        name="supplymesh-manufacturing-orchestrator",
        seed=seed,
        port=port,
        mailbox=mailbox,
        publish_agent_details=publish_agent_details,
        description=(
            "Manufacturing procurement orchestration for BOM, inventory shortages, supplier RFQs, "
            "human-approved purchase orders, and X12 acknowledgments."
        ),
    )
    agent.include(build_chat_protocol(), publish_manifest=True)
    return agent
