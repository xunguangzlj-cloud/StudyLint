<p align="center">
  <img src="assets/logo.svg" width="112" alt="StudyLint logo">
</p>

<h1 align="center">StudyLint</h1>

<p align="center"><strong>让每条学习笔记都能追溯来源。</strong></p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-4338CA">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2DD4BF">
  <img alt="Version 0.3" src="https://img.shields.io/badge/Version-0.3-F59E0B">
</p>

StudyLint 是一个本地运行的课程笔记检查工具。把笔记和课程材料交给它，它会检查失效引用、不匹配的原文、缺少来源的结论和冲突定义，并生成可点击来源的中文报告。

它不会把“相似文本”冒充已验证事实，也不需要账号或大模型API。

<p align="center">
  <img src="assets/demo.gif" width="900" alt="StudyLint terminal demo">
</p>

## 主要功能

- **自动发现课程材料**：选择资料文件夹即可递归读取支持的文件。
- **检查页码和时间点**：发现不存在的PDF页码、PPT页码或字幕时间点。
- **核对直接引语**：检查引号内的原文能否在指定来源位置找到。
- **发现缺少来源的结论**：标记较长但没有引用的笔记内容。
- **推荐可能证据**：使用本地文本匹配提供最多3条候选来源，由用户最终确认。
- **发现冲突定义**：提示同一术语在笔记中出现差异较大的定义。
- **离线HTML报告**：显示问题原因、修改建议、笔记原文和可点击来源。
- **论文存在性核验**：通过Crossref按DOI精确查询，或按题名检索候选论文并给出直达链接。
- **图形界面与CLI**：普通学生使用文件选择界面，开发者可使用终端和JSON。

## 最快使用方法：图形界面

不想安装Python时，从GitHub Releases下载`StudyLint.exe`并双击运行即可。Windows首次打开陌生发布者程序时可能显示安全提示，请先确认文件来自本项目的Release页面。

从源码运行需要Python 3.10或更新版本：

```powershell
git clone <你的StudyLint仓库地址>
cd StudyLint
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .
studylint gui
```

然后：

1. 选择一份`.md`、`.txt`或`.docx`笔记；
2. 选择存放PPT、PDF和课堂转写的资料文件夹；
3. 点击“开始检查并打开报告”；
4. 在浏览器中查看错误、警告和证据候选。

核实AI生成的论文时，在界面下方粘贴DOI、论文标题或完整参考文献，然后点击“核实并查看”。DOI核验最准确；标题检索会列出候选记录，仍需核对作者、年份和期刊。

所有材料只在本机处理。生成的报告保存在笔记旁边：

```text
原文件：信息管理复习笔记.docx
报告：  信息管理复习笔记-studylint-report.html
```

## 命令行使用方法

### 检查整个资料文件夹

```powershell
studylint check "复习笔记.docx" `
  --source-dir "课程材料" `
  --format html `
  --open
```

`--source-dir`会递归发现文件夹内所有支持的课程材料，并自动排除正在检查的笔记。

### 明确指定来源文件

```powershell
studylint check notes.md `
  --source slides.pdf `
  --source lecture.srt
```

`--source`和`--source-dir`可以同时使用。

### 生成JSON结果

```powershell
studylint check notes.md `
  --source-dir materials `
  --format json `
  --output report.json
```

### 核实论文是否有登记记录

优先使用DOI：

```powershell
studylint paper "10.1038/nature12373" --format html --open
```

没有DOI时，可以输入标题或整条参考文献：

```powershell
studylint paper "Nanometre-scale thermometry in a living cell" --format html --open
```

结果会显示标题、作者、年份、期刊、匹配度和DOI链接。数据来自Crossref开放元数据，需要联网。Crossref未检索到记录不等于论文一定不存在，因为部分论文可能登记在其他数据库，或输入信息不完整。

退出码：

- `0`：没有错误，可能仍有警告；
- `1`：至少发现一个错误；
- `2`：输入文件、参数或资料目录无效。

## 支持格式

| 用途 | 格式 | 说明 |
|---|---|---|
| 待检查笔记 | Markdown、TXT、DOCX | DOCX中的“行号”表示段落序号 |
| 课程来源 | PDF、PPTX、SRT、Markdown、TXT、DOCX | DOCX来源暂作为一个整体位置处理 |

扫描版PDF如果没有文本层，目前不会自动OCR。StudyLint会读取可提取的文字，OCR将作为可选组件另行提供。

## 可选引用语法

用户不必先写引用；没有引用的结论也会获得候选来源。如果希望进行精确校验，可以使用：

```markdown
信息具有可传递性。[slides.pdf#page=12]
老师强调需要理解该概念。[lecture.srt#time=00:31:42]
```

Markdown或TXT来源可以用标记模拟页码：

```markdown
<!-- page: 1 -->
第一页内容

<!-- page: 2 -->
第二页内容
```

## 忽略一次误报

在Markdown或TXT笔记中，把忽略指令放在需要忽略的内容前：

```markdown
<!-- studylint-ignore ST004 -->
这是我自己的总结，不需要课程来源。
```

该指令只影响下一条有效笔记，不会关闭后续检查。可以同时忽略多条规则：

```markdown
<!-- studylint-ignore ST004, ST005 -->
```

## 检查规则

| 规则 | 级别 | 含义 |
|---|---|---|
| `ST001` | 错误 | 引用的来源文件没有提供 |
| `ST002` | 错误 | 引用页码或时间点无效 |
| `ST003` | 错误 | 引号内的原文没有出现在引用位置 |
| `ST004` | 警告 | 较长的笔记结论没有来源引用 |
| `ST005` | 警告 | 同一术语出现差异较大的定义 |

`ST003`只检查中文或英文引号中的直接引语，不会判断改写后的句子是否语义正确。证据推荐只代表文本相关，不代表来源已经支持该结论。

## Windows免安装版本

仓库包含标签发布工作流。推送`v*`标签后，GitHub Actions会测试项目、构建`StudyLint.exe`并附加到GitHub Release。GitHub仓库发布前，也可以在Windows本机测试：

```powershell
pip install -e ".[dev,build]"
pytest -q
pyinstaller --noconfirm --clean --onefile --windowed `
  --name StudyLint `
  --collect-all pymupdf `
  --collect-all pptx `
  src/studylint/gui.py
```

生成结果位于`dist/StudyLint.exe`。

## 开发

```powershell
pip install -e ".[dev]"
pytest -q
```

项目刻意不加入账号、云同步、聊天、闪卡和学习计划。当前重点是让来源检查可靠、便携并可操作。

## 隐私与课程材料

- 文件默认只在本机读取和处理；
- 使用论文核验时，输入的DOI、标题或参考文献会发送到Crossref查询；
- 不要向公开仓库提交受版权保护的课件、私人课堂转写或个人信息；
- 示例课程完全虚构；
- HTML报告可能包含笔记与来源片段，不应随意公开分享。

## English summary

StudyLint is a local-first linter for study notes. It checks source references, pages, transcript timestamps, direct quotations, uncited claims, and conflicting definitions. It supports a desktop-style file picker, CLI, JSON, and self-contained HTML reports without requiring an AI API.

## License

MIT
