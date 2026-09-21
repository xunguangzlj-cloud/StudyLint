<p align="center">
  <img src="assets/logo.svg" width="112" alt="StudyLint logo">
</p>

<h1 align="center">StudyLint</h1>

<p align="center"><strong>打破学习中的AI幻觉：核查笔记事实，也核查论文引用。</strong></p>

<p align="center">
  <img alt="Python 3.10+" src="https://img.shields.io/badge/Python-3.10%2B-4338CA">
  <img alt="License MIT" src="https://img.shields.io/badge/License-MIT-2DD4BF">
  <img alt="Version 0.5" src="https://img.shields.io/badge/Version-0.5-F59E0B">
</p>

StudyLint 是一个面向AI学习场景的证据核查工具。把AI整理的笔记和可信课程材料交给它，它会检查失效引用、页码与结论不匹配、直接引语错误、高风险事实缺少来源和冲突定义；把AI生成的参考文献交给它，它会批量核验开放元数据并提供人工检索入口。

它不会把“相似文本”冒充已验证事实，也不需要账号或大模型API。

<p align="center">
  <img src="assets/demo.gif" width="900" alt="StudyLint terminal demo">
</p>

## 主要功能

- **自动发现课程材料**：选择资料文件夹即可递归读取支持的文件。
- **检查页码和时间点**：发现不存在的PDF页码、PPT页码或字幕时间点。
- **核对页码是否支持结论**：不是只判断页码存在，还检查笔记内容与指定位置是否有明显文本关联。
- **核对直接引语**：检查引号内的原文能否在指定来源位置找到。
- **发现高风险事实**：优先标记没有来源的数字、因果关系和绝对化表述。
- **识别无法自动核验的页**：扫描图片页、空文本页和同名来源会单独提示，而不是误判内容错误。
- **推荐可能证据**：使用本地文本匹配提供最多3条候选来源，由用户最终确认。
- **发现冲突定义**：提示同一术语在笔记中出现差异较大的定义。
- **离线HTML报告**：显示问题原因、修改建议、笔记原文和可点击来源。
- **批量论文核验**：通过Crossref与OpenAlex核验DOI或题名，过滤低相关结果，并提供知网等人工检索入口。
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
3. 点击“开始事实与引用核查”；
4. 在浏览器中分别查看确定错误、事实支持不足、内部冲突和证据候选。

核实AI生成的论文时，切换到“AI论文引用核查”标签页，每行粘贴一个DOI、论文标题或完整参考文献，然后点击“开始批量核验”。也可以导入TXT或CSV清单。输入区支持右键剪切、复制、粘贴和全选。报告中的人工检索链接会在新标签页打开，也可以一键打开全部论文的知网核查页。

笔记与课程材料只在本机处理。生成的报告保存在笔记旁边：

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

批量核验时准备一个每行一篇的`papers.txt`：

```powershell
studylint paper --file papers.txt --format html --open
```

结果会显示标题、作者、年份、期刊、匹配度和论文链接。自动查询Crossref与OpenAlex开放元数据；低相关结果会被过滤。每篇结果还提供知网、Google Scholar和百度学术搜索链接。开放数据库未匹配不等于论文一定不存在，因为部分中文论文可能只被知网等数据库收录，或输入信息不完整。

退出码：

- `0`：笔记没有错误，或全部论文都有开放数据库候选；
- `1`：笔记至少有一个错误，或至少一篇论文没有可靠候选；
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

页码还可以写成`#p=12`、`#页=12`或`#页码=12`；时间点还可以写成`#t=00:31:42`或`#时间=00:31:42`。StudyLint会先确认位置存在，再检查结论与该位置文本是否匹配。

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
| `ST006` | 警告 | 笔记结论与所标页码或时间点缺少明显关联 |
| `ST007` | 警告 | 数字、因果或绝对化高风险事实没有来源 |
| `ST008` | 警告 | 引用位置没有可提取文字，无法自动核验 |
| `ST009` | 错误 | 资料目录存在同名文件，引用来源不明确 |

`ST003`检查直接引语，`ST006`检查结论与指定位置的文本支持度。它们都不会凭空判断世界知识真假：只有与用户提供的可信材料对照后，才能指出确定错误或证据不足。证据推荐只代表文本相关，不代表来源已经支持该结论。

## 速度优化

- 多份PDF、PPTX、DOCX和字幕材料会并行解析；
- 批量论文最多四路并行查询，同时保留输入顺序；
- 重复的文本标准化和相似度基础数据会缓存；
- 网络核验在后台执行，图形界面不会因批量任务失去响应。

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

项目刻意不加入账号、云同步、聊天、闪卡和学习计划。核心始终是用可信证据约束AI生成内容，降低学习笔记与论文写作中的事实和引用幻觉。

## 隐私与课程材料

- 文件默认只在本机读取和处理；
- 使用论文核验时，输入的DOI、标题或参考文献会发送到Crossref与OpenAlex查询；只有点击人工检索按钮后，浏览器才会访问知网、Google Scholar或百度学术；
- 不要向公开仓库提交受版权保护的课件、私人课堂转写或个人信息；
- 示例课程完全虚构；
- HTML报告可能包含笔记与来源片段，不应随意公开分享。

## English summary

StudyLint is a local-first guard against hallucinated study notes and paper citations. It checks source locations, quotation accuracy, claim-to-page support, risky uncited facts, conflicting definitions, and batches suspicious references for metadata and manual verification.

## License

MIT
