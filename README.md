<p align="center">
  <img src="assets/logo.svg" width="112" alt="StudyLint logo">
</p>

<h1 align="center">StudyLint</h1>

<p align="center"><strong>ESLint for AI-generated study notes.</strong></p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-4338CA">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2DD4BF">
  <img alt="Status Alpha" src="https://img.shields.io/badge/Status-Alpha-F59E0B">
</p>

StudyLint checks Markdown study notes against the original slides, PDFs, and lecture transcripts. It catches missing sources, broken page or timestamp references, unsupported quotations, and conflicting definitions — without requiring an AI API.

**中文简介：** StudyLint 是一个面向学习笔记的确定性检查器。它不会替你编写笔记，而是检查笔记中的重要结论是否有来源、页码和时间戳是否有效、引用原文能否找到，以及同一术语是否出现冲突定义。

## Why StudyLint?

AI can generate convincing notes, but convincing is not the same as traceable. StudyLint treats course material as the source of truth and reports verifiable problems with stable rule codes.

<p align="center">
  <img src="assets/demo.gif" width="900" alt="StudyLint terminal demo">
</p>

```text
slides / PDF / transcript + notes.md
                 ↓
              StudyLint
                 ↓
       errors, warnings, JSON report
```

## Quick start

StudyLint requires Python 3.10 or newer.

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e .
studylint check examples/synthetic-course/notes.md \
  --source examples/synthetic-course/slides.md \
  --source examples/synthetic-course/lecture.srt
```

The example intentionally contains errors, so the command exits with status `1` after printing the report.

On older Windows terminals, set `PYTHONUTF8=1` if Chinese text is displayed incorrectly:

```powershell
$env:PYTHONUTF8 = "1"
```

## Citation syntax

Use inline citations in Markdown notes:

```markdown
信息具有可传递性。[slides.pdf#page=12]
老师强调需要理解该概念。[lecture.srt#time=00:31:42]
```

For Markdown or text source files, page boundaries can be represented with markers:

```markdown
<!-- page: 1 -->
第一页内容

<!-- page: 2 -->
第二页内容
```

## Rules in v0.1

| Rule | Level | Meaning |
|---|---|---|
| `ST001` | Error | The cited source file was not provided. |
| `ST002` | Error | The cited page or timestamp is invalid. |
| `ST003` | Error | Quoted text was not found at the cited location. |
| `ST004` | Warning | A substantial note line has no citation. |
| `ST005` | Warning | The same term has substantially different definitions. |

`ST003` only checks text inside straight or Chinese quotation marks. Paraphrases are not judged in v0.1.

## Supported source formats

- PDF (`.pdf`)
- PowerPoint (`.pptx`)
- SubRip transcript (`.srt`)
- Markdown (`.md`)
- Plain text (`.txt`)

## JSON reports

```bash
studylint check notes.md -s slides.pdf -s lecture.srt \
  --format json --output report.json
```

Exit codes:

- `0`: no errors; warnings may exist
- `1`: at least one lint error
- `2`: invalid command input or unreadable source

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Scope

StudyLint v0.1 deliberately avoids semantic truth judgments, model providers, accounts, and a web UI. Its first goal is to make references mechanically auditable. Semantic support checking and editor integrations can be added after the deterministic core is reliable.

## Privacy and course materials

StudyLint runs locally. Do not commit copyrighted slides, private transcripts, personal data, or restricted course materials to a public repository. The included example is synthetic.

## License

MIT
