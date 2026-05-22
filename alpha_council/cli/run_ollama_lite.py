from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime

from alpha_council.cli.run import (
    APP_NAME,
    EXIT_EXPECTED_ERROR,
    EXIT_OK,
    DEFAULT_TIMEOUT_SECONDS,
    CliUsageError,
    RunOutcome,
    _extract_final_text,
    _has_error_event,
    _infer_market,
    _load_local_env_files,
    _normalize_ticker,
)
from alpha_council.llm_config import get_model_auth_error

_FINAL_HEADER = "# Ollama Lite Decision"


def _sanitize_final_text(text: str) -> str:
    value = (text or "").strip()
    if not value:
        return value
    idx = value.rfind(_FINAL_HEADER)
    if idx >= 0:
        return value[idx:].strip()
    return value


async def _run_pipeline(*, ticker: str, market: str, timeout_sec: int, debug: bool) -> RunOutcome:
    import uuid

    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from alpha_council.agent_ollama_lite import root_agent

    session_service = InMemorySessionService()
    runner = Runner(app_name=f"{APP_NAME}-ollama-lite", agent=root_agent, session_service=session_service)
    user_id = "cli"
    session_id = uuid.uuid4().hex
    initial_state = {
        "analysis_intent": True,
        "market": market,
        "ticker": ticker,
        "date": datetime.now(UTC).date().isoformat(),
    }

    await session_service.create_session(
        app_name=f"{APP_NAME}-ollama-lite",
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )

    msg = types.UserContent(parts=[types.Part.from_text(text=f"{ticker} {market.upper()}")])
    events = []

    async def _consume() -> None:
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=msg):
            events.append(event)
            if debug:
                author = getattr(event, "author", None)
                print(f"event[{len(events)}] author={author}", flush=True)

    try:
        await asyncio.wait_for(_consume(), timeout=timeout_sec)
    except TimeoutError:
        session = await session_service.get_session(
            app_name=f"{APP_NAME}-ollama-lite",
            user_id=user_id,
            session_id=session_id,
        )
        return RunOutcome(
            status="TIMEOUT",
            final_text="",
            session_id=session_id,
            state=dict(session.state) if session else {},
            event_count=len(events),
        )

    session = await session_service.get_session(
        app_name=f"{APP_NAME}-ollama-lite",
        user_id=user_id,
        session_id=session_id,
    )
    state = dict(session.state) if session else {}
    if _has_error_event(events):
        return RunOutcome(
            status="FAILED",
            final_text=_sanitize_final_text(_extract_final_text(events)),
            session_id=session_id,
            state=state,
            event_count=len(events),
        )
    return RunOutcome(
        status="SUCCEEDED",
        final_text=_sanitize_final_text(_extract_final_text(events)),
        session_id=session_id,
        state=state,
        event_count=len(events),
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha-council-ollama-lite",
        description="AlphaCouncil Ollama lite command-line interface",
    )
    parser.add_argument("--ticker", required=True, help="Stock ticker, e.g. AAPL or 2330")
    parser.add_argument("--market", choices=["us", "tw"], help="Market code")
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=1800 if True else DEFAULT_TIMEOUT_SECONDS,
        help="Run timeout in seconds",
    )
    parser.add_argument("--debug", action="store_true", help="Enable verbose debug output")
    return parser


async def _run_command(args: argparse.Namespace) -> int:
    auth_error = get_model_auth_error()
    if auth_error:
        raise CliUsageError(auth_error)

    market = _infer_market(args.ticker, args.market)
    ticker = _normalize_ticker(args.ticker, market)
    outcome = await _run_pipeline(
        ticker=ticker,
        market=market,
        timeout_sec=args.timeout_seconds,
        debug=bool(args.debug),
    )

    if outcome.status != "SUCCEEDED":
        print(f"run ended with status={outcome.status}")
        return EXIT_EXPECTED_ERROR

    print(outcome.final_text)
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    try:
        _load_local_env_files()
        parser = build_parser()
        args = parser.parse_args(argv)
        return asyncio.run(_run_command(args))
    except CliUsageError as exc:
        print(f"usage error: {exc}")
        return EXIT_EXPECTED_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
