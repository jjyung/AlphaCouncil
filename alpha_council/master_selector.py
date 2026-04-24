"""Master selection agent — two-phase interactive flow.

Phase 1 (no master_choice provided):
    Show master menu, set awaiting_master_choice=True, halt pipeline.

Phase 2 (user replies with numbers or "random"):
    Parse selection, write selected_masters, clear awaiting_master_choice,
    allowing masters_panel and consolidator to proceed.

Session state written:
    selected_masters: list[str]       — master name strings
    awaiting_master_choice: bool      — True while waiting for user reply
"""
import logging
import random

from google.adk.agents.llm_agent import Agent
from google.genai import types

from alpha_council.utils.master_runtime import (
    ALL_MASTERS,
    MASTER_DISPLAY_NAMES,
    MASTER_PHILOSOPHIES,
)

logger = logging.getLogger(__name__)

# Menu: 1-based number → master name
MASTER_MENU: dict[int, str] = {i + 1: name for i, name in enumerate(ALL_MASTERS)}

_RECOMMENDED_GROUPS: list[tuple[str, list[int]]] = [
    ("價值穩健組", [1, 2, 3]),
    ("成長創新組", [6, 8, 9]),
    ("宏觀風險組", [7, 11, 13]),
    ("估值紀律組", [4, 5, 10]),
]

_MIN = 0
_MAX = 6

# Keywords that mean "pick for me"
_RANDOM_KEYWORDS = {"random", "隨機", "你選", "幫我選", "你幫我選", "不指定", "都可以", "隨便"}
_SKIP_KEYWORDS = {"skip", "跳過"}


def _menu_str() -> str:
    lines: list[str] = []
    for k, v in MASTER_MENU.items():
        philosophy = MASTER_PHILOSOPHIES.get(v, "")
        lines.append(f"{k}. {MASTER_DISPLAY_NAMES[v]}｜{philosophy}")
    return "\n".join(lines)


def _recommended_groups_str() -> str:
    lines: list[str] = []
    for group_name, nums in _RECOMMENDED_GROUPS:
        members = "、".join(f"{n}.{MASTER_DISPLAY_NAMES[MASTER_MENU[n]]}" for n in nums)
        lines.append(f"- {group_name}：{members}")
    return "\n".join(lines)


def _random_sample(n: int = _MIN) -> list[str]:
    names = random.sample(ALL_MASTERS, n)
    logger.info("Random master sample (%d): %s", n, names)
    return names


def _do_random(state: dict, reason: str) -> str:
    """Select random masters, write to state, clear awaiting flag."""
    names = _random_sample()
    state["selected_masters"] = names
    state["awaiting_master_choice"] = False
    display = ", ".join(MASTER_DISPLAY_NAMES[n] for n in names)
    logger.info("Master selection: %s → random %s", reason, names)
    return f"已隨機選擇 {_MIN} 位大師：{display}"


def _do_select(state: dict, unique: list[int], warnings: list[str]) -> str:
    """Commit a validated unique list of menu numbers to state."""
    names = [MASTER_MENU[n] for n in unique]
    state["selected_masters"] = names
    state["awaiting_master_choice"] = False
    display = ", ".join(MASTER_DISPLAY_NAMES[n] for n in names)
    logger.info("Master selection: user → %s", names)
    msg = f"已選擇 {len(names)} 位大師：{display}"
    if warnings:
        msg += "\n" + "\n".join(f"  ⚠ {w}" for w in warnings)
    return msg


def _do_skip(state: dict, reason: str) -> str:
    """Skip masters phase and keep only analyst outputs for this turn."""
    state["selected_masters"] = []
    state["awaiting_master_choice"] = False
    logger.info("Master selection: %s → skip masters phase", reason)
    return "已跳過大師分析，將直接以分析師報告作為本輪輸出。"


def skip_if_no_analysis_intent(callback_context) -> types.Content | None:
    """Silently stop the agent when analysis_intent is explicitly False.

    Returns Content with no parts — sets end_invocation=True (agent won't run)
    without producing any visible message in the UI.
    Returns None when flag is True or absent to preserve backward-compatibility.
    """
    if callback_context.state.get("analysis_intent") is False:
        logger.info("Skipping agent: analysis_intent=False.")
        return types.Content(parts=[])

    return None


def select_masters(choice: str, tool_context) -> str:
    """Parse user master selection and persist it to session state.

    Args:
        choice: One of —
            • Comma-separated 1-based master numbers (e.g. "1,3,5").
            • "random" (or similar keyword) to let the system pick.
            • Empty string "" when no choice was provided.

    Returns:
        Human-readable confirmation shown to the user.

    Side-effects:
        Writes ``selected_masters: list[str]`` and ``awaiting_master_choice: bool``
        to ``tool_context.state``.
    """
    state = tool_context.state
    choice = (choice or "").strip()
    awaiting = bool(state.get("awaiting_master_choice"))
    normalized = choice.lower()

    # ------------------------------------------------------------------ explicit skip
    if choice == "0" or normalized in _SKIP_KEYWORDS:
        return _do_skip(state, f"explicit skip {choice!r}")

    # ------------------------------------------------------------------ random keyword
    if normalized in _RANDOM_KEYWORDS or any(k in choice for k in _RANDOM_KEYWORDS):
        return _do_random(state, f"keyword {choice!r}")

    # ------------------------------------------------------------------ no input
    if not choice:
        if not awaiting:
            # First time with no choice: pause pipeline, show menu, wait for reply.
            # Clear any stale selected_masters from a previous analysis turn.
            state["awaiting_master_choice"] = True
            state["selected_masters"] = []
            logger.info("Master selection: no choice, showing menu (awaiting=True)")
            return (
                "【已暫停後續流程，等待您選擇投資大師】\n\n"
                f"請選擇希望分析這支股票的投資大師（{_MIN}~{_MAX} 位）：\n\n"
                f"{_menu_str()}\n\n"
                "【建議組合（按照風格分組，可直接照抄編號）】\n"
                f"{_recommended_groups_str()}\n\n"
                f"請回覆編號，以逗號分隔，例如 \"1,2,3\"。\n"
                f"若希望系統隨機選擇，請回覆「隨機」。\n"
                f"若想跳過大師分析，請回覆「跳過」或「0」。"
            )
        else:
            # User replied but still no choice → give up and random
            return _do_random(state, "second prompt with no input")

    # ------------------------------------------------------------------ parse numbers
    try:
        raw_numbers = [int(p.strip()) for p in choice.split(",") if p.strip()]
    except ValueError:
        if awaiting:
            return _do_random(state, f"parse error on awaiting reply {choice!r}")
        names = _random_sample()
        state["selected_masters"] = names
        state["awaiting_master_choice"] = False
        display = ", ".join(MASTER_DISPLAY_NAMES[n] for n in names)
        logger.warning("Master selection: parse error %r → random %s", choice, names)
        return (
            f"格式錯誤（{choice!r}），已自動隨機選擇 {_MIN} 位：{display}\n\n"
            f"正確格式範例：\"1,3,5\"\n可選清單：\n{_menu_str()}"
        )

    # ------------------------------------------------------------------ range check
    invalid = [n for n in raw_numbers if n not in MASTER_MENU]
    if invalid:
        if awaiting:
            return _do_random(state, f"out-of-range {invalid} on awaiting reply")
        names = _random_sample()
        state["selected_masters"] = names
        state["awaiting_master_choice"] = False
        display = ", ".join(MASTER_DISPLAY_NAMES[n] for n in names)
        logger.warning("Master selection: out-of-range %s → random %s", invalid, names)
        return (
            f"編號 {invalid} 超出範圍（1–{len(MASTER_MENU)}），"
            f"已自動隨機選擇 {_MIN} 位：{display}\n\n"
            f"可選清單：\n{_menu_str()}"
        )

    # ------------------------------------------------------------------ deduplicate
    seen: set[int] = set()
    unique: list[int] = [n for n in raw_numbers if not (n in seen or seen.add(n))]  # type: ignore[func-returns-value]

    # ------------------------------------------------------------------ count guard
    warnings: list[str] = []
    if len(unique) < _MIN:
        remaining = [n for n in MASTER_MENU if n not in set(unique)]
        extras = random.sample(remaining, _MIN - len(unique))
        unique.extend(extras)
        warnings.append(f"數量不足 {_MIN}，已隨機補足至 {_MIN} 位。")
        logger.warning("Master count too low, extended to %d: %s", _MIN, unique)
    elif len(unique) > _MAX:
        unique = unique[:_MAX]
        warnings.append(f"數量超過 {_MAX}，已截斷至前 {_MAX} 位。")
        logger.warning("Master count capped at %d.", _MAX)

    return _do_select(state, unique, warnings)


_NORMAL_SELECTOR_INSTRUCTION = """你是大師選擇助手。可選大師共 13 位（編號僅供解析使用）：
Warren Buffett(1), Ben Graham(2), Charlie Munger(3), Aswath Damodaran(4),
Bill Ackman(5), Cathie Wood(6), Michael Burry(7), Peter Lynch(8),
Phil Fisher(9), Mohnish Pabrai(10), Stanley Druckenmiller(11),
Rakesh Jhunjhunwala(12), Nassim Taleb(13)

【執行順序 — 不可跳過步驟 1】
步驟 1：立即呼叫 select_masters(choice=<字串>)，choice 規則如下：
  - 使用者訊息含逗號分隔編號（如 "1,3,5" 或 "master_choice=1,3,5"）→ 傳入該編號字串
  - 使用者訊息為「跳過」或 "0" → 傳入 "0"
  - 含「隨機」「你選」「幫我選」「不指定」等字 → 傳入 "random"
  - 未明確指定 → 傳入 ""
步驟 2：將工具回傳文字原樣輸出，不要自行列出大師清單或修改格式。

限制：只呼叫一次 select_masters。
"""

_AWAITING_SELECTOR_INSTRUCTION = """你是大師選擇助手。使用者正在回覆之前顯示的大師選擇清單。

任務：
1. 從使用者訊息中提取大師選擇：
   - 若是數字列表（如 "1,3,7"），提取為 choice="1,3,7"
   - 若是「跳過」或 "0"，提取為 choice="0"
   - 若包含「隨機」「你選」「幫我選」「不指定」等，提取為 choice="random"
   - 若無法辨識，傳入 choice=""（系統將隨機選擇）
2. 呼叫 select_masters(choice=<字串>) 完成選擇。
3. 將工具回傳的說明文字原樣回報給使用者。

限制：只呼叫一次 select_masters，不要自行調整或覆蓋結果。
"""


def _master_selector_instruction(ctx) -> str:
    if ctx.state.get("awaiting_master_choice"):
        return _AWAITING_SELECTOR_INSTRUCTION
    return _NORMAL_SELECTOR_INSTRUCTION


master_selector_agent = Agent(
    model="gemini-2.5-flash",
    name="master_selector",
    description="解析使用者的大師選擇（兩階段互動：無選擇時先展示選單，再等待回覆）。",
    tools=[select_masters],
    before_agent_callback=skip_if_no_analysis_intent,
    instruction=_master_selector_instruction,
)
