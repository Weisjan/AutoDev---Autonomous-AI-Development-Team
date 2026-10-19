import pytest
from pydantic import ValidationError

from autodev.config import AgentConfig, AutoDevConfig, load_config_from_env
from autodev.model_policy import ModelPolicy, RoleOverrides, resolve_config, resolve_policy


@pytest.mark.parametrize(
    "preset, architect, developer, reviewer",
    [
        ("fast", ("gpt-6.1-sol", "medium"), ("gpt-6.1-sol", "low"), ("gpt-6.1-sol", "medium")),
        ("balanced", ("gpt-6-astra", "high"), ("gpt-6.1-sol", "high"), ("gpt-6-astra", "high")),
        (
            "maximum_quality",
            ("gpt-6-astra", "xhigh"),
            ("gpt-6.1-sol", "xhigh"),
            ("gpt-6-astra", "xhigh"),
        ),
    ],
)
def test_presets_are_explicit_and_do_not_expand_limits(preset, architect, developer, reviewer):
    config = AutoDevConfig(model_policy=ModelPolicy(preset=preset))
    result = resolve_config(config)
    for role, expected in zip(
        ("architect", "developer", "reviewer"), (architect, developer, reviewer), strict=True
    ):
        actual = result.for_role(role)
        assert (actual.model, actual.reasoning_effort) == expected
    assert config.parallel == AutoDevConfig().parallel
    assert config.codex_cli == AutoDevConfig().codex_cli


def test_legacy_models_and_architect_inheritance_are_preserved():
    config = AutoDevConfig(agents=AgentConfig(developer_model="old-model", reviewer_model="review"))
    policy = resolve_config(config)
    assert policy.architect.model == policy.developer.model == "old-model"
    assert policy.reviewer.model == "review"
    assert policy.preset is None and policy.developer.reasoning_effort is None
    assert resolve_config(AutoDevConfig()).architect.model is None


def test_override_precedence_and_frozen_snapshot():
    request = ModelPolicy(overrides={"developer": {"reasoning_effort": "xhigh"}})
    operator = RoleOverrides(developer={"model": "gpt-6-astra", "reasoning_effort": "low"})
    result = resolve_policy(request, operator=operator)
    assert result.developer.model == "gpt-6-astra"
    assert result.developer.model_source == "operator"
    assert result.developer.reasoning_effort == "xhigh"
    assert result.developer.effort_source == "override"
    assert resolve_policy(result) is result
    with pytest.raises(ValidationError):
        result.developer.model = "changed"


@pytest.mark.parametrize(
    "override",
    [
        {"model": "unknown"},
        {"model": "--add-dir"},
        {"reasoning_effort": "extra-high"},
        {"reasoning_effort": "max"},
        {"reasoning_effort": "ultra"},
        {"reasoning_effort": 'high"\nsandbox_mode="danger-full-access'},
        {"executable": "bad"},
        {},
    ],
)
def test_invalid_policy_is_rejected_without_substitution(override):
    with pytest.raises(ValidationError):
        ModelPolicy(overrides={"architect": override})


def test_new_policy_is_codex_only():
    with pytest.raises(ValidationError, match="ChatGPT"):
        AutoDevConfig(provider="openai_api", model_policy=ModelPolicy())


def test_environment_legacy_and_explicit_opt_in(monkeypatch):
    monkeypatch.setattr("autodev.config.load_dotenv", lambda: None)
    for name in (
        "MODEL_PRESET",
        "ARCHITECT_MODEL",
        "ARCHITECT_REASONING_EFFORT",
        "DEVELOPER_REASONING_EFFORT",
        "REVIEWER_REASONING_EFFORT",
        "PROVIDER",
    ):
        monkeypatch.delenv(f"AUTODEV_{name}", raising=False)
    monkeypatch.setenv("AUTODEV_DEVELOPER_MODEL", "gpt-6.1-sol")
    config = load_config_from_env()
    assert config.model_policy is None
    monkeypatch.setenv("AUTODEV_DEVELOPER_MODEL", "legacy-arbitrary-model")
    legacy = load_config_from_env()
    assert legacy.model_policy is None
    assert resolve_config(legacy).architect.model == "legacy-arbitrary-model"
    monkeypatch.setenv("AUTODEV_DEVELOPER_MODEL", "gpt-6.1-sol")
    monkeypatch.setenv("AUTODEV_MODEL_PRESET", "fast")
    monkeypatch.setenv("AUTODEV_ARCHITECT_REASONING_EFFORT", "high")
    policy = resolve_config(load_config_from_env())
    assert policy.architect.reasoning_effort == "high"
    assert policy.architect.effort_source == "operator"
