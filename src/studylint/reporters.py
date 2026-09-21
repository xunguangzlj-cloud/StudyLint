from __future__ import annotations

import html
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
    severity_names = {"error": "错误", "warning": "警告"}
    for finding in findings:
        lines.append(
            f"{severity_names.get(finding.severity, finding.severity):4} "
            f"{finding.code} 第{finding.line}行：{finding.message}"
        )
        if finding.action:
            lines.append(f"       建议：{finding.action}")
        for suggestion in finding.suggestions:
            locator = (
                f"第{suggestion.locator_value}页"
                if suggestion.locator_type == "page"
                else f"{_format_time(suggestion.locator_value)}"
            )
            lines.append(
                f"       可能来源：{suggestion.source_name} {locator} "
                f"（相关度 {suggestion.score}%）"
            )
    counts = summary(findings)
    lines.append(
        f"\n{counts['errors']} 个错误，{counts['warnings']} 个警告，"
        f"共 {counts['total']} 个问题"
    )
    return "\n".join(lines)


def render_json(notes_path: Path, findings: list[Finding]) -> str:
    payload = {
        "notes": str(notes_path),
        "summary": summary(findings),
        "findings": [finding.to_dict() for finding in findings],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _format_time(seconds: int) -> str:
    hours, remainder = divmod(seconds, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def _source_link(source_path: str, locator_type: str, locator_value: int) -> str:
    uri = Path(source_path).resolve().as_uri()
    if locator_type == "page":
        return f"{uri}#page={locator_value}"
    return uri


def render_html(notes_path: Path, findings: list[Finding]) -> str:
    counts = summary(findings)
    cards: list[str] = []
    for finding in findings:
        severity_label = "错误" if finding.severity == "error" else "警告"
        suggestions = ""
        if finding.suggestions:
            items: list[str] = []
            for suggestion in finding.suggestions:
                locator = (
                    f"第{suggestion.locator_value}页"
                    if suggestion.locator_type == "page"
                    else _format_time(suggestion.locator_value)
                )
                link = _source_link(
                    suggestion.source_path,
                    suggestion.locator_type,
                    suggestion.locator_value,
                )
                items.append(
                    "<li>"
                    f'<a href="{html.escape(link, quote=True)}">'
                    f"{html.escape(suggestion.source_name)} · {html.escape(locator)}</a>"
                    f'<span class="score">相关度 {suggestion.score}%</span>'
                    f"<blockquote>{html.escape(suggestion.excerpt)}</blockquote>"
                    "</li>"
                )
            suggestions = (
                '<section class="suggestions"><h3>可能相关的来源</h3><ol>'
                + "".join(items)
                + '</ol><p class="disclaimer">候选来源由文本相似度生成，需要人工确认。</p></section>'
            )
        cards.append(
            f'<article class="finding {html.escape(finding.severity)}">'
            '<div class="finding-head">'
            f'<span class="badge">{severity_label}</span>'
            f'<code>{html.escape(finding.code)}</code>'
            f'<span class="line">第 {finding.line} 行</span>'
            "</div>"
            f"<h2>{html.escape(finding.title or finding.code)}</h2>"
            f"<p>{html.escape(finding.message)}</p>"
            f'<pre class="note">{html.escape(finding.note_text)}</pre>'
            f'<p class="action"><strong>建议：</strong>{html.escape(finding.action)}</p>'
            f"{suggestions}</article>"
        )

    empty_state = (
        '<article class="empty"><h2>没有发现问题</h2>'
        "<p>当前规则检查已通过。它不代表笔记绝对正确，仍建议人工复核重要内容。</p></article>"
        if not findings
        else ""
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>StudyLint 检查报告</title>
  <style>
    :root {{ color-scheme: light; --bg:#f6f8fa; --card:#fff; --text:#1f2328; --muted:#656d76; --border:#d0d7de; --error:#cf222e; --warning:#9a6700; --accent:#4338ca; }}
    * {{ box-sizing:border-box; }}
    body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif; }}
    main {{ width:min(960px,calc(100% - 32px)); margin:40px auto 80px; }}
    header {{ margin-bottom:28px; }}
    h1 {{ margin:0 0 6px; font-size:34px; }}
    .meta {{ color:var(--muted); word-break:break-all; }}
    .summary {{ display:flex; gap:12px; margin:24px 0; flex-wrap:wrap; }}
    .summary div {{ min-width:140px; padding:16px 20px; background:var(--card); border:1px solid var(--border); border-radius:12px; }}
    .summary strong {{ display:block; font-size:26px; }}
    .finding,.empty {{ background:var(--card); border:1px solid var(--border); border-left:5px solid var(--accent); border-radius:12px; padding:22px; margin:18px 0; box-shadow:0 2px 8px #1f23280a; }}
    .finding.error {{ border-left-color:var(--error); }} .finding.warning {{ border-left-color:var(--warning); }}
    .finding-head {{ display:flex; align-items:center; gap:10px; color:var(--muted); }}
    .badge {{ border-radius:999px; padding:2px 9px; color:#fff; background:var(--accent); font-size:13px; font-weight:700; }}
    .error .badge {{ background:var(--error); }} .warning .badge {{ background:var(--warning); }}
    .line {{ margin-left:auto; }} h2 {{ margin:12px 0 4px; font-size:21px; }}
    .note {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#f6f8fa; border:1px solid var(--border); padding:13px; border-radius:8px; }}
    .action {{ background:#eef2ff; padding:12px 14px; border-radius:8px; }}
    .suggestions ol {{ padding-left:22px; }} .suggestions li {{ margin:14px 0; }}
    .suggestions a {{ color:var(--accent); font-weight:650; }} .score {{ margin-left:10px; color:var(--muted); font-size:14px; }}
    blockquote {{ margin:7px 0; padding:8px 12px; border-left:3px solid #a5b4fc; background:#f8faff; }}
    .disclaimer {{ color:var(--muted); font-size:13px; }}
  </style>
</head>
<body><main>
  <header><h1>StudyLint 检查报告</h1><div class="meta">笔记：{html.escape(str(notes_path))}</div></header>
  <section class="summary">
    <div><strong>{counts['errors']}</strong>错误</div>
    <div><strong>{counts['warnings']}</strong>警告</div>
    <div><strong>{counts['total']}</strong>全部问题</div>
  </section>
  {empty_state}{''.join(cards)}
</main></body></html>"""
