import json
from pathlib import Path

from studylint.cli import build_parser, run_check, run_paper
from studylint.gui import check_to_html, paper_to_html
from studylint.models import Finding
from studylint.papers import PaperMatch, PaperVerification
from studylint.reporters import render_html


def test_json_report(tmp_path: Path) -> None:
    notes = tmp_path / "notes.md"
    source = tmp_path / "slides.md"
    output = tmp_path / "report.json"
    notes.write_text("这是一条没有来源的重要学习结论。", encoding="utf-8")
    source.write_text("课程材料。", encoding="utf-8")

    args = build_parser().parse_args(
        [
            "check",
            str(notes),
            "--source",
            str(source),
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )
    assert run_check(args) == 0
    payload = json.loads(output.read_text(encoding="utf-8"))
    assert payload["summary"] == {"errors": 0, "warnings": 1, "total": 1}
    assert payload["findings"][0]["code"] == "ST004"


def test_source_directory_and_html_report(tmp_path: Path) -> None:
    notes = tmp_path / "notes.md"
    sources = tmp_path / "materials"
    sources.mkdir()
    notes.write_text("信息能够减少决策过程中的不确定性。", encoding="utf-8")
    (sources / "slides.md").write_text(
        "信息能够减少决策过程中的不确定性。", encoding="utf-8"
    )

    args = build_parser().parse_args(
        [
            "check",
            str(notes),
            "--source-dir",
            str(sources),
            "--format",
            "html",
        ]
    )
    assert run_check(args) == 0
    report = tmp_path / "notes-studylint-report.html"
    content = report.read_text(encoding="utf-8")
    assert "可能相关的来源" in content
    assert "slides.md" in content


def test_html_escapes_user_content(tmp_path: Path) -> None:
    report = render_html(
        tmp_path / "notes.md",
        [
            Finding(
                "ST004",
                "warning",
                1,
                "<script>alert(1)</script>",
                title="不安全<title>",
                note_text="<img src=x onerror=alert(1)>",
            )
        ],
    )
    assert "<script>alert(1)</script>" not in report
    assert "&lt;script&gt;" in report
    assert "<img src=x" not in report


def test_gui_check_creates_report(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    sources = tmp_path / "materials"
    sources.mkdir()
    notes.write_text("这是一条没有来源但可以检查的较长结论。", encoding="utf-8")
    (sources / "slides.txt").write_text("相关课程材料。", encoding="utf-8")

    output, counts = check_to_html(notes, sources)
    assert output.is_file()
    assert counts["warnings"] == 1


def sample_verification() -> PaperVerification:
    return PaperVerification(
        query="测试论文",
        query_type="bibliographic",
        matches=(
            PaperMatch(
                title="测试论文",
                doi="10.1234/example",
                authors=("张三",),
                year="2026",
                venue="测试期刊",
                publisher="测试出版社",
                work_type="journal-article",
                url="https://doi.org/10.1234/example",
                similarity=100,
            ),
        ),
    )


def test_paper_cli_html(monkeypatch, tmp_path: Path) -> None:
    output = tmp_path / "paper.html"
    monkeypatch.setattr("studylint.cli.verify_paper", lambda query, email="": sample_verification())
    args = build_parser().parse_args(
        ["paper", "测试论文", "--format", "html", "--output", str(output)]
    )

    assert run_paper(args) == 0
    assert "查看论文页面" in output.read_text(encoding="utf-8")


def test_gui_paper_helper(tmp_path: Path) -> None:
    output, verification = paper_to_html(
        "测试论文", tmp_path, lookup=lambda query: sample_verification()
    )

    assert output.is_file()
    assert verification.matches[0].doi == "10.1234/example"
