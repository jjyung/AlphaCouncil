import re
from collections.abc import Iterable

from google.genai import types


_TW_PATTERN = re.compile(r"^\d{4,6}(\s*(tw|TW))?$")
_US_PATTERN = re.compile(r"^[A-Za-z]{1,5}\s+(US|us)$")
_TW_SEARCH_PATTERN = re.compile(r"(?<!\d)\d{4,6}(\s*(tw|TW))?(?!\d)")
_US_SEARCH_PATTERN = re.compile(r"\b[A-Za-z]{1,5}\s+(US|us)\b")


def _extract_user_text(raw_input) -> str:
    """Best-effort extraction for ADK callback input payloads."""
    if raw_input is None:
        return ""
    if isinstance(raw_input, str):
        return raw_input.strip()
    if isinstance(raw_input, types.Content):
        texts: list[str] = []
        for part in raw_input.parts or []:
            text = getattr(part, "text", None)
            if text:
                texts.append(str(text).strip())
        return " ".join(t for t in texts if t).strip()
    if isinstance(raw_input, dict):
        text = raw_input.get("text")
        if isinstance(text, str):
            return text.strip()
        parts = raw_input.get("parts")
        if parts is not None:
            parsed_parts = _extract_user_text(parts)
            if parsed_parts:
                return parsed_parts
        content = raw_input.get("content")
        if content is not None:
            parsed_content = _extract_user_text(content)
            if parsed_content:
                return parsed_content
        message = raw_input.get("message")
        if message is not None:
            parsed_message = _extract_user_text(message)
            if parsed_message:
                return parsed_message
    if isinstance(raw_input, Iterable) and not isinstance(raw_input, (bytes, bytearray)):
        texts: list[str] = []
        for item in raw_input:
            parsed = _extract_user_text(item)
            if parsed:
                texts.append(parsed)
        # History payloads often contain multiple messages; use the latest one.
        if texts:
            return texts[-1].strip()
        return ""
    return str(raw_input).strip()


def stock_code_guard_callback(callback_context) -> types.Content | None:
    """
    Guardrail: 僅允許台股/美股正確股票代號格式。
    台股：4~6 碼數字（如 2330、00878），可選空格+tw/TW（如 2330 tw）。
    美股：1–5 碼英文+空格+US/us（如 AAPL US、TSLA us）。
    """
    state = callback_context.state

    # 第二輪正在等待大師選擇時，允許輸入編號（如 1,3,7）直接通過。
    if state.get("awaiting_master_choice"):
        return None

    # ADK CallbackContext uses `user_content` (not `input`).
    raw_user_content = getattr(callback_context, "user_content", None)
    if raw_user_content is None:
        raw_user_content = getattr(callback_context, "input", None)
    user_input = _extract_user_text(raw_user_content)
    if (
        _TW_PATTERN.match(user_input)
        or _US_PATTERN.match(user_input)
        or _TW_SEARCH_PATTERN.search(user_input)
        or _US_SEARCH_PATTERN.search(user_input)
    ):
        return None

    msg = (
        "請輸入正確的股票代號格式：\n"
        "台股：4~6 碼數字（如 2330、00878、2330 tw）\n"
        "美股：英文代號+空格+US（如 AAPL US）"
    )
    return types.Content(parts=[types.Part(text=msg)])
