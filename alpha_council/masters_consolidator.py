"""Masters consolidation — deterministic (no LLM).

All logic is in ``_build_consolidated_report`` and ``_before_callback``.
The LLM is never invoked: before_agent_callback builds the report, writes it
to state["consolidated_masters_report"], then returns Content to skip the model.

Session state written:
    consolidated_masters_report: str
"""
import logging
import re

from google.adk.agents.llm_agent import Agent
from google.genai import types

from alpha_council.utils.master_factory import MASTER_OUTPUT_KEYS

logger = logging.getLogger(__name__)

# Matches the exact placeholder produced by make_before_callback:
#   "[{master_name} 未被選中，本輪跳過。]"
_SKIP_RE = re.compile(r"^\[[\w_]+ 未被選中，本輪跳過。\]$")

_FALLBACK_REPORT = (
    "### consolidated_masters_report\n"
    "[本輪無可用大師報告 — 所有選中大師均被跳過或未產出有效內容]\n"
    "selected_masters: []\n"
    "included_count: 0\n"
    "included_masters: []"
)


# ---------------------------------------------------------------------------
# Value validation
# ---------------------------------------------------------------------------


def _check_value(master_name: str, key: str, raw_value) -> tuple[bool, str]:
    """Return (is_substantive, reason).

    reason: "missing" | "empty" | "non_string" | "skip_placeholder" | "ok"
    """
    if raw_value is None:
        return False, "missing"
    if not isinstance(raw_value, str):
        return False, "non_string"
    if not raw_value.strip():
        return False, "empty"
    if _SKIP_RE.match(raw_value.strip()):
        return False, "skip_placeholder"
    return True, "ok"


# ---------------------------------------------------------------------------
# Core deterministic builder
# ---------------------------------------------------------------------------


def _build_consolidated_report(state) -> str:
    """Build consolidated_masters_report by copy-pasting selected master reports.

    Only examines masters listed in state["selected_masters"] — unselected
    masters' stale entries are ignored entirely.
    """
    selected: list[str] = list(state.get("selected_masters") or [])
    logger.info("Consolidator: selected_masters=%s (count=%d)", selected, len(selected))

    found: list[str] = []
    parts: list[str] = []

    for master_name in selected:
        key = MASTER_OUTPUT_KEYS.get(master_name)
        if key is None:
            logger.warning("  %s → not in MASTER_OUTPUT_KEYS — skipping", master_name)
            continue

        raw_value = state.get(key)
        substantive, reason = _check_value(master_name, key, raw_value)
        length = len(raw_value) if isinstance(raw_value, str) else 0

        if substantive:
            logger.debug("  %s → key=%r len=%d substantive=True", master_name, key, length)
            parts.append(f"### {key}\n{raw_value.strip()}")
            found.append(master_name)
        else:
            log_fn = logger.warning if reason == "non_string" else logger.debug
            log_fn(
                "  %s → key=%r exists=%s len=%d substantive=False reason=%s",
                master_name, key, raw_value is not None, length, reason,
            )

    logger.info("Consolidator: collected %d/%d report(s): %s", len(found), len(selected), found)

    if not parts:
        logger.warning("Consolidator: no substantive reports — using fallback.")
        selected_str = ", ".join(selected)
        return (
            "### consolidated_masters_report\n"
            "[本輪無可用大師報告 — 所有選中大師均被跳過或未產出有效內容]\n"
            f"selected_masters: [{selected_str}]\n"
            "included_count: 0\n"
            "included_masters: []"
        )

    selected_str = ", ".join(selected)
    included_str = ", ".join(found)
    header = (
        f"### consolidated_masters_report\n"
        f"selected_masters: [{selected_str}]\n"
        f"included_count: {len(found)}\n"
        f"included_masters: [{included_str}]"
    )
    body = "\n\n---\n".join(parts)
    return f"{header}\n\n---\n{body}"


# ---------------------------------------------------------------------------
# ADK callbacks
# ---------------------------------------------------------------------------


def _before_callback(callback_context) -> types.Content | None:
    """Deterministic consolidation: build report, write to state, skip LLM.

    ADK behaviour: returning Content here sets ctx.end_invocation=True so
    _run_async_impl (LLM) and after_agent_callback are both skipped.
    All error handling must live here.
    """
    try:
        report = _build_consolidated_report(callback_context.state)
    except Exception:
        logger.exception(
            "Consolidator before_callback: unexpected error building report — using fallback."
        )
        report = _FALLBACK_REPORT

    callback_context.state["consolidated_masters_report"] = report
    logger.info(
        "Consolidator before_callback: wrote consolidated_masters_report (%d chars) — LLM skipped.",
        len(report),
    )
    return types.Content(parts=[types.Part(text=report)])


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

masters_consolidator = Agent(
    model="gemini-2.5-flash",
    name="masters_consolidator",
    description="deterministic consolidator — 原文彙整本輪選中大師的報告，不做 LLM 語義改寫。",
    output_key="consolidated_masters_report",
    before_agent_callback=_before_callback,
    instruction="（本 agent 由 before_agent_callback 直接處理，LLM 不會被呼叫。）",
)
