import importlib.metadata
import importlib.util
import re
import runpy
import tomllib
from pathlib import Path

import pytest
from packaging.requirements import Requirement

ROOT = Path(__file__).resolve().parents[1]


def environment_checker(monkeypatch, missing=None):
    namespace = runpy.run_path(str(ROOT / "docker/sandbox/check_environment.py"))
    declarations = [
        "pydantic>=2.7",
        "python-dotenv>=1",
        "pytest>=8; extra == 'dev'",
        "ruff>=0.6; extra == 'dev'",
        "openai-agents>=0.1; extra == 'openai_api'",
    ]
    versions = {"pydantic": "2.14.1", "python-dotenv": "1.2.4", "pytest": "9.1.1", "ruff": "0.17.0"}

    def version(name):
        assert name != "openai-agents"  # Paid backend never included in the sandbox.
        if name == missing or name not in versions:
            raise importlib.metadata.PackageNotFoundError(name)
        return versions[name]

    monkeypatch.setattr(importlib.metadata, "requires", lambda _: declarations)
    monkeypatch.setattr(importlib.metadata, "version", version)
    monkeypatch.setattr(importlib.util, "find_spec", lambda _: object())
    return namespace["validate_environment"]


@pytest.mark.parametrize("dependency", ["pydantic", "python-dotenv", "pytest", "ruff"])
def test_image_preflight_detects_missing_dependencies(tmp_path, monkeypatch, dependency):
    validate = environment_checker(monkeypatch, dependency)
    result = validate(tmp_path / "no-manifest.toml")
    assert result["status"] == "infrastructure_failure"
    assert any(dependency in issue for issue in result["issues"])


def test_image_preflight_validates_integrated_project_dependencies(tmp_path, monkeypatch):
    validate = environment_checker(monkeypatch)
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname="example"\ndependencies=["numpy>=2"]\n')
    result = validate(project)
    assert result["issues"] == ["numpy: distribution is not installed"]


def test_image_preflight_rejects_incompatible_installed_version(tmp_path, monkeypatch):
    validate = environment_checker(monkeypatch)
    project = tmp_path / "pyproject.toml"
    project.write_text('[project]\nname="example"\ndependencies=["pydantic>=3"]\n')
    result = validate(project)
    assert any("does not satisfy" in issue for issue in result["issues"])


def test_image_preflight_accepts_healthy_image_and_dev_dependencies(tmp_path, monkeypatch):
    validate = environment_checker(monkeypatch)
    result = validate(tmp_path / "no-manifest.toml")
    assert result["status"] == "ready"
    assert set(result["installed"]) == {"pydantic", "python-dotenv", "pytest", "ruff"}


def test_dependency_lock_covers_project_runtime_dev_and_build_requirements():
    manifest = tomllib.loads((ROOT / "pyproject.toml").read_text())
    text = (ROOT / "docker/sandbox/requirements.lock").read_text()
    pinned = {
        requirement.name: str(next(iter(requirement.specifier)).version)
        for requirement in (
            Requirement(line.removesuffix(" \\"))
            for line in text.splitlines()
            if line and not line.startswith(("#", " "))
        )
    }
    dependencies = (
        manifest["project"]["dependencies"]
        + manifest["project"]["optional-dependencies"]["dev"]
        + manifest["build-system"]["requires"]
    )
    for declaration in dependencies:
        requirement = Requirement(declaration)
        assert requirement.name in pinned
        assert pinned[requirement.name] in requirement.specifier
    assert "openai-agents" not in pinned
    assert len(re.findall(r"--hash=sha256:[0-9a-f]{64}", text)) >= len(pinned)
