from pathlib import Path

import pytest

from autodev.schemas import GeneratedFile
from autodev.workspace import Workspace, WorkspaceViolation


def test_workspace_writes_generated_files_inside_root(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "generated")

    written = workspace.write_generated_files(
        [GeneratedFile(path="package/module.py", content="VALUE = 1\n")]
    )

    assert written == [workspace.root / "package" / "module.py"]
    assert (workspace.root / "package" / "module.py").read_text(encoding="utf-8") == "VALUE = 1\n"


def test_workspace_rejects_traversal(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "generated")

    with pytest.raises(WorkspaceViolation):
        workspace.resolve("../outside.py")


def test_workspace_rejects_protected_test_overwrite(tmp_path: Path) -> None:
    workspace = Workspace(tmp_path / "generated")

    with pytest.raises(WorkspaceViolation):
        workspace.write_generated_files(
            [GeneratedFile(path="tests/test_calculator.py", content="")],
            protected_prefixes=("tests",),
        )


def test_generated_file_schema_rejects_absolute_path() -> None:
    with pytest.raises(ValueError):
        GeneratedFile(path="/tmp/outside.py", content="")


def test_generated_file_schema_rejects_windows_drive_path() -> None:
    with pytest.raises(ValueError):
        GeneratedFile(path="C:/tmp/outside.py", content="")
