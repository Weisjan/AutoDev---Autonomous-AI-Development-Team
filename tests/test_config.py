import pytest
from pydantic import ValidationError

from autodev.config import AgentConfig, AutoDevConfig, CodexCLIConfig, load_config_from_env


def test_max_iterations_is_capped_at_three() -> None:
    with pytest.raises(ValidationError):
        AgentConfig(max_iterations=4)


def test_provider_defaults_to_codex_cli_without_api_key(monkeypatch):
    monkeypatch.setattr("autodev.config.load_dotenv", lambda: None)
    monkeypatch.delenv("AUTODEV_PROVIDER", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    assert load_config_from_env().provider == "codex_cli"


def test_provider_and_codex_settings_from_env(monkeypatch):
    monkeypatch.setattr("autodev.config.load_dotenv", lambda: None)
    monkeypatch.setenv("AUTODEV_PROVIDER", "openai_api")
    monkeypatch.setenv("AUTODEV_CODEX_TIMEOUT_SECONDS", "42")
    monkeypatch.setenv("AUTODEV_CODEX_EXECUTABLE", "C:/tools/codex.exe")
    monkeypatch.setenv("AUTODEV_CODEX_MAX_OUTPUT_BYTES", "5000")
    config = load_config_from_env()
    assert config.provider == "openai_api"
    assert config.codex_cli.timeout_seconds == 42
    assert config.codex_cli.executable == "C:/tools/codex.exe"
    assert config.codex_cli.max_output_bytes == 5000


def test_unknown_provider_is_rejected():
    with pytest.raises(ValidationError):
        AutoDevConfig(provider="unknown")


@pytest.mark.parametrize("field", ["timeout_seconds", "max_output_bytes"])
def test_codex_limits_must_be_positive(field):
    with pytest.raises(ValidationError):
        CodexCLIConfig(**{field: 0})
