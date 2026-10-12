from __future__ import annotations

import os
import shutil
from pathlib import Path

from autodev.schemas import GeneratedFile


class WorkspaceViolation(ValueError):
    """Raised when a generated file attempts to escape the workspace."""


class Workspace:
    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def clear(self) -> None:
        self._assert_inside(self.root)
        if self.root == Path.cwd().resolve() or (self.root / ".git").exists():
            raise WorkspaceViolation(f"refusing to clear unsafe workspace root: {self.root}")
        for child in self.root.iterdir():
            if child.is_dir():
                shutil.rmtree(child)
            else:
                child.unlink()

    def resolve(self, relative_path: str) -> Path:
        normalized = relative_path.replace("\\", "/").strip()
        parts = [part for part in normalized.split("/") if part]
        if (
            not normalized
            or normalized.startswith("/")
            or ".." in parts
            or any(":" in part for part in parts)
        ):
            raise WorkspaceViolation(f"path escapes workspace: {relative_path}")
        target = (self.root / Path(*parts)).resolve()
        self._assert_inside(target)
        return target

    def write_generated_files(
        self,
        files: list[GeneratedFile],
        protected_prefixes: tuple[str, ...] = (),
    ) -> list[Path]:
        written = []
        for generated_file in files:
            if self._is_protected(generated_file.path, protected_prefixes):
                raise WorkspaceViolation(
                    f"generated file targets protected path: {generated_file.path}"
                )
            target = self.resolve(generated_file.path)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(generated_file.content, encoding="utf-8")
            written.append(target)
        return written

    def copy_tree_into(self, source: Path, destination: str) -> None:
        source = source.resolve()
        if not source.is_dir():
            raise FileNotFoundError(f"test seed directory not found: {source}")
        destination_root = self.resolve(destination)
        destination_root.mkdir(parents=True, exist_ok=True)
        for source_file in source.rglob("*"):
            if source_file.is_file():
                relative = source_file.relative_to(source)
                target = destination_root / relative
                self._assert_inside(target.resolve())
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source_file, target)

    def snapshot_files(self, max_bytes_per_file: int = 16_000) -> list[GeneratedFile]:
        files = []
        for path in sorted(self.root.rglob("*.py")):
            if not path.is_file():
                continue
            relative = path.relative_to(self.root).as_posix()
            content = path.read_text(encoding="utf-8")[:max_bytes_per_file]
            files.append(GeneratedFile(path=relative, content=content))
        return files

    def _assert_inside(self, target: Path) -> None:
        try:
            common = os.path.commonpath([str(self.root), str(target)])
        except ValueError as exc:
            raise WorkspaceViolation(f"path escapes workspace: {target}") from exc
        if common != str(self.root):
            raise WorkspaceViolation(f"path escapes workspace: {target}")

    @staticmethod
    def _is_protected(path: str, protected_prefixes: tuple[str, ...]) -> bool:
        normalized = path.replace("\\", "/").strip().lstrip("/")
        for prefix in protected_prefixes:
            clean_prefix = prefix.replace("\\", "/").strip().strip("/")
            if normalized == clean_prefix or normalized.startswith(f"{clean_prefix}/"):
                return True
        return False
