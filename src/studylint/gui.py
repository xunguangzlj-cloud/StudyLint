from __future__ import annotations

import ctypes
import sys
import threading
import webbrowser
from pathlib import Path

from studylint.parsers import discover_sources, load_source, parse_notes
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
    render_paper_batch_html,
    render_paper_html,
    summary,
)
from studylint.rules import lint


def check_to_html(notes_path: Path, source_directory: Path) -> tuple[Path, dict[str, int]]:
    source_paths = discover_sources(source_directory, exclude=notes_path)
    if not source_paths:
        raise ValueError("资料文件夹中没有可支持的课程材料。")
    units = parse_notes(notes_path)
    sources = [load_source(path) for path in source_paths]
    findings = lint(units, sources)
    output = notes_path.with_name(f"{notes_path.stem}-studylint-report.html")
    output.write_text(render_html(notes_path, findings), encoding="utf-8")
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
) -> tuple[Path, list[PaperVerification]]:
    verifications = lookup(queries)
    output = output_directory / "studylint-paper-report.html"
    output.write_text(render_paper_batch_html(verifications), encoding="utf-8")
    return output, verifications


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


def main() -> None:
    enable_high_dpi()

    import tkinter as tk
    from tkinter import filedialog, font as tkfont, messagebox, scrolledtext, ttk

    root = tk.Tk()
    root.title("StudyLint")
    root.geometry("780x600")
    root.minsize(700, 540)

    for font_name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
        tkfont.nametofont(font_name).configure(family="Microsoft YaHei UI", size=10)

    style = ttk.Style(root)
    style.configure("Accent.TButton", font=("Microsoft YaHei UI", 10, "bold"))

    notes_value = tk.StringVar()
    sources_value = tk.StringVar()
    notes_status = tk.StringVar(value="选择笔记和课程资料文件夹，然后开始检查。")
    paper_status = tk.StringVar(value="每行输入一篇论文，可一次核验多篇。")

    outer = ttk.Frame(root, padding=(28, 22))
    outer.pack(fill="both", expand=True)
    ttk.Label(outer, text="StudyLint", font=("Segoe UI", 25, "bold")).pack(anchor="w")
    ttk.Label(outer, text="核对学习笔记，也核实可疑论文").pack(anchor="w", pady=(0, 18))

    notebook = ttk.Notebook(outer)
    notebook.pack(fill="both", expand=True)
    notes_tab = ttk.Frame(notebook, padding=24)
    papers_tab = ttk.Frame(notebook, padding=24)
    notebook.add(notes_tab, text="  笔记检查  ")
    notebook.add(papers_tab, text="  论文核验  ")

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

    ttk.Label(notes_tab, text="笔记文件").grid(row=0, column=0, sticky="w", pady=9)
    notes_entry = ttk.Entry(notes_tab, textvariable=notes_value)
    notes_entry.grid(row=0, column=1, sticky="ew", padx=12, pady=9)
    add_edit_menu(notes_entry)

    def choose_notes() -> None:
        selected = filedialog.askopenfilename(
            title="选择笔记",
            filetypes=[("支持的笔记", "*.md *.txt *.docx"), ("全部文件", "*.*")],
        )
        if selected:
            notes_value.set(selected)

    ttk.Button(notes_tab, text="选择", command=choose_notes).grid(row=0, column=2)
    ttk.Label(notes_tab, text="资料文件夹").grid(row=1, column=0, sticky="w", pady=9)
    sources_entry = ttk.Entry(notes_tab, textvariable=sources_value)
    sources_entry.grid(row=1, column=1, sticky="ew", padx=12, pady=9)
    add_edit_menu(sources_entry)

    def choose_sources() -> None:
        selected = filedialog.askdirectory(title="选择课程资料文件夹")
        if selected:
            sources_value.set(selected)

    ttk.Button(notes_tab, text="选择", command=choose_sources).grid(row=1, column=2)

    def run_check() -> None:
        notes_path = Path(notes_value.get())
        source_directory = Path(sources_value.get())
        if not notes_path.is_file() or not source_directory.is_dir():
            messagebox.showerror("无法开始", "请选择有效的笔记文件和资料文件夹。")
            return
        notes_status.set("正在检查，请稍候……")
        root.update_idletasks()
        try:
            output, counts = check_to_html(notes_path, source_directory)
        except (OSError, ValueError) as error:
            notes_status.set("检查失败。")
            messagebox.showerror("检查失败", str(error))
            return
        notes_status.set(f"完成：{counts['errors']}个错误，{counts['warnings']}个警告。")
        webbrowser.open(output.resolve().as_uri())

    ttk.Button(
        notes_tab,
        text="开始检查并打开报告",
        command=run_check,
        style="Accent.TButton",
    ).grid(row=2, column=0, columnspan=3, sticky="ew", pady=(24, 14))
    ttk.Label(notes_tab, textvariable=notes_status, foreground="#4338ca").grid(
        row=3, column=0, columnspan=3, sticky="w"
    )
    ttk.Label(
        notes_tab,
        text="课程材料仅在本机读取；证据候选仍需人工确认。",
        foreground="#656d76",
    ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(26, 0))
    notes_tab.columnconfigure(1, weight=1)

    ttk.Label(
        papers_tab,
        text="粘贴DOI、论文标题或完整参考文献，每行一篇：",
    ).grid(row=0, column=0, columnspan=3, sticky="w", pady=(0, 10))
    paper_input = scrolledtext.ScrolledText(
        papers_tab,
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

    ttk.Button(papers_tab, text="导入清单", command=import_papers).grid(
        row=2, column=0, sticky="w", pady=(14, 0)
    )
    ttk.Button(
        papers_tab,
        text="清空",
        command=lambda: paper_input.delete("1.0", "end"),
    ).grid(row=2, column=1, sticky="w", pady=(14, 0), padx=10)

    verify_button = ttk.Button(papers_tab, text="开始批量核验", style="Accent.TButton")
    verify_button.grid(row=2, column=2, sticky="e", pady=(14, 0))

    def finish_paper_error(message: str) -> None:
        verify_button.state(["!disabled"])
        paper_status.set("论文核验失败。")
        messagebox.showerror("论文核验失败", message)

    def finish_paper_check(output: Path, verifications: list[PaperVerification]) -> None:
        verify_button.state(["!disabled"])
        matched = sum(bool(item.matches) for item in verifications)
        paper_status.set(f"完成：{len(verifications)}篇中有{matched}篇找到可靠候选。")
        webbrowser.open(output.resolve().as_uri())

    def run_paper_check() -> None:
        queries = parse_queries(paper_input.get("1.0", "end"))
        if not queries:
            messagebox.showerror("无法核实", "请至少输入一篇论文。")
            return
        verify_button.state(["disabled"])
        paper_status.set(f"正在查询Crossref与OpenAlex，共{len(queries)}篇……")
        notes_path = Path(notes_value.get())
        output_directory = notes_path.parent if notes_path.is_file() else Path.cwd()

        def worker() -> None:
            try:
                output, verifications = papers_to_html(queries, output_directory)
            except (OSError, PaperLookupError, ValueError) as error:
                root.after(0, lambda message=str(error): finish_paper_error(message))
                return
            root.after(0, lambda: finish_paper_check(output, verifications))

        threading.Thread(target=worker, daemon=True).start()

    verify_button.configure(command=run_paper_check)
    ttk.Label(papers_tab, textvariable=paper_status, foreground="#4338ca").grid(
        row=3, column=0, columnspan=3, sticky="w", pady=(16, 0)
    )
    ttk.Label(
        papers_tab,
        text="自动查询开放数据库；未匹配时报告会提供知网等人工检索入口。查询文字会发送到相应服务。",
        foreground="#656d76",
        wraplength=660,
    ).grid(row=4, column=0, columnspan=3, sticky="w", pady=(20, 0))
    papers_tab.columnconfigure(1, weight=1)
    papers_tab.rowconfigure(1, weight=1)

    root.mainloop()


if __name__ == "__main__":
    main()
