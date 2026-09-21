from __future__ import annotations

import argparse
import sys
from pathlib import Path

from studylint.parsers import load_source, parse_notes
from studylint.reporters import render_console, render_json
from studylint.rules import lint


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studylint",
        description="Check study notes against cited source material.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    check = subparsers.add_parser("check", help="Check a Markdown notes file.")
    check.add_argument("notes", type=Path, help="Path to the Markdown notes file.")
    check.add_argument(
        "--source",
        "-s",
        action="append",
        type=Path,
        required=True,
        help="Source file. Repeat for multiple sources.",
    )
    check.add_argument(
        "--format",
        choices=("console", "json"),
        default="console",
        help="Report format.",
    )
    check.add_argument("--output", "-o", type=Path, help="Write the report to a file.")
    return parser


def run_check(args: argparse.Namespace) -> int:
    if not args.notes.is_file():
        print(f"Notes file not found: {args.notes}", file=sys.stderr)
        return 2
    missing_sources = [path for path in args.source if not path.is_file()]
    if missing_sources:
        for path in missing_sources:
            print(f"Source file not found: {path}", file=sys.stderr)
        return 2

    try:
        units = parse_notes(args.notes)
        sources = [load_source(path) for path in args.source]
    except (OSError, ValueError) as error:
        print(str(error), file=sys.stderr)
        return 2

    findings = lint(units, sources)
    report = (
        render_json(args.notes, findings)
        if args.format == "json"
        else render_console(args.notes, findings)
    )
    if args.output:
        args.output.write_text(report + "\n", encoding="utf-8")
    else:
        print(report)
    return 1 if any(finding.severity == "error" for finding in findings) else 0


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "check":
        raise SystemExit(run_check(args))

