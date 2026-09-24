from pathlib import Path

import pymupdf
import pytest

from studylint.claims import verify_claims


def make_pdf(path: Path, lines: list[str]) -> None:
    document = pymupdf.open()
    page = document.new_page()
    for index, line in enumerate(lines):
        page.insert_text((72, 72 + index * 28), line)
    document.save(path)
    document.close()


def test_direct_support_and_page_number(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    claim = "The treatment reduced complications by 20 percent."
    make_pdf(paper, [claim, "A second unrelated sentence."])

    verification = verify_claims([claim], paper)[0]

    assert verification.verdict == "DIRECT_SUPPORT"
    assert verification.evidences[0].page == 1
    assert verification.evidences[0].score == 100


def test_numeric_mismatch_is_not_reported_as_support(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(paper, ["The treatment reduced complications by 20 percent."])

    verification = verify_claims(
        ["The treatment reduced complications by 50 percent."], paper
    )[0]

    assert verification.verdict == "NUMERIC_MISMATCH"
    assert "数字" in verification.explanation


def test_hedged_evidence_flags_overstatement(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(
        paper,
        ["The results suggest that the intervention may improve recovery."],
    )

    verification = verify_claims(
        ["The results prove that the intervention improves recovery."], paper
    )[0]

    assert verification.verdict == "POSSIBLE_OVERSTATEMENT"


def test_opposite_polarity_flags_possible_contradiction(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(paper, ["The treatment did not reduce mortality."])

    verification = verify_claims(
        ["The treatment reduced mortality."], paper
    )[0]

    assert verification.verdict == "POSSIBLE_CONTRADICTION"


def test_unrelated_claim_has_insufficient_evidence(tmp_path: Path) -> None:
    paper = tmp_path / "paper.pdf"
    make_pdf(paper, ["The experiment measured temperature in living cells."])

    verification = verify_claims(
        ["The study established a new theory of economic growth."], paper
    )[0]

    assert verification.verdict == "INSUFFICIENT_EVIDENCE"


def test_scanned_or_blank_pdf_requests_ocr(tmp_path: Path) -> None:
    paper = tmp_path / "blank.pdf"
    make_pdf(paper, [])

    with pytest.raises(ValueError, match="OCR"):
        verify_claims(["Any claim"], paper)
