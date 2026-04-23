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

MASTER_DISPLAY_NAMES: dict[str, str] = {
    "warren_buffett": "Warren Buffett",
    "ben_graham": "Ben Graham",
    "charlie_munger": "Charlie Munger",
    "aswath_damodaran": "Aswath Damodaran",
    "bill_ackman": "Bill Ackman",
    "cathie_wood": "Cathie Wood",
    "michael_burry": "Michael Burry",
    "peter_lynch": "Peter Lynch",
    "phil_fisher": "Phil Fisher",
    "mohnish_pabrai": "Mohnish Pabrai",
    "stanley_druckenmiller": "Stanley Druckenmiller",
    "rakesh_jhunjhunwala": "Rakesh Jhunjhunwala",
    "nassim_taleb": "Nassim Taleb",
}

MASTER_PHILOSOPHIES: dict[str, str] = {
    "warren_buffett": "護城河 + 長期複利，重視可預測現金流與管理層紀律。",
    "ben_graham": "深度價值與安全邊際，偏好低估且下檔受保護標的。",
    "charlie_munger": "高品質企業合理價，強調心智模型與長期競爭優勢。",
    "aswath_damodaran": "估值導向，先釐清敘事再回到現金流與折現假設。",
    "bill_ackman": "高信念集中投資，催化劑與管理改善是關鍵。",
    "cathie_wood": "顛覆式創新成長，押注長期技術曲線與平台效應。",
    "michael_burry": "逆向與錯價修正，偏好不對稱風險報酬機會。",
    "peter_lynch": "由生活洞察找成長，重視業務可理解與基本面驗證。",
    "phil_fisher": "Scuttlebutt 深度研究，聚焦成長品質與管理層執行力。",
    "mohnish_pabrai": "低風險高不對稱，複製優秀策略並保持耐心。",
    "stanley_druckenmiller": "宏觀趨勢 + 風險動態調整，重視時機與部位管理。",
    "rakesh_jhunjhunwala": "成長與價值並重，敢於集中於高 conviction 標的。",
    "nassim_taleb": "反脆弱與尾部風險，避免脆弱曝險並追求非對稱性。",
}

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


def make_instruction(
    master_name: str,
    base_instruction: str,
    report_key_specs: list[str] | None = None,
):
    """Return a callable instruction that prepends analyst reports at runtime.

    Args:
        master_name:       The unique identifier of the master (used for header).
        base_instruction:  The master's original system-prompt string.
        report_key_specs:  List of "key" / "key?" specs to inject from state.
                           Defaults to DEFAULT_ANALYST_KEYS if None.

    The returned callable matches ADK's InstructionProvider signature:
        (ReadonlyContext) -> str
    """
    specs = report_key_specs if report_key_specs is not None else DEFAULT_ANALYST_KEYS
    display_name = MASTER_DISPLAY_NAMES.get(master_name, master_name)

    def dynamic_instruction(ctx) -> str:
        state = ctx.state
        context_block = build_reports_context(state, specs)

        header_instruction = (
            f"【回應格式規範 — 極重要】\n"
            f"你的回應必須以 Markdown 一級標題開始，內容為你的名字：\n"
            f"# {display_name}\n\n"
        )

        if context_block:
            return (
                f"{header_instruction}"
                "【前置分析報告 — 請優先閱讀以下資料再發表你的觀點】\n\n"
                f"{context_block}\n\n"
                "---\n\n"
                f"{base_instruction}"
            )
        return f"{header_instruction}{base_instruction}"

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
