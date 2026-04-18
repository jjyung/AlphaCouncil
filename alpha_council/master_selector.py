"""Master selection agent (Req 1).

Allows users to choose 3–7 investment masters before the masters_panel runs.
If the user provides no valid selection, three masters are chosen at random.

Session state written:
    selected_masters: list[str]  — master name strings, e.g. ["warren_buffett", "ben_graham"]
"""
import logging
import random

from google.adk.agents.llm_agent import Agent

from alpha_council.utils.master_factory import ALL_MASTERS

logger = logging.getLogger(__name__)

# Menu: 1-based number → master name
MASTER_MENU: dict[int, str] = {i + 1: name for i, name in enumerate(ALL_MASTERS)}

_DISPLAY_NAMES: dict[str, str] = {
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

_MIN = 3
_MAX = 7


def _menu_str() -> str:
    return "\n".join(f"  {k}. {_DISPLAY_NAMES[v]}" for k, v in MASTER_MENU.items())


def _random_sample(n: int = _MIN) -> list[str]:
    names = random.sample(ALL_MASTERS, n)
    logger.info("Random master sample (%d): %s", n, names)
    return names


def select_masters(choice: str, tool_context) -> str:
    """Parse user master selection and persist it to session state.

    Args:
        choice: Comma-separated 1-based master numbers (e.g. "1,3,5").
                Pass an empty string to trigger random selection of 3 masters.

    Returns:
        Human-readable confirmation that is shown to the user.

    Side-effect:
        Writes ``selected_masters: list[str]`` to ``tool_context.state``.
    """
    state = tool_context.state
    choice = (choice or "").strip()

    # ------------------------------------------------------------------ no input
    if not choice:
        names = _random_sample()
        state["selected_masters"] = names
        display = ", ".join(_DISPLAY_NAMES[n] for n in names)
        logger.info("Master selection: no input → random %s", names)
        return (
            f"未指定大師，已隨機選擇 {_MIN} 位：{display}\n\n"
            f"下次可用逗號分隔編號指定（如 \"1,3,5\"）。\n\n可選清單：\n{_menu_str()}"
        )

    # ------------------------------------------------------------------ parse
    try:
        raw_numbers = [int(p.strip()) for p in choice.split(",") if p.strip()]
    except ValueError:
        names = _random_sample()
        state["selected_masters"] = names
        display = ", ".join(_DISPLAY_NAMES[n] for n in names)
        logger.warning("Master selection: parse error %r → random %s", choice, names)
        return (
            f"格式錯誤（{choice!r}），已自動隨機選擇 {_MIN} 位：{display}\n\n"
            f"正確格式範例：\"1,3,5\"\n可選清單：\n{_menu_str()}"
        )

    # ------------------------------------------------------------------ range check
    invalid = [n for n in raw_numbers if n not in MASTER_MENU]
    if invalid:
        names = _random_sample()
        state["selected_masters"] = names
        display = ", ".join(_DISPLAY_NAMES[n] for n in names)
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

    names = [MASTER_MENU[n] for n in unique]
    state["selected_masters"] = names
    display = ", ".join(_DISPLAY_NAMES[n] for n in names)
    logger.info("Master selection: user → %s", names)

    msg = f"已選擇 {len(names)} 位大師：{display}"
    if warnings:
        msg += "\n" + "\n".join(f"  ⚠ {w}" for w in warnings)
    return msg


master_selector_agent = Agent(
    model="gemini-2.5-flash",
    name="master_selector",
    description="解析使用者的大師選擇意圖（3–7 位，無輸入則隨機 3 位），寫入 selected_masters 至 session state。",
    tools=[select_masters],
    instruction="""你是大師選擇助手。

可選大師清單（共 13 位）：
  1. Warren Buffett       2. Ben Graham           3. Charlie Munger
  4. Aswath Damodaran     5. Bill Ackman          6. Cathie Wood
  7. Michael Burry        8. Peter Lynch          9. Phil Fisher
 10. Mohnish Pabrai      11. Stanley Druckenmiller
 12. Rakesh Jhunjhunwala 13. Nassim Taleb

任務：
1. 從使用者訊息中提取「master_choice」欄位（逗號分隔的編號，如 "1,3,5"）。
   - 若使用者未明確指定大師，傳入空字串 ""。
2. 呼叫 select_masters(choice=<字串>) 完成選擇。
3. 將工具回傳的說明文字原樣回報給使用者。

限制：只呼叫一次 select_masters，不要自行調整或覆蓋結果。
""",
)
