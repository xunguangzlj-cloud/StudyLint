from __future__ import annotations

import argparse
import os
import sys
import webbrowser
from pathlib import Path

from studylint.ai_audit import AIConfig, AI_MODES, AI_SKILLS, deep_verify_audits
from studylint.manuscripts import audit_manuscript, scan_manuscript_issues
from studylint.parsers import discover_sources, load_sources, parse_notes
from studylint.papers import PaperLookupError, parse_queries, read_query_file, verify_papers
from studylint.reporters import (
    render_console,
    render_html,
    render_json,
    render_manuscript_console,
    render_manuscript_html,
    render_manuscript_json,
    render_paper_batch_console,
    render_paper_batch_html,
)
from studylint.rules import lint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studylint",
        description="核查AI总结与论文内容中的可验证幻觉。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="检查一份AI总结。")
    check.add_argument("notes", type=Path, help="AI总结文件路径。")
    check.add_argument(
        "--source",
        "-s",
        action="append",
        type=Path,
        help="课程材料文件；可重复使用以添加多个来源。",
    )
    check.add_argument(
        "--source-dir",
        action="append",
        type=Path,
        help="递归发现资料目录中的支持文件。",
    )
    check.add_argument(
        "--format",
        choices=("console", "json", "html"),
        default="console",
        help="报告格式。",
    )
    check.add_argument("--output", "-o", type=Path, help="报告输出路径。")
    check.add_argument(
        "--open",
        action="store_true",
        help="生成后在默认浏览器中打开HTML报告。",
    )
    subparsers.add_parser("gui", help="打开本地图形界面。")
    paper = subparsers.add_parser("paper", help="按DOI或题名核实论文记录。")
    paper.add_argument("query", nargs="?", help="论文DOI、标题或完整参考文献。")
    paper.add_argument(
        "--file",
        type=Path,
        help="批量论文清单，每行一个DOI、标题或完整参考文献。",
    )
    paper.add_argument(
        "--format",
        choices=("console", "html"),
        default="console",
        help="结果格式。",
    )
    paper.add_argument("--output", "-o", type=Path, help="HTML结果输出路径。")
    paper.add_argument("--open", action="store_true", help="在浏览器中打开HTML结果。")
    paper.add_argument(
        "--email",
        default="",
        help="可选联系邮箱，用于Crossref礼貌请求池。",
    )
    manuscript = subparsers.add_parser(
        "manuscript", help="核查论文稿件中的引用证据与内容幻觉。"
    )
    manuscript.add_argument("draft", type=Path, help="论文稿件。")
    manuscript.add_argument(
        "--source",
        "-s",
        action="append",
        type=Path,
        help="本地参考文献PDF或EPUB；可重复使用。",
    )
    manuscript.add_argument(
        "--source-dir",
        action="append",
        type=Path,
        help="递归读取文件夹中的参考文献PDF或EPUB。",
    )
    manuscript.add_argument(
        "--fetch-fulltext",
        action="store_true",
        help="从开放数据库核验文献记录并获取可合法访问的开放原文。",
    )
    manuscript.add_argument(
        "--format",
        choices=("console", "json", "html"),
        default="console",
        help="结果格式。",
    )
    manuscript.add_argument("--output", "-o", type=Path, help="结果输出路径。")
    manuscript.add_argument("--open", action="store_true", help="在浏览器中打开HTML结果。")
    manuscript.add_argument(
        "--ai",
        action="store_true",
        help="启用使用者自行配置的AI深度核验。",
    )
    manuscript.add_argument(
        "--ai-endpoint",
        default="https://api.openai.com/v1/chat/completions",
        help="OpenAI兼容的chat/completions完整地址。",
    )
    manuscript.add_argument("--ai-model", default="", help="AI接口的模型名称。")
    manuscript.add_argument(
        "--ai-mode",
        choices=tuple(AI_MODES),
        default="fast",
        help="AI核验模式。",
    )
    manuscript.add_argument(
        "--ai-skill",
        choices=tuple(AI_SKILLS),
        default="general",
        help="AI核验技能。",
    )
    manuscript.add_argument(
        "--ai-key-env",
        default="STUDYLINT_AI_API_KEY",
        help="保存API Key的环境变量名；密钥不会作为命令行参数传入。",
    )
    return parser


def collect_source_paths(args: argparse.Namespace) -> list[Path]:
    paths = list(args.source or [])
    for directory in args.source_dir or []:
        paths.extend(discover_sources(directory, exclude=args.notes))
    unique: dict[Path, None] = {}
    for path in paths:
        unique[path.resolve()] = None
    return list(unique)


def run_check(args: argparse.Namespace) -> int:
    if not args.notes.is_file():
        print(f"找不到笔记文件：{args.notes}", file=sys.stderr)
        return 2
    try:
        source_paths = collect_source_paths(args)
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 2
    if not source_paths:
        print("请至少提供一个 --source 或 --source-dir。", file=sys.stderr)
        return 2
    missing_sources = [path for path in source_paths if not path.is_file()]
    if missing_sources:
        for path in missing_sources:
            print(f"找不到来源文件：{path}", file=sys.stderr)
        return 2

    try:
        units = parse_notes(args.notes)
        sources = load_sources(source_paths)
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    findings = lint(units, sources)
    renderers = {
        "console": render_console,
        "json": render_json,
        "html": render_html,
    }
    report = renderers[args.format](args.notes, findings)
    output = args.output
    if args.format == "html" and output is None:
        output = args.notes.with_name(f"{args.notes.stem}-studylint-report.html")
    if output:
        output.write_text(report + "\n", encoding="utf-8")
        print(f"报告已生成：{output}")
    else:
        print(report)
    if args.open:
        if args.format != "html" or output is None:
            print("--open 只能与HTML报告一起使用。", file=sys.stderr)
            return 2
        webbrowser.open(output.resolve().as_uri())
    return 1 if any(finding.severity == "error" for finding in findings) else 0


def run_paper(args: argparse.Namespace) -> int:
    try:
        queries = parse_queries(args.query or "")
        if args.file:
            queries.extend(read_query_file(args.file))
        queries = list(dict.fromkeys(queries))
        verifications = verify_papers(queries, email=args.email)
    except (PaperLookupError, ValueError) as error:
        print(f"论文核验失败：{error}", file=sys.stderr)
        return 2

    if args.format == "html":
        output = args.output or Path("studylint-paper-report.html")
        try:
            output.write_text(render_paper_batch_html(verifications), encoding="utf-8")
        except OSError as error:
            print(f"无法写入核验结果：{error}", file=sys.stderr)
            return 2
        print(f"论文核验结果已生成：{output}")
        if args.open:
            webbrowser.open(output.resolve().as_uri())
    else:
        if args.output or args.open:
            print("--output和--open只能与HTML格式一起使用。", file=sys.stderr)
            return 2
        print(render_paper_batch_console(verifications))
    accepted = {"VERIFIED_METADATA", "IDENTIFIER_FOUND"}
    return 0 if all(item.verdict in accepted for item in verifications) else 1


def run_manuscript(args: argparse.Namespace) -> int:
    reference_inputs = list(args.source or []) + list(args.source_dir or [])
    try:
        audits = audit_manuscript(
            args.draft,
            reference_inputs,
            auto_fetch=args.fetch_fulltext,
            cache_dir=args.draft.parent / "StudyLint-原文",
        )
        issues = scan_manuscript_issues(args.draft)
        if args.ai:
            api_key = os.environ.get(args.ai_key_env, "")
            if not api_key:
                raise ValueError(f"环境变量{args.ai_key_env}中没有API Key。")
            audits = deep_verify_audits(
                audits,
                AIConfig(
                    endpoint=args.ai_endpoint,
                    model=args.ai_model,
                    api_key=api_key,
                    mode=args.ai_mode,
                    skill=args.ai_skill,
                ),
            )
    except (OSError, ValueError) as error:
        print(f"论文内容核查失败：{error}", file=sys.stderr)
        return 2

    renderers = {
        "console": lambda: render_manuscript_console(audits, issues),
        "json": lambda: render_manuscript_json(args.draft, audits, issues),
        "html": lambda: render_manuscript_html(args.draft, audits, issues),
    }
    report = renderers[args.format]()
    output = args.output
    if args.format == "html" and output is None:
        output = args.draft.with_name(
            f"{args.draft.stem}-paper-content-audit.html"
        )
    if output:
        try:
            output.write_text(report + "\n", encoding="utf-8")
        except OSError as error:
            print(f"无法写入核验结果：{error}", file=sys.stderr)
            return 2
        print(f"论文内容核查结果已生成：{output}")
    else:
        print(report)
    if args.open:
        if args.format != "html" or output is None:
            print("--open 只能与HTML结果一起使用。", file=sys.stderr)
            return 2
        webbrowser.open(output.resolve().as_uri())
    rules_passed = all(audit.verdict == "DIRECT_SUPPORT" for audit in audits)
    ai_passed = not args.ai or all(
        audit.ai_verdict in {"SUPPORTED", "NOT_RUN_RULE_DIRECT"}
        for audit in audits
    )
    return 0 if rules_passed and ai_passed and not issues else 1


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        raise SystemExit(run_check(args))
    if args.command == "gui":
        from studylint.gui import main as gui_main

        gui_main()
    if args.command == "paper":
        raise SystemExit(run_paper(args))
    if args.command == "manuscript":
        raise SystemExit(run_manuscript(args))
