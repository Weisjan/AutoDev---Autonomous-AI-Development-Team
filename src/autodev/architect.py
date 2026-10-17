from __future__ import annotations

from autodev.project_models import ProjectSpec


class ProjectArchitect:
    def __init__(self, client, max_tasks=8):
        self.client, self.max_tasks = client, max_tasks

    async def design(self, request, files) -> ProjectSpec:
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
        return spec
