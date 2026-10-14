"""Trusted image preflight. Never install packages or execute workspace code."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import sys
import tomllib
from pathlib import Path

from packaging.requirements import InvalidRequirement, Requirement


def validate_environment(project: Path) -> dict:
    issues = []
    installed = {}
    requirements = list(importlib.metadata.requires("autodev") or [])
    if project.is_file():
        manifest = tomllib.loads(project.read_text(encoding="utf-8"))
        metadata = manifest.get("project", {})
        requirements += metadata.get("dependencies", [])
        requirements += metadata.get("optional-dependencies", {}).get("dev", [])
        if "dependencies" in metadata.get("dynamic", []):
            issues.append("Dynamic project dependencies require a project-specific sandbox image")
    for declaration in sorted(set(requirements)):
        requirement = Requirement(declaration)
        if requirement.marker and not any(
            requirement.marker.evaluate({"extra": extra}) for extra in ("", "dev")
        ):
            continue
        if requirement.url:
            issues.append(f"{requirement.name}: direct-URL dependency requires a custom image")
            continue
        try:
            version = importlib.metadata.version(requirement.name)
        except importlib.metadata.PackageNotFoundError:
            issues.append(f"{requirement.name}: distribution is not installed")
            continue
        installed[requirement.name] = version
        if version not in requirement.specifier:
            issues.append(
                f"{requirement.name}: installed {version} does not satisfy {requirement.specifier}"
            )
    for module in ("pytest", "ruff", "pydantic", "dotenv"):
        if importlib.util.find_spec(module) is None:
            issues.append(f"{module}: required module is missing")
    return {
        "status": "infrastructure_failure" if issues else "ready",
        "issues": issues,
        "installed": installed,
    }


def main() -> int:
    project = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("/workspace/pyproject.toml")
    try:
        result = validate_environment(project)
    except (
        OSError,
        ValueError,
        TypeError,
        InvalidRequirement,
        importlib.metadata.PackageNotFoundError,
    ):
        result = {
            "status": "infrastructure_failure",
            "issues": ["Cannot validate project metadata or installed image dependencies"],
        }
    print(json.dumps(result, sort_keys=True))
    return 78 if result["status"] != "ready" else 0


if __name__ == "__main__":
    raise SystemExit(main())
