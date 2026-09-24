import json
import os
from dataclasses import replace
from pathlib import Path

from studylint import PROJECT_URL
from studylint import gui
from studylint.cli import build_parser, run_check, run_manuscript, run_paper
from studylint.gui import (
    check_to_html,
    manuscript_to_html,
    open_local_report,
    paper_to_html,
    papers_to_html,
)
from studylint.models import Finding
from studylint.manuscripts import CitationAudit, ManuscriptIssue
from studylint.papers import PaperMatch, PaperVerification
from studylint.reporters import render_html, render_manuscript_html


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
    assert payload["summary"] == {"errors": 0, "warnings": 0, "total": 0}
    assert payload["findings"] == []


def test_open_local_report_uses_windows_file_association(
    tmp_path: Path, monkeypatch
) -> None:
    report = tmp_path / "report.html"
    report.write_text("<p>ok</p>", encoding="utf-8")
    opened: list[Path] = []
    monkeypatch.setattr(gui.sys, "platform", "win32")
    monkeypatch.setattr(
        os, "startfile", lambda path: opened.append(Path(path)), raising=False
    )
    monkeypatch.setattr(
        gui.webbrowser,
        "open_new_tab",
        lambda _url: (_ for _ in ()).throw(AssertionError("不应回退到浏览器模块")),
    )

    assert open_local_report(report) is True
    assert opened == [report.resolve()]


def test_open_local_report_falls_back_and_reports_failure(
    tmp_path: Path, monkeypatch
) -> None:
    report = tmp_path / "report.html"
    report.write_text("<p>ok</p>", encoding="utf-8")
    monkeypatch.setattr(gui.sys, "platform", "win32")
    monkeypatch.setattr(
        os,
        "startfile",
        lambda _path: (_ for _ in ()).throw(OSError("association failed")),
        raising=False,
    )
    monkeypatch.setattr(gui.webbrowser, "open_new_tab", lambda _url: False)

    assert open_local_report(report) is False


def test_source_directory_and_html_report(tmp_path: Path) -> None:
    notes = tmp_path / "notes.md"
    sources = tmp_path / "materials"
    sources.mkdir()
    notes.write_text(
        "信息能够减少决策过程中的不确定性。[slides.md#page=1]",
        encoding="utf-8",
    )
    (sources / "slides.md").write_text(
        "<!-- page: 1 -->\n本页介绍信息系统的组成。\n"
        "<!-- page: 4 -->\n信息能够减少决策过程中的不确定性。",
        encoding="utf-8",
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
                "ST006",
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
    assert ">⭐ Star</a>" in report
    assert PROJECT_URL in report


def test_gui_check_creates_report(tmp_path: Path) -> None:
    notes = tmp_path / "notes.txt"
    sources = tmp_path / "materials"
    sources.mkdir()
    notes.write_text("这是一条没有来源但可以检查的较长结论。", encoding="utf-8")
    (sources / "slides.txt").write_text("相关课程材料。", encoding="utf-8")

    events: list[tuple[int, str]] = []
    output, counts = check_to_html(
        notes,
        sources,
        progress=lambda value, message: events.append((value, message)),
    )
    assert output.is_file()
    assert counts["warnings"] == 0
    assert events[-1] == (100, "核查完成")


def test_gui_check_accepts_individual_source_files(tmp_path: Path) -> None:
    import pymupdf

    notes = tmp_path / "notes.txt"
    first = tmp_path / "slides.pdf"
    second = tmp_path / "lecture.md"
    notes.write_text("这是一条没有来源但可以检查的较长结论。", encoding="utf-8")
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), "First course source")
    document.save(first)
    document.close()
    second.write_text("第二份课程资料。", encoding="utf-8")

    output, counts = check_to_html(notes, [first, second])

    assert output.is_file()
    assert counts["warnings"] == 0


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
    monkeypatch.setattr(
        "studylint.cli.verify_papers",
        lambda queries, email="": [sample_verification()],
    )
    args = build_parser().parse_args(
        ["paper", "测试论文", "--format", "html", "--output", str(output)]
    )

    assert run_paper(args) == 0
    report = output.read_text(encoding="utf-8")
    assert "没有需要继续人工核查的论文" in report
    assert "测试论文" not in report


def test_gui_paper_helper(tmp_path: Path) -> None:
    output, verification = paper_to_html(
        "测试论文", tmp_path, lookup=lambda query: sample_verification()
    )

    assert output.is_file()
    assert verification.matches[0].doi == "10.1234/example"


def test_paper_cli_batch_file(monkeypatch, tmp_path: Path) -> None:
    source = tmp_path / "papers.txt"
    output = tmp_path / "batch.html"
    source.write_text("第一篇\n第二篇\n", encoding="utf-8")

    def fake_lookup(queries, email=""):
        assert queries == ["第一篇", "第二篇"]
        return [sample_verification(), sample_verification()]

    monkeypatch.setattr("studylint.cli.verify_papers", fake_lookup)
    args = build_parser().parse_args(
        ["paper", "--file", str(source), "--format", "html", "--output", str(output)]
    )

    assert run_paper(args) == 0
    report = output.read_text(encoding="utf-8")
    assert "需要自行核查 <strong>0</strong> 篇" in report
    assert "没有需要继续人工核查的论文" in report


def test_gui_batch_paper_helper(tmp_path: Path) -> None:
    events: list[tuple[int, str]] = []

    def lookup(queries, progress=None):
        results = []
        for completed, _query in enumerate(queries, start=1):
            results.append(sample_verification())
            if progress:
                progress(completed, len(queries))
        return results

    output, verifications = papers_to_html(
        ["第一篇", "第二篇"],
        tmp_path,
        lookup=lookup,
        progress=lambda value, message: events.append((value, message)),
    )

    assert output.is_file()
    assert len(verifications) == 2
    assert events[-1] == (100, "论文核验完成")
    assert any(value == 90 and "2/2" in message for value, message in events)


def test_manuscript_cli_and_gui_helper(monkeypatch, tmp_path: Path) -> None:
    import pymupdf

    draft = tmp_path / "draft.md"
    paper = tmp_path / "1-example.pdf"
    output = tmp_path / "manuscript.html"
    claim = "The treatment reduced complications by 20 percent."
    draft.write_text(
        f"{claim} [1]\n\n# References\n[1] Example study.\n",
        encoding="utf-8",
    )
    document = pymupdf.open()
    page = document.new_page()
    page.insert_text((72, 72), claim)
    document.save(paper)
    document.close()
    args = build_parser().parse_args(
        [
            "manuscript",
            str(draft),
            "--source",
            str(paper),
            "--format",
            "html",
            "--output",
            str(output),
        ]
    )

    assert run_manuscript(args) == 0
    assert "原文直接支持" in output.read_text(encoding="utf-8")

    events: list[tuple[int, str]] = []
    gui_output, audits = manuscript_to_html(
        draft,
        [paper],
        progress=lambda value, message: events.append((value, message)),
    )
    assert gui_output.is_file()
    assert audits[0].verdict == "DIRECT_SUPPORT"
    assert audits[0].location == "第1行"
    assert events[-1] == (100, "论文内容核查完成")
    assert "第1行" in gui_output.read_text(encoding="utf-8")

    captured = {}

    def fake_deep_verify(items, config):
        captured["model"] = config.model
        captured["mode"] = config.mode
        captured["skill"] = config.skill
        return [replace(item, ai_verdict="SUPPORTED") for item in items]

    monkeypatch.setenv("TEST_STUDYLINT_AI_KEY", "test-key")
    monkeypatch.setattr("studylint.cli.deep_verify_audits", fake_deep_verify)
    ai_args = build_parser().parse_args(
        [
            "manuscript",
            str(draft),
            "--source",
            str(paper),
            "--format",
            "html",
            "--output",
            str(output),
            "--ai",
            "--ai-model",
            "test-model",
            "--ai-mode",
            "strict",
            "--ai-skill",
            "biomedical",
            "--ai-key-env",
            "TEST_STUDYLINT_AI_KEY",
        ]
    )

    assert run_manuscript(ai_args) == 0
    assert captured == {
        "model": "test-model",
        "mode": "strict",
        "skill": "biomedical",
    }

    monkeypatch.setattr(
        "studylint.cli.deep_verify_audits",
        lambda items, config: [
            replace(item, ai_verdict="OVERSTATED") for item in items
        ],
    )
    assert run_manuscript(ai_args) == 1


def test_manuscript_html_opens_with_inline_problem_annotations(tmp_path: Path) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        "该研究证明所有学生的成绩都会提高 [1]。\n\n"
        "参考文献\n[1] Example study. 2024.\n",
        encoding="utf-8",
    )
    audit = CitationAudit(
        claim="该研究证明所有学生的成绩都会提高。",
        paragraph=1,
        citation_number=1,
        reference_text="Example study. 2024.",
        source_path="paper.pdf",
        verdict="POSSIBLE_OVERSTATEMENT",
        explanation="原文只说明可能提高，当前表述过于确定。",
    )

    report = render_manuscript_html(draft, [audit])

    assert 'class="annotation-paper"' in report
    assert 'class="problem-text"' in report
    assert 'class="issue-marker"' in report
    assert "疑似夸大" in report
    assert "当前表述过于确定" in report
    assert "将鼠标移到红色感叹号上查看理由" in report


def test_supported_manuscript_text_is_not_marked_red(tmp_path: Path) -> None:
    draft = tmp_path / "draft.txt"
    draft.write_text(
        "该结论得到原文直接支持 [1]。\n参考文献\n[1] Example.\n",
        encoding="utf-8",
    )
    audit = CitationAudit(
        claim="该结论得到原文直接支持。",
        paragraph=1,
        citation_number=1,
        reference_text="Example.",
        source_path="paper.pdf",
        verdict="DIRECT_SUPPORT",
        explanation="在论文正文中找到了直接对应的原文。",
    )

    report = render_manuscript_html(draft, [audit])

    assert 'class="problem-text"' not in report
    assert 'class="issue-marker"' not in report
    assert "没有发现需要在原稿中标红的问题" in report


def test_reference_issue_is_annotated_in_reference_list(tmp_path: Path) -> None:
    draft = tmp_path / "draft.md"
    draft.write_text(
        "正文内容。\n\n参考文献\n[1] TODO citation. 2099.\n",
        encoding="utf-8",
    )
    issue = ManuscriptIssue(
        code="PLACEHOLDER_REFERENCE",
        category="引用与来源",
        paragraph=0,
        message="参考文献[1]仍含占位内容。",
        excerpt="TODO citation. 2099.",
        location="参考文献表",
    )

    report = render_manuscript_html(draft, [], [issue])

    assert "TODO citation. 2099." in report
    assert 'class="problem-text"' in report
    assert "仍含占位内容" in report
