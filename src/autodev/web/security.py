from __future__ import annotations

import re
import stat
from pathlib import Path


def redact(value):
    if isinstance(value, dict):
        return {
            key: "[REDACTED]"
            if re.search(
                r"(?i)^(api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)$", key
            )
            else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if not isinstance(value, str):
        return value
    value = re.sub(r"(?i)(bearer\s+)[\w.\-]+", r"\1[REDACTED]", value)
    value = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "[REDACTED]", value)
    value = re.sub(r"\beyJ[A-Za-z0-9_-]{15,}\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+", "[REDACTED]", value)
    return re.sub(
        r"""(?i)((?:api[_-]?key|access[_-]?token|refresh[_-]?token|password|secret)\s*["']?\s*[:=]\s*["']?)[^\s,"';]+""",
        r"\1[REDACTED]",
        value,
    )


def contained(root: Path, relative: str) -> Path:
    """Refuse traversal and symlink/junction escapes before reading any artifact."""
    path = root / relative
    resolved = path.resolve()
    if not resolved.is_relative_to(root.resolve()) or path.is_symlink():
        raise ValueError("unsafe artifact path")
    current = path
    while current != root:
        try:
            reparse = getattr(current.lstat(), "st_file_attributes", 0) & getattr(
                stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024
            )
        except FileNotFoundError:
            reparse = False
        if current.is_symlink() or reparse:
            raise ValueError("unsafe artifact path")
        if current.parent == current:
            raise ValueError("unsafe artifact path")
        current = current.parent
    return resolved
