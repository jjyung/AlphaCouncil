"""DynamicMastersPanel — sequential panel running only selected masters.

Why sequential (not ParallelAgent):
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
from typing_extensions import override

from alpha_council.utils.master_factory import MASTER_OUTPUT_KEYS

logger = logging.getLogger(__name__)

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
        selected: list[str] = list(ctx.session.state.get("selected_masters") or [])

        if not selected:
            logger.info("DynamicMastersPanel: selected_masters empty — nothing to run.")
            return

        registry: dict[str, BaseAgent] = {a.name: a for a in self.sub_agents}

        for master_name in selected:
            agent = registry.get(master_name)
            if agent is None:
                logger.warning("DynamicMastersPanel: %r not found in registry — skipping.", master_name)
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
