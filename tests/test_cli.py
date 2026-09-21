import json
from pathlib import Path

from studylint.cli import build_parser, run_check


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

