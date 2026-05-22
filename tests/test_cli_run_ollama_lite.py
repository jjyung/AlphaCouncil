import asyncio

from alpha_council.cli import run_ollama_lite


def test_sanitize_final_text_keeps_last_final_section() -> None:
    text = "draft\n# Ollama Lite Decision\nold\n# Ollama Lite Decision\nfinal"

    assert run_ollama_lite._sanitize_final_text(text) == "# Ollama Lite Decision\nfinal"


def test_run_command_success(monkeypatch) -> None:
    outcome = run_ollama_lite.RunOutcome(
        status="SUCCEEDED",
        final_text="# Ollama Lite Decision\n\n買入",
        session_id="s1",
        state={},
        event_count=4,
    )

    async def fake_run_pipeline(**kwargs):
        return outcome

    monkeypatch.setattr(run_ollama_lite, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(run_ollama_lite, "get_model_auth_error", lambda: None)

    args = run_ollama_lite.build_parser().parse_args(["--ticker", "2330", "--market", "tw"])
    code = asyncio.run(run_ollama_lite._run_command(args))
    assert code == run_ollama_lite.EXIT_OK


def test_run_command_timeout(monkeypatch) -> None:
    outcome = run_ollama_lite.RunOutcome(
        status="TIMEOUT",
        final_text="",
        session_id="s1",
        state={},
        event_count=3,
    )

    async def fake_run_pipeline(**kwargs):
        return outcome

    monkeypatch.setattr(run_ollama_lite, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(run_ollama_lite, "get_model_auth_error", lambda: None)

    args = run_ollama_lite.build_parser().parse_args(["--ticker", "AAPL", "--market", "us"])
    code = asyncio.run(run_ollama_lite._run_command(args))
    assert code == run_ollama_lite.EXIT_EXPECTED_ERROR
