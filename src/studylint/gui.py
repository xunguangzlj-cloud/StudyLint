from __future__ import annotations

import webbrowser
from pathlib import Path

from studylint.parsers import discover_sources, load_source, parse_notes
from studylint.reporters import render_html, summary
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


def main() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    root = tk.Tk()
    root.title("StudyLint")
    root.geometry("700x360")
    root.minsize(620, 330)

    notes_value = tk.StringVar()
    sources_value = tk.StringVar()
    status_value = tk.StringVar(value="选择笔记和课程资料文件夹，然后开始检查。")

    frame = ttk.Frame(root, padding=28)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="StudyLint", font=("Segoe UI", 24, "bold")).grid(
        row=0, column=0, columnspan=3, sticky="w", pady=(0, 4)
    )
    ttk.Label(frame, text="让每条学习笔记都能追溯来源").grid(
        row=1, column=0, columnspan=3, sticky="w", pady=(0, 24)
    )

    ttk.Label(frame, text="笔记文件").grid(row=2, column=0, sticky="w", pady=8)
    ttk.Entry(frame, textvariable=notes_value).grid(
        row=2, column=1, sticky="ew", padx=10, pady=8
    )

    def choose_notes() -> None:
        selected = filedialog.askopenfilename(
            title="选择笔记",
            filetypes=[
                ("支持的笔记", "*.md *.txt *.docx"),
                ("全部文件", "*.*"),
            ],
        )
        if selected:
            notes_value.set(selected)

    ttk.Button(frame, text="选择", command=choose_notes).grid(row=2, column=2)

    ttk.Label(frame, text="资料文件夹").grid(row=3, column=0, sticky="w", pady=8)
    ttk.Entry(frame, textvariable=sources_value).grid(
        row=3, column=1, sticky="ew", padx=10, pady=8
    )

    def choose_sources() -> None:
        selected = filedialog.askdirectory(title="选择课程资料文件夹")
        if selected:
            sources_value.set(selected)

    ttk.Button(frame, text="选择", command=choose_sources).grid(row=3, column=2)

    def run_check() -> None:
        notes_path = Path(notes_value.get())
        source_directory = Path(sources_value.get())
        if not notes_path.is_file() or not source_directory.is_dir():
            messagebox.showerror("无法开始", "请选择有效的笔记文件和资料文件夹。")
            return
        status_value.set("正在检查，请稍候……")
        root.update_idletasks()
        try:
            output, counts = check_to_html(notes_path, source_directory)
        except (OSError, ValueError) as error:
            status_value.set("检查失败。")
            messagebox.showerror("检查失败", str(error))
            return
        status_value.set(
            f"完成：{counts['errors']}个错误，{counts['warnings']}个警告。"
        )
        webbrowser.open(output.resolve().as_uri())

    ttk.Button(frame, text="开始检查并打开报告", command=run_check).grid(
        row=4, column=0, columnspan=3, sticky="ew", pady=(26, 14)
    )
    ttk.Label(frame, textvariable=status_value, foreground="#4338ca").grid(
        row=5, column=0, columnspan=3, sticky="w"
    )
    ttk.Label(
        frame,
        text="所有文件仅在本机处理。证据候选需要人工确认。",
        foreground="#656d76",
    ).grid(row=6, column=0, columnspan=3, sticky="w", pady=(24, 0))

    frame.columnconfigure(1, weight=1)
    root.mainloop()


if __name__ == "__main__":
    main()
