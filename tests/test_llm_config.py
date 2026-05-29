from google.adk.models.lite_llm import LiteLlm

from alpha_council import llm_config


def test_gemini_defaults(monkeypatch) -> None:
    monkeypatch.delenv("ALPHACOUNCIL_MODEL_PROVIDER", raising=False)
    monkeypatch.delenv("ALPHACOUNCIL_MODEL", raising=False)

    assert llm_config.get_model_provider() == "gemini"
    assert llm_config.get_model_name() == llm_config.DEFAULT_GEMINI_MODEL


def test_ollama_builds_litellm_model(monkeypatch) -> None:
    monkeypatch.setenv("ALPHACOUNCIL_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("ALPHACOUNCIL_MODEL", "qwen3:8b")
    monkeypatch.setenv("OLLAMA_API_BASE", "https://ollama.example.com")
    monkeypatch.setenv("OLLAMA_API_KEY", "secret-token")

    model = llm_config.build_agent_model()

    assert isinstance(model, LiteLlm)
    assert getattr(model, "model", None) == "ollama_chat/qwen3:8b"
    assert model._additional_args["api_base"] == "https://ollama.example.com"
    assert model._additional_args["api_key"] == "secret-token"


def test_ollama_auth_token_alias_is_supported(monkeypatch) -> None:
    monkeypatch.setenv("ALPHACOUNCIL_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_API_BASE", "https://ollama.example.com")
    monkeypatch.delenv("OLLAMA_API_KEY", raising=False)
    monkeypatch.setenv("OLLAMA_AUTH_TOKEN", "alias-token")

    model = llm_config.build_agent_model()

    assert model._additional_args["api_key"] == "alias-token"


def test_ollama_cloudflare_access_headers_are_supported(monkeypatch) -> None:
    monkeypatch.setenv("ALPHACOUNCIL_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_API_BASE", "https://ollama.example.com")
    monkeypatch.setenv("OLLAMA_CF_ACCESS_CLIENT_ID", "client-id")
    monkeypatch.setenv("OLLAMA_CF_ACCESS_CLIENT_SECRET", "client-secret")
    monkeypatch.delenv("OLLAMA_CF_AUTHORIZATION", raising=False)

    model = llm_config.build_agent_model()

    assert model._additional_args["extra_headers"] == {
        "CF-Access-Client-Id": "client-id",
        "CF-Access-Client-Secret": "client-secret",
    }


def test_ollama_cloudflare_authorization_cookie_is_supported(monkeypatch) -> None:
    monkeypatch.setenv("ALPHACOUNCIL_MODEL_PROVIDER", "ollama")
    monkeypatch.setenv("OLLAMA_API_BASE", "https://ollama.example.com")
    monkeypatch.delenv("OLLAMA_CF_ACCESS_CLIENT_ID", raising=False)
    monkeypatch.delenv("OLLAMA_CF_ACCESS_CLIENT_SECRET", raising=False)
    monkeypatch.setenv("OLLAMA_CF_AUTHORIZATION", "cookie-token")

    model = llm_config.build_agent_model()

    assert model._additional_args["extra_headers"] == {
        "Cookie": "CF_Authorization=cookie-token"
    }


def test_invalid_provider_returns_auth_error(monkeypatch) -> None:
    monkeypatch.setenv("ALPHACOUNCIL_MODEL_PROVIDER", "bad-provider")

    assert "ALPHACOUNCIL_MODEL_PROVIDER" in (llm_config.get_model_auth_error() or "")


def test_ollama_requires_api_base(monkeypatch) -> None:
    monkeypatch.setenv("ALPHACOUNCIL_MODEL_PROVIDER", "ollama")
    monkeypatch.delenv("OLLAMA_API_BASE", raising=False)

    assert "OLLAMA_API_BASE" in (llm_config.get_model_auth_error() or "")


def test_expand_path_supports_user_and_env(monkeypatch) -> None:
    monkeypatch.setenv("ALPHA_TMP", "/tmp/alpha-council")

    expanded = llm_config.expand_path("$ALPHA_TMP/reports")

    assert expanded == "/tmp/alpha-council/reports"
