from __future__ import annotations

import re
from collections import defaultdict

from rapidfuzz import fuzz

from studylint.models import Citation, Finding, NoteUnit, SourceDocument, SourceSpan
from studylint.parsers import CITATION_PATTERN


QUOTE_PATTERN = re.compile(r"“([^”]{4,})”|\"([^\"]{4,})\"")
DEFINITION_PATTERN = re.compile(
    r"^(?:[-*+]\s*)?(?:\*\*)?([^:：]{2,40}?)(?:\*\*)?\s*[:：]\s*(.+)$"
)


def _normalize(text: str) -> str:
    return re.sub(r"\s+", "", text).casefold()


def _source_map(sources: list[SourceDocument]) -> dict[str, SourceDocument]:
    return {source.name.casefold(): source for source in sources}


def _find_span(source: SourceDocument, citation: Citation) -> SourceSpan | None:
    if citation.locator_value is None:
        return None
    if citation.locator_type == "page":
        return next(
            (
                span
                for span in source.spans
                if span.locator_type == "page"
                and span.locator_value == citation.locator_value
            ),
            None,
        )
    return next(
        (
            span
            for span in source.spans
            if span.locator_type == "time"
            and span.locator_value <= citation.locator_value <= (span.end_value or span.locator_value)
        ),
        None,
    )


def _citation_findings(
    unit: NoteUnit, source_lookup: dict[str, SourceDocument]
) -> tuple[list[Finding], list[SourceSpan]]:
    findings: list[Finding] = []
    valid_spans: list[SourceSpan] = []
    for citation in unit.citations:
        source = source_lookup.get(citation.source_name.casefold())
        if source is None:
            findings.append(
                Finding(
                    "ST001",
                    "error",
                    unit.line,
                    f"Source not found: {citation.source_name}",
                )
            )
            continue
        span = _find_span(source, citation)
        if span is None:
            findings.append(
                Finding(
                    "ST002",
                    "error",
                    unit.line,
                    f"Invalid {citation.locator_type} '{citation.raw_value}' for {source.name}",
                )
            )
            continue
        valid_spans.append(span)
    return findings, valid_spans


def _quote_findings(unit: NoteUnit, spans: list[SourceSpan]) -> list[Finding]:
    quotes = [next(group for group in match.groups() if group) for match in QUOTE_PATTERN.finditer(unit.text)]
    if not quotes or not spans:
        return []

    findings: list[Finding] = []
    source_texts = [_normalize(span.text) for span in spans]
    for quote in quotes:
        normalized_quote = _normalize(quote)
        supported = any(
            normalized_quote in source_text or fuzz.partial_ratio(normalized_quote, source_text) >= 90
            for source_text in source_texts
        )
        if not supported:
            findings.append(
                Finding(
                    "ST003",
                    "error",
                    unit.line,
                    f"Quoted evidence was not found at the cited location: {quote}",
                )
            )
    return findings


def _is_claim(text: str) -> bool:
    without_citations = CITATION_PATTERN.sub("", text)
    without_markdown = re.sub(r"^[>*+-]\s*", "", without_citations).strip()
    return len(re.sub(r"\s+", "", without_markdown)) >= 12


def _missing_citation_finding(unit: NoteUnit) -> Finding | None:
    if unit.citations or not _is_claim(unit.text):
        return None
    return Finding(
        "ST004",
        "warning",
        unit.line,
        "Claim has no source citation.",
    )


def _definition_findings(units: list[NoteUnit]) -> list[Finding]:
    definitions: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
    for unit in units:
        text = CITATION_PATTERN.sub("", unit.text).strip()
        match = DEFINITION_PATTERN.match(text)
        if not match:
            continue
        term = re.sub(r"[*_`]", "", match.group(1)).strip()
        definition = match.group(2).strip()
        definitions[term.casefold()].append((unit.line, term, definition))

    findings: list[Finding] = []
    for entries in definitions.values():
        if len(entries) < 2:
            continue
        baseline = entries[0][2]
        for line, term, definition in entries[1:]:
            if fuzz.ratio(_normalize(baseline), _normalize(definition)) < 65:
                findings.append(
                    Finding(
                        "ST005",
                        "warning",
                        line,
                        f"Conflicting definitions detected for term '{term}'.",
                    )
                )
    return findings


def lint(units: list[NoteUnit], sources: list[SourceDocument]) -> list[Finding]:
    source_lookup = _source_map(sources)
    findings: list[Finding] = []
    for unit in units:
        citation_findings, spans = _citation_findings(unit, source_lookup)
        findings.extend(citation_findings)
        findings.extend(_quote_findings(unit, spans))
        missing = _missing_citation_finding(unit)
        if missing:
            findings.append(missing)
    findings.extend(_definition_findings(units))
    return sorted(findings, key=lambda finding: (finding.line, finding.code))

