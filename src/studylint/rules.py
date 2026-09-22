from __future__ import annotations

import re
from collections import defaultdict
from functools import lru_cache

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
@lru_cache(maxsize=2048)
def _normalize(text: str) -> str:
    return re.sub(r"[^\w\u4e00-\u9fff]+", "", text).casefold()


@lru_cache(maxsize=2048)
def _bigrams(text: str) -> frozenset[str]:
    normalized = _normalize(text)
    if len(normalized) < 2:
        return frozenset({normalized}) if normalized else frozenset()
    return frozenset(
        normalized[index : index + 2] for index in range(len(normalized) - 1)
    )


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


def _support_score(claim: str, source_text: str) -> int:
    claim_normalized = _normalize(claim)
    source_normalized = _normalize(source_text)
    if not claim_normalized or not source_normalized:
        return 0
    claim_bigrams = _bigrams(claim)
    source_bigrams = _bigrams(source_text)
    coverage = (
        len(claim_bigrams & source_bigrams) / len(claim_bigrams)
        if claim_bigrams
        else 0
    )
    fuzzy = fuzz.partial_ratio(claim_normalized, source_normalized) / 100
    return round((coverage * 0.65 + fuzzy * 0.35) * 100)


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


def _source_map(sources: list[SourceDocument]) -> dict[str, list[SourceDocument]]:
    lookup: dict[str, list[SourceDocument]] = defaultdict(list)
    for source in sources:
        lookup[source.name.casefold()].append(source)
    return dict(lookup)


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
    unit: NoteUnit, source_lookup: dict[str, list[SourceDocument]]
) -> tuple[list[Finding], list[SourceSpan]]:
    findings: list[Finding] = []
    valid_spans: list[SourceSpan] = []
    for citation in unit.citations:
        matching_sources = source_lookup.get(citation.source_name.casefold(), [])
        if not matching_sources:
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
        if len(matching_sources) > 1:
            findings.append(
                Finding(
                    "ST009",
                    "error",
                    unit.line,
                    f"资料目录中存在多个同名文件：{citation.source_name}",
                    title="引用来源存在歧义",
                    action="重命名同名文件，并同步修改笔记引用，确保来源唯一。",
                    note_text=unit.text,
                )
            )
            continue
        source = matching_sources[0]
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
        if not span.text.strip():
            findings.append(
                Finding(
                    "ST008",
                    "warning",
                    unit.line,
                    f"{source.name} 的指定位置没有可提取文字。",
                    title="引用位置无法自动核验",
                    action="该页可能是扫描图片；请人工查看原页，或先进行OCR再检查。",
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


def _claim_text(text: str) -> str:
    without_citations = CITATION_PATTERN.sub("", text)
    return re.sub(
        r"^(?:[>*+-]\s*|\d+[.、)]\s*)", "", without_citations
    ).strip()


def _citation_support_finding(
    unit: NoteUnit,
    spans: list[SourceSpan],
    sources: list[SourceDocument],
) -> Finding | None:
    if not unit.citations or not spans or QUOTE_PATTERN.search(unit.text):
        return None
    claim = _claim_text(unit.text)
    if len(_normalize(claim)) < 8:
        return None
    score = max(_support_score(claim, span.text) for span in spans)
    if score >= 28:
        return None
    return Finding(
        "ST006",
        "warning",
        unit.line,
        f"该结论与所标来源位置的文本关联较低（支持度 {score}%）。",
        title="页码与笔记结论可能不匹配",
        action="回到所标页码或时间点核对；若引用位置写错，请更正，若是概括请补充能对应原文的表述。",
        note_text=unit.text,
        suggestions=_suggest_evidence(claim, sources),
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
        support = _citation_support_finding(unit, spans, sources)
        if support and support.code not in unit.ignored_codes:
            findings.append(support)
    findings.extend(_definition_findings(units))
    return sorted(findings, key=lambda finding: (finding.line, finding.code))
