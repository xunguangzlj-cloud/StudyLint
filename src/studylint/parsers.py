from __future__ import annotations

import re
from pathlib import Path

from studylint.models import Citation, NoteUnit, SourceDocument, SourceSpan


CITATION_PATTERN = re.compile(
    r"\[(?P<source>[^\]#]+)#(?P<kind>page|time)=(?P<value>[^\]]+)\]"
)
PAGE_MARKER_PATTERN = re.compile(r"^\s*<!--\s*page\s*:\s*(\d+)\s*-->\s*$", re.I)
SRT_TIME_PATTERN = re.compile(
    r"(?P<start>\d{2}:\d{2}:\d{2}[,.]\d{3})\s*-->\s*"
    r"(?P<end>\d{2}:\d{2}:\d{2}[,.]\d{3})"
)


def parse_time(value: str) -> int | None:
    match = re.fullmatch(r"\s*(\d{1,2}):(\d{2}):(\d{2})(?:[,.](\d{3}))?\s*", value)
    if not match:
        return None
    hours, minutes, seconds = (int(part) for part in match.group(1, 2, 3))
    if minutes >= 60 or seconds >= 60:
        return None
    return hours * 3600 + minutes * 60 + seconds


def extract_citations(text: str) -> tuple[Citation, ...]:
    citations: list[Citation] = []
    for match in CITATION_PATTERN.finditer(text):
        kind = match.group("kind").lower()
        raw_value = match.group("value").strip()
        if kind == "page":
            try:
                value = int(raw_value)
            except ValueError:
                value = None
        else:
            value = parse_time(raw_value)
        citations.append(
            Citation(
                source_name=match.group("source").strip(),
                locator_type=kind,
                locator_value=value,
                raw_value=raw_value,
                raw=match.group(0),
            )
        )
    return tuple(citations)


def parse_notes(path: Path) -> list[NoteUnit]:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    units: list[NoteUnit] = []
    in_code_block = False
    for line_number, line in enumerate(lines, start=1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code_block = not in_code_block
            continue
        if (
            in_code_block
            or not stripped
            or stripped.startswith("#")
            or stripped.startswith("<!--")
        ):
            continue
        units.append(
            NoteUnit(
                line=line_number,
                text=stripped,
                citations=extract_citations(stripped),
            )
        )
    return units


def _parse_markdown_or_text(path: Path) -> SourceDocument:
    lines = path.read_text(encoding="utf-8-sig").splitlines()
    page = 1
    pages: dict[int, list[str]] = {page: []}
    for line in lines:
        marker = PAGE_MARKER_PATTERN.match(line)
        if marker:
            page = int(marker.group(1))
            pages.setdefault(page, [])
            continue
        pages[page].append(line)

    spans = [
        SourceSpan(path.name, "page", number, "\n".join(content).strip())
        for number, content in sorted(pages.items())
    ]
    return SourceDocument(path.name, path, path.suffix.lower().lstrip("."), spans)


def _parse_pdf(path: Path) -> SourceDocument:
    import fitz

    document = fitz.open(path)
    try:
        spans = [
            SourceSpan(path.name, "page", index + 1, page.get_text("text").strip())
            for index, page in enumerate(document)
        ]
    finally:
        document.close()
    return SourceDocument(path.name, path, "pdf", spans)


def _parse_pptx(path: Path) -> SourceDocument:
    from pptx import Presentation

    presentation = Presentation(path)
    spans: list[SourceSpan] = []
    for index, slide in enumerate(presentation.slides, start=1):
        text_parts = [
            shape.text.strip()
            for shape in slide.shapes
            if hasattr(shape, "text") and shape.text.strip()
        ]
        spans.append(SourceSpan(path.name, "page", index, "\n".join(text_parts)))
    return SourceDocument(path.name, path, "pptx", spans)


def _parse_srt(path: Path) -> SourceDocument:
    content = path.read_text(encoding="utf-8-sig")
    blocks = re.split(r"\r?\n\s*\r?\n", content.strip())
    spans: list[SourceSpan] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines() if line.strip()]
        time_index = next(
            (index for index, line in enumerate(lines) if SRT_TIME_PATTERN.fullmatch(line)),
            None,
        )
        if time_index is None:
            continue
        match = SRT_TIME_PATTERN.fullmatch(lines[time_index])
        if match is None:
            continue
        start = parse_time(match.group("start"))
        end = parse_time(match.group("end"))
        if start is None or end is None:
            continue
        text = " ".join(lines[time_index + 1 :]).strip()
        spans.append(SourceSpan(path.name, "time", start, text, end))
    return SourceDocument(path.name, path, "srt", spans)


def load_source(path: Path) -> SourceDocument:
    suffix = path.suffix.lower()
    parsers = {
        ".md": _parse_markdown_or_text,
        ".txt": _parse_markdown_or_text,
        ".pdf": _parse_pdf,
        ".pptx": _parse_pptx,
        ".srt": _parse_srt,
    }
    if suffix not in parsers:
        supported = ", ".join(sorted(parsers))
        raise ValueError(f"Unsupported source type: {suffix or '(none)'}. Supported: {supported}")
    return parsers[suffix](path)

