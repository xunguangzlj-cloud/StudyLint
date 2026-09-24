from __future__ import annotations

import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from rapidfuzz import fuzz

from studylint.parsers import load_source
from studylint.papers import parse_queries


MIN_EVIDENCE_SCORE = 35
PARTIAL_SUPPORT_SCORE = 50
LIKELY_SUPPORT_SCORE = 75
ENGLISH_STOPWORDS = {
    "a", "an", "and", "are", "as", "at", "be", "by", "for", "from",
    "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
    "was", "were", "with",
}
NEGATION_PATTERNS = (
    "没有", "并非", "不能", "不支持", "不相关", "不增加", "不降低",
    "不显著", "未发现", "未显示", "无显著", "无差异",
    " no ", " not ", " never ", " without ", "did not", "cannot",
)
STRONG_CLAIM_PATTERNS = (
    "证明", "证实", "必然", "导致", "完全", "确定", "肯定",
    "proves", "proved", "causes", "caused", "always", "definitively",
)
HEDGE_PATTERNS = (
    "可能", "也许", "提示", "暗示", "相关", "尚不清楚", "无统计学意义",
    "may", "might", "could", "suggests", "suggested", "associated",
    "not statistically significant",
)


@dataclass(frozen=True)
class ClaimEvidence:
    source_path: str
    page: int
    text: str
    score: int
    locator_type: str = "page"

    def to_dict(self) -> dict[str, str | int]:
        return {
            "source_path": self.source_path,
            "page": self.page,
            "text": self.text,
            "score": self.score,
            "locator_type": self.locator_type,
        }


@dataclass(frozen=True)
class ClaimVerification:
    claim: str
    verdict: str
    explanation: str
    evidences: tuple[ClaimEvidence, ...]

    def to_dict(self) -> dict[str, object]:
        return {
            "claim": self.claim,
            "verdict": self.verdict,
            "explanation": self.explanation,
            "evidences": [evidence.to_dict() for evidence in self.evidences],
        }


@lru_cache(maxsize=8192)
def _normalized_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value.casefold())
    return "".join(character for character in value if character.isalnum())


@lru_cache(maxsize=8192)
def _features(value: str) -> Counter[str]:
    value = unicodedata.normalize("NFKC", value.casefold())
    features: list[str] = []
    for token in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?%?|[\u4e00-\u9fff]+", value):
        if re.fullmatch(r"[\u4e00-\u9fff]+", token):
            features.extend(
                token[index : index + 2]
                for index in range(max(1, len(token) - 1))
            )
        elif token not in ENGLISH_STOPWORDS:
            features.append(token)
    return Counter(features)


def _similarity(claim: str, evidence: str) -> int:
    claim_features = _features(claim)
    evidence_features = _features(evidence)
    if not claim_features or not evidence_features:
        return 0
    overlap = sum((claim_features & evidence_features).values())
    precision = overlap / sum(claim_features.values())
    recall = overlap / sum(evidence_features.values())
    feature_score = (
        round(200 * precision * recall / (precision + recall))
        if precision and recall
        else 0
    )
    character_score = round(
        fuzz.ratio(_normalized_text(claim), _normalized_text(evidence))
    )
    return max(feature_score, character_score)


def _sentences(text: str) -> list[str]:
    joined = re.sub(r"(?<![.!?。！？])\n(?=\S)", " ", text.replace("\r", ""))
    parts = re.split(r"\n{2,}|(?<=[.!?。！？])\s*", joined)
    return [part.strip() for part in parts if len(_normalized_text(part)) >= 8]


def _numbers(value: str) -> set[str]:
    normalized = unicodedata.normalize("NFKC", value).replace(",", "")
    return set(re.findall(r"(?<![\w.])[+-]?\d+(?:\.\d+)?%?", normalized))


def _contains_pattern(value: str, patterns: tuple[str, ...]) -> bool:
    lowered = f" {unicodedata.normalize('NFKC', value.casefold())} "
    return any(pattern in lowered for pattern in patterns)


def _classify(claim: str, evidence: ClaimEvidence) -> tuple[str, str]:
    if evidence.score < MIN_EVIDENCE_SCORE:
        return "INSUFFICIENT_EVIDENCE", "正文中没有找到足够相关的原文。"

    claim_numbers = _numbers(claim)
    evidence_numbers = _numbers(evidence.text)
    if (
        evidence.score >= PARTIAL_SUPPORT_SCORE
        and claim_numbers
        and not claim_numbers.issubset(evidence_numbers)
    ):
        return "NUMERIC_MISMATCH", "找到了相关原文，但AI结论中的数字未在该证据中匹配。"

    claim_negative = _contains_pattern(claim, NEGATION_PATTERNS)
    evidence_negative = _contains_pattern(evidence.text, NEGATION_PATTERNS)
    if evidence.score >= 70 and claim_negative != evidence_negative:
        return "POSSIBLE_CONTRADICTION", "AI结论与原文的肯定/否定方向可能相反。"

    if (
        evidence.score >= PARTIAL_SUPPORT_SCORE
        and _contains_pattern(claim, STRONG_CLAIM_PATTERNS)
        and _contains_pattern(evidence.text, HEDGE_PATTERNS)
    ):
        return "POSSIBLE_OVERSTATEMENT", "原文使用了可能、相关或提示等谨慎表述，AI结论可能将其夸大为确定结论。"

    normalized_claim = _normalized_text(claim)
    normalized_evidence = _normalized_text(evidence.text)
    if normalized_claim and normalized_claim in normalized_evidence:
        return "DIRECT_SUPPORT", "在论文正文中找到了与AI结论直接对应的原文。"
    if evidence.score >= LIKELY_SUPPORT_SCORE:
        return "LIKELY_SUPPORT", "原文与AI结论高度相关，但仍需人工确认语义和研究边界。"
    if evidence.score >= PARTIAL_SUPPORT_SCORE:
        return "PARTIAL_SUPPORT", "找到了部分相关证据，但尚不足以确认整句结论。"
    return "INSUFFICIENT_EVIDENCE", "只找到了弱相关内容，不能确认论文支持该结论。"


def verify_claims(claims: list[str], paper_path: Path) -> list[ClaimVerification]:
    cleaned_claims = parse_queries("\n".join(claims))
    if not cleaned_claims:
        raise ValueError("请至少输入一条AI结论。")
    if not paper_path.is_file():
        raise ValueError(f"找不到论文原文文件：{paper_path}")
    if paper_path.suffix.lower() not in {".pdf", ".epub"}:
        raise ValueError("论文正文核验支持PDF和EPUB文件。")

    document = load_source(paper_path)
    candidates = [
        (span.locator_type, span.locator_value, sentence)
        for span in document.spans
        for sentence in _sentences(span.text)
    ]
    if not candidates:
        raise ValueError("该原文没有可提取的文字；若为扫描版PDF，请先进行OCR。")

    results: list[ClaimVerification] = []
    for claim in cleaned_claims:
        ranked = sorted(
            (
                ClaimEvidence(
                    str(paper_path),
                    location,
                    text,
                    _similarity(claim, text),
                    locator_type,
                )
                for locator_type, location, text in candidates
            ),
            key=lambda item: item.score,
            reverse=True,
        )[:5]
        best = ranked[0]
        verdict, explanation = _classify(claim, best)
        results.append(
            ClaimVerification(claim, verdict, explanation, tuple(ranked))
        )
    return results
