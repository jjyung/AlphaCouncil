from __future__ import annotations

import os
from typing import Literal

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"
DEFAULT_OLLAMA_MODEL = "gemma3:latest"
DEFAULT_OLLAMA_API_BASE = "http://localhost:11434"

ModelProvider = Literal["gemini", "ollama"]


def expand_path(value: str) -> str:
    return os.path.expandvars(os.path.expanduser(value.strip()))


def get_model_provider() -> ModelProvider:
    provider = (os.getenv("ALPHACOUNCIL_MODEL_PROVIDER") or "gemini").strip().lower()
    if provider not in {"gemini", "ollama"}:
        raise ValueError(
            "ALPHACOUNCIL_MODEL_PROVIDER must be one of: gemini, ollama."
        )
    return provider  # type: ignore[return-value]


def get_model_name(provider: ModelProvider | None = None) -> str:
    provider = provider or get_model_provider()
    model = (os.getenv("ALPHACOUNCIL_MODEL") or "").strip()
    if model:
        return model
    if provider == "ollama":
        return DEFAULT_OLLAMA_MODEL
    return DEFAULT_GEMINI_MODEL


def build_agent_model():
    provider = get_model_provider()
    model_name = get_model_name(provider)
    if provider == "gemini":
        return model_name

    from google.adk.models.lite_llm import LiteLlm

    api_base = (os.getenv("OLLAMA_API_BASE") or DEFAULT_OLLAMA_API_BASE).strip()
    api_key = (
        os.getenv("OLLAMA_API_KEY")
        or os.getenv("OLLAMA_AUTH_TOKEN")
        or ""
    ).strip()
    cf_access_client_id = (os.getenv("OLLAMA_CF_ACCESS_CLIENT_ID") or "").strip()
    cf_access_client_secret = (os.getenv("OLLAMA_CF_ACCESS_CLIENT_SECRET") or "").strip()
    cf_authorization = (os.getenv("OLLAMA_CF_AUTHORIZATION") or "").strip()

    if model_name.startswith("ollama_chat/"):
        resolved = model_name
    elif model_name.startswith("ollama/"):
        resolved = model_name.replace("ollama/", "ollama_chat/", 1)
    else:
        resolved = f"ollama_chat/{model_name}"

    kwargs = {"model": resolved, "api_base": api_base}
    if api_key:
        kwargs["api_key"] = api_key
    extra_headers = {
        key: value
        for key, value in {
            "CF-Access-Client-Id": cf_access_client_id,
            "CF-Access-Client-Secret": cf_access_client_secret,
            "Cookie": f"CF_Authorization={cf_authorization}" if cf_authorization else "",
        }.items()
        if value
    }
    if extra_headers:
        kwargs["extra_headers"] = extra_headers
    return LiteLlm(**kwargs)


def get_model_auth_error() -> str | None:
    try:
        provider = get_model_provider()
    except ValueError as exc:
        return str(exc)

    if provider == "gemini":
        api_key = (os.getenv("GOOGLE_API_KEY") or "").strip()
        use_vertex = (os.getenv("GOOGLE_GENAI_USE_VERTEXAI") or "").strip().lower()
        if api_key or use_vertex in {"1", "true", "yes", "y", "on"}:
            return None
        return (
            "missing model auth for gemini provider: set GOOGLE_API_KEY, or set "
            "GOOGLE_GENAI_USE_VERTEXAI=true with proper GCP auth."
        )

    api_base = (os.getenv("OLLAMA_API_BASE") or "").strip()
    if not api_base:
        return (
            "missing model config for ollama provider: set OLLAMA_API_BASE "
            f"(for example {DEFAULT_OLLAMA_API_BASE})."
        )
    return None



def get_default_agent_model():
    return build_agent_model()
