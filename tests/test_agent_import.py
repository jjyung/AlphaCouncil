from alpha_council.agent import root_agent


def test_root_agent_importable() -> None:
    assert root_agent is not None
    assert getattr(root_agent, "name", "") == "AlphaCouncilPipelineAgent"
