from __future__ import annotations

import json
from pathlib import Path

from studylint.models import Finding


def summary(findings: list[Finding]) -> dict[str, int]:
    return {
        "errors": sum(finding.severity == "error" for finding in findings),
        "warnings": sum(finding.severity == "warning" for finding in findings),
        "total": len(findings),
    }


def render_console(notes_path: Path, findings: list[Finding]) -> str:
    lines = [f"StudyLint: {notes_path}"]
    for finding in findings:
        lines.append(
            f"{finding.severity.upper():7} {finding.code} "
            f"line {finding.line}: {finding.message}"
        )
    counts = summary(findings)
    lines.append(
        f"\n{counts['errors']} error(s), {counts['warnings']} warning(s), "
        f"{counts['total']} finding(s)"
    )
    return "\n".join(lines)


def render_json(notes_path: Path, findings: list[Finding]) -> str:
    payload = {
        "notes": str(notes_path),
        "summary": summary(findings),
        "findings": [finding.to_dict() for finding in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)

