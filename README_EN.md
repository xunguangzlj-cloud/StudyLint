<p align="center">
  <img src="assets/logo.svg" width="112" alt="StudyLint logo">
</p>

<h1 align="center">StudyLint</h1>

<p align="center"><strong>Break learning-time AI hallucinations by checking study notes and paper citations.</strong></p>

<p align="center"><a href="README.md">简体中文</a> · <a href="README_EN.md">English</a></p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-4338CA">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2DD4BF">
  <img alt="Version 0.5.4" src="https://img.shields.io/badge/Version-0.5.4-F59E0B">
</p>

<p align="center">
  <sub><a href="https://github.com/xunguangzlj-cloud/StudyLint">⭐ Star</a> · <a href="https://github.com/xunguangzlj-cloud">Author</a></sub>
</p>

StudyLint is an evidence checker for AI-assisted learning. Give it AI-generated notes plus trusted course materials, and it checks broken references, page-to-claim mismatches, inaccurate direct quotations, and explicit definition conflicts. Give it AI-generated references, and it batch-checks open scholarly metadata while providing links for manual verification.

It never presents text similarity as verified truth, and it needs neither an account nor an LLM API.

<p align="center">
  <img src="assets/demo.gif" width="900" alt="StudyLint terminal demo">
</p>

## Features

- **Flexible source selection:** select one or more files directly, or recursively load an entire folder.
- **Page and timestamp validation:** detect missing PDF pages, slide numbers, or transcript timestamps.
- **Claim-to-location checks:** verify that the cited location has a meaningful textual relationship to the note.
- **Direct quotation checks:** test whether quoted text appears at the cited location.
- **Unextractable-page detection:** report scanned image pages, blank text layers, and ambiguous duplicate filenames separately.
- **Evidence suggestions:** show up to three locally matched candidate passages for human review.
- **Explicit definition conflicts:** compare only clear definition statements or bold term headings, skipping table fields and scenario labels.
- **Offline HTML reports:** show the reason, suggested action, original note, and clickable local source locations.
- **Batch paper verification:** query Crossref and OpenAlex by DOI or title, filter weak matches, and provide CNKI and other manual search links.
- **GUI and CLI:** a file-picker interface for students and command-line/JSON output for developers.

## Quick start: graphical interface

Download `StudyLint.exe` from GitHub Releases and run it. Windows may display an unknown-publisher warning for an unsigned executable; confirm that the file came from this repository's Release page.

To run from source, install Python 3.10 or later:

```powershell
git clone https://github.com/xunguangzlj-cloud/StudyLint.git
cd StudyLint
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
studylint gui
```

Then:

1. Select a `.md`, `.txt`, or `.docx` note file.
2. Select one or more PDF, PPTX, DOCX, Markdown, TXT, or SRT source files, or choose a source folder.
3. Click the note verification button.
4. Review confirmed errors, insufficient support, internal conflicts, and candidate evidence in the browser report.

For AI-generated paper references, switch to the paper verification tab and enter one DOI, title, or full reference per line. You may also import a TXT or CSV list. Manual search links open in new tabs, and all CNKI checks can be opened together.

Notes and course materials stay on the local device. The generated report is stored next to the note file:

```text
Input:  information-management-notes.docx
Report: information-management-notes-studylint-report.html
```

## Command line

### Check a source folder

```powershell
studylint check "notes.docx" `
  --source-dir "course-materials" `
  --format html `
  --open
```

`--source-dir` recursively discovers supported files and excludes the note file being checked.

### Select individual source files

```powershell
studylint check notes.md `
  --source slides.pdf `
  --source lecture.srt
```

`--source` and `--source-dir` can be used together.

### Generate JSON

```powershell
studylint check notes.md `
  --source-dir materials `
  --format json `
  --output report.json
```

### Verify paper metadata

Prefer a DOI when available:

```powershell
studylint paper "10.1038/nature12373" --format html --open
```

Without a DOI, enter a title or complete reference:

```powershell
studylint paper "Nanometre-scale thermometry in a living cell" --format html --open
```

For batch verification, prepare a file with one reference per line:

```powershell
studylint paper --file papers.txt --format html --open
```

Results include title, authors, year, venue, match score, and paper link. StudyLint automatically queries Crossref and OpenAlex and filters weak matches. Each result also provides searches for CNKI, Google Scholar, and Baidu Scholar. No open-database match does not prove that a paper is nonexistent, especially for Chinese-language literature.

Exit codes:

- `0`: no note errors, or every paper has a reliable open-metadata candidate;
- `1`: at least one note error, or at least one paper lacks a reliable candidate;
- `2`: invalid input, argument, source file, or directory.

## Supported formats

| Purpose | Formats | Notes |
|---|---|---|
| Notes | Markdown, TXT, DOCX | DOCX line numbers represent paragraph numbers |
| Course sources | PDF, PPTX, SRT, Markdown, TXT, DOCX | A DOCX source is currently treated as one location |

Scanned PDFs without a text layer are not OCRed automatically. StudyLint reports locations where no text can be extracted so that they can be checked manually.

## Optional citation syntax

StudyLint does not flag a statement merely because it has no citation. To check whether a statement matches course material, add a source location:

```markdown
Information can be transmitted between subjects. [slides.pdf#page=12]
The instructor emphasized understanding this concept. [lecture.srt#time=00:31:42]
```

Page aliases include `#p=12`, `#页=12`, and `#页码=12`; timestamp aliases include `#t=00:31:42` and `#时间=00:31:42`. StudyLint first verifies that the location exists, then compares the note with the extracted text.

Markdown and TXT sources can simulate pages with markers:

```markdown
<!-- page: 1 -->
Page one content

<!-- page: 2 -->
Page two content
```

## Ignore one false positive

In Markdown or TXT notes, place an ignore directive immediately before the affected note:

```markdown
<!-- studylint-ignore ST006 -->
This is my paraphrase. [slides.pdf#page=12]
```

The directive applies only to the next valid note. Multiple rules may be listed:

```markdown
<!-- studylint-ignore ST005, ST006 -->
```

## Rules

| Rule | Level | Meaning |
|---|---|---|
| `ST001` | Error | The cited source file was not supplied |
| `ST002` | Error | The cited page or timestamp does not exist |
| `ST003` | Error | A direct quotation does not appear at the cited location |
| `ST005` | Warning | The same explicitly defined term has substantially different explanations |
| `ST006` | Warning | The note has little textual support at the cited page or timestamp |
| `ST008` | Warning | No text can be extracted at the cited location |
| `ST009` | Error | Duplicate source filenames make the citation ambiguous |

ST003 checks direct quotations; ST006 checks textual support at an explicitly cited location. Missing citations do not trigger findings. StudyLint does not independently determine world truth: it checks against the trusted materials supplied by the user. Candidate evidence is a similarity-based suggestion, not proof.

## Performance

- PDF, PPTX, DOCX, and transcript sources are parsed in parallel.
- Batch paper verification uses up to four concurrent requests while preserving input order.
- Repeated text normalization and similarity features are cached.
- Network paper verification runs in the background so that the GUI remains responsive.

## Windows portable build

Pushing a `v*` tag triggers the included GitHub Actions workflow, runs the tests, builds `StudyLint.exe`, and attaches it to a GitHub Release.

To build locally:

```powershell
pip install -e ".[dev,build]"
pytest -q
pyinstaller --noconfirm --clean --onefile --windowed `
  --name StudyLint `
  --collect-all pymupdf `
  --collect-all pptx `
  src/studylint/gui.py
```

The result is written to `dist/StudyLint.exe`.

## Development

```powershell
pip install -e ".[dev]"
pytest -q
```

StudyLint intentionally excludes accounts, cloud sync, chat, flashcards, and study planning. Its focus is evidence-constrained verification of AI-generated notes and paper references.

## Privacy and course materials

- Notes and course materials are read and processed locally by default.
- Paper verification sends the entered DOI, title, or reference to Crossref and OpenAlex. CNKI, Google Scholar, or Baidu Scholar is contacted only after the user clicks a manual-search link.
- Do not commit copyrighted slides, private transcripts, or personal information to a public repository.
- Included examples are fictional.
- HTML reports may contain note and source excerpts and should not be shared casually.

## License

MIT
