from __future__ import annotations

import html
import json
from pathlib import Path

from studylint import AUTHOR_URL, PROJECT_URL
from studylint.manuscripts import (
    CitationAudit,
    ManuscriptIssue,
    read_manuscript_blocks,
)
from studylint.models import Finding
from studylint.papers import PaperVerification


def _support_footer() -> str:
    return (
        '<aside class="project-support"><span>StudyLint</span>'
        f'<a target="_blank" rel="noopener noreferrer" href="{PROJECT_URL}">⭐ Star</a>'
        f'<a target="_blank" rel="noopener noreferrer" href="{AUTHOR_URL}">作者</a>'
        "</aside>"
    )


def summary(findings: list[Finding]) -> dict[str, int]:
    return {
        "errors": sum(finding.severity == "error" for finding in findings),
        "warnings": sum(finding.severity == "warning" for finding in findings),
        "total": len(findings),
    }


def finding_category(code: str) -> str:
    if code in {"ST001", "ST002", "ST009"}:
        return "引用完整性"
    if code == "ST005":
        return "内部一致性"
    return "事实支持"


def render_console(notes_path: Path, findings: list[Finding]) -> str:
    lines = [f"StudyLint: {notes_path}"]
    severity_names = {"error": "错误", "warning": "警告"}
    for finding in findings:
        lines.append(
            f"{severity_names.get(finding.severity, finding.severity):4} "
            f"{finding.code} [{finding_category(finding.code)}] "
            f"第{finding.line}行：{finding.message}"
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


def paper_status(verification: PaperVerification) -> tuple[str, str]:
    if verification.verdict == "RETRACTED":
        return "撤稿警告", "OpenAlex将该论文标记为已撤稿；请打开原始记录并核对撤稿说明。"
    if verification.verdict == "METADATA_MISMATCH":
        return "元数据冲突", "DOI真实存在，但输入的题名或参考文献信息与权威记录明显不符。"
    if verification.verdict == "VERIFIED_METADATA":
        return "元数据高度匹配", "题名与开放数据库记录高度一致；仍需人工核对作者、年份和正文。"
    if verification.verdict == "IDENTIFIER_FOUND":
        source = verification.matches[0].source if verification.matches else "开放数据库"
        return "DOI已登记", f"{source}中存在该DOI；本次输入没有足够题名信息可供比对。"
    if verification.verdict == "PARTIAL_MATCH":
        return "部分匹配", "找到了相关记录，但题名相似度有限，请勿直接视为核验通过。"
    return "开放数据库未匹配", "多个开放及专业数据库当前没有可靠匹配，但这不能证明论文不存在。"


def render_paper_console(verification: PaperVerification) -> str:
    return render_paper_batch_console([verification])


def render_paper_batch_console(verifications: list[PaperVerification]) -> str:
    verified = sum(
        item.verdict in {"VERIFIED_METADATA", "IDENTIFIER_FOUND"}
        for item in verifications
    )
    conflicts = sum(item.verdict == "METADATA_MISMATCH" for item in verifications)
    retracted = sum(item.verdict == "RETRACTED" for item in verifications)
    lines = [
        f"批量论文核验：{len(verifications)}篇，{verified}篇通过，"
        f"{conflicts}篇元数据冲突，{retracted}篇撤稿警告"
    ]
    for number, verification in enumerate(verifications, start=1):
        status, explanation = paper_status(verification)
        lines.extend(
            [
                f"\n[{number}] {verification.query}",
                f"状态：{status}（{verification.verdict}）",
                explanation,
            ]
        )
        for warning in verification.warnings:
            lines.append(f"服务提示：{warning}")
        for index, match in enumerate(verification.matches, start=1):
            metadata = " · ".join(
                value
                for value in (
                    ", ".join(match.authors),
                    match.year,
                    match.venue,
                )
                if value
            )
            lines.extend(
                [
                    f"  {index}. {match.title}",
                    f"     {metadata}" if metadata else "",
                    f"     来源：{match.source} · 匹配度：{match.similarity}%",
                    f"     DOI：{match.doi}" if match.doi else "",
                    f"     查看：{match.url}" if match.url else "",
                ]
            )
        for link in verification.search_links:
            lines.append(f"  {link.name}：{link.url}")
    lines.append("\n说明：数据库未匹配不等于论文不存在；请使用知网等入口继续核查。")
    return "\n".join(line for line in lines if line)


def _paper_verification_html(verification: PaperVerification, number: int) -> str:
    search_links = "".join(
        f'<a class="search" target="_blank" rel="noopener noreferrer" href="{html.escape(link.url, quote=True)}">{html.escape(link.name)}</a>'
        for link in verification.search_links
    )
    return (
        '<section class="verification">'
        f'<div class="query-number">待核查 {number}</div>'
        f"<h2>{html.escape(verification.query)}</h2>"
        '<p class="review-prompt">请自行核查这篇论文。</p>'
        f'<div class="manual">{search_links}</div></section>'
    )


def render_paper_html(verification: PaperVerification) -> str:
    return render_paper_batch_html([verification])


def render_paper_batch_html(verifications: list[PaperVerification]) -> str:
    accepted = {"VERIFIED_METADATA", "IDENTIFIER_FOUND"}
    pending = [item for item in verifications if item.verdict not in accepted]
    sections = "".join(
        _paper_verification_html(verification, number)
        for number, verification in enumerate(pending, start=1)
    )
    if not sections:
        sections = '<section class="empty">没有需要继续人工核查的论文。</section>'
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <title>StudyLint 论文核验</title>
  <style>
    :root {{ --bg:#f6f8fa; --card:#fff; --text:#1f2328; --muted:#656d76; --border:#d0d7de; --accent:#4338ca; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif; }}
    main {{ width:min(960px,calc(100% - 32px)); margin:40px auto 80px; }} h1 {{ margin-bottom:4px; }}
    .meta,.notice {{ color:var(--muted); }} .summary {{ display:flex; gap:12px; margin:22px 0 30px; }}
    .summary div {{ padding:12px 18px; background:var(--card); border:1px solid var(--border); border-radius:10px; }}
    .verification,.empty {{ margin:24px 0; padding:24px; background:var(--card); border:1px solid var(--border); border-radius:14px; }}
    .verification>h2 {{ margin:4px 0 14px; font-size:22px; }} .query-number {{ color:var(--accent); font-weight:700; }}
    .review-prompt {{ margin:10px 0; color:var(--muted); }} .manual {{ margin-top:16px; padding-top:14px; border-top:1px solid var(--border); }} .search {{ display:inline-block; margin:8px 8px 0 0; padding:7px 11px; color:var(--accent); border:1px solid #a5b4fc; border-radius:7px; text-decoration:none; }}
    .notice {{ margin-top:28px; padding-top:18px; border-top:1px solid var(--border); font-size:14px; }}
    .project-support {{ margin-top:24px; padding-top:10px; border-top:1px solid var(--border); color:var(--muted); font-size:12px; text-align:right; }} .project-support a {{ margin-left:10px; color:var(--muted); text-decoration:none; }} .project-support a:hover {{ color:var(--accent); text-decoration:underline; }}
  </style>
</head>
<body><main>
  <header><h1>需要自行核查的论文</h1><div class="meta">已通过的论文不在此显示。</div></header>
  <section class="summary"><div>需要自行核查 <strong>{len(pending)}</strong> 篇</div></section>
  {sections}
  <p class="notice">请通过上方检索入口逐篇确认。</p>
  {_support_footer()}
</main></body></html>"""


CLAIM_STATUS = {
    "DIRECT_SUPPORT": ("原文直接支持", "supported"),
    "LIKELY_SUPPORT": ("可能支持，需复核", "supported"),
    "PARTIAL_SUPPORT": ("部分支持", "partial"),
    "NUMERIC_MISMATCH": ("数字不匹配", "warning"),
    "POSSIBLE_OVERSTATEMENT": ("疑似夸大", "warning"),
    "POSSIBLE_CONTRADICTION": ("疑似矛盾", "danger"),
    "INSUFFICIENT_EVIDENCE": ("证据不足", "partial"),
}


MANUSCRIPT_STATUS = {
    **CLAIM_STATUS,
    "MISSING_REFERENCE": ("参考文献条目缺失", "danger"),
    "SOURCE_UNAVAILABLE": ("当前无可核验原文", "partial"),
}

AI_STATUS = {
    "SUPPORTED": ("AI判断：支持", "supported"),
    "PARTIAL": ("AI判断：部分支持", "partial"),
    "CONTRADICTED": ("AI判断：存在矛盾", "danger"),
    "OVERSTATED": ("AI判断：论述夸大", "warning"),
    "INSUFFICIENT": ("AI判断：证据不足", "partial"),
    "NOT_RUN_RULE_DIRECT": ("未调用AI：规则已直接确认", "partial"),
    "NOT_RUN_NO_SOURCE": ("未调用AI：缺少正文", "partial"),
    "NOT_RUN_NO_EVIDENCE": ("未调用AI：没有候选原文", "partial"),
    "ERROR": ("AI核验失败", "danger"),
}

AI_ISSUE_LABELS = {
    "CITATION_SOURCE": "引用/来源",
    "FACT_BACKGROUND": "事实与背景",
    "DATA_RESULT": "数据与结果",
    "METHOD_PROCESS": "方法与过程",
    "LOGIC_REASONING": "推理与逻辑",
    "MATH_FORMULA": "数学与公式",
    "CONCEPT_TERMINOLOGY": "概念与术语",
    "ATTRIBUTION_SOURCE": "归因与来源",
    "ETHICS_COMPLIANCE": "伦理与合规",
    "FORMAT_INTERNAL_CONSISTENCY": "格式与内部一致性",
    "TIME_VERSION": "时间与版本",
}

REFERENCE_STATUS = {
    "VERIFIED_METADATA": "文献记录高度匹配",
    "IDENTIFIER_FOUND": "标识符已登记",
    "PARTIAL_MATCH": "文献记录部分匹配",
    "METADATA_MISMATCH": "文献元数据冲突",
    "RETRACTED": "撤稿警告",
    "NEEDS_MANUAL": "需人工核对文献记录",
    "LOOKUP_FAILED": "文献元数据服务暂时不可用",
}

SOURCE_STATUS = {
    "LOCAL": "使用本地原文",
    "LOCAL_FILE": "使用本地原文",
    "CACHED_FILE": "使用已校验的原文缓存",
    "DOWNLOADED": "已获取开放原文",
    "METADATA_ONLY": "已找到记录，当前未取得开放原文",
    "AMBIGUOUS": "文献匹配不唯一，未自动下载",
    "LOW_CONFIDENCE": "候选匹配度不足，未自动下载",
    "UNAVAILABLE": "当前未取得开放原文",
    "NOT_FOUND": "开放数据库未可靠匹配",
    "DOWNLOAD_FAILED": "开放原文获取失败",
}


def _evidence_locator(locator_type: str, locator_value: int) -> str:
    if locator_type == "page":
        return f"第{locator_value}页"
    if locator_type == "chapter":
        return f"第{locator_value}章"
    return f"位置{locator_value}"


def render_manuscript_console(
    audits: list[CitationAudit], issues: list[ManuscriptIssue] | None = None
) -> str:
    issues = issues or []
    lines = [f"论文内容幻觉核查：{len(audits)}处引用，{len(issues)}个整稿问题"]
    for issue in issues:
        location = issue.location or (
            f"第{issue.paragraph}处" if issue.paragraph else "参考文献表"
        )
        lines.append(
            f"\n[{issue.code}] {issue.category} · {location}：{issue.message}\n"
            f"  {issue.excerpt}"
        )
    for number, audit in enumerate(audits, start=1):
        label = MANUSCRIPT_STATUS[audit.verdict][0]
        lines.extend(
            [
                f"\n[{number}] {audit.location or f'第{audit.paragraph}处'} · 引用[{audit.citation_number}]",
                f"论述：{audit.claim}",
                f"结果：{label}（{audit.verdict}）",
                audit.explanation,
                f"参考文献：{audit.reference_text}" if audit.reference_text else "",
                f"原文文件：{audit.source_path}" if audit.source_path else "",
                (
                    f"文献记录：{REFERENCE_STATUS.get(audit.reference_verdict, audit.reference_verdict)}"
                    if audit.reference_verdict
                    else ""
                ),
                (
                    f"全文状态：{SOURCE_STATUS.get(audit.source_status, audit.source_status)}"
                    if audit.source_status
                    else ""
                ),
            ]
        )
        for evidence in audit.evidences:
            lines.append(
                f"  {_evidence_locator(evidence.locator_type, evidence.page)} · "
                f"相关度{evidence.score}%：{evidence.text}"
            )
        if audit.ai_verdict:
            ai_label = AI_STATUS.get(audit.ai_verdict, (audit.ai_verdict, ""))[0]
            confidence = (
                f" · 置信度{audit.ai_confidence}%"
                if audit.ai_verdict in {"SUPPORTED", "PARTIAL", "CONTRADICTED", "OVERSTATED", "INSUFFICIENT"}
                else ""
            )
            lines.append(f"  {ai_label}{confidence}：{audit.ai_explanation}")
            if audit.ai_issue_types:
                lines.append(
                    "  问题类型："
                    + "、".join(
                        AI_ISSUE_LABELS.get(value, value)
                        for value in audit.ai_issue_types
                    )
                )
    return "\n".join(line for line in lines if line)


def render_manuscript_json(
    manuscript_path: Path,
    audits: list[CitationAudit],
    issues: list[ManuscriptIssue] | None = None,
) -> str:
    payload = {
        "manuscript": str(manuscript_path),
        "document_issues": [issue.to_dict() for issue in (issues or [])],
        "audits": [audit.to_dict() for audit in audits],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2)


def _annotation_reason(audit: CitationAudit) -> tuple[str, str] | None:
    def concise(value: str) -> str:
        cleaned = " ".join(value.split())
        return cleaned if len(cleaned) <= 180 else f"{cleaned[:177]}…"

    details: list[str] = []
    if audit.verdict != "DIRECT_SUPPORT":
        label = MANUSCRIPT_STATUS.get(audit.verdict, (audit.verdict, ""))[0]
        details.append(f"{label}：{concise(audit.explanation)}")
    if audit.ai_verdict in {
        "PARTIAL",
        "CONTRADICTED",
        "OVERSTATED",
        "INSUFFICIENT",
        "ERROR",
    }:
        ai_label = AI_STATUS.get(audit.ai_verdict, (audit.ai_verdict, ""))[0]
        details.append(
            f"{ai_label}：{concise(audit.ai_explanation or '需要人工复核。')}"
        )
    if audit.reference_verdict in {
        "PARTIAL_MATCH",
        "METADATA_MISMATCH",
        "RETRACTED",
        "NEEDS_MANUAL",
        "LOOKUP_FAILED",
    }:
        reference_label = REFERENCE_STATUS.get(
            audit.reference_verdict, audit.reference_verdict
        )
        details.append(
            f"{reference_label}：{concise(audit.reference_message or '参考文献记录需要人工核对。')}"
        )
    if not details:
        return None
    return "引用核验提示", " ".join(dict.fromkeys(details))


def _find_annotation_range(text: str, excerpt: str) -> tuple[int, int] | None:
    candidate = excerpt.strip()
    for value in (candidate, candidate.rstrip(".!?。！？;；")):
        if not value:
            continue
        start = text.casefold().find(value.casefold())
        if start >= 0:
            return start, start + len(value)
    return None


def _annotated_text(
    text: str, annotations: list[tuple[str, str, str]]
) -> str:
    ranges: list[tuple[int, int, list[tuple[str, str]]]] = []
    for excerpt, title, reason in annotations:
        located = _find_annotation_range(text, excerpt)
        if located is None:
            located = (0, len(text))
        start, end = located
        if start == end:
            continue
        ranges.append((start, end, [(title, reason)]))
    if not ranges:
        return html.escape(text)
    merged: list[tuple[int, int, list[tuple[str, str]]]] = []
    for start, end, details in sorted(ranges, key=lambda item: (item[0], item[1])):
        if merged and start < merged[-1][1]:
            previous_start, previous_end, previous_details = merged[-1]
            merged[-1] = (
                previous_start,
                max(previous_end, end),
                previous_details + details,
            )
        else:
            merged.append((start, end, details))
    pieces: list[str] = []
    cursor = 0
    for start, end, details in merged:
        pieces.append(html.escape(text[cursor:start]))
        unique_details = list(dict.fromkeys(details))
        tooltip = "".join(
            f"<strong>{html.escape(title)}</strong><span>{html.escape(reason)}</span>"
            for title, reason in unique_details
        )
        accessible = "；".join(f"{title}：{reason}" for title, reason in unique_details)
        pieces.append(
            f'<span class="problem-text">{html.escape(text[start:end])}</span>'
            f'<span class="issue-marker" tabindex="0" aria-label="{html.escape(accessible, quote=True)}">!'
            f'<span class="issue-tooltip" role="tooltip">{tooltip}</span></span>'
        )
        cursor = end
    pieces.append(html.escape(text[cursor:]))
    return "".join(pieces)


def _render_annotated_manuscript(
    manuscript_path: Path,
    audits: list[CitationAudit],
    issues: list[ManuscriptIssue],
) -> tuple[str, int]:
    try:
        blocks = read_manuscript_blocks(manuscript_path)
    except (OSError, ValueError):
        blocks = list(dict.fromkeys(audit.claim for audit in audits if audit.claim))
    annotations: dict[int, list[tuple[str, str, str]]] = {}
    for audit in audits:
        detail = _annotation_reason(audit)
        if detail is not None and audit.paragraph > 0:
            annotations.setdefault(audit.paragraph, []).append(
                (audit.claim, detail[0], detail[1])
            )
    for issue in issues:
        paragraph = issue.paragraph
        if paragraph <= 0:
            paragraph = next(
                (
                    number
                    for number, block in enumerate(blocks, start=1)
                    if issue.excerpt and issue.excerpt.casefold() in block.casefold()
                ),
                0,
            )
        if paragraph > 0:
            annotations.setdefault(paragraph, []).append(
                (issue.excerpt, issue.category, issue.message)
            )
    rendered_blocks: list[str] = []
    for number, block in enumerate(blocks, start=1):
        if not block.strip():
            rendered_blocks.append('<div class="manuscript-gap" aria-hidden="true"></div>')
            continue
        content = _annotated_text(block, annotations.get(number, []))
        rendered_blocks.append(
            f'<div class="manuscript-paragraph" data-position="{number}">{content}</div>'
        )
    problem_count = sum(
        len({excerpt.casefold() for excerpt, _title, _reason in values})
        for values in annotations.values()
    )
    if problem_count:
        summary_text = f"已在原稿中标出 {problem_count} 处需要核对的内容。"
    else:
        summary_text = "本次核查没有发现需要在原稿中标红的问题。"
    return (
        '<section class="annotation-panel">'
        '<div class="annotation-heading"><div><span>批注版原稿</span>'
        f'<h1>{html.escape(manuscript_path.name)}</h1></div>'
        f'<p>{html.escape(summary_text)} 将鼠标移到红色感叹号上查看理由。</p></div>'
        f'<article class="annotation-paper">{"".join(rendered_blocks)}</article>'
        '</section>',
        problem_count,
    )


def render_manuscript_html(
    manuscript_path: Path,
    audits: list[CitationAudit],
    issues: list[ManuscriptIssue] | None = None,
) -> str:
    issues = issues or []
    cards: list[str] = []
    ai_enabled = any(audit.ai_verdict for audit in audits)
    ai_reviewed = sum(
        audit.ai_verdict in {"SUPPORTED", "PARTIAL", "CONTRADICTED", "OVERSTATED", "INSUFFICIENT"}
        for audit in audits
    )
    ai_errors = sum(audit.ai_verdict == "ERROR" for audit in audits)
    for number, audit in enumerate(audits, start=1):
        label, status_class = MANUSCRIPT_STATUS[audit.verdict]
        reference = (
            f'<p class="reference"><strong>参考文献[{audit.citation_number}]：</strong>'
            f"{html.escape(audit.reference_text)}</p>"
            if audit.reference_text
            else ""
        )
        reference_check = ""
        if audit.reference_verdict or audit.source_status:
            reference_label = REFERENCE_STATUS.get(
                audit.reference_verdict, audit.reference_verdict or "未运行"
            )
            source_label = SOURCE_STATUS.get(
                audit.source_status, audit.source_status or "未运行"
            )
            record_link = (
                f'<a target="_blank" rel="noopener noreferrer" href="{html.escape(audit.reference_url, quote=True)}">查看文献记录</a>'
                if audit.reference_url
                else ""
            )
            warnings = "".join(
                f"<li>{html.escape(value)}</li>"
                for value in audit.reference_warnings
            )
            warning_block = f'<ul class="warnings">{warnings}</ul>' if warnings else ""
            details = " · ".join(
                value
                for value in (
                    f"类型：{audit.reference_type}" if audit.reference_type else "",
                    f"许可：{audit.source_license}" if audit.source_license else "",
                )
                if value
            )
            reference_check = (
                '<div class="reference-check">'
                f'<strong>文献记录：{html.escape(reference_label)}</strong>'
                f'<span>原文：{html.escape(source_label)}</span>'
                f'<span>{html.escape(details)}</span>'
                f'<p>{html.escape(audit.reference_message)}</p>'
                f'<p>{html.escape(audit.source_message)}</p>'
                f'{record_link}{warning_block}</div>'
            )
        source = (
            f'<p class="source"><strong>用于核验的原文：</strong>{html.escape(audit.source_path)}</p>'
            if audit.source_path
            else ""
        )
        evidences: list[str] = []
        for evidence in audit.evidences:
            page_url = _source_link(
                evidence.source_path, evidence.locator_type, evidence.page
            )
            locator = _evidence_locator(evidence.locator_type, evidence.page)
            evidences.append(
                '<li class="evidence">'
                f'<a target="_blank" rel="noopener noreferrer" href="{html.escape(page_url, quote=True)}">'
                f"打开{html.escape(locator)}</a>"
                f'<span class="score">相关度 {evidence.score}%</span>'
                f"<blockquote>{html.escape(evidence.text)}</blockquote></li>"
            )
        evidence_block = (
            f'<h3>相关原文</h3><ol>{"".join(evidences)}</ol>'
            if evidences
            else ""
        )
        ai_block = ""
        if audit.ai_verdict:
            ai_label, ai_class = AI_STATUS.get(
                audit.ai_verdict, (audit.ai_verdict, "partial")
            )
            confidence = (
                f" · 置信度 {audit.ai_confidence}%"
                if audit.ai_verdict in {"SUPPORTED", "PARTIAL", "CONTRADICTED", "OVERSTATED", "INSUFFICIENT"}
                else ""
            )
            pages = (
                " · 使用位置 " + ", ".join(map(str, audit.ai_evidence_pages))
                if audit.ai_evidence_pages
                else ""
            )
            mode = {"fast": "快速", "strict": "严格"}.get(
                audit.ai_mode, audit.ai_mode
            )
            skill = {
                "general": "通用学术",
                "biomedical": "医学与临床",
                "social_science": "社会科学",
            }.get(audit.ai_skill, audit.ai_skill)
            issue_badges = "".join(
                f'<span class="issue-type">{html.escape(AI_ISSUE_LABELS.get(value, value))}</span>'
                for value in audit.ai_issue_types
            )
            ai_block = (
                f'<div class="ai-verdict {ai_class}"><strong>{html.escape(ai_label)}</strong>'
                f'<code>{html.escape(audit.ai_verdict)}</code>'
                f'<p>{html.escape(audit.ai_explanation)}</p>'
                f'<span>模型：{html.escape(audit.ai_model)} · 模式：{html.escape(mode)}'
                f' · 技能：{html.escape(skill)}{html.escape(confidence)}{html.escape(pages)}</span>'
                f'<div class="issue-types">{issue_badges}</div></div>'
            )
        cards.append(
            '<article class="audit">'
            f'<div class="location">{html.escape(audit.location or f"第{audit.paragraph}处")} · 引用[{audit.citation_number}] · 第{number}处</div>'
            f"<h2>{html.escape(audit.claim)}</h2>"
            f'<div class="verdict {status_class}"><strong>{html.escape(label)}</strong>'
            f'<code>{html.escape(audit.verdict)}</code>'
            f"<p>{html.escape(audit.explanation)}</p></div>"
            f"{reference}{reference_check}{source}{ai_block}{evidence_block}</article>"
        )
    issue_cards = "".join(
        '<article class="document-issue">'
        f'<div><code>{html.escape(issue.code)}</code> · {html.escape(issue.category)} · {html.escape(issue.location or "参考文献表")}</div>'
        f'<strong>{html.escape(issue.message)}</strong>'
        f'<blockquote>{html.escape(issue.excerpt)}</blockquote></article>'
        for issue in issues
    )
    document_issues = (
        f'<section class="document-issues"><h2>整稿一致性提示（{len(issues)}）</h2>{issue_cards}</section>'
        if issues
        else ""
    )
    ai_summary = (
        '<section class="ai-summary"><strong>已启用可选AI深度核验</strong>'
        f"<span>AI实际复核 {ai_reviewed} 处 · 失败 {ai_errors} 处。"
        "规则结果与AI结果分开显示，AI判断不是最终学术结论。</span></section>"
        if ai_enabled
        else ""
    )
    annotated_manuscript, problem_count = _render_annotated_manuscript(
        Path(manuscript_path), audits, issues
    )
    details_open = " open" if problem_count == 0 else ""
    return f"""<!doctype html>
<html lang="zh-CN"><head>
  <meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
  <title>StudyLint 论文内容幻觉核查</title>
  <style>
    :root {{ --bg:#edf0f3; --card:#fff; --text:#18212b; --muted:#66717d; --border:#d8dde3; --accent:#344b63; --warn:#9a6700; --danger:#c62828; --ok:#1a7f37; --paper:#fff; --paper-edge:#d7dce1; }}
    * {{ box-sizing:border-box; }} body {{ margin:0; background:var(--bg); color:var(--text); font:16px/1.6 system-ui,"Microsoft YaHei",sans-serif; }}
    main {{ width:min(1040px,calc(100% - 32px)); margin:30px auto 80px; }} h1 {{ margin:0 0 6px; }} .meta,.notice,.source {{ color:var(--muted); word-break:break-all; }}
    .report-header {{ margin-bottom:18px; }} .report-header h1 {{ font-size:18px; color:var(--muted); font-weight:600; }}
    .annotation-panel {{ margin-top:18px; }} .annotation-heading {{ display:flex; justify-content:space-between; align-items:end; gap:24px; margin:0 auto 14px; width:min(860px,100%); }}
    .annotation-heading span {{ color:var(--danger); font-size:13px; font-weight:800; letter-spacing:.12em; }} .annotation-heading h1 {{ margin:2px 0 0; font-size:26px; }} .annotation-heading p {{ max-width:420px; margin:0; color:var(--muted); font-size:14px; text-align:right; }}
    .annotation-paper {{ width:min(860px,100%); min-height:65vh; margin:0 auto; padding:64px 72px 82px; background:var(--paper); border:1px solid var(--paper-edge); box-shadow:0 18px 48px rgba(24,33,43,.09); font:17px/1.95 Georgia,"Noto Serif SC","Songti SC",SimSun,serif; }}
    .manuscript-paragraph {{ margin:.7em 0; white-space:pre-wrap; overflow-wrap:anywhere; }} .manuscript-gap {{ height:.8em; }}
    .problem-text {{ text-decoration-line:underline; text-decoration-color:var(--danger); text-decoration-thickness:2px; text-underline-offset:4px; background:linear-gradient(transparent 72%,rgba(198,40,40,.08) 72%); }}
    .issue-marker {{ position:relative; display:inline-grid; place-items:center; width:17px; height:17px; margin-left:4px; border-radius:50%; background:var(--danger); color:#fff; font:800 12px/1 system-ui,sans-serif; vertical-align:super; cursor:help; outline:none; }}
    .issue-marker:focus-visible {{ box-shadow:0 0 0 3px rgba(198,40,40,.24); }} .issue-tooltip {{ position:absolute; z-index:20; left:50%; bottom:calc(100% + 10px); width:min(320px,80vw); padding:11px 13px; border:1px solid #f0b7b7; border-radius:9px; background:#fff7f7; box-shadow:0 10px 28px rgba(75,20,20,.16); color:#4d2020; font:13px/1.45 system-ui,"Microsoft YaHei",sans-serif; text-align:left; transform:translate(-50%,5px); opacity:0; visibility:hidden; pointer-events:none; transition:opacity .14s ease,transform .14s ease; }}
    .issue-tooltip strong,.issue-tooltip span {{ display:block; }} .issue-tooltip strong {{ color:#a31515; margin-bottom:3px; }} .issue-tooltip span + strong {{ margin-top:8px; padding-top:7px; border-top:1px solid #f2cece; }} .issue-marker:hover .issue-tooltip,.issue-marker:focus .issue-tooltip {{ opacity:1; visibility:visible; transform:translate(-50%,0); }}
    .audit-details {{ width:min(960px,100%); margin:28px auto 0; padding:0; }} .audit-details > summary {{ cursor:pointer; color:var(--accent); font-weight:750; padding:14px 0; }}
    @media (max-width:680px) {{ main {{ width:min(100% - 20px,1040px); margin-top:18px; }} .annotation-heading {{ align-items:start; flex-direction:column; gap:6px; }} .annotation-heading p {{ text-align:left; }} .annotation-paper {{ padding:34px 22px 52px; font-size:16px; }} }}
    @media (prefers-reduced-motion:reduce) {{ .issue-tooltip {{ transition:none; }} }}
    .audit {{ margin:22px 0; padding:24px; background:var(--card); border:1px solid var(--border); border-radius:14px; }}
    .location {{ color:var(--accent); font-weight:700; }} .audit h2 {{ margin:5px 0 14px; font-size:21px; }}
    .verdict {{ padding:14px 16px; border-left:5px solid var(--accent); border-radius:9px; background:#eef2ff; }} .verdict strong {{ display:block; font-size:18px; }} .verdict code {{ color:var(--muted); }} .verdict p {{ margin:5px 0 0; }}
    .verdict.supported {{ border-color:var(--ok); background:#dafbe1; }} .verdict.warning {{ border-color:var(--warn); background:#fff8c5; }} .verdict.danger {{ border-color:var(--danger); background:#ffebe9; }}
    .ai-summary {{ display:flex; gap:12px; flex-wrap:wrap; margin:20px 0; padding:14px 16px; background:#f0f7ff; border:1px solid #80bfff; border-radius:10px; }} .ai-summary strong {{ color:#0969da; }}
    .ai-verdict {{ margin-top:14px; padding:14px 16px; border-left:5px solid var(--accent); border-radius:9px; background:#eef2ff; }} .ai-verdict strong {{ display:block; font-size:17px; }} .ai-verdict code {{ color:var(--muted); }} .ai-verdict p {{ margin:5px 0; }} .ai-verdict span {{ color:var(--muted); font-size:13px; }}
    .ai-verdict.supported {{ border-color:var(--ok); background:#dafbe1; }} .ai-verdict.warning {{ border-color:var(--warn); background:#fff8c5; }} .ai-verdict.danger {{ border-color:var(--danger); background:#ffebe9; }}
    .reference {{ padding:10px 12px; background:#f6f8fa; border-radius:8px; }} .reference-check {{ display:grid; gap:4px; margin:12px 0; padding:12px; border:1px solid var(--border); border-radius:8px; }} .reference-check span,.reference-check p {{ color:var(--muted); margin:0; }} .reference-check a {{ color:var(--accent); }} .warnings {{ color:var(--warn); }}
    .document-issues {{ margin:20px 0; }} .document-issue {{ margin:10px 0; padding:14px 16px; background:#fff8c5; border-left:5px solid var(--warn); border-radius:9px; }} .document-issue strong {{ display:block; margin-top:4px; }}
    .issue-types {{ display:flex; gap:6px; flex-wrap:wrap; margin-top:8px; }} .issue-type {{ padding:2px 7px; border:1px solid #a5b4fc; border-radius:999px; background:#fff; }}
    .evidence {{ margin:16px 0; }} .evidence a {{ color:var(--accent); font-weight:700; }} .score {{ margin-left:10px; color:var(--muted); }}
    blockquote {{ margin:7px 0; padding:10px 13px; background:#f6f8fa; border-left:3px solid #a5b4fc; white-space:pre-wrap; }}
    .notice {{ margin-top:28px; padding-top:18px; border-top:1px solid var(--border); }} .project-support {{ margin-top:24px; color:var(--muted); font-size:12px; text-align:right; }} .project-support a {{ margin-left:10px; color:var(--muted); text-decoration:none; }}
  </style>
</head><body><main>
  <header class="report-header"><h1>StudyLint · 论文内容幻觉核查</h1><div class="meta">稿件：{html.escape(str(manuscript_path))}</div></header>
  {annotated_manuscript}
  <details class="audit-details"{details_open}><summary>查看完整核验明细（{len(audits)}处引用，{len(issues)}个整稿提示）</summary>
    {ai_summary}
    {document_issues}
    {''.join(cards)}
    <p class="notice">StudyLint会核对参考文献记录、可取得的PDF/EPUB原文、数字与否定方向、措辞强度及部分整稿一致性。当前未取得开放原文不代表论文不存在，“证据不足”也不代表论述为假。实验是否真实实施、原始数据是否伪造、伦理审批真实性和完整数学推导仍需原始材料与人工复核。</p>
  </details>
  {_support_footer()}
</main></body></html>"""


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
            f'<span class="category">{finding_category(finding.code)}</span>'
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
  <title>StudyLint AI总结核查报告</title>
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
    .category {{ padding:1px 7px; border:1px solid var(--border); border-radius:999px; font-size:13px; }}
    .note {{ white-space:pre-wrap; overflow-wrap:anywhere; background:#f6f8fa; border:1px solid var(--border); padding:13px; border-radius:8px; }}
    .action {{ background:#eef2ff; padding:12px 14px; border-radius:8px; }}
    .suggestions ol {{ padding-left:22px; }} .suggestions li {{ margin:14px 0; }}
    .suggestions a {{ color:var(--accent); font-weight:650; }} .score {{ margin-left:10px; color:var(--muted); font-size:14px; }}
    blockquote {{ margin:7px 0; padding:8px 12px; border-left:3px solid #a5b4fc; background:#f8faff; }}
    .disclaimer {{ color:var(--muted); font-size:13px; }}
    .project-support {{ margin-top:24px; padding-top:10px; border-top:1px solid var(--border); color:var(--muted); font-size:12px; text-align:right; }} .project-support a {{ margin-left:10px; color:var(--muted); text-decoration:none; }} .project-support a:hover {{ color:var(--accent); text-decoration:underline; }}
  </style>
</head>
<body><main>
  <header><h1>AI总结核查报告</h1><div class="meta">对照可信资料，检查已标注来源的引用、事实支持与内部一致性。<br>总结：{html.escape(str(notes_path))}</div></header>
  <section class="summary">
    <div><strong>{counts['errors']}</strong>错误</div>
    <div><strong>{counts['warnings']}</strong>警告</div>
    <div><strong>{counts['total']}</strong>全部问题</div>
  </section>
  {empty_state}{''.join(cards)}
  {_support_footer()}
</main></body></html>"""
