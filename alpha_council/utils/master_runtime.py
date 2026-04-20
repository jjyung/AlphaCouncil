"""master_runtime — consolidated master utilities and panel agent.

Merges the former master_factory (constants, callbacks, instruction factory)
and dynamic_masters_panel (DynamicMastersPanel class) into a single module.

Why sequential (not ParallelAgent) for DynamicMastersPanel:
  Each master writes to a unique output_key ({name}_report), so there are
  no state conflicts. Sequential keeps the implementation simple and avoids
  duplicating ADK's internal parallel-merge machinery.

Why subclass BaseAgent instead of reusing ParallelAgent:
  ParallelAgent.sub_agents is fixed at construction; there is no public API
  to filter it at runtime. BaseAgent._run_async_impl is the correct extension
  point for custom routing logic.

Event count comparison (3 masters selected, 10 unselected):
  Before (ParallelAgent + callbacks): 13 events per turn (10 skip + 3 real)
  After (DynamicMastersPanel):         3 events per turn (3 real)

All 13 masters remain in sub_agents so ADK's agent-tree (find_agent, parent
resolution) works correctly. Only _run_async_impl restricts execution.
"""
import logging
import re
from typing import AsyncGenerator

from google.adk.agents.base_agent import BaseAgent
from google.adk.agents.invocation_context import InvocationContext
from google.adk.events.event import Event
from google.genai import types
from typing_extensions import override

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants and mappings
# ---------------------------------------------------------------------------

# Ordered list of all available masters (index+1 = menu number).
ALL_MASTERS: list[str] = [
    "warren_buffett",
    "ben_graham",
    "charlie_munger",
    "aswath_damodaran",
    "bill_ackman",
    "cathie_wood",
    "michael_burry",
    "peter_lynch",
    "phil_fisher",
    "mohnish_pabrai",
    "stanley_druckenmiller",
    "rakesh_jhunjhunwala",
    "nassim_taleb",
]

# Maps master name -> session-state key where their report is stored.
MASTER_OUTPUT_KEYS: dict[str, str] = {name: f"{name}_report" for name in ALL_MASTERS}

# Default analyst report keys each master should try to read.
# "news_report" is required; append "?" to make a key optional (e.g. "technical_report?").
DEFAULT_ANALYST_KEYS: list[str] = [
    "news_report",
    "technical_report",
    "psychology_report",
    "fundamentals_report",
    "chip_report",
]

# ---------------------------------------------------------------------------
# Report context builder
# ---------------------------------------------------------------------------


def build_reports_context(state: dict, key_specs: list[str]) -> str:
    """Build a context block from session state based on key specifications.

    key_specs format:
        "key"   -> required: missing emits a warning and injects a placeholder.
        "key?"  -> optional: missing is silently skipped with a note.

    Returns a formatted multi-section string ready to prepend to instructions.
    """
    parts: list[str] = []
    for spec in key_specs:
        optional = spec.endswith("?")
        key = spec.rstrip("?")
        value = state.get(key)
        if value is None:
            if optional:
                logger.info("Optional key %r absent from state, skipping.", key)
            else:
                logger.warning(
                    "Required key %r missing from state; degrading gracefully.", key
                )
                parts.append(
                    f"[⚠ 警告：必要輸入 {key!r} 不在 session state 中，"
                    "分析品質可能受影響，請在報告中標記此缺失。]"
                )
        else:
            parts.append(f"### {key}\n{value}")
    return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# before_agent_callback factory
# ---------------------------------------------------------------------------


def make_before_callback(master_name: str):
    """Return a before_agent_callback that skips *master_name* when appropriate.

    Skip conditions (checked in order):
    1. analysis_intent is explicitly False  -> chitchat turn, skip everyone.
    2. selected_masters is set and this master is not in it -> not chosen.
    If selected_masters is absent and analysis_intent is not False, the master
    proceeds -- preserving backward-compatibility with direct pipeline runs.
    """

    def callback(callback_context) -> types.Content | None:
        state = callback_context.state

        # Gate 1: skip entire masters phase on chitchat turns.
        if state.get("analysis_intent") is False:
            logger.info("Master %r skipping: analysis_intent=False.", master_name)
            return types.Content(
                parts=[types.Part(text=f"[{master_name} 未被選中，本輪跳過。]")]
            )

        # Gate 2: skip masters not in the user's selection.
        selected = state.get("selected_masters")
        if selected is not None and master_name not in selected:
            logger.info(
                "Master %r not in selected_masters %s -- skipping.", master_name, selected
            )
            return types.Content(
                parts=[types.Part(text=f"[{master_name} 未被選中，本輪跳過。]")]
            )

        return None

    return callback


# ---------------------------------------------------------------------------
# Callable instruction factory
# ---------------------------------------------------------------------------


def make_instruction(base_instruction: str, report_key_specs: list[str] | None = None):
    """Return a callable instruction that prepends analyst reports at runtime.

    Args:
        base_instruction:  The master's original system-prompt string.
        report_key_specs:  List of "key" / "key?" specs to inject from state.
                           Defaults to DEFAULT_ANALYST_KEYS if None.

    The returned callable matches ADK's InstructionProvider signature:
        (ReadonlyContext) -> str
    """
    specs = report_key_specs if report_key_specs is not None else DEFAULT_ANALYST_KEYS

    def dynamic_instruction(ctx) -> str:
        state = ctx.state
        context_block = build_reports_context(state, specs)
        if context_block:
            return (
                "【前置分析報告 — 請優先閱讀以下資料再發表你的觀點】\n\n"
                f"{context_block}\n\n"
                "---\n\n"
                f"{base_instruction}"
            )
        return base_instruction

    return dynamic_instruction


# ---------------------------------------------------------------------------
# DynamicMastersPanel
# ---------------------------------------------------------------------------

_SKIP_RE = re.compile(r"^\[[\w_]+ 未被選中，本輪跳過。\]$")
_FALLBACK_REPORT = (
    "### consolidated_masters_report\n"
    "[本輪無可用大師報告 — 所有選中大師均被跳過或未產出有效內容]\n"
    "selected_masters: []\n"
    "included_count: 0\n"
    "included_masters: []"
)


def _check_value(raw_value) -> tuple[bool, str]:
    """Return (is_substantive, reason)."""
    if raw_value is None:
        return False, "missing"
    if not isinstance(raw_value, str):
        return False, "non_string"
    if not raw_value.strip():
        return False, "empty"
    if _SKIP_RE.match(raw_value.strip()):
        return False, "skip_placeholder"
    return True, "ok"


def _build_consolidated_report(state: dict) -> str:
    """Build consolidated_masters_report by copy-pasting selected master reports."""
    selected: list[str] = list(state.get("selected_masters") or [])
    logger.info("DynamicMastersPanel: selected_masters=%s (count=%d)", selected, len(selected))

    found: list[str] = []
    parts: list[str] = []

    for master_name in selected:
        key = MASTER_OUTPUT_KEYS.get(master_name)
        if key is None:
            logger.warning("  %s -> not in MASTER_OUTPUT_KEYS, skipping", master_name)
            continue

        raw_value = state.get(key)
        substantive, reason = _check_value(raw_value)
        length = len(raw_value) if isinstance(raw_value, str) else 0

        if substantive:
            logger.debug("  %s -> key=%r len=%d substantive=True", master_name, key, length)
            parts.append(f"### {key}\n{raw_value.strip()}")
            found.append(master_name)
        else:
            log_fn = logger.warning if reason == "non_string" else logger.debug
            log_fn(
                "  %s -> key=%r exists=%s len=%d substantive=False reason=%s",
                master_name,
                key,
                raw_value is not None,
                length,
                reason,
            )

    logger.info(
        "DynamicMastersPanel: collected %d/%d report(s): %s", len(found), len(selected), found
    )

    if not parts:
        logger.warning("DynamicMastersPanel: no substantive reports, using fallback.")
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
        "### consolidated_masters_report\n"
        f"selected_masters: [{selected_str}]\n"
        f"included_count: {len(found)}\n"
        f"included_masters: [{included_str}]"
    )
    body = "\n\n---\n".join(parts)
    return f"{header}\n\n---\n{body}"


class DynamicMastersPanel(BaseAgent):
    """Runs selected masters, then writes deterministic consolidated_masters_report."""

    @override
    async def _run_async_impl(
        self, ctx: InvocationContext
    ) -> AsyncGenerator[Event, None]:
        state = ctx.session.state

        if state.get("analysis_intent") is False:
            logger.info("DynamicMastersPanel: analysis_intent=False -- skipping.")
            return

        if state.get("awaiting_master_choice"):
            logger.info("DynamicMastersPanel: awaiting_master_choice=True -- skipping.")
            return

        selected: list[str] = list(state.get("selected_masters") or [])

        if not selected:
            logger.info("DynamicMastersPanel: selected_masters empty -- nothing to run.")
            return

        registry: dict[str, BaseAgent] = {a.name: a for a in self.sub_agents}

        for master_name in selected:
            agent = registry.get(master_name)
            if agent is None:
                logger.warning(
                    "DynamicMastersPanel: %r not found in registry -- skipping.", master_name
                )
                continue
            logger.info("DynamicMastersPanel: running %r", master_name)
            async for event in agent.run_async(ctx):
                yield event

        try:
            report = _build_consolidated_report(ctx.session.state)
        except Exception:
            logger.exception(
                "DynamicMastersPanel: unexpected error building consolidated report, using fallback."
            )
            report = _FALLBACK_REPORT

        ctx.session.state["consolidated_masters_report"] = report
        logger.info(
            "DynamicMastersPanel: wrote consolidated_masters_report (%d chars).", len(report)
        )
