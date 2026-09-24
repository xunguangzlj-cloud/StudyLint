<p align="center">
  <img src="assets/logo.svg" width="112" alt="StudyLint logo">
</p>

<h1 align="center">StudyLint</h1>

<p align="center"><strong>Break learning-time AI hallucinations by checking AI summaries and paper content.</strong></p>

<p align="center"><a href="README.md">简体中文</a> · <a href="README_EN.md">English</a></p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-4338CA">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2DD4BF">
  <img alt="Version 0.6.0" src="https://img.shields.io/badge/Version-0.6.0-F59E0B">
</p>

<p align="center">
  <sub><a href="https://github.com/xunguangzlj-cloud/StudyLint">⭐ Star</a> · <a href="https://github.com/xunguangzlj-cloud">Author</a></sub>
</p>

StudyLint is an evidence checker for AI-assisted learning and writing. Give it an AI summary plus trusted materials, and it checks marked source locations, page-to-claim mismatches, inaccurate direct quotations, numbers, and explicit internal conflicts. Give it AI-generated references or a manuscript, and it checks paper records and whether available cited full text supports the surrounding claim.

It never presents text similarity as verified truth. Deterministic checks need neither an account nor an LLM API; optional AI review uses the user's own key.

<p align="center">
  <img src="assets/demo.gif" width="900" alt="StudyLint terminal demo">
</p>

## Features

- **AI summary checking:** accepts Markdown, TXT, DOCX, PDF, and EPUB summaries and compares marked claims against user-supplied trusted materials.
- **Flexible source selection:** select one or more files directly, or recursively load an entire folder.
- **Page and timestamp validation:** detect missing PDF pages, slide numbers, or transcript timestamps.
- **Claim-to-location checks:** verify that the cited location has a meaningful textual relationship to the note.
- **Direct quotation checks:** test whether quoted text appears at the cited location.
- **Unextractable-page detection:** report scanned image pages, blank text layers, and ambiguous duplicate filenames separately.
- **Evidence suggestions:** show up to three locally matched candidate passages for human review.
- **Explicit definition conflicts:** compare only clear definition statements or bold term headings, skipping table fields and scenario labels.
- **Offline HTML reports:** show the reason, suggested action, original note, and clickable local source locations.
- **Paper checks:** “Does the paper exist?” verifies DOI, title, year, and retraction metadata. “Paper-content hallucination check” connects each claim, citation number, reference entry, and PDF/EPUB full text.
- **Progress and exact locations:** all three checks show a percentage and current stage. Paper-content reports identify Markdown/TXT lines, DOCX paragraphs, or PDF pages and page-local lines, alongside the exact claim and citation number.
- **Lawful open-full-text retrieval:** local PDF/EPUB files take priority. For high-confidence metadata matches, StudyLint can fetch an openly accessible PDF; failure prompts the user to import a PDF/EPUB and never proves nonexistence.
- **Optional AI deep review:** users supply their own OpenAI-compatible endpoint, model, and API key, then select fast/strict mode and a general, biomedical, or social-science review skill. Results use 11 controlled issue categories while remaining separate from rule verdicts.
- **GUI and CLI:** a file-picker interface for students and command-line/JSON output for developers.

## Quick start: graphical interface

Windows users can download the installer or portable ZIP from [GitHub Releases](https://github.com/xunguangzlj-cloud/StudyLint/releases/latest). The `setup` installer is recommended and creates desktop and Start-menu shortcuts. The portable ZIP runs after extraction and does not create shortcuts. Every release also includes `SHA256SUMS.txt` for integrity verification.

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

1. Under “AI summary check,” select a Markdown, TXT, DOCX, PDF, or EPUB summary.
2. Select one or more trusted PDF, EPUB, PPTX, DOCX, Markdown, TXT, or SRT files, or choose a source folder.
3. Click “Start check.”
4. Review confirmed errors, insufficient support, internal conflicts, and candidate evidence in the browser report.

For AI-generated paper references, open “Paper checks,” choose “Does the paper exist?”, and enter one DOI, title, or full reference per line. You may also import a TXT or CSV list. Papers that pass are hidden; the report lists only items that need manual checking, with per-paper search links that open in new tabs.

To check a complete AI-written or AI-assisted manuscript, choose “Paper-content hallucination check.” Local cited PDF/EPUB files are optional because StudyLint can first verify reference names/identifiers and try to retrieve lawful open full text. It recognizes half-width/full-width bracketed numbers, groups and ranges, parenthesized numbers, Unicode or DOCX superscripts, and Chinese or English author–year citations. Author–year citations are linked only when author and year uniquely match one bibliography entry. Naming a file `1-paper-title.pdf` or `1-paper-title.epub` improves matching. If no safe full text is available, the report retains the metadata result and asks for a local file instead of inferring support from a title or abstract.

Rule-based verification is local. For difficult paraphrases, optional AI deep review supports DeepSeek, OpenAI, Gemini, Qwen through Alibaba Cloud Model Studio, or a custom OpenAI-compatible service. Users enter their own key, which remains only in process memory. StudyLint sends only the claim, reference entry, and selected evidence snippets—not the full manuscript, PDF, or EPUB.

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

Results include title, authors, year, venue, match score, and paper link. StudyLint first queries Crossref and OpenAlex in parallel. Only when neither source produces a high-confidence match, or content checking still lacks open full text, does it query Semantic Scholar, arXiv, DBLP, Europe PMC, and DOAJ in parallel. DBLP improves computer-science coverage, Europe PMC covers life science and biomedicine, arXiv adds preprints, and DOAJ adds open-access journal articles. Weak results are filtered, duplicate records are merged, and OpenAlex retraction flags are reported separately.

Paper-content results open as an annotated manuscript view. Problematic passages are underlined in red, with a small red exclamation mark that shows the issue type and a concise reason on hover or keyboard focus. Full evidence remains available in a collapsed details section below the manuscript.

On Windows, local HTML reports are opened through the system file association. If automatic opening fails, StudyLint shows the saved path and keeps an “Open audit report” button available.

Items that need manual checking provide searches for CNKI, Google Scholar, and Baidu Scholar. The report hides passed papers and does not expose database responses or technical error details; it simply directs the user to verify each remaining item through the search links.

### Paper-content hallucination check

```powershell
studylint manuscript "ai-assisted-draft.docx" `
  --source-dir "cited-full-text" `
  --fetch-fulltext `
  --format html --open
```

You can repeat `--source` to specify local PDFs or EPUBs. With `--fetch-fulltext`, StudyLint checks the reference metadata and downloads only lawful open PDFs for high-confidence candidates. It then reports support level and relevant pages/chapters. Ambiguous same-author/same-year citations, footnote or endnote fields, and scanned PDFs still require manual review.

### Optional AI deep review

The GUI provides presets for DeepSeek, OpenAI, Gemini, Qwen through Alibaba Cloud Model Studio, and custom OpenAI-compatible services. Selecting a provider fills in a recommended endpoint and model while keeping both editable. The GUI masks the API key and does not persist it. The CLI reads the key from an environment variable so it does not appear in command history:

```powershell
studylint manuscript "ai-assisted-draft.docx" `
  --source-dir "cited-pdfs" `
  --format html --open `
  --ai `
  --ai-endpoint "https://api.openai.com/v1/chat/completions" `
  --ai-model "your-model-name" `
  --ai-mode strict `
  --ai-skill biomedical `
  --ai-key-env STUDYLINT_AI_API_KEY
```

`fast` reviews only cases that deterministic rules cannot directly confirm, reducing latency and cost. `strict` reviews every citation with available evidence. Skills are `general`, `biomedical`, and `social_science`. Controlled issue types cover citation/source, fact/background, data/result, method/process, logic, mathematics/formulas, concepts/terms, attribution, ethics/compliance, format/internal consistency, and time/version. The service must support the `chat/completions` message format; users are responsible for the provider's pricing, retention, and data-handling terms.

Exit codes:

- `0`: no note errors, every paper has a reliable candidate, or all manuscript checks have direct support;
- `1`: an error, unreliable candidate, or manuscript result requiring review exists;
- `2`: invalid input, argument, source file, or directory.

## Supported formats

| Purpose | Formats | Notes |
|---|---|---|
| AI summary check | Markdown, TXT, DOCX, PDF, EPUB | PDF/EPUB must contain extractable text |
| Trusted sources | PDF, EPUB, PPTX, SRT, Markdown, TXT, DOCX | A DOCX source is currently treated as one location |
| Paper-content hallucination check | Markdown, TXT, DOCX, PDF manuscript + local PDF/EPUB references | Numeric citations only; lawful open retrieval is optional |

Scanned PDFs without a text layer are not OCRed automatically. StudyLint reports locations where no text can be extracted so that they can be checked manually.

## Reliability boundaries

- No open-database match and no downloadable full text do not prove that a paper is nonexistent.
- StudyLint can flag insufficient evidence, number conflicts, opposite polarity, overstatement, and selected internal inconsistencies. A paper's own prose cannot prove that an experiment happened, raw data were not fabricated, or an ethics statement is genuine.
- The mathematics category is a review signal, not a complete proof checker or statistical-method validator.
- Missing verifiable evidence should produce “insufficient evidence,” not an accusation of fabrication or misconduct.

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
| `ST010` | Warning | A number in the note does not occur at an otherwise related cited location |

ST003 checks direct quotations; ST006 checks textual support at an explicitly cited location; ST010 then checks numbers when the cited passage is otherwise related. Missing citations do not trigger findings. StudyLint does not independently determine world truth: it checks against the trusted materials supplied by the user. Candidate evidence is a similarity-based suggestion, not proof.

## Performance

- PDF, PPTX, DOCX, and transcript sources are parsed in parallel.
- Batch paper verification uses up to four concurrent requests while preserving input order.
- Repeated text normalization and similarity features are cached.
- Network paper verification runs in the background so that the GUI remains responsive.

## Windows installer and portable build

The tag workflow publishes a per-user `windows-x64-setup.exe`, a `windows-x64-portable.zip`, and `SHA256SUMS.txt`. GitHub also adds source ZIP/TAR archives automatically. The installer creates desktop and Start-menu shortcuts; the portable build runs after extraction without modifying the system installation directory.

To build locally:

```powershell
pip install -e ".[dev,build]"
pytest -q
python -c "import tkinter; root = tkinter.Tcl(); print(root.eval('info patchlevel'))"
pyinstaller --noconfirm --clean --onefile --windowed `
  --name StudyLint `
  --icon src/studylint/assets/studylint.ico `
  --add-data "src/studylint/assets/studylint.ico;studylint/assets" `
  --collect-all pymupdf `
  --collect-all pptx `
  src/studylint/gui.py
```

The portable result is written to `dist/StudyLint.exe`. The Tcl/Tk check must pass before packaging; otherwise PyInstaller may omit `tkinter` and produce a GUI that cannot start. `installer/StudyLint.iss` builds the installer with Inno Setup.

## Development

```powershell
pip install -e ".[dev]"
pytest -q
```

StudyLint intentionally excludes accounts, cloud sync, chat, flashcards, and study planning. Its focus is evidence-constrained verification of AI-generated notes and paper references.

## Privacy and course materials

- Notes and course materials are read and processed locally by default.
- Manuscript citation checks are local by default. When optional AI review is enabled, only the claim, reference entry, and selected evidence snippets are sent to the user-configured endpoint; full files are not sent.
- Automatic full-text retrieval is restricted to high-confidence metadata. It follows openly accessible PDF links and, when an API exposes no PDF, may inspect the public landing page for a standard PDF metadata tag. Local PDF/EPUB files take priority, and StudyLint does not bypass paywalls.
- GUI API keys remain in process memory for the current run and are not written to project files. The CLI reads only from the user-selected environment variable.
- Paper-existence verification sends the entered DOI, title, or reference to Crossref and OpenAlex. If neither source produces a high-confidence match, the input is also sent to Semantic Scholar, arXiv, DBLP, Europe PMC, and DOAJ. CNKI, Google Scholar, or Baidu Scholar is contacted only after the user clicks a manual-search link.
- Do not commit copyrighted slides, private transcripts, or personal information to a public repository.
- Included examples are fictional.
- HTML reports may contain note and source excerpts and should not be shared casually.

## Design references and acknowledgements

- [cite-verify](https://github.com/jonckr/cite-verify) inspired bidirectional coverage/F1 title matching that resists truncated-title false positives, and separate reporting for real identifiers paired with conflicting metadata.
- [RefChecker](https://github.com/markrussinovich/refchecker) inspired field-level checks for titles and years and conservative treatment of database candidates.
- [CiteCheck](https://github.com/color4-alt/CiteCheck) inspired layered multi-database retrieval. StudyLint uses a lightweight tiered and parallel variant.
- [Reference Integrity Checker](https://github.com/danielaristo/reference-integrity-checker) inspired cross-source deduplication, retraction screening, and the boundary that not found does not mean fabricated.
- [receipts](https://github.com/JamesWeatherhead/receipts) and [ClaimLint](https://github.com/klittle32/claimlint) inspired evidence-by-evidence discrepancy reporting and the boundary that unsupported does not automatically mean false.
- [sciwrite-lint](https://github.com/authentic-research-partners/sciwrite-lint) and the [UCL Citation Integrity Auditor](https://github.com/UCL-ERL/skills/tree/main/skills/writing/citation-integrity-auditor) inspired the claim–citation–metadata–full-text chain, graded support verdicts, and the rule that unavailable full text remains unverified.
- [LitRAG](https://github.com/nickjlamb/litrag) inspired the two-stage design: deterministic passage location first, then model judging only where needed.
- [RAGChecker](https://github.com/amazon-science/RAGChecker) and [DeepEval Faithfulness](https://github.com/confident-ai/deepeval/blob/main/docs/content/docs/%28rag%29/metrics-faithfulness.mdx) inspired claim-level verification, evidence grounding, and configurable judge prompts.
- The [citation-verify skill](https://github.com/InfinityScopebio/citation-verify) inspired atomic calls, structured JSON output, and per-item failure isolation.
- [Hallucinator](https://github.com/gianlucasb/hallucinator) inspired the arXiv, DBLP, and Europe PMC adapter strategy. Because it uses the AGPL, StudyLint learned from the design only and did not copy its code.
- [OpenAlex](https://help.openalex.org/access/fulltext/), [Unpaywall/oadoi](https://github.com/ourresearch/oadoi), [DOAJ](https://github.com/DOAJ/doaj), [arxiv.py](https://github.com/lukasschwab/arxiv.py), [Europe PMC](https://github.com/EuropePMC), and the [Semantic Scholar API](https://api.semanticscholar.org/api-docs/) were used to verify correct open-full-text, identifier, preprint, and disciplinary-database behavior.

StudyLint remains lightweight and local-first and does not include those projects' model-driven workflows. Refer to each upstream repository for its current license terms.

## License

MIT
