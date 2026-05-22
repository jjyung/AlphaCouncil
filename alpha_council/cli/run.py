from __future__ import annotations

import argparse
import asyncio
import json
import os
import traceback
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from alpha_council.llm_config import expand_path, get_model_auth_error

APP_NAME = "alpha-council"
EXIT_OK = 0
EXIT_EXPECTED_ERROR = 2
EXIT_UNEXPECTED_ERROR = 3
DEFAULT_TIMEOUT_SECONDS = 1800


class CliUsageError(ValueError):
    """A predictable, user-facing CLI usage error."""


@dataclass
class RunOutcome:
    status: str
    final_text: str
    session_id: str
    state: dict
    event_count: int


def _strip_wrapped_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _load_local_env_files() -> None:
    """Load local .env files for CLI runs without overriding existing env.

    Cloud runtimes already inject env vars, so existing values always win.
    Local convenience loading checks project-root `.env` and `alpha_council/.env`.
    """

    candidate_paths: list[Path] = []
    explicit_env_file = (os.getenv("ALPHACOUNCIL_ENV_FILE") or "").strip()
    if explicit_env_file:
        candidate_paths.append(Path(expand_path(explicit_env_file)))
    candidate_paths.extend([Path(".env"), Path("alpha_council/.env")])
    for env_path in candidate_paths:
        if not env_path.exists() or not env_path.is_file():
            continue
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith("export "):
                line = line[len("export ") :].strip()
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            if not key:
                continue
            os.environ.setdefault(key, _strip_wrapped_quotes(value.strip()))


def _parse_bool_env(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "y", "on"}


def _infer_market(ticker: str, market: str | None) -> str:
    if market:
        normalized = market.strip().lower()
        if normalized not in {"tw", "us"}:
            raise CliUsageError("--market must be either 'tw' or 'us'.")
        return normalized
    if ticker.isdigit():
        return "tw"
    return "us"


def _normalize_ticker(ticker: str, market: str) -> str:
    raw = (ticker or "").strip()
    if not raw:
        raise CliUsageError("--ticker is required.")
    if market == "tw":
        if not raw.isdigit():
            raise CliUsageError("TW ticker must be 4-6 digits.")
        if not (4 <= len(raw) <= 6):
            raise CliUsageError("TW ticker must be 4-6 digits.")
        return raw
    if not raw.isalpha():
        raise CliUsageError("US ticker must be 1-5 letters.")
    if not (1 <= len(raw) <= 5):
        raise CliUsageError("US ticker must be 1-5 letters.")
    return raw.upper()


def _resolve_report_format(cli_value: str | None) -> str:
    candidate = (cli_value or os.getenv("REPORT_FORMAT") or "json").strip().lower()
    if candidate not in {"json", "md"}:
        raise CliUsageError("report format must be json or md.")
    return candidate


def _has_model_auth() -> bool:
    return get_model_auth_error() is None


def parse_masters(raw: str | None) -> list[str]:
    from alpha_council.master_selector import MASTER_MENU
    from alpha_council.utils.master_runtime import ALL_MASTERS

    value = (raw or "").strip()
    if not value:
        return []

    by_number = MASTER_MENU
    valid_names = set(ALL_MASTERS)
    name_aliases = {name.lower(): name for name in ALL_MASTERS}
    selections: list[str] = []
    seen: set[str] = set()

    for part in value.split(","):
        token = part.strip()
        if not token:
            continue

        name: str | None = None
        if token.isdigit():
            idx = int(token)
            name = by_number.get(idx)
            if name is None:
                raise CliUsageError(
                    f"invalid master index {idx}; valid range is 1-{len(by_number)}."
                )
        else:
            lookup = token.lower().replace("-", "_").replace(" ", "_")
            name = name_aliases.get(lookup)
            if name is None and token in valid_names:
                name = token

        if name is None:
            raise CliUsageError(f"invalid master '{token}'.")

        if name not in seen:
            seen.add(name)
            selections.append(name)

    return selections


def _build_user_message(ticker: str, market: str, masters_raw: str | None) -> str:
    ticker_text = f"{ticker} US" if market == "us" else ticker
    choice = (masters_raw or "").strip() or "0"
    return f"{ticker_text}\nmaster_choice={choice}"


def _extract_final_text(events: list) -> str:
    for event in reversed(events):
        checker = getattr(event, "is_final_response", None)
        if callable(checker) and checker():
            content = getattr(event, "content", None)
            if not content:
                continue
            texts: list[str] = []
            for part in content.parts or []:
                text = getattr(part, "text", None)
                if text:
                    texts.append(str(text).strip())
            if texts:
                return "\n".join(t for t in texts if t)
    return ""


def _has_error_event(events: list) -> bool:
    for event in events:
        if getattr(event, "error_code", None) or getattr(event, "error_message", None):
            return True
    return False


async def _run_pipeline(
    *,
    ticker: str,
    market: str,
    masters: list[str],
    masters_raw: str | None,
    timeout_sec: int,
    debug: bool,
) -> RunOutcome:
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    from alpha_council.agent import root_agent

    session_service = InMemorySessionService()
    runner = Runner(app_name=APP_NAME, agent=root_agent, session_service=session_service)
    user_id = "cli"
    session_id = uuid.uuid4().hex
    initial_state = {
        "selected_masters": masters,
        "awaiting_master_choice": False,
        "skip_master_selector": True,
        "analysis_intent": True,
        "market": market,
        "ticker": ticker,
        "date": datetime.now(UTC).date().isoformat(),
    }

    await session_service.create_session(
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
        state=initial_state,
    )

    msg = types.UserContent(
        parts=[types.Part.from_text(text=_build_user_message(ticker, market, masters_raw))]
    )
    events = []

    async def _consume() -> None:
        async for event in runner.run_async(user_id=user_id, session_id=session_id, new_message=msg):
            events.append(event)
            if debug:
                author = getattr(event, "author", None)
                turn_complete = bool(getattr(event, "turn_complete", False))
                event_id = getattr(event, "id", "")
                print(
                    f"event[{len(events)}] author={author} turn_complete={turn_complete} id={event_id}",
                    flush=True,
                )

                content = getattr(event, "content", None)
                if content and getattr(content, "parts", None):
                    text_parts: list[str] = []
                    for part in content.parts:
                        text = getattr(part, "text", None)
                        if text:
                            text_parts.append(str(text).strip())
                    if text_parts:
                        merged = "\n".join(p for p in text_parts if p)
                        if merged:
                            print("event text start", flush=True)
                            print(merged, flush=True)
                            print("event text end", flush=True)

    try:
        await asyncio.wait_for(_consume(), timeout=timeout_sec)
    except TimeoutError:
        if debug:
            print(f"run timeout after {timeout_sec}s", flush=True)
        session = await session_service.get_session(
            app_name=APP_NAME,
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
        app_name=APP_NAME,
        user_id=user_id,
        session_id=session_id,
    )
    state = dict(session.state) if session else {}
    if _has_error_event(events):
        return RunOutcome(
            status="FAILED",
            final_text=_extract_final_text(events),
            session_id=session_id,
            state=state,
            event_count=len(events),
        )
    return RunOutcome(
        status="SUCCEEDED",
        final_text=_extract_final_text(events),
        session_id=session_id,
        state=state,
        event_count=len(events),
    )


def _build_report(*, outcome: RunOutcome, ticker: str, market: str) -> dict:
    generated_at = datetime.now(UTC).isoformat()
    return {
        "meta": {
            "run_id": outcome.session_id,
            "session_id": outcome.session_id,
            "generated_at": generated_at,
            "ticker": ticker,
            "date": generated_at[:10],
            "market": market,
            "status": outcome.status,
        },
        "final_decision": outcome.final_text,
    }


def _as_markdown(report: dict) -> str:
    meta = report["meta"]
    lines = [
        "# Portfolio Report",
        "",
        "## Meta",
        f"- run_id: {meta['run_id']}",
        f"- session_id: {meta['session_id']}",
        f"- generated_at: {meta['generated_at']}",
        f"- ticker: {meta['ticker']}",
        f"- date: {meta['date']}",
        f"- market: {meta['market']}",
        f"- status: {meta['status']}",
        "",
        "## Final Decision",
        report.get("final_decision") or "",
        "",
    ]
    return "\n".join(lines)


def _parse_gs_root(gs_root: str) -> tuple[str, str]:
    if not gs_root.startswith("gs://"):
        raise CliUsageError("GCS_BUCKET_ROOT must start with gs://")
    without_scheme = gs_root[5:]
    if not without_scheme:
        raise CliUsageError("GCS_BUCKET_ROOT must include a bucket name")
    parts = without_scheme.split("/", 1)
    bucket = parts[0]
    prefix = parts[1] if len(parts) > 1 else ""
    return bucket, prefix.strip("/")


def _persist_report(report: dict, *, ticker: str, market: str, report_format: str) -> str:
    date = report["meta"]["date"]
    filename = f"portfolio_report.{report_format}"

    gcs_root = (os.getenv("GCS_BUCKET_ROOT") or "").strip()
    if gcs_root:
        from google.cloud import storage

        bucket_name, root_prefix = _parse_gs_root(gcs_root)
        path_parts = [p for p in [root_prefix, market, ticker, date, filename] if p]
        blob_name = "/".join(path_parts)

        client = storage.Client()
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        if report_format == "json":
            payload = json.dumps(report, ensure_ascii=False, indent=2)
            blob.upload_from_string(payload, content_type="application/json")
        else:
            payload = _as_markdown(report)
            blob.upload_from_string(payload, content_type="text/markdown")
        return f"gs://{bucket_name}/{blob_name}"

    local_root = expand_path((os.getenv("LOCAL_REPORT_ROOT") or "./reports").strip())
    target = Path(local_root) / market / ticker / date / filename
    target.parent.mkdir(parents=True, exist_ok=True)
    if report_format == "json":
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    else:
        target.write_text(_as_markdown(report), encoding="utf-8")
    return str(target)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="alpha-council",
        description="AlphaCouncil command-line interface",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run AlphaCouncil pipeline once")
    run_parser.add_argument("--ticker", required=True, help="Stock ticker, e.g. AAPL or 2330")
    run_parser.add_argument("--market", choices=["us", "tw"], help="Market code")
    run_parser.add_argument(
        "--masters",
        help="Comma-separated master indexes or names, e.g. 1,3,5 or warren_buffett,ben_graham",
    )
    run_parser.add_argument("--report-format", choices=["json", "md"], help="Report format")
    run_parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=int(os.getenv("ORCHESTRATOR_TIMEOUT_SECONDS", str(DEFAULT_TIMEOUT_SECONDS))),
        help="Run timeout in seconds",
    )
    run_parser.add_argument("--debug", action="store_true", help="Enable verbose debug output")
    return parser


async def _run_command(args: argparse.Namespace) -> int:
    auth_error = get_model_auth_error()
    if auth_error:
        raise CliUsageError(auth_error)

    market = _infer_market(args.ticker, args.market)
    ticker = _normalize_ticker(args.ticker, market)
    masters = parse_masters(args.masters)
    report_format = _resolve_report_format(args.report_format)

    outcome = await _run_pipeline(
        ticker=ticker,
        market=market,
        masters=masters,
        masters_raw=args.masters,
        timeout_sec=args.timeout_seconds,
        debug=bool(args.debug),
    )

    if args.debug:
        print(
            "run debug:",
            json.dumps(
                {
                    "status": outcome.status,
                    "session_id": outcome.session_id,
                    "event_count": outcome.event_count,
                    "awaiting_master_choice": bool(outcome.state.get("awaiting_master_choice")),
                    "selected_masters": outcome.state.get("selected_masters", []),
                },
                ensure_ascii=False,
            ),
        )

    if args.debug and outcome.final_text:
        print("final response start")
        print(outcome.final_text)
        print("final response end")

    if outcome.state.get("awaiting_master_choice"):
        print("run ended with incomplete master selection state (awaiting_master_choice=True)")
        return EXIT_EXPECTED_ERROR

    if outcome.status != "SUCCEEDED":
        print(f"run ended with status={outcome.status}")
        return EXIT_EXPECTED_ERROR

    persist_enabled = _parse_bool_env("ALPHACOUNCIL_PERSIST_ENABLED", default=False)
    report = _build_report(outcome=outcome, ticker=ticker, market=market)
    if persist_enabled:
        path = _persist_report(report, ticker=ticker, market=market, report_format=report_format)
        print(f"report persisted: {path}")
    else:
        print("persist disabled; skip writing report")

    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    try:
        _load_local_env_files()
        parser = build_parser()
        args = parser.parse_args(argv)

        if args.command != "run":
            parser.print_help()
            return EXIT_EXPECTED_ERROR

        return asyncio.run(_run_command(args))
    except CliUsageError as exc:
        print(f"usage error: {exc}")
        return EXIT_EXPECTED_ERROR
    except ExceptionGroup as exc:
        print(f"unexpected error group: {exc}")
        for idx, sub_exc in enumerate(exc.exceptions, start=1):
            print(f"[{idx}] {type(sub_exc).__name__}: {sub_exc}")
            tb = "".join(traceback.format_exception(type(sub_exc), sub_exc, sub_exc.__traceback__))
            print(tb)
        return EXIT_UNEXPECTED_ERROR
    except Exception as exc:  # pragma: no cover
        print(f"unexpected error: {exc}")
        return EXIT_UNEXPECTED_ERROR


if __name__ == "__main__":
    raise SystemExit(main())
