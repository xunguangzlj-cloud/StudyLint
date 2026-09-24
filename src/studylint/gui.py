from __future__ import annotations

import ctypes
import os
import sys
import threading
import webbrowser
from pathlib import Path
from typing import Callable

from studylint import AUTHOR_URL, PROJECT_URL
from studylint.ai_audit import (
    AI_CUSTOM_PROVIDER,
    AI_PROVIDER_PRESETS,
    AIConfig,
    AI_SKILLS,
    deep_verify_audits,
)
from studylint.manuscripts import (
    CitationAudit,
    audit_manuscript,
    scan_manuscript_issues,
)
from studylint.parsers import discover_sources, load_sources, parse_notes
from studylint.papers import (
    PaperLookupError,
    PaperVerification,
    parse_queries,
    read_query_file,
    verify_paper,
    verify_papers,
)
from studylint.reporters import (
    render_html,
    render_manuscript_html,
    render_paper_batch_html,
    render_paper_html,
    summary,
)
from studylint.rules import lint


ProgressCallback = Callable[[int, str], None]


def open_local_report(path: Path) -> bool:
    """用系统文件关联打开本地报告，失败时再回退到浏览器模块。"""
    resolved = path.resolve()
    if sys.platform == "win32":
        try:
            os.startfile(resolved)  # type: ignore[attr-defined]
        except OSError:
            pass
        else:
            return True
    try:
        return webbrowser.open_new_tab(resolved.as_uri())
    except (OSError, webbrowser.Error):
        return False


def check_to_html(
    notes_path: Path,
    source_inputs: Path | list[Path],
    progress: ProgressCallback | None = None,
) -> tuple[Path, dict[str, int]]:
    inputs = [source_inputs] if isinstance(source_inputs, Path) else source_inputs
    source_paths: list[Path] = []
    for source_input in inputs:
        if source_input.is_dir():
            source_paths.extend(discover_sources(source_input, exclude=notes_path))
        elif source_input.is_file():
            if source_input.resolve() != notes_path.resolve():
                source_paths.append(source_input)
        else:
            raise ValueError(f"资料不存在：{source_input}")
    source_paths = list(dict.fromkeys(path.resolve() for path in source_paths))
    if not source_paths:
        raise ValueError("没有选择可支持的课程资料。")
    if progress:
        progress(20, "正在读取AI总结")
    units = parse_notes(notes_path)
    if progress:
        progress(45, f"正在解析{len(source_paths)}份对照资料")
    sources = load_sources(source_paths)
    if progress:
        progress(75, "正在核对引用与内部一致性")
    findings = lint(units, sources)
    if progress:
        progress(92, "正在生成核查报告")
    output = notes_path.with_name(f"{notes_path.stem}-studylint-report.html")
    output.write_text(render_html(notes_path, findings), encoding="utf-8")
    if progress:
        progress(100, "核查完成")
    return output, summary(findings)


def paper_to_html(
    query: str,
    output_directory: Path,
    lookup=verify_paper,
) -> tuple[Path, PaperVerification]:
    verification = lookup(query)
    output = output_directory / "studylint-paper-report.html"
    output.write_text(render_paper_html(verification), encoding="utf-8")
    return output, verification


def papers_to_html(
    queries: list[str],
    output_directory: Path,
    lookup=verify_papers,
    progress: ProgressCallback | None = None,
) -> tuple[Path, list[PaperVerification]]:
    if progress:
        progress(5, f"准备核验{len(queries)}篇论文")

        def paper_progress(completed: int, total: int) -> None:
            progress(
                5 + round(85 * completed / total),
                f"正在核验论文（{completed}/{total}）",
            )

        verifications = lookup(queries, progress=paper_progress)
        progress(95, "正在生成论文核验报告")
    else:
        verifications = lookup(queries)
    output = output_directory / "studylint-paper-report.html"
    output.write_text(render_paper_batch_html(verifications), encoding="utf-8")
    if progress:
        progress(100, "论文核验完成")
    return output, verifications


def manuscript_to_html(
    manuscript_path: Path,
    reference_inputs: list[Path],
    ai_config: AIConfig | None = None,
    auto_fetch: bool = False,
    progress: ProgressCallback | None = None,
) -> tuple[Path, list[CitationAudit]]:
    audits = audit_manuscript(
        manuscript_path,
        reference_inputs,
        auto_fetch=auto_fetch,
        cache_dir=manuscript_path.parent / "StudyLint-原文",
        progress=progress,
    )
    if ai_config is not None:
        if progress:
            progress(78, "正在准备AI深度复核")

            def ai_progress(completed: int, total: int) -> None:
                progress(
                    78 + round(17 * completed / total),
                    f"正在进行AI深度复核（{completed}/{total}）",
                )

            audits = deep_verify_audits(audits, ai_config, progress=ai_progress)
        else:
            audits = deep_verify_audits(audits, ai_config)
    if progress:
        progress(96, "正在检查整稿一致性")
    issues = scan_manuscript_issues(manuscript_path)
    output = manuscript_path.with_name(
        f"{manuscript_path.stem}-paper-content-audit.html"
    )
    output.write_text(
        render_manuscript_html(manuscript_path, audits, issues), encoding="utf-8"
    )
    if progress:
        progress(100, "论文内容核查完成")
    return output, audits


def enable_high_dpi() -> None:
    if sys.platform != "win32":
        return
    try:
        setter = ctypes.windll.user32.SetProcessDpiAwarenessContext
        setter.argtypes = [ctypes.c_void_p]
        setter(ctypes.c_void_p(-4))
    except (AttributeError, OSError):
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def _application_icon_path() -> Path | None:
    candidates = [Path(__file__).resolve().parent / "assets" / "studylint.ico"]
    bundle_root = getattr(sys, "_MEIPASS", "")
    if bundle_root:
        candidates.insert(
            0, Path(bundle_root) / "studylint" / "assets" / "studylint.ico"
        )
    return next((path for path in candidates if path.is_file()), None)


def _apply_window_icon(window) -> None:
    icon = _application_icon_path()
    if icon is None:
        return
    try:
        window.iconbitmap(default=str(icon))
    except Exception:
        pass


def main() -> None:
    enable_high_dpi()

    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("StudyLint")
    root.geometry("820x640")
    root.minsize(720, 600)
    _apply_window_icon(root)

    for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(font_name).configure(family="Microsoft YaHei UI", size=10)

    style = ttk.Style(root)
    style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    notes_value = tk.StringVar()
    sources_value = tk.StringVar()
    notes_status = tk.StringVar(value="待核查")
    notes_progress = tk.DoubleVar(value=0)
    paper_status = tk.StringVar(value="待核验")
    paper_progress = tk.DoubleVar(value=0)
    manuscript_value = tk.StringVar()
    manuscript_sources_value = tk.StringVar()
    manuscript_status = tk.StringVar(value="待核查")
    manuscript_progress = tk.DoubleVar(value=0)
    auto_fetch_fulltext = tk.BooleanVar(value=True)
    ai_enabled = tk.BooleanVar(value=False)
    default_ai_provider = "DeepSeek"
    default_ai_endpoint, default_ai_model = AI_PROVIDER_PRESETS[default_ai_provider]
    ai_provider = tk.StringVar(value=default_ai_provider)
    ai_endpoint = tk.StringVar(value=default_ai_endpoint)
    ai_model = tk.StringVar(value=default_ai_model)
    ai_api_key = tk.StringVar()
    ai_mode = tk.StringVar(value="快速")
    ai_skill = tk.StringVar(value="通用学术")

    def set_progress(progress_var, status_var, value: int, message: str) -> None:
        value = max(0, min(100, value))
        progress_var.set(value)
        status_var.set(f"{value}% · {message}")

    def queue_progress(progress_var, status_var, value: int, message: str) -> None:
        root.after(
            0,
            lambda: set_progress(progress_var, status_var, value, message),
        )

    outer = ttk.Frame(root, padding=(28, 22))
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="StudyLint", font=("Segoe UI", 25, "bold")).pack(anchor="w")

    notebook = ttk.Notebook(outer)
    notebook.pack(fill="both", expand=True, pady=(12, 0))
    notes_tab = ttk.Frame(notebook, padding=24)
    papers_tab = ttk.Frame(notebook, padding=(14, 12))
    notebook.add(notes_tab, text="  AI总结核查  ")
    notebook.add(papers_tab, text="  论文核查  ")

    paper_modes = ttk.Notebook(papers_tab)
    paper_modes.pack(fill="both", expand=True)
    paper_existence_tab = ttk.Frame(paper_modes, padding=20)
    manuscript_tab = ttk.Frame(paper_modes, padding=20)
    paper_modes.add(paper_existence_tab, text="  论文是否真实存在  ")
    paper_modes.add(manuscript_tab, text="  论文内容幻觉核查  ")

    def add_edit_menu(widget, text_widget: bool = False) -> None:
        menu = tk.Menu(widget, tearoff=False)
        menu.add_command(label="剪切", command=lambda: widget.event_generate("<<Cut>>"))
        menu.add_command(label="复制", command=lambda: widget.event_generate("<<Copy>>"))
        menu.add_command(label="粘贴", command=lambda: widget.event_generate("<<Paste>>"))
        menu.add_separator()

        def select_all() -> None:
            if text_widget:
                widget.tag_add("sel", "1.0", "end-1c")
                widget.mark_set("insert", "1.0")
            else:
                widget.selection_range(0, "end")
                widget.icursor("end")

        menu.add_command(label="全选", command=select_all)

        def show_menu(event) -> str:
            widget.focus_set()
            menu.tk_popup(event.x_root, event.y_root)
            return "break"

        widget.bind("<Button-3>", show_menu)

    ttk.Label(notes_tab, text="AI总结文件").grid(row=0, column=0, sticky="w", pady=9)
    notes_entry = ttk.Entry(notes_tab, textvariable=notes_value)
    notes_entry.grid(row=0, column=1, sticky="ew", padx=12, pady=9)
    add_edit_menu(notes_entry)

    def choose_notes() -> None:
        selected = filedialog.askopenfilename(
            title="选择AI总结",
            filetypes=[
                ("支持的总结", "*.md *.txt *.docx *.pdf *.epub"),
                ("全部文件", "*.*"),
            ],
        )
        if selected:
            notes_value.set(selected)

    ttk.Button(notes_tab, text="选择", command=choose_notes).grid(row=0, column=2)
    ttk.Label(notes_tab, text="对照资料").grid(row=1, column=0, sticky="w", pady=9)
    sources_entry = ttk.Entry(notes_tab, textvariable=sources_value)
    sources_entry.grid(row=1, column=1, sticky="ew", padx=12, pady=9)
    add_edit_menu(sources_entry)

    def choose_source_files() -> None:
        selected = filedialog.askopenfilenames(
            title="选择课程资料",
            filetypes=[
                ("支持的资料", "*.pdf *.epub *.pptx *.docx *.md *.txt *.srt"),
                ("全部文件", "*.*"),
            ],
        )
        if selected:
            sources_value.set("; ".join(selected))

    def choose_source_directory() -> None:
        selected = filedialog.askdirectory(title="选择课程资料文件夹")
        if selected:
            sources_value.set(selected)

    ttk.Button(notes_tab, text="选择文件", command=choose_source_files).grid(
        row=1, column=2, padx=(0, 6)
    )
    ttk.Button(notes_tab, text="选择文件夹", command=choose_source_directory).grid(
        row=1, column=3
    )

    def run_check() -> None:
        notes_path = Path(notes_value.get())
        source_inputs = [
            Path(value.strip().strip('"'))
            for value in sources_value.get().split(";")
            if value.strip()
        ]
        if not notes_path.is_file() or not source_inputs:
            messagebox.showerror("无法开始", "请选择有效的笔记文件和课程资料。")
            return
        notes_button.state(["disabled"])
        set_progress(notes_progress, notes_status, 0, "准备开始核查")

        def worker() -> None:
            try:
                output, counts = check_to_html(
                    notes_path,
                    source_inputs,
                    progress=lambda value, message: queue_progress(
                        notes_progress, notes_status, value, message
                    ),
                )
            except (OSError, ValueError) as error:
                root.after(0, lambda message=str(error): finish_notes_error(message))
                return
            root.after(0, lambda: finish_notes_check(output, counts))

        threading.Thread(target=worker, daemon=True).start()

    def finish_notes_error(message: str) -> None:
        notes_button.state(["!disabled"])
        notes_status.set(f"{round(notes_progress.get())}% · 核查失败")
        messagebox.showerror("检查失败", message)

    def finish_notes_check(output: Path, counts: dict[str, int]) -> None:
        notes_button.state(["!disabled"])
        notes_progress.set(100)
        notes_status.set(
            f"100% · 完成：{counts['errors']}个错误，{counts['warnings']}个警告"
        )
        if not open_local_report(output):
            messagebox.showwarning(
                "报告已生成",
                f"系统未能自动打开报告，请手动打开：\n{output.resolve()}",
            )

    notes_button = ttk.Button(
        notes_tab,
        text="开始核查",
        command=run_check,
        style="Accent.TButton",
    )
    notes_button.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(24, 10))
    ttk.Progressbar(
        notes_tab, variable=notes_progress, maximum=100, mode="determinate"
    ).grid(row=3, column=0, columnspan=4, sticky="ew")
    ttk.Label(notes_tab, textvariable=notes_status, foreground="#4338ca").grid(
        row=4, column=0, columnspan=4, sticky="w", pady=(6, 0)
    )
    notes_tab.columnconfigure(1, weight=1)

    ttk.Label(
        paper_existence_tab,
        text="粘贴AI生成或引用的DOI、论文标题、完整参考文献，每行一篇：",
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
    paper_input = scrolledtext.ScrolledText(
        paper_existence_tab,
        height=10,
        wrap="word",
        undo=True,
        font=("Microsoft YaHei UI", 10),
        relief="solid",
        borderwidth=1,
    )
    paper_input.grid(row=1, column=0, columnspan=3, sticky="nsew")
    add_edit_menu(paper_input, text_widget=True)

    def import_papers() -> None:
        selected = filedialog.askopenfilename(
            title="导入论文清单",
            filetypes=[("文本清单", "*.txt *.csv"), ("全部文件", "*.*")],
        )
        if not selected:
            return
        try:
            queries = read_query_file(Path(selected))
        except (OSError, ValueError) as error:
            messagebox.showerror("导入失败", str(error))
            return
        paper_input.delete("1.0", "end")
        paper_input.insert("1.0", "\n".join(queries))
        paper_status.set(f"已导入{len(queries)}篇论文。")

    ttk.Button(paper_existence_tab, text="导入清单", command=import_papers).grid(
        row=2, column=0, sticky="w", pady=(14, 0)
    )
    ttk.Button(
        paper_existence_tab,
        text="清空",
        command=lambda: paper_input.delete("1.0", "end"),
    ).grid(row=2, column=1, sticky="w", pady=(14, 0), padx=10)

    verify_button = ttk.Button(
        paper_existence_tab, text="开始真实性核验", style="Accent.TButton"
    )
    verify_button.grid(row=2, column=2, sticky="e", pady=(14, 0))

    def finish_paper_error(message: str) -> None:
        verify_button.state(["!disabled"])
        paper_status.set(f"{round(paper_progress.get())}% · 论文核验失败")
        messagebox.showerror("论文核验失败", message)

    def finish_paper_check(output: Path, verifications: list[PaperVerification]) -> None:
        verify_button.state(["!disabled"])
        accepted = {"VERIFIED_METADATA", "IDENTIFIER_FOUND"}
        pending = sum(item.verdict not in accepted for item in verifications)
        paper_progress.set(100)
        message = (
            f"{pending}篇需要自行核查；已通过项不显示。"
            if pending
            else "没有需要继续人工核查的论文。"
        )
        paper_status.set(f"100% · 完成：{message}")
        if not open_local_report(output):
            messagebox.showwarning(
                "报告已生成",
                f"系统未能自动打开报告，请手动打开：\n{output.resolve()}",
            )

    def run_paper_check() -> None:
        queries = parse_queries(paper_input.get("1.0", "end"))
        if not queries:
            messagebox.showerror("无法核实", "请至少输入一篇论文。")
            return
        verify_button.state(["disabled"])
        set_progress(paper_progress, paper_status, 0, f"准备核验{len(queries)}篇论文")
        notes_path = Path(notes_value.get())
        output_directory = notes_path.parent if notes_path.is_file() else Path.cwd()

        def worker() -> None:
            try:
                output, verifications = papers_to_html(
                    queries,
                    output_directory,
                    progress=lambda value, message: queue_progress(
                        paper_progress, paper_status, value, message
                    ),
                )
            except (OSError, PaperLookupError, ValueError) as error:
                root.after(0, lambda message=str(error): finish_paper_error(message))
                return
            root.after(0, lambda: finish_paper_check(output, verifications))

        threading.Thread(target=worker, daemon=True).start()

    verify_button.configure(command=run_paper_check)
    ttk.Progressbar(
        paper_existence_tab, variable=paper_progress, maximum=100, mode="determinate"
    ).grid(row=3, column=0, columnspan=3, sticky="ew", pady=(16, 0))
    ttk.Label(paper_existence_tab, textvariable=paper_status, foreground="#4338ca").grid(
        row=4, column=0, columnspan=3, sticky="w", pady=(6, 0)
    )
    paper_existence_tab.columnconfigure(1, weight=1)
    paper_existence_tab.rowconfigure(1, weight=1)

    ttk.Label(manuscript_tab, text="论文稿件").grid(
        row=0, column=0, sticky="w", pady=9
    )
    manuscript_entry = ttk.Entry(manuscript_tab, textvariable=manuscript_value)
    manuscript_entry.grid(row=0, column=1, columnspan=2, sticky="ew", padx=12, pady=9)
    add_edit_menu(manuscript_entry)

    def choose_manuscript() -> None:
        selected = filedialog.askopenfilename(
            title="选择论文稿件",
            filetypes=[
                ("支持的写作稿", "*.md *.txt *.docx *.pdf"),
                ("全部文件", "*.*"),
            ],
        )
        if selected:
            manuscript_value.set(selected)

    ttk.Button(manuscript_tab, text="选择", command=choose_manuscript).grid(
        row=0, column=3
    )
    ttk.Label(manuscript_tab, text="本地原文（可选）").grid(
        row=1, column=0, sticky="w", pady=9
    )
    manuscript_sources_entry = ttk.Entry(
        manuscript_tab, textvariable=manuscript_sources_value
    )
    manuscript_sources_entry.grid(
        row=1, column=1, columnspan=2, sticky="ew", padx=12, pady=9
    )
    add_edit_menu(manuscript_sources_entry)

    def set_manuscript_sources(paths: tuple[str, ...] | list[str]) -> None:
        existing = [
            value.strip()
            for value in manuscript_sources_value.get().split(";")
            if value.strip()
        ]
        manuscript_sources_value.set("; ".join(dict.fromkeys(existing + list(paths))))

    def choose_manuscript_sources() -> None:
        selected = filedialog.askopenfilenames(
            title="选择本地原文",
            filetypes=[("PDF或EPUB", "*.pdf *.epub"), ("全部文件", "*.*")],
        )
        if selected:
            set_manuscript_sources(selected)

    def choose_manuscript_source_directory() -> None:
        selected = filedialog.askdirectory(title="选择本地原文文件夹")
        if selected:
            set_manuscript_sources([selected])

    ttk.Button(
        manuscript_tab, text="选择文件", command=choose_manuscript_sources
    ).grid(row=1, column=3, padx=(0, 6))
    ttk.Button(
        manuscript_tab,
        text="选择文件夹",
        command=choose_manuscript_source_directory,
    ).grid(row=1, column=4)
    mode_codes = {"快速": "fast", "严格": "strict"}
    skill_codes = {label: code for code, (label, _) in AI_SKILLS.items()}

    def current_ai_config() -> AIConfig:
        config = AIConfig(
            endpoint=ai_endpoint.get(),
            model=ai_model.get(),
            api_key=ai_api_key.get(),
            mode=mode_codes.get(ai_mode.get(), ""),
            skill=skill_codes.get(ai_skill.get(), ""),
        )
        config.validate()
        return config

    def open_ai_settings() -> None:
        dialog = tk.Toplevel(root)
        dialog.title("可选AI深度核验设置")
        dialog.geometry("620x410")
        dialog.resizable(True, False)
        dialog.transient(root)
        dialog.grab_set()
        _apply_window_icon(dialog)
        body = ttk.Frame(dialog, padding=20)
        body.pack(fill="both", expand=True)

        ttk.Label(body, text="AI服务商").grid(row=0, column=0, sticky="w", pady=7)
        provider_box = ttk.Combobox(
            body,
            textvariable=ai_provider,
            values=tuple(AI_PROVIDER_PRESETS) + (AI_CUSTOM_PROVIDER,),
            state="readonly",
        )
        provider_box.grid(
            row=0, column=1, columnspan=3, sticky="ew", padx=(12, 0), pady=7
        )

        def apply_provider_preset(_event=None) -> None:
            preset = AI_PROVIDER_PRESETS.get(ai_provider.get())
            if preset:
                ai_endpoint.set(preset[0])
                ai_model.set(preset[1])

        provider_box.bind("<<ComboboxSelected>>", apply_provider_preset)
        ttk.Label(body, text="兼容接口地址").grid(row=1, column=0, sticky="w", pady=7)
        endpoint_entry = ttk.Entry(body, textvariable=ai_endpoint)
        endpoint_entry.grid(row=1, column=1, columnspan=3, sticky="ew", padx=(12, 0), pady=7)
        add_edit_menu(endpoint_entry)
        ttk.Label(body, text="模型名称").grid(row=2, column=0, sticky="w", pady=7)
        model_entry = ttk.Entry(body, textvariable=ai_model)
        model_entry.grid(row=2, column=1, columnspan=3, sticky="ew", padx=(12, 0), pady=7)
        add_edit_menu(model_entry)
        ttk.Label(body, text="API Key").grid(row=3, column=0, sticky="w", pady=7)
        key_entry = ttk.Entry(body, textvariable=ai_api_key, show="•")
        key_entry.grid(row=3, column=1, columnspan=3, sticky="ew", padx=(12, 0), pady=7)
        add_edit_menu(key_entry)
        ttk.Label(body, text="核验模式").grid(row=4, column=0, sticky="w", pady=7)
        ttk.Combobox(
            body,
            textvariable=ai_mode,
            values=("快速", "严格"),
            state="readonly",
            width=12,
        ).grid(row=4, column=1, sticky="w", padx=(12, 18), pady=7)
        ttk.Label(body, text="核验技能").grid(row=4, column=2, sticky="w", pady=7)
        ttk.Combobox(
            body,
            textvariable=ai_skill,
            values=tuple(skill_codes),
            state="readonly",
            width=14,
        ).grid(row=4, column=3, sticky="w", padx=(12, 0), pady=7)
        ttk.Label(
            body,
            text=(
                "快速模式只让AI复核规则无法直接确认的项目；严格模式复核所有有正文证据的项目。\n"
                "选择服务商会填入推荐地址和模型，二者仍可修改。密钥仅保存在本次运行内存中。\n"
                "启用后只发送论述、参考文献条目和候选原文片段。"
            ),
            foreground="#656d76",
            wraplength=560,
        ).grid(row=5, column=0, columnspan=4, sticky="w", pady=(16, 10))

        def save_settings() -> None:
            try:
                current_ai_config()
            except ValueError as error:
                messagebox.showerror("AI设置无效", str(error), parent=dialog)
                return
            ai_enabled.set(True)
            dialog.destroy()

        ttk.Button(
            body,
            text="保存本次设置并启用",
            command=save_settings,
            style="Accent.TButton",
        ).grid(row=6, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        body.columnconfigure(1, weight=1)
        body.columnconfigure(3, weight=1)

    ttk.Checkbutton(
        manuscript_tab,
        text="自动获取可合法访问的开放原文",
        variable=auto_fetch_fulltext,
    ).grid(row=2, column=0, columnspan=5, sticky="w", pady=(10, 0))

    ttk.Checkbutton(
        manuscript_tab,
        text="启用可选AI深度核验（使用者自行提供API Key）",
        variable=ai_enabled,
    ).grid(row=3, column=0, columnspan=3, sticky="w", pady=(8, 0))
    ttk.Button(
        manuscript_tab, text="AI设置", command=open_ai_settings
    ).grid(row=3, column=3, columnspan=2, sticky="e", pady=(10, 0))

    manuscript_button = ttk.Button(
        manuscript_tab, text="开始论文内容核查", style="Accent.TButton"
    )
    manuscript_button.grid(
        row=4, column=0, columnspan=5, sticky="ew", pady=(18, 12)
    )
    last_manuscript_report: Path | None = None

    def finish_manuscript_error(message: str) -> None:
        manuscript_button.state(["!disabled"])
        manuscript_status.set(
            f"{round(manuscript_progress.get())}% · 论文内容核查失败"
        )
        messagebox.showerror("论文内容核查失败", message)

    def finish_manuscript_check(output: Path, audits: list[CitationAudit]) -> None:
        nonlocal last_manuscript_report
        manuscript_button.state(["!disabled"])
        last_manuscript_report = output.resolve()
        manuscript_report_button.state(["!disabled"])
        direct = sum(audit.verdict == "DIRECT_SUPPORT" for audit in audits)
        unavailable = sum(
            audit.verdict in {"SOURCE_UNAVAILABLE", "MISSING_REFERENCE"}
            for audit in audits
        )
        review = len(audits) - direct - unavailable
        manuscript_progress.set(100)
        manuscript_status.set(
            f"100% · 完成：{len(audits)}处引用，{direct}处直接支持，"
            f"{review}处需复核，{unavailable}处缺少条目或正文。"
        )
        ai_reviewed = sum(
            audit.ai_verdict
            and not audit.ai_verdict.startswith("NOT_RUN")
            and audit.ai_verdict != "ERROR"
            for audit in audits
        )
        ai_errors = sum(audit.ai_verdict == "ERROR" for audit in audits)
        if any(audit.ai_verdict for audit in audits):
            manuscript_status.set(
                f"{manuscript_status.get()} AI复核{ai_reviewed}处，失败{ai_errors}处。"
            )
        if not open_local_report(output):
            messagebox.showwarning(
                "核查报告已生成",
                "系统未能自动打开浏览器。请点击“打开核查报告”，"
                f"或手动打开：\n{output.resolve()}",
            )

    def open_last_manuscript_report() -> None:
        if last_manuscript_report is None or not last_manuscript_report.is_file():
            messagebox.showinfo("暂无报告", "请先完成一次论文内容核查。")
            return
        if not open_local_report(last_manuscript_report):
            messagebox.showwarning(
                "无法打开报告",
                f"请手动打开：\n{last_manuscript_report}",
            )

    def run_manuscript_check() -> None:
        manuscript_path = Path(manuscript_value.get().strip().strip('"'))
        reference_inputs = [
            Path(value.strip().strip('"'))
            for value in manuscript_sources_value.get().split(";")
            if value.strip()
        ]
        if not manuscript_path.is_file():
            messagebox.showerror("无法开始", "请选择有效的论文稿件。")
            return
        try:
            ai_config = current_ai_config() if ai_enabled.get() else None
        except ValueError as error:
            messagebox.showerror("AI设置无效", str(error))
            return
        fetch_fulltext = auto_fetch_fulltext.get()
        manuscript_button.state(["disabled"])
        set_progress(
            manuscript_progress,
            manuscript_status,
            0,
            "准备进行论文内容核查",
        )

        def worker() -> None:
            try:
                output, audits = manuscript_to_html(
                    manuscript_path,
                    reference_inputs,
                    ai_config,
                    fetch_fulltext,
                    progress=lambda value, message: queue_progress(
                        manuscript_progress, manuscript_status, value, message
                    ),
                )
            except (OSError, ValueError) as error:
                root.after(
                    0, lambda message=str(error): finish_manuscript_error(message)
                )
                return
            root.after(0, lambda: finish_manuscript_check(output, audits))

        threading.Thread(target=worker, daemon=True).start()

    manuscript_button.configure(command=run_manuscript_check)
    ttk.Progressbar(
        manuscript_tab,
        variable=manuscript_progress,
        maximum=100,
        mode="determinate",
    ).grid(row=5, column=0, columnspan=5, sticky="ew")
    ttk.Label(
        manuscript_tab,
        textvariable=manuscript_status,
        foreground="#4338ca",
        wraplength=570,
        justify="left",
    ).grid(row=6, column=0, columnspan=4, sticky="w", pady=(6, 0))
    manuscript_report_button = ttk.Button(
        manuscript_tab,
        text="打开核查报告",
        command=open_last_manuscript_report,
        state="disabled",
    )
    manuscript_report_button.grid(row=6, column=4, sticky="e", pady=(6, 0))
    manuscript_tab.columnconfigure(1, weight=1)

    support = ttk.Frame(outer)
    support.pack(fill="x", pady=(8, 0))
    ttk.Label(
        support,
        text="StudyLint",
        foreground="#656d76",
        font=("Segoe UI", 9),
    ).pack(side="left")
    star_link = ttk.Label(
        support,
        text="  ·  ⭐ Star",
        foreground="#4338ca",
        cursor="hand2",
        font=("Segoe UI", 9, "underline"),
    )
    star_link.pack(side="left")
    star_link.bind("<Button-1>", lambda _event: webbrowser.open(PROJECT_URL))
    author_link = ttk.Label(
        support,
        text="  ·  作者",
        foreground="#4338ca",
        cursor="hand2",
        font=("Segoe UI", 9, "underline"),
    )
    author_link.pack(side="left")
    author_link.bind("<Button-1>", lambda _event: webbrowser.open(AUTHOR_URL))

    root.mainloop()


if __name__ == "__main__":
    main()
