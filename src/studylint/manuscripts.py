from __future__ import annotations

import re
from dataclasses import dataclass, replace
from datetime import date
from pathlib import Path
from typing import Callable

from rapidfuzz import fuzz

from studylint.claims import ClaimEvidence, verify_claims
from studylint.fulltext import ReferenceResolution, resolve_reference_sources


SUPPORTED_MANUSCRIPT_SUFFIXES = {".md", ".txt", ".docx", ".pdf"}
SUPPORTED_REFERENCE_SUFFIXES = {".pdf", ".epub"}
REFERENCE_HEADING = re.compile(
    r"^\s*(?:#{1,6}\s*)?(?:参考文献|references|bibliography|works\s+cited)\s*[:：]?\s*$",
    re.IGNORECASE,
)
REFERENCE_ENTRY = re.compile(
    r"^\s*(?:[\[［【](\d+)[\]］】]|[（(](\d+)[）)]|(\d+)[.、)])\s*(.+)$"
)
INLINE_CITATIONS = re.compile(
    r"(?:[\[［【](?P<bracket>\d+(?:\s*(?:[-–—,，;；]\s*)\d+)*)[\]］】])"
    r"|(?:[（(](?P<paren>\d+(?:\s*(?:[-–—,，;；]\s*)\d+)*)[）)])"
    r"|(?P<superscript>[⁰¹²³⁴⁵⁶⁷⁸⁹]+(?:\s*(?:[⁻–—,，;；]\s*)[⁰¹²³⁴⁵⁶⁷⁸⁹]+)*)"
)
AUTHOR_YEAR_PARENTHESES = re.compile(r"[（(]([^()（）]{1,200})[）)]")
AUTHOR_YEAR_NARRATIVE = re.compile(
    r"(?P<authors>"
    r"(?:[A-Z][A-Za-z'’.-]+(?:\s+(?:et\s+al\.?|and\s+[A-Z][A-Za-z'’.-]+|&\s*[A-Z][A-Za-z'’.-]+))?)"
    r"|(?:[\u3400-\u9fff]{2,12}(?:等)?)"
    r")\s*[（(](?P<year>(?:19|20)\d{2})[a-z]?[）)]"
)
SUPERSCRIPT_TRANSLATION = str.maketrans("⁰¹²³⁴⁵⁶⁷⁸⁹⁻", "0123456789-")


@dataclass(frozen=True)
class CitationAudit:
    claim: str
    paragraph: int
    citation_number: int
    reference_text: str
    source_path: str
    verdict: str
    explanation: str
    evidences: tuple[ClaimEvidence, ...] = ()
    ai_verdict: str = ""
    ai_confidence: int = 0
    ai_explanation: str = ""
    ai_evidence_pages: tuple[int, ...] = ()
    ai_model: str = ""
    ai_mode: str = ""
    ai_skill: str = ""
    reference_verdict: str = ""
    reference_message: str = ""
    reference_url: str = ""
    reference_type: str = ""
    reference_warnings: tuple[str, ...] = ()
    source_status: str = ""
    source_message: str = ""
    source_license: str = ""
    ai_issue_types: tuple[str, ...] = ()
    location: str = ""

    def to_dict(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "claim": self.claim,
            "paragraph": self.paragraph,
            "location": self.location,
            "citation_number": self.citation_number,
            "reference_text": self.reference_text,
            "source_path": self.source_path,
            "verdict": self.verdict,
            "explanation": self.explanation,
            "evidences": [evidence.to_dict() for evidence in self.evidences],
        }
        if self.reference_verdict or self.source_status:
            payload["reference_check"] = {
                "verdict": self.reference_verdict,
                "message": self.reference_message,
                "url": self.reference_url,
                "type": self.reference_type,
                "warnings": list(self.reference_warnings),
            }
            payload["full_text"] = {
                "status": self.source_status,
                "message": self.source_message,
                "license": self.source_license,
            }
        if self.ai_verdict:
            payload["ai_review"] = {
                "verdict": self.ai_verdict,
                "confidence": self.ai_confidence,
                "explanation": self.ai_explanation,
                "evidence_pages": list(self.ai_evidence_pages),
                "model": self.ai_model,
                "mode": self.ai_mode,
                "skill": self.ai_skill,
                "issue_types": list(self.ai_issue_types),
            }
        return payload


@dataclass(frozen=True)
class ManuscriptIssue:
    code: str
    category: str
    paragraph: int
    message: str
    excerpt: str
    location: str = ""

    def to_dict(self) -> dict[str, str | int]:
        return {
            "code": self.code,
            "category": self.category,
            "paragraph": self.paragraph,
            "location": self.location,
            "message": self.message,
            "excerpt": self.excerpt,
        }


def _read_blocks_with_locations(path: Path) -> tuple[list[str], dict[int, str]]:
    suffix = path.suffix.lower()
    if suffix in {".md", ".txt"}:
        blocks = path.read_text(encoding="utf-8-sig").splitlines()
        return blocks, {number: f"第{number}行" for number in range(1, len(blocks) + 1)}
    if suffix == ".docx":
        from docx import Document

        blocks: list[str] = []
        for paragraph in Document(path).paragraphs:
            parts: list[str] = []
            for run in paragraph.runs:
                text = run.text
                if run.font.superscript and re.fullmatch(
                    r"\s*\d+(?:\s*(?:[-–—,，;；]\s*)\d+)*\s*", text
                ):
                    text = f"［{text.strip()}］"
                parts.append(text)
            blocks.append("".join(parts))
        return blocks, {
            number: f"第{number}段" for number in range(1, len(blocks) + 1)
        }
    if suffix == ".pdf":
        import pymupdf

        document = pymupdf.open(path)
        try:
            blocks: list[str] = []
            locations: dict[int, str] = {}
            for page_number, page in enumerate(document, start=1):
                for line_number, line in enumerate(
                    page.get_text("text").splitlines(), start=1
                ):
                    stripped = line.strip()
                    if not stripped:
                        continue
                    blocks.append(stripped)
                    locations[len(blocks)] = f"第{page_number}页第{line_number}行"
            return blocks, locations
        finally:
            document.close()
    supported = ", ".join(sorted(SUPPORTED_MANUSCRIPT_SUFFIXES))
    raise ValueError(f"不支持的论文稿件格式：{suffix or '(无扩展名)'}。支持：{supported}")


def _read_blocks(path: Path) -> list[str]:
    return _read_blocks_with_locations(path)[0]


def read_manuscript_blocks(path: Path) -> list[str]:
    """按核验时使用的顺序读取稿件文本，供批注报告复用。"""
    return _read_blocks_with_locations(path)[0]


def _split_manuscript(
    blocks: list[str],
) -> tuple[list[tuple[int, str]], dict[int, str]]:
    heading_index = next(
        (index for index, block in enumerate(blocks) if REFERENCE_HEADING.match(block)),
        None,
    )
    prose_blocks = blocks if heading_index is None else blocks[:heading_index]
    reference_blocks = [] if heading_index is None else blocks[heading_index + 1 :]
    references: dict[int, str] = {}
    current_number: int | None = None
    has_numbered_entries = any(
        REFERENCE_ENTRY.match(block.strip())
        for block in reference_blocks
        if block.strip()
    )
    for block in reference_blocks:
        stripped = block.strip()
        if not stripped:
            continue
        if not has_numbered_entries:
            references[len(references) + 1] = stripped
            continue
        match = REFERENCE_ENTRY.match(stripped)
        if match:
            current_number = int(match.group(1) or match.group(2) or match.group(3))
            references[current_number] = match.group(4).strip()
        elif current_number is not None:
            references[current_number] = f"{references[current_number]} {stripped}"
    prose = [
        (number, block.strip())
        for number, block in enumerate(prose_blocks, start=1)
        if block.strip()
    ]
    return prose, references


def _expand_citation_group(value: str) -> list[int]:
    numbers: list[int] = []
    for part in re.split(r"\s*[,，;；]\s*", value):
        range_match = re.fullmatch(r"(\d+)\s*[-–—]\s*(\d+)", part)
        if range_match:
            start, end = map(int, range_match.groups())
            if start <= end and end - start <= 100:
                numbers.extend(range(start, end + 1))
            continue
        if part.strip().isdigit():
            numbers.append(int(part.strip()))
    return list(dict.fromkeys(numbers))


def _parse_author_year_group(value: str) -> list[tuple[str, int]]:
    citations: list[tuple[str, int]] = []
    for part in re.split(r"\s*[;；]\s*", value):
        match = re.match(
            r"\s*(?P<authors>.+?)[,，]\s*(?P<year>(?:19|20)\d{2})[a-z]?(?:\b|(?=\D|$))",
            part,
            re.IGNORECASE,
        )
        if match:
            citations.append((match.group("authors").strip(), int(match.group("year"))))
    return citations


def _strip_citations(text: str) -> str:
    stripped = AUTHOR_YEAR_NARRATIVE.sub("", text)
    stripped = AUTHOR_YEAR_PARENTHESES.sub(
        lambda match: "" if _parse_author_year_group(match.group(1)) else match.group(0),
        stripped,
    )
    return INLINE_CITATIONS.sub("", stripped)


def _claim_around_citation(text: str, start: int, end: int) -> str:
    left = max(
        text.rfind(marker, 0, start)
        for marker in (".", "!", "?", "。", "！", "？", ";", "；")
    )
    right_candidates = [
        position
        for marker in (".", "!", "?", "。", "！", "？", ";", "；")
        if (position := text.find(marker, end)) >= 0
    ]
    right = min(right_candidates) + 1 if right_candidates else len(text)
    claim = _strip_citations(text[left + 1 : right]).strip(" 	,，;；")
    claim = re.sub(r"\s+([.!?。！？])", r"\1", claim)
    return claim or _strip_citations(text).strip()


def _author_tokens(authors: str) -> list[str]:
    cleaned = re.sub(r"\s+et\s+al\.?\s*$|等\s*$", "", authors, flags=re.IGNORECASE)
    parts = re.split(r"\s*(?:,|，|、|&|\band\b)\s*", cleaned, flags=re.IGNORECASE)
    ignored = {"研究", "本研究", "该研究", "文献", "本文", "结果"}
    return [part.casefold() for part in parts if part and part not in ignored]


def _reference_for_author_year(
    authors: str, year: int, references: dict[int, str]
) -> int | None:
    tokens = _author_tokens(authors)
    if not tokens:
        return None
    candidates: list[int] = []
    for number, reference in references.items():
        if not re.search(rf"(?<!\d){year}(?!\d)", reference):
            continue
        normalized = reference.casefold()
        if all(
            token in normalized
            if not token.isascii()
            else re.search(rf"\b{re.escape(token)}\b", normalized) is not None
            for token in tokens
        ):
            candidates.append(number)
    return candidates[0] if len(candidates) == 1 else None


def extract_citation_claims(
    blocks: list[str],
) -> tuple[list[tuple[int, int, str]], dict[int, str]]:
    prose, references = _split_manuscript(blocks)
    claims: list[tuple[int, int, str]] = []
    seen: set[tuple[int, str]] = set()
    for paragraph, text in prose:
        for match in INLINE_CITATIONS.finditer(text):
            claim = _claim_around_citation(text, match.start(), match.end())
            raw_group = match.group("bracket") or match.group("paren")
            if raw_group is None:
                raw_group = match.group("superscript").translate(SUPERSCRIPT_TRANSLATION)
            numbers = _expand_citation_group(raw_group)
            if match.group("paren") or match.group("superscript"):
                numbers = [number for number in numbers if number in references]
            for number in numbers:
                key = (number, claim.casefold())
                if claim and key not in seen:
                    seen.add(key)
                    claims.append((paragraph, number, claim))
        for match in AUTHOR_YEAR_PARENTHESES.finditer(text):
            mapped = [
                _reference_for_author_year(authors, year, references)
                for authors, year in _parse_author_year_group(match.group(1))
            ]
            claim = _claim_around_citation(text, match.start(), match.end())
            for number in mapped:
                if number is None:
                    continue
                key = (number, claim.casefold())
                if claim and key not in seen:
                    seen.add(key)
                    claims.append((paragraph, number, claim))
        for match in AUTHOR_YEAR_NARRATIVE.finditer(text):
            number = _reference_for_author_year(
                match.group("authors"), int(match.group("year")), references
            )
            if number is None:
                continue
            claim = _claim_around_citation(text, match.start(), match.end())
            key = (number, claim.casefold())
            if claim and key not in seen:
                seen.add(key)
                claims.append((paragraph, number, claim))
    return claims, references


def discover_reference_files(inputs: list[Path]) -> list[Path]:
    paths: list[Path] = []
    for source in inputs:
        if source.is_dir():
            paths.extend(
                sorted(
                    path
                    for path in source.rglob("*")
                    if path.is_file()
                    and path.suffix.lower() in SUPPORTED_REFERENCE_SUFFIXES
                )
            )
        elif source.is_file() and source.suffix.lower() in SUPPORTED_REFERENCE_SUFFIXES:
            paths.append(source)
        else:
            raise ValueError(f"本地原文不存在或格式不支持（仅支持PDF/EPUB）：{source}")
    return list(dict.fromkeys(path.resolve() for path in paths))


def discover_reference_pdfs(inputs: list[Path]) -> list[Path]:
    """保留旧接口；现在同时发现PDF和EPUB。"""
    return discover_reference_files(inputs)


def _match_reference_files(
    references: dict[int, str], source_paths: list[Path]
) -> dict[int, Path]:
    matched: dict[int, Path] = {}
    unused = set(source_paths)
    for number in references:
        exact = next(
            (
                path
                for path in unused
                if re.match(rf"^\[?0*{number}\]?(?:\D|$)", path.stem)
            ),
            None,
        )
        if exact is not None:
            matched[number] = exact
            unused.remove(exact)
    for number, reference in references.items():
        if number in matched or not unused:
            continue
        candidates = sorted(
            (
                fuzz.token_set_ratio(
                    reference.casefold(),
                    re.sub(r"[_-]+", " ", path.stem).casefold(),
                ),
                path,
            )
            for path in unused
        )
        score, best = candidates[-1]
        if score >= 70:
            matched[number] = best
            unused.remove(best)
    if len(references) == 1 and len(source_paths) == 1 and not matched:
        matched[next(iter(references))] = source_paths[0]
    return matched


def _match_reference_pdfs(
    references: dict[int, str], pdf_paths: list[Path]
) -> dict[int, Path]:
    """保留旧接口；现在同时匹配PDF和EPUB。"""
    return _match_reference_files(references, pdf_paths)


def _numeric_signature(text: str) -> tuple[str, tuple[str, ...]] | None:
    text_without_citations = _strip_citations(text)
    numbers = tuple(
        re.findall(r"(?<![\w.])[+-]?\d+(?:\.\d+)?%?", text_without_citations)
    )
    if not numbers:
        return None
    skeleton = re.sub(
        r"(?<![\w.])[+-]?\d+(?:\.\d+)?%?", "#", text_without_citations.casefold()
    )
    skeleton = "".join(character for character in skeleton if character.isalnum() or character == "#")
    if len(skeleton) < 16:
        return None
    return skeleton, numbers


def scan_manuscript_issues(manuscript_path: Path) -> list[ManuscriptIssue]:
    blocks, locations = _read_blocks_with_locations(manuscript_path)
    prose, references = _split_manuscript(blocks)
    claims, _ = extract_citation_claims(blocks)
    cited = {number for _, number, _ in claims}
    issues: list[ManuscriptIssue] = []

    for number, reference in references.items():
        if number not in cited:
            issues.append(
                ManuscriptIssue(
                    "UNUSED_REFERENCE",
                    "引用与来源",
                    0,
                    f"参考文献[{number}]没有在正文中被引用。",
                    reference,
                )
            )
        if re.search(
            r"\b(?:todo|tbd|citation\s+needed|xxxx|yyyy)\b|待补|补充文献|文献待核",
            reference,
            re.IGNORECASE,
        ):
            issues.append(
                ManuscriptIssue(
                    "PLACEHOLDER_REFERENCE",
                    "引用与来源",
                    0,
                    f"参考文献[{number}]仍含占位内容。",
                    reference,
                )
            )
        years = [int(value) for value in re.findall(r"(?<!\d)(?:19|20)\d{2}(?!\d)", reference)]
        future_years = [year for year in years if year > date.today().year]
        if future_years:
            issues.append(
                ManuscriptIssue(
                    "FUTURE_REFERENCE_YEAR",
                    "时间与版本",
                    0,
                    f"参考文献[{number}]包含未来年份{max(future_years)}，请核对版本和出版状态。",
                    reference,
                )
            )

    signatures: dict[str, tuple[tuple[str, ...], int, str]] = {}
    for paragraph, block in prose:
        for sentence in re.split(r"(?<=[.!?。！？])\s*|\n+", block):
            signature = _numeric_signature(sentence.strip())
            if signature is None:
                continue
            skeleton, numbers = signature
            previous = signatures.get(skeleton)
            if previous and previous[0] != numbers:
                issues.append(
                    ManuscriptIssue(
                        "INCONSISTENT_NUMERIC_STATEMENT",
                        "数据与内部一致性",
                        paragraph,
                        f"与第{previous[1]}段的近似表述使用了不同数字，请回查数据来源。",
                        sentence.strip(),
                    )
                )
            else:
                signatures[skeleton] = (numbers, paragraph, sentence.strip())
    return [
        replace(issue, location=locations.get(issue.paragraph, "参考文献表"))
        for issue in issues
    ]


def _resolution_fields(
    resolution: ReferenceResolution | None,
) -> dict[str, object]:
    if resolution is None:
        return {}
    return {
        "reference_verdict": resolution.verification_verdict,
        "reference_message": resolution.verification_message,
        "reference_url": resolution.url,
        "reference_type": resolution.work_type,
        "reference_warnings": resolution.warnings,
        "source_status": resolution.source_status,
        "source_message": resolution.source_message,
        "source_license": resolution.license,
    }


def audit_manuscript(
    manuscript_path: Path,
    reference_inputs: list[Path],
    *,
    auto_fetch: bool = False,
    cache_dir: Path | None = None,
    progress: Callable[[int, str], None] | None = None,
) -> list[CitationAudit]:
    if not manuscript_path.is_file():
        raise ValueError(f"找不到论文稿件：{manuscript_path}")
    if progress:
        progress(5, "读取稿件并定位正文")
    blocks, locations = _read_blocks_with_locations(manuscript_path)
    claims, references = extract_citation_claims(blocks)
    if not claims:
        raise ValueError(
            "未找到可与参考文献表关联的正文引用。支持半角/全角方括号、"
            "圆括号数字、Unicode或DOCX上标数字，以及作者—年份格式；"
            "作者—年份引用只有在作者和年份能唯一匹配参考文献时才会自动关联。"
        )
    if progress:
        progress(15, f"已定位{len(claims)}处正文引用")
    source_paths = discover_reference_files(reference_inputs)
    matched_sources = _match_reference_files(references, source_paths)
    resolutions: dict[int, ReferenceResolution] = {}
    resolution_error = ""
    if auto_fetch and references:
        try:
            resolutions = resolve_reference_sources(
                references,
                matched_sources,
                cache_dir or manuscript_path.parent / "StudyLint-原文",
            )
        except (OSError, RuntimeError, ValueError) as error:
            resolution_error = f"文献记录或开放原文获取未完成：{error}"
        else:
            matched_sources.update(
                {
                    number: resolution.path
                    for number, resolution in resolutions.items()
                    if resolution.path is not None
                }
            )
    if progress:
        progress(50, "文献记录和可用原文处理完成")

    audits: list[CitationAudit | None] = [None] * len(claims)
    grouped: dict[Path, list[tuple[int, int, int, str]]] = {}
    for index, (paragraph, number, claim) in enumerate(claims):
        reference = references.get(number, "")
        resolution = resolutions.get(number)
        resolution_fields = _resolution_fields(resolution)
        if not reference:
            audits[index] = CitationAudit(
                claim,
                paragraph,
                number,
                "",
                "",
                "MISSING_REFERENCE",
                "写作稿中使用了该引用编号，但参考文献表没有对应条目。",
            )
            continue
        source = matched_sources.get(number)
        if source is None:
            if resolution is not None:
                unavailable_message = (
                    f"{resolution.source_message} 请导入该文献的PDF或EPUB后重试。"
                )
            elif resolution_error:
                unavailable_message = (
                    f"{resolution_error} 请导入该文献的PDF或EPUB后重试。"
                )
            else:
                unavailable_message = (
                    "找到了参考文献条目，但当前没有可核验原文。"
                    "请导入该文献的PDF或EPUB，或启用开放原文获取。"
                )
            audits[index] = CitationAudit(
                claim,
                paragraph,
                number,
                reference,
                "",
                "SOURCE_UNAVAILABLE",
                unavailable_message,
                **resolution_fields,
            )
            continue
        grouped.setdefault(source, []).append((index, paragraph, number, claim))

    grouped_items = list(grouped.items())
    for group_index, (source, items) in enumerate(grouped_items, start=1):
        unique_claims = list(dict.fromkeys(item[3] for item in items))
        try:
            verifications = verify_claims(unique_claims, source)
        except ValueError as error:
            for index, paragraph, number, claim in items:
                resolution = resolutions.get(number)
                audits[index] = CitationAudit(
                    claim,
                    paragraph,
                    number,
                    references[number],
                    str(source),
                    "SOURCE_UNAVAILABLE",
                    f"原文无法提取用于核验：{error}",
                    **_resolution_fields(resolution),
                )
            continue
        by_claim = {
            verification.claim.casefold(): verification
            for verification in verifications
        }
        for item in items:
            index, paragraph, number, claim = item
            verification = by_claim[claim.casefold()]
            audit = CitationAudit(
                claim,
                paragraph,
                number,
                references[number],
                str(source),
                verification.verdict,
                verification.explanation,
                verification.evidences,
            )
            audits[index] = replace(
                audit, **_resolution_fields(resolutions.get(number))
            )
        if progress:
            progress(
                50 + round(25 * group_index / len(grouped_items)),
                f"正在核对原文证据（{group_index}/{len(grouped_items)}）",
            )
    completed = [audit for audit in audits if audit is not None]
    if progress:
        progress(75, f"已完成{len(completed)}处引用的规则核验")
    return [
        replace(audit, location=locations.get(audit.paragraph, f"第{audit.paragraph}处"))
        for audit in completed
    ]
