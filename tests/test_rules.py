from pathlib import Path

from studylint.parsers import load_source, parse_notes
from studylint.rules import lint


def _lint(tmp_path: Path, notes: str, source: str) -> list[str]:
    notes_path = tmp_path / "notes.md"
    source_path = tmp_path / "slides.md"
    notes_path.write_text(notes, encoding="utf-8")
    source_path.write_text(source, encoding="utf-8")
    findings = lint(parse_notes(notes_path), [load_source(source_path)])
    return [finding.code for finding in findings]


def test_valid_quote_and_citation(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "信息具有“可传递性”，能够被不同主体接收。[slides.md#page=2]",
        "<!-- page: 2 -->\n信息具有可传递性，能够被不同主体接收。",
    )
    assert codes == []


def test_missing_source_and_invalid_page(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "结论一需要足够长。[missing.pdf#page=1]\n结论二需要足够长。[slides.md#page=9]",
        "第一页内容",
    )
    assert codes == ["ST001", "ST002"]


def test_quote_missing_and_uncited_claim(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "课程明确要求“逐字背诵所有例子”。[slides.md#page=1]\n这是一条没有引用来源的重要学习结论。",
        "课程要求理解概念，不要求背诵例子。",
    )
    assert codes == ["ST003", "ST004"]


def test_conflicting_definitions(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "信息：能够减少不确定性的内容。[slides.md#page=1]\n"
        "信息：没有经过处理的随机字符集合。[slides.md#page=1]",
        "信息是能够减少不确定性的内容。",
    )
    assert codes == ["ST005"]

