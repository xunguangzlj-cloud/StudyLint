from __future__ import annotations

import argparse
import sys
import webbrowser
from pathlib import Path

from studylint.parsers import discover_sources, load_source, parse_notes
from studylint.reporters import render_console, render_html, render_json
from studylint.rules import lint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studylint",
        description="对照课程材料检查学习笔记中的引用与结论。",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="检查一份学习笔记。")
    check.add_argument("notes", type=Path, help="笔记文件路径。")
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
        sources = [load_source(path) for path in source_paths]
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


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        raise SystemExit(run_check(args))
    if args.command == "gui":
        from studylint.gui import main as gui_main

        gui_main()
