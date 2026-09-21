from __future__ import annotations

import re
from collections import defaultdict

from rapidfuzz import fuzz

from studylint.models import (
    Citation,
    EvidenceSuggestion,
    Finding,
    NoteUnit,
    SourceDocument,
    SourceSpan,
)
from studylint.parsers import CITATION_PATTERN


QUOTE_PATTERN = re.compile(r"“([^”]{4,})”|\"([^\"]{4,})\"")
DEFINITION_PATTERN = re.compile(
    r"^(?:[-*+]\s*)?(?:\*\*)?([^:：]{2,40}?)(?:\*\*)?\s*[:：]\s*(.+)$"
)


def _normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text).casefold()


def _bigrams(text: str) -> set[str]:
    normalized = _normalize(text)
    if len(normalized) < 2:
        return {normalized} if normalized else set()
    return {normalized[index : index + 2] for index in range(len(normalized) - 1)}


def _similarity(left: str, right: str) -> int:
    left_normalized = _normalize(left)
    right_normalized = _normalize(right)
    if not left_normalized or not right_normalized:
        return 0
    left_bigrams = _bigrams(left)
    right_bigrams = _bigrams(right)
    union = left_bigrams | right_bigrams
    jaccard = len(left_bigrams & right_bigrams) / len(union) if union else 0
    fuzzy = fuzz.partial_ratio(left_normalized, right_normalized) / 100
    return round((jaccard * 0.55 + fuzzy * 0.45) * 100)


def _excerpt(text: str, limit: int = 180) -> str:
    compact = re.sub(r"\s+", " ", text).strip()
    return compact if len(compact) <= limit else compact[: limit - 1] + "…"


def _suggest_evidence(
    claim: str, sources: list[SourceDocument], limit: int = 3
) -> tuple[EvidenceSuggestion, ...]:
    candidates: list[EvidenceSuggestion] = []
    for source in sources:
        for span in source.spans:
            if not span.text.strip():
                continue
            score = _similarity(claim, span.text)
            if score < 20:
                continue
            candidates.append(
                EvidenceSuggestion(
                    source_name=source.name,
                    source_path=str(source.path.resolve()),
                    locator_type=span.locator_type,
                    locator_value=span.locator_value,
                    excerpt=_excerpt(span.text),
                    score=score,
                )
            )
    candidates.sort(key=lambda item: item.score, reverse=True)
    return tuple(candidates[:limit])


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
                    f"未提供引用的来源文件：{citation.source_name}",
                    title="引用来源不存在",
                    action="把该文件加入资料目录，或修正笔记中的文件名。",
                    note_text=unit.text,
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
                    f"{source.name} 中不存在 {citation.locator_type}={citation.raw_value}",
                    title="页码或时间点无效",
                    action="核对引用位置，并注意PDF文件页码可能与印刷页码不同。",
                    note_text=unit.text,
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
                    f"引用位置中没有找到原文：“{quote}”",
                    title="引用原文不匹配",
                    action="检查页码、时间点或引号中的原文，改写内容请不要标成直接引语。",
                    note_text=unit.text,
                )
            )
    return findings


def _is_claim(text: str) -> bool:
    without_citations = CITATION_PATTERN.sub("", text)
    without_markdown = re.sub(r"^[>*+-]\s*", "", without_citations).strip()
    return len(re.sub(r"\s+", "", without_markdown)) >= 12


def _missing_citation_finding(
    unit: NoteUnit, sources: list[SourceDocument]
) -> Finding | None:
    if unit.citations or not _is_claim(unit.text):
        return None
    suggestions = _suggest_evidence(unit.text, sources)
    return Finding(
        "ST004",
        "warning",
        unit.line,
        "这条较长的笔记没有来源引用。",
        title="结论缺少来源",
        action=(
            "核对下方可能相关的来源；确认后补充页码或时间点引用。"
            if suggestions
            else "暂未找到明显相关来源，请人工搜索课程材料或确认这是否属于个人总结。"
        ),
        note_text=unit.text,
        suggestions=suggestions,
    )


def _definition_findings(units: list[NoteUnit]) -> list[Finding]:
    definitions: dict[str, list[tuple[NoteUnit, str, str]]] = defaultdict(list)
    for unit in units:
        text = CITATION_PATTERN.sub("", unit.text).strip()
        match = DEFINITION_PATTERN.match(text)
        if not match:
            continue
        term = re.sub(r"[*_`]", "", match.group(1)).strip()
        definition = match.group(2).strip()
        definitions[term.casefold()].append((unit, term, definition))

    findings: list[Finding] = []
    for entries in definitions.values():
        if len(entries) < 2:
            continue
        baseline = entries[0][2]
        for unit, term, definition in entries[1:]:
            if "ST005" in unit.ignored_codes:
                continue
            if fuzz.ratio(_normalize(baseline), _normalize(definition)) < 65:
                findings.append(
                    Finding(
                        "ST005",
                        "warning",
                        unit.line,
                        f"术语“{term}”出现了差异较大的定义。",
                        title="术语定义可能冲突",
                        action="回到课程材料核对采用哪个定义，并说明不同定义的适用范围。",
                        note_text=unit.text,
                    )
                )
    return findings


def lint(units: list[NoteUnit], sources: list[SourceDocument]) -> list[Finding]:
    source_lookup = _source_map(sources)
    findings: list[Finding] = []
    for unit in units:
        citation_findings, spans = _citation_findings(unit, source_lookup)
        findings.extend(
            finding
            for finding in citation_findings
            if finding.code not in unit.ignored_codes
        )
        findings.extend(
            finding
            for finding in _quote_findings(unit, spans)
            if finding.code not in unit.ignored_codes
        )
        missing = _missing_citation_finding(unit, sources)
        if missing:
            if missing.code not in unit.ignored_codes:
                findings.append(missing)
    findings.extend(_definition_findings(units))
    return sorted(findings, key=lambda finding: (finding.line, finding.code))
