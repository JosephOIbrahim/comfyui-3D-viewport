"""Codebase loader: builds the file inventory and supports citation verification.

Strategy: instead of inlining every source file in the prompt (token-expensive
and stale-prone), we expose the file inventory plus per-file digests and let
experts use Read/Grep tools to explore on demand. The full content blob is
held in memory only to support `verify.py` citation checks.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from pathlib import Path

# File globs included in the review scope. Anything outside is INFO-only per R4.
INCLUDE_GLOBS = (
    "src/*.py",
    "tests/*.py",
    "tests/conftest.py",
    "data/*.json",
    "docs/*.md",
    "requirements.txt",
    "pytest.ini",
    ".gitignore",
    "CLAUDE.md",
    "SUPERDUPER_3D_GRAFT.md",
    "EXECUTION_SPEC.md",
    "DISPATCH_PROFILERX.md",
)


@dataclass
class FileEntry:
    rel_path: str
    abs_path: Path
    line_count: int
    sha256: str
    content: str = field(repr=False)


@dataclass
class CodebaseSnapshot:
    root: Path
    files: list[FileEntry]
    git_sha: str

    def total_lines(self) -> int:
        return sum(f.line_count for f in self.files)

    def content_hash(self) -> str:
        h = hashlib.sha256()
        for f in sorted(self.files, key=lambda x: x.rel_path):
            h.update(f.rel_path.encode())
            h.update(b"\0")
            h.update(f.sha256.encode())
            h.update(b"\0")
        return h.hexdigest()[:16]

    def get(self, rel_path: str) -> FileEntry | None:
        for f in self.files:
            if f.rel_path == rel_path:
                return f
        return None

    def inventory_block(self) -> str:
        """Render the file inventory as a Markdown table for system prompts.

        Compact: path | lines | sha. Experts use Read/Grep to fetch content.
        """
        lines = ["| path | lines | sha |", "|---|---|---|"]
        for f in sorted(self.files, key=lambda x: x.rel_path):
            lines.append(f"| `{f.rel_path}` | {f.line_count} | `{f.sha256[:8]}` |")
        return "\n".join(lines)


def load_snapshot(root: Path, git_sha: str) -> CodebaseSnapshot:
    files: list[FileEntry] = []
    seen: set[str] = set()
    for pattern in INCLUDE_GLOBS:
        for p in sorted(root.glob(pattern)):
            if not p.is_file():
                continue
            rel = p.relative_to(root).as_posix()
            if rel in seen:
                continue
            seen.add(rel)
            try:
                content = p.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            files.append(FileEntry(
                rel_path=rel,
                abs_path=p,
                line_count=content.count("\n") + (0 if content.endswith("\n") else 1) if content else 0,
                sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
                content=content,
            ))
    return CodebaseSnapshot(root=root, files=files, git_sha=git_sha)
