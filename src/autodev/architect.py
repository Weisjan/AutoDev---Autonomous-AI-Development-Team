from __future__ import annotations

import re
from dataclasses import dataclass

from autodev.project_models import ProjectSpec
from autodev.providers import ProviderSchemaError


@dataclass(frozen=True)
class RequestedMilestone:
    name: str
    files: frozenset[str]
    independent: bool


def milestone_requirements(request: str) -> tuple[int | None, list[RequestedMilestone]]:
    """Recognize explicit counts and numbered headings, without guessing arbitrary prose."""
    numbers = {"one": 1, "two": 2, "three": 3, "four": 4}
    matches = re.findall(
        r"\b(?:design|use|create|plan|exactly)\s+(one|two|three|four|\d+)\s+"
        r"(?:ordered\s+)?milestones\b",
        request,
        re.IGNORECASE,
    )
    counts = {numbers[m.lower()] if m.lower() in numbers else int(m) for m in matches}
    if not counts:
        return None, []
    if len(counts) != 1 or not 1 <= next(iter(counts)) <= 4:
        raise ProviderSchemaError(
            "Requested milestone count is conflicting or exceeds Phase 1 limits"
        )
    count = counts.pop()
    headings = re.findall(r"^\s*(\d+)[.)]\s+([^:\n]{1,60}):\s*([^\n]*)", request, re.MULTILINE)
    if [int(n) for n, _, _ in headings] != list(range(1, count + 1)):
        return count, []
    groups = []
    for _, name, heading in headings:
        files = set(
            re.findall(
                r"(?<![\w./-])(?:[A-Za-z0-9_-]+/)*[A-Za-z0-9_-]+\.(?:py|md|json|txt|html|css)\b",
                heading,
            )
        )
        groups.append(
            RequestedMilestone(
                name.strip(),
                frozenset(files),
                bool(
                    re.search(
                        r"\b(?:independent|concurrent(?:ly)?|parallel)\b",
                        heading,
                        re.IGNORECASE,
                    )
                ),
            )
        )
    return count, groups


def validate_requested_milestones(spec: ProjectSpec, request: str) -> None:
    count, groups = milestone_requirements(request)
    if count is not None and len(spec.milestones) != count:
        raise ProviderSchemaError(
            f"Architecture must preserve the requested {count} milestones; "
            "no developers started. Review the plan before starting a new run."
        )
    for index, group in enumerate(groups):
        milestone = spec.milestones[index]
        if not re.search(
            r"\b" + re.escape(group.name) + r"\b",
            milestone.id.replace("_", " ").replace("-", " ") + " " + milestone.description,
            re.IGNORECASE,
        ):
            raise ProviderSchemaError(
                f"Architecture changed the requested name/order of milestone {index + 1}; "
                "no developers started."
            )
        if not group.files:
            continue
        owners = {t.id for t in spec.tasks if group.files & set(t.owned_files)}
        covered = {p for t in spec.tasks if t.id in owners for p in t.owned_files}
        if not group.files <= covered or owners != set(spec.milestones[index].task_ids):
            raise ProviderSchemaError(
                f"Architecture changed the requested file grouping for milestone {index + 1}; "
                "no developers started."
            )
        if group.independent and any(
            set(t.depends_on) & owners for t in spec.tasks if t.id in owners
        ):
            raise ProviderSchemaError(
                f"Architecture serialized explicitly independent tasks in milestone {index + 1}; "
                "no developers started."
            )


class ProjectArchitect:
    def __init__(self, client, max_tasks=8):
        self.client, self.max_tasks = client, max_tasks

    async def design(self, request, files) -> ProjectSpec:
        milestone_requirements(request)  # Reject unsupported counts before the model call.
        spec = ProjectSpec.model_validate(
            await self.client.architect(request, files, self.max_tasks)
        )
        if len(spec.tasks) > self.max_tasks:
            raise ValueError("Architect exceeded configured task count")
        existing = {f.path for f in files}
        tests = {p for t in spec.tasks for p in t.test_paths}
        tests |= {p for m in spec.milestones for p in m.test_paths}
        if not tests <= existing:
            raise ValueError("Architecture references tests absent from the trusted baseline")
        validate_requested_milestones(spec, request)
        return spec
