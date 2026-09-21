from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class SourceSpan:
    source_name: str
    locator_type: str
    locator_value: int
    text: str
    end_value: int | None = None


@dataclass
class SourceDocument:
    name: str
    path: Path
    kind: str
    spans: list[SourceSpan] = field(default_factory=list)


@dataclass(frozen=True)
class Citation:
    source_name: str
    locator_type: str
    locator_value: int | None
    raw_value: str
    raw: str


@dataclass(frozen=True)
class NoteUnit:
    line: int
    text: str
    citations: tuple[Citation, ...]


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    line: int
    message: str

    def to_dict(self) -> dict[str, str | int]:
        return {
            "code": self.code,
            "severity": self.severity,
            "line": self.line,
            "message": self.message,
        }

