from uagents_core.contrib.protocols.chat import chat_protocol_spec

from supplymesh.agents.orchestrator import build_chat_protocol, build_orchestrator_agent


def test_official_chat_protocol_version_and_manifest() -> None:
    protocol = build_chat_protocol()
    assert chat_protocol_spec.version == "0.3.0"
    assert protocol.version == "0.3.0"
    assert len(protocol.models) == 2


def test_orchestrator_requires_a_stable_seed() -> None:
    try:
        build_orchestrator_agent(seed="")
    except ValueError as exc:
        assert "ORCHESTRATOR_AGENT_SEED" in str(exc)
    else:
        raise AssertionError("empty seed must be rejected")
