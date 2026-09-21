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
    ignored_codes: tuple[str, ...] = ()


@dataclass(frozen=True)
class EvidenceSuggestion:
    source_name: str
    source_path: str
    locator_type: str
    locator_value: int
    excerpt: str
    score: int

    def to_dict(self) -> dict[str, str | int]:
        return {
            "source_name": self.source_name,
            "source_path": self.source_path,
            "locator_type": self.locator_type,
            "locator_value": self.locator_value,
            "excerpt": self.excerpt,
            "score": self.score,
        }


@dataclass(frozen=True)
class Finding:
    code: str
    severity: str
    line: int
    message: str
    title: str = ""
    action: str = ""
    note_text: str = ""
    suggestions: tuple[EvidenceSuggestion, ...] = ()

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "severity": self.severity,
            "line": self.line,
            "message": self.message,
            "title": self.title,
            "action": self.action,
            "note_text": self.note_text,
            "suggestions": [suggestion.to_dict() for suggestion in self.suggestions],
        }
