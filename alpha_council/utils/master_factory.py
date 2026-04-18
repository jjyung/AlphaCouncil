"""Utilities for building conditional master agents with session-state injection.

Each master agent needs two runtime behaviours:
1. Skip itself if it was not selected by the user (before_agent_callback).
2. Inject previous analyst reports into its instruction (callable instruction).
"""
import logging

from google.genai import types

logger = logging.getLogger(__name__)

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

# Maps master name → session-state key where their report is stored.
MASTER_OUTPUT_KEYS: dict[str, str] = {name: f"{name}_report" for name in ALL_MASTERS}

# Default analyst report keys each master should try to read.
# "news_report" is required; append "?" to make a key optional (e.g. "technical_report?").
DEFAULT_ANALYST_KEYS: list[str] = [
    "news_report",
]


# ---------------------------------------------------------------------------
# Report context builder
# ---------------------------------------------------------------------------


def build_reports_context(state: dict, key_specs: list[str]) -> str:
    """Build a context block from session state based on key specifications.

    key_specs format:
        "key"   → required: missing emits a warning and injects a placeholder.
        "key?"  → optional: missing is silently skipped with a note.

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
                # Do not inject anything for absent optional keys.
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
    """Return a before_agent_callback that skips *master_name* if not selected.

    If 'selected_masters' is absent from state (no selection step ran), the
    master always proceeds — backwards-compatible with direct pipeline runs.
    """

    def callback(callback_context) -> types.Content | None:
        selected = callback_context.state.get("selected_masters")
        if selected is not None and master_name not in selected:
            logger.info(
                "Master %r not in selected_masters %s — skipping.", master_name, selected
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
