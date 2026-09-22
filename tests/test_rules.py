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


def test_quote_missing_and_uncited_claim_is_not_flagged(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "课程明确要求“逐字背诵所有例子”。[slides.md#page=1]\n这是一条没有引用来源的重要学习结论。",
        "课程要求理解概念，不要求背诵例子。",
    )
    assert codes == ["ST003"]


def test_conflicting_definitions(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "信息：能够减少不确定性的内容。[slides.md#page=1]\n"
        "信息：没有经过处理的随机字符集合。[slides.md#page=1]",
        "信息是能够减少不确定性的内容。",
    )
    assert codes == ["ST005", "ST006"]


def test_ignore_next_rule(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "信息：能够减少不确定性的内容。\n"
        "<!-- studylint-ignore ST005 -->\n"
        "信息：没有经过处理的随机字符集合。",
        "信息是能够减少不确定性的内容。",
    )
    assert codes == []


def test_cited_mismatch_has_evidence_suggestion(tmp_path: Path) -> None:
    notes_path = tmp_path / "notes.md"
    source_path = tmp_path / "slides.md"
    notes_path.write_text(
        "信息能够减少决策过程中的不确定性。[slides.md#page=1]",
        encoding="utf-8",
    )
    source_path.write_text(
        "<!-- page: 1 -->\n本页介绍信息系统的组成。\n"
        "<!-- page: 4 -->\n信息能够减少决策过程中的不确定性。",
        encoding="utf-8",
    )

    findings = lint(parse_notes(notes_path), [load_source(source_path)])
    assert findings[0].code == "ST006"
    assert findings[0].suggestions[0].source_name == "slides.md"
    assert findings[0].suggestions[0].locator_value == 4
    assert findings[0].suggestions[0].score >= 90


def test_uncited_claim_is_not_flagged(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "研究表明该方法能够提高效率37%，而且一定优于其他方法。",
        "课程材料。",
    )
    assert codes == []


def test_cited_claim_matches_marked_page(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "信息能够减少决策中的不确定性。[slides.md#页=2]",
        "<!-- page: 2 -->\n信息能够减少决策中的不确定性。",
    )
    assert codes == []


def test_cited_claim_does_not_match_marked_page(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "香农在1948年首次提出知识管理理论。[slides.md#p=2]",
        "<!-- page: 2 -->\n本页介绍组织中的隐性知识与显性知识。",
    )
    assert codes == ["ST006"]


def test_empty_cited_page_requires_manual_check(tmp_path: Path) -> None:
    codes = _lint(
        tmp_path,
        "这条结论来自扫描图片页。[slides.md#page=2]",
        "<!-- page: 2 -->\n",
    )
    assert codes == ["ST008"]


def test_duplicate_source_names_are_ambiguous(tmp_path: Path) -> None:
    notes_path = tmp_path / "notes.md"
    notes_path.write_text("需要核对的结论。[slides.md#page=1]", encoding="utf-8")
    first = tmp_path / "a" / "slides.md"
    second = tmp_path / "b" / "slides.md"
    first.parent.mkdir()
    second.parent.mkdir()
    first.write_text("第一份资料", encoding="utf-8")
    second.write_text("第二份资料", encoding="utf-8")

    findings = lint(parse_notes(notes_path), [load_source(first), load_source(second)])
    assert [finding.code for finding in findings] == ["ST009"]
