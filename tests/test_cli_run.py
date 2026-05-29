import asyncio
import os

from alpha_council.cli import run


def test_parse_masters_by_index_and_name() -> None:
    selected = run.parse_masters("1, ben_graham,1, peter-lynch")
    assert selected == ["warren_buffett", "ben_graham", "peter_lynch"]


def test_parse_masters_empty_is_skip() -> None:
    assert run.parse_masters("") == []
    assert run.parse_masters(None) == []


def test_parse_masters_invalid_raises() -> None:
    try:
        run.parse_masters("999")
    except run.CliUsageError:
        pass
    else:  # pragma: no cover
        raise AssertionError("expected CliUsageError")


def test_infer_market_and_ticker_normalization() -> None:
    assert run._infer_market("2330", None) == "tw"
    assert run._infer_market("aapl", None) == "us"
    assert run._normalize_ticker("aapl", "us") == "AAPL"
    assert run._normalize_ticker("2330", "tw") == "2330"


def test_build_user_message_defaults_to_skip_when_no_masters() -> None:
    msg = run._build_user_message("2330", "tw", None)
    assert "2330" in msg
    assert "master_choice=0" in msg


def test_build_user_message_includes_masters_choice() -> None:
    msg = run._build_user_message("AAPL", "us", "1,2,3")
    assert "AAPL US" in msg
    assert "master_choice=1,2,3" in msg


def test_run_command_persist_enabled(monkeypatch) -> None:
    outcome = run.RunOutcome(
        status="SUCCEEDED",
        final_text="buy",
        session_id="s1",
        state={},
        event_count=3,
        error_messages=[],
    )

    async def fake_run_pipeline(**kwargs):
        return outcome

    monkeypatch.setattr(run, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(run, "_has_model_auth", lambda: True)
    monkeypatch.setattr(run, "_persist_report", lambda *args, **kwargs: "./reports/x.json")
    monkeypatch.setenv("ALPHACOUNCIL_PERSIST_ENABLED", "true")

    args = run.build_parser().parse_args(["run", "--ticker", "2330", "--market", "tw"])
    code = asyncio.run(run._run_command(args))
    assert code == run.EXIT_OK


def test_run_command_failed_status(monkeypatch) -> None:
    outcome = run.RunOutcome(
        status="FAILED",
        final_text="",
        session_id="s1",
        state={},
        event_count=2,
        error_messages=[],
    )

    async def fake_run_pipeline(**kwargs):
        return outcome

    monkeypatch.setattr(run, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(run, "_has_model_auth", lambda: True)
    args = run.build_parser().parse_args(["run", "--ticker", "AAPL", "--market", "us"])
    code = asyncio.run(run._run_command(args))
    assert code == run.EXIT_EXPECTED_ERROR


def test_run_pipeline_with_retry_retries_resource_exhausted(monkeypatch) -> None:
    outcomes = [
        run.RunOutcome(
            status="FAILED",
            final_text="",
            session_id="s1",
            state={},
            event_count=1,
            error_messages=["RESOURCE_EXHAUSTED 429"],
        ),
        run.RunOutcome(
            status="SUCCEEDED",
            final_text="buy",
            session_id="s2",
            state={},
            event_count=2,
            error_messages=[],
        ),
    ]
    sleep_calls: list[int] = []

    async def fake_run_pipeline(**kwargs):
        return outcomes.pop(0)

    async def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(run, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(run.asyncio, "sleep", fake_sleep)

    outcome = asyncio.run(
        run._run_pipeline_with_retry(
            ticker="2330",
            market="tw",
            masters=[],
            masters_raw=None,
            timeout_sec=30,
            debug=False,
        )
    )

    assert outcome.status == "SUCCEEDED"
    assert sleep_calls == [300]


def test_run_pipeline_with_retry_does_not_retry_non_429(monkeypatch) -> None:
    outcome = run.RunOutcome(
        status="FAILED",
        final_text="",
        session_id="s1",
        state={},
        event_count=1,
        error_messages=["permission denied"],
    )
    sleep_calls: list[int] = []

    async def fake_run_pipeline(**kwargs) -> run.RunOutcome:
        return outcome

    async def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(run, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(run.asyncio, "sleep", fake_sleep)

    result = asyncio.run(
        run._run_pipeline_with_retry(
            ticker="2330",
            market="tw",
            masters=[],
            masters_raw=None,
            timeout_sec=30,
            debug=False,
        )
    )

    assert result is outcome
    assert sleep_calls == []


def test_run_command_ollama_provider_skips_google_auth(monkeypatch) -> None:
    outcome = run.RunOutcome(
        status="SUCCEEDED", final_text="buy", session_id="s1", state={},
        event_count=3, error_messages=[],
    )

    async def fake_run_pipeline(**kwargs):
        return outcome

    monkeypatch.setattr(run, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("ALPHACOUNCIL_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_API_BASE", "http://localhost:11434")
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_GENAI_USE_VERTEXAI", raising=False)

    args = run.build_parser().parse_args(["run", "--ticker", "AAPL", "--market", "us"])
    code = asyncio.run(run._run_command(args))
    assert code == run.EXIT_OK


def test_run_pipeline_with_retry_retries_exception_group(monkeypatch) -> None:
    calls = {"count": 0}
    sleep_calls: list[int] = []

    async def fake_run_pipeline(**kwargs):
        calls["count"] += 1
        if calls["count"] == 1:
            raise ExceptionGroup("run failed", [RuntimeError("429 RESOURCE_EXHAUSTED")])
        return run.RunOutcome(
            status="SUCCEEDED",
            final_text="buy",
            session_id="s2",
            state={},
            event_count=2,
            error_messages=[],
        )

    async def fake_sleep(seconds: int) -> None:
        sleep_calls.append(seconds)

    monkeypatch.setattr(run, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setattr(run.asyncio, "sleep", fake_sleep)

    outcome = asyncio.run(
        run._run_pipeline_with_retry(
            ticker="AAPL",
            market="us",
            masters=[],
            masters_raw=None,
            timeout_sec=30,
            debug=False,
        )
    )

    assert outcome.status == "SUCCEEDED"
    assert sleep_calls == [300]


def test_run_command_ollama_provider_accepts_optional_auth_token(monkeypatch) -> None:
    outcome = run.RunOutcome(
        status="SUCCEEDED", final_text="buy", session_id="s1", state={},
        event_count=3, error_messages=[],
    )

    async def fake_run_pipeline(**kwargs):
        return outcome

    monkeypatch.setattr(run, "_run_pipeline", fake_run_pipeline)
    monkeypatch.setenv("ALPHACOUNCIL_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_API_BASE", "https://ollama.example.com")
    monkeypatch.setenv("OLLAMA_API_KEY", "secret-token")

    args = run.build_parser().parse_args(["run", "--ticker", "AAPL", "--market", "us"])
    code = asyncio.run(run._run_command(args))
    assert code == run.EXIT_OK


def test_load_local_env_files_supports_explicit_env_file(monkeypatch, tmp_path) -> None:
    env_file = tmp_path / "alpha.env"
    env_file.write_text("OLLAMA_API_BASE=http://127.0.0.1:11434\n", encoding="utf-8")

    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)
    monkeypatch.setenv("ALPHACOUNCIL_ENV_FILE", str(env_file))

    run._load_local_env_files()

    assert os.environ["OLLAMA_API_BASE"] == "http://127.0.0.1:11434"


def test_persist_report_expands_local_root_env_vars(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("ALPHA_REPORT_ROOT", str(tmp_path))
    monkeypatch.setenv("LOCAL_REPORT_ROOT", "$ALPHA_REPORT_ROOT/reports")

    report = {
        "meta": {
            "date": "2026-05-20",
            "run_id": "r1",
            "session_id": "s1",
            "generated_at": "2026-05-20T00:00:00+00:00",
            "ticker": "AAPL",
            "market": "us",
            "status": "SUCCEEDED",
        },
        "final_decision": "buy",
    }

    path = run._persist_report(report, ticker="AAPL", market="us", report_format="json")

    assert path.startswith(str(tmp_path / "reports"))
