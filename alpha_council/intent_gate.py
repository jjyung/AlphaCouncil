"""Lightweight intent gate — first agent in the pipeline.

Uses a single small LLM call to decide whether the user's message contains
a stock-analysis request.  The result is written to state immediately via
after_agent_callback so every downstream agent can check it.

State written:
    analysis_intent_raw: str  — raw LLM output
    analysis_intent: bool     — True = proceed with analysis, False = chitchat

Exported helpers:
    skip_if_no_analysis_intent      — skip when analysis_intent is False
    skip_if_awaiting_master_choice  — skip when awaiting_master_choice is True
"""
import logging

from google.adk.agents.llm_agent import Agent
from google.genai import types

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared skip helpers (imported by other modules)
# ---------------------------------------------------------------------------


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


def skip_if_awaiting_master_choice(callback_context) -> types.Content | None:
    """Silently stop the agent when awaiting_master_choice is True.

    Returns Content with no parts — sets end_invocation=True without producing
    any visible message in the UI.
    Returns None when absent or False so downstream phases proceed normally.
    """
    if callback_context.state.get("awaiting_master_choice"):
        logger.info("Skipping agent: awaiting_master_choice=True.")
        return types.Content(parts=[])
    return None


# ---------------------------------------------------------------------------
# Intent gate callbacks
# ---------------------------------------------------------------------------


def _after_intent_gate(callback_context) -> types.Content | None:
    """Parse the LLM's binary output and set analysis_intent bool in state."""
    state = callback_context.state
    raw: str = state.get("analysis_intent_raw", "").strip()
    has_intent = raw.upper().startswith("ANALYSIS")
    state["analysis_intent"] = has_intent
    logger.info(
        "Intent gate: raw=%r → analysis_intent=%s", raw[:60], has_intent
    )
    return None


_NORMAL_INSTRUCTION = """你是「投資分析意圖偵測器」，只負責判斷使用者最後一條訊息是否為股票投資分析請求。

【分析意圖判斷標準 — 符合任一條 → 輸出 ANALYSIS】
- 含有股票代號（4~6位數字，如 2330、00878；或英文代號 AAPL、TSMC）
- 含有公司名稱（如台積電、鴻海、聯發科、蘋果、Google）
- 含有投資相關關鍵字：分析、研究、看法、買進、賣出、持有、投資、大師、新聞、技術面、基本面、籌碼面、股價

【輸出規則（嚴格二選一）】
情況 A — 有分析意圖：
  只輸出以下一行（第一個字必須是 ANALYSIS，後面可加一句說明）：
  ANALYSIS

情況 B — 無分析意圖（閒聊、問候、測試、其他話題）：
  輸出一段簡短友善的中文回應，說明使用者可以提供股票代號讓你分析。
  範例：「你好！我是 AlphaCouncil 投資分析助手。請提供你想了解的股票代號（例如「請分析 2330 台積電」），我會為你召集大師團隊進行深度分析。」

【禁止】不可輸出任何股票分析內容、不可推測股價、只做意圖分類。
"""

_AWAITING_INSTRUCTION = """你是「投資分析意圖偵測器」。

【特殊情況】系統目前正在等待使用者回覆大師選擇。使用者的回覆不論內容為何，
都應視為延續本輪分析流程。

【輸出規則】只輸出以下一行，不得有其他文字：
ANALYSIS
"""


def _intent_gate_instruction(ctx) -> str:
    if ctx.state.get("awaiting_master_choice"):
        return _AWAITING_INSTRUCTION
    return _NORMAL_INSTRUCTION


# ---------------------------------------------------------------------------
# Agent definition
# ---------------------------------------------------------------------------

intent_gate = Agent(
    model="gemini-2.5-flash",
    name="intent_gate",
    description="意圖偵測閘：判斷是否為股票投資分析請求；閒聊則友善回覆並阻止後續流程。",
    output_key="analysis_intent_raw",
    after_agent_callback=_after_intent_gate,
    instruction=_intent_gate_instruction,
)
