import os

from google.adk.agents.llm_agent import Agent
from google.adk.agents.sequential_agent import SequentialAgent
from google.adk.models.lite_llm import LiteLlm

from alpha_council.analysts import fundamental_analyst, news_analyst, technical_analyst
from alpha_council.llm_config import get_default_agent_model
from alpha_council.utils.master_runtime import build_reports_context

_ANALYST_KEYS = [
    "technical_report?",
    "news_report?",
    "fundamentals_report?",
]


def _build_ollama_lite_model():
    model = get_default_agent_model()
    if isinstance(model, LiteLlm):
        model._additional_args.setdefault(
            "timeout",
            float(os.getenv("ALPHACOUNCIL_OLLAMA_LITE_MODEL_TIMEOUT_SECONDS", "1800")),
        )
    return model


def _ollama_lite_instruction(ctx) -> str:
    reports = build_reports_context(ctx.state, _ANALYST_KEYS)
    base = (
        "你是 AlphaCouncil 的 Ollama 精簡版投資總結代理。\n\n"
        "請只根據上方三份分析師報告（技術、新聞、基本面）做結論，不要引用不存在的資料。\n"
        "若任一報告缺失，必須在風險提示中明確標示。\n\n"
        "禁止輸出你的思考過程、分析步驟、自我檢查、草稿或 chain-of-thought。"
        "直接輸出最終答案，不要在答案前加入任何前言。\n\n"
        "輸出格式固定如下：\n"
        "# Ollama Lite Decision\n\n"
        "1. 標的摘要：一句話說明公司與目前情境。\n"
        "2. 技術面重點：1-2 點。\n"
        "3. 新聞面重點：1-2 點。\n"
        "4. 基本面重點：1-2 點。\n"
        "5. 最終建議：買入 / 持有 / 賣出（三選一）。\n"
        "6. 風險提示：列出 2-3 點。\n"
        "7. 信心等級：高 / 中 / 低。\n"
    )
    if reports:
        return f"{reports}\n\n---\n\n{base}"
    return base


ollama_lite_conclusion = Agent(
    model=_build_ollama_lite_model(),
    name="ollama_lite_conclusion",
    description="精簡版結論代理：整合技術、新聞、基本面三份報告並輸出最終建議。",
    instruction=_ollama_lite_instruction,
    output_key="ollama_lite_decision",
)

root_agent = SequentialAgent(
    name="AlphaCouncilOllamaLitePipeline",
    sub_agents=[
        technical_analyst,
        news_analyst,
        fundamental_analyst,
        ollama_lite_conclusion,
    ],
    description="Ollama 精簡版流程：技術 -> 新聞 -> 基本面 -> 最終結論。",
)
