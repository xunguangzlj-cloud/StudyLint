# GitHub首次发布清单

## 建议仓库信息

**Repository name**

`StudyLint`

**Description**

> A deterministic linter for citation-backed study notes, with Crossref paper verification to catch fabricated references.

**Topics**

`python`, `education`, `citations`, `crossref`, `doi`, `provenance`, `study-notes`, `markdown`, `pdf`, `powerpoint`, `transcript`, `linter`, `local-first`, `open-source`

## 发布前

- [x] `pyproject.toml` 作者已设置为GitHub用户名 `xunguangzlj-cloud`。
- [x] `LICENSE` 版权归属已设置为GitHub用户名 `xunguangzlj-cloud`。
- [x] 2026-09-21检查时，PyPI未发现名为 `studylint` 的发行包；正式发布前应再次确认。
- [ ] 将 `assets/social-preview.png` 上传到仓库社交预览设置。
- [ ] 运行 `pytest -q`。
- [ ] 确认示例中不存在受版权保护或私人资料。
- [ ] 创建标签 `v0.3.0`；发布工作流将构建Windows可执行文件并创建GitHub Release。

## 首次发布文案

> I built StudyLint because AI-generated study notes and references often look correct without being traceable. Check notes against course materials locally, then verify suspicious papers by DOI or title through Crossref with direct links to the registered record. No account or AI API required.
