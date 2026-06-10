from __future__ import annotations

import queue
import sys
import threading
from pathlib import Path

from .pipeline import PipelineResult, PipelineSettings, run_pipeline

tk = None
ttk = None
filedialog = None
messagebox = None


def app_base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def default_settings_for_base_dir(base_dir: Path | None = None) -> PipelineSettings:
    base_path = Path(base_dir) if base_dir is not None else app_base_dir()
    data_dir = base_path / "data"
    return PipelineSettings(
        env_file=base_path / ".env",
        atera_output=data_dir / "atera_agents.csv",
        bd_output=data_dir / "bd_endpoint_status.csv",
        report_output=data_dir / "mismatch.csv",
        duplicates_output=data_dir / "duplicates.csv",
        company_aliases=data_dir / "company_aliases.csv",
        device_aliases=data_dir / "device_aliases.csv",
    )


def load_tkinter() -> None:
    global filedialog, messagebox, tk, ttk
    import tkinter as tk_module
    from tkinter import filedialog as filedialog_module
    from tkinter import messagebox as messagebox_module
    from tkinter import ttk as ttk_module

    tk = tk_module
    ttk = ttk_module
    filedialog = filedialog_module
    messagebox = messagebox_module


def show_native_error(title: str, message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(None, message, title, 0x10)
    except Exception:
        print(f"{title}: {message}", file=sys.stderr)


class AutoCompareApp:
    def __init__(self, root, base_dir: Path | None = None) -> None:
        self.root = root
        self.base_dir = Path(base_dir) if base_dir is not None else app_base_dir()
        defaults = default_settings_for_base_dir(self.base_dir)
        self.messages: queue.Queue[tuple[str, str]] = queue.Queue()
        self.worker: threading.Thread | None = None

        self.env_file = tk.StringVar(value=str(defaults.env_file))
        self.output_dir = tk.StringVar(value=str(defaults.atera_output.parent))
        self.atera_page_size = tk.StringVar(value=str(defaults.atera_page_size))
        self.bd_page_size = tk.StringVar(value=str(defaults.bd_page_size))
        self.include_unprotected = tk.BooleanVar(value=defaults.bd_include_unprotected)
        self.status = tk.StringVar(value="Ready")

        self.root.title("BD / Atera AutoCompare")
        self.root.minsize(760, 520)
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        self.build_form()
        self.build_log()
        self.root.after(100, self.drain_messages)

    def build_form(self) -> None:
        frame = ttk.Frame(self.root, padding=16)
        frame.grid(row=0, column=0, sticky="ew")
        frame.columnconfigure(1, weight=1)

        ttk.Label(frame, text=".env").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frame, textvariable=self.env_file).grid(row=0, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Browse", command=self.choose_env_file).grid(row=0, column=2, padx=(8, 0), pady=4)

        ttk.Label(frame, text="Output").grid(row=1, column=0, sticky="w", padx=(0, 8), pady=4)
        ttk.Entry(frame, textvariable=self.output_dir).grid(row=1, column=1, sticky="ew", pady=4)
        ttk.Button(frame, text="Browse", command=self.choose_output_dir).grid(row=1, column=2, padx=(8, 0), pady=4)

        options = ttk.Frame(frame)
        options.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        options.columnconfigure(4, weight=1)

        ttk.Label(options, text="Atera page").grid(row=0, column=0, sticky="w")
        ttk.Spinbox(options, from_=1, to=500, textvariable=self.atera_page_size, width=8).grid(
            row=0,
            column=1,
            sticky="w",
            padx=(8, 18),
        )
        ttk.Label(options, text="BD page").grid(row=0, column=2, sticky="w")
        ttk.Spinbox(options, from_=1, to=500, textvariable=self.bd_page_size, width=8).grid(
            row=0,
            column=3,
            sticky="w",
            padx=(8, 18),
        )
        ttk.Checkbutton(
            options,
            text="Include unprotected BD endpoints",
            variable=self.include_unprotected,
        ).grid(row=0, column=4, sticky="w")

        actions = ttk.Frame(frame)
        actions.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(14, 0))
        actions.columnconfigure(1, weight=1)
        self.run_button = ttk.Button(actions, text="Run", command=self.start_run)
        self.run_button.grid(row=0, column=0, sticky="w")
        ttk.Label(actions, textvariable=self.status).grid(row=0, column=1, sticky="w", padx=(12, 0))

    def build_log(self) -> None:
        frame = ttk.Frame(self.root, padding=(16, 0, 16, 16))
        frame.grid(row=1, column=0, sticky="nsew")
        frame.columnconfigure(0, weight=1)
        frame.rowconfigure(0, weight=1)

        self.log = tk.Text(frame, height=18, wrap="word", state="disabled")
        self.log.grid(row=0, column=0, sticky="nsew")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.log.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log.configure(yscrollcommand=scrollbar.set)

    def choose_env_file(self) -> None:
        selected = filedialog.askopenfilename(
            title="Select .env",
            initialdir=str(Path(self.env_file.get()).parent),
            filetypes=[("Environment files", "*.env"), ("All files", "*.*")],
        )
        if selected:
            self.env_file.set(selected)

    def choose_output_dir(self) -> None:
        selected = filedialog.askdirectory(title="Select output folder", initialdir=self.output_dir.get())
        if selected:
            self.output_dir.set(selected)

    def build_settings(self) -> PipelineSettings:
        output_path = Path(self.output_dir.get())
        return PipelineSettings(
            env_file=Path(self.env_file.get()),
            atera_output=output_path / "atera_agents.csv",
            atera_page_size=int(self.atera_page_size.get()),
            bd_output=output_path / "bd_endpoint_status.csv",
            bd_page_size=int(self.bd_page_size.get()),
            bd_include_unprotected=self.include_unprotected.get(),
            report_output=output_path / "mismatch.csv",
            duplicates_output=output_path / "duplicates.csv",
            company_aliases=output_path / "company_aliases.csv",
            device_aliases=output_path / "device_aliases.csv",
        )

    def start_run(self) -> None:
        if self.worker and self.worker.is_alive():
            return

        try:
            settings = self.build_settings()
        except ValueError as exc:
            messagebox.showerror("Invalid settings", str(exc))
            return

        self.log_message("Starting comparison...")
        self.status.set("Running")
        self.run_button.state(["disabled"])
        self.worker = threading.Thread(target=self.run_worker, args=(settings,), daemon=True)
        self.worker.start()

    def run_worker(self, settings: PipelineSettings) -> None:
        try:
            result = run_pipeline(settings, status=lambda message: self.messages.put(("log", message)))
        except Exception as exc:
            self.messages.put(("error", str(exc)))
            return
        self.messages.put(("done", self.result_summary(result)))

    def result_summary(self, result: PipelineResult) -> str:
        return (
            f"Done. Atera rows: {result.atera_rows}; "
            f"BD rows: {result.bd_rows}; mismatches: {result.mismatch_rows}. "
            f"Report: {result.report_output}"
        )

    def drain_messages(self) -> None:
        while True:
            try:
                kind, message = self.messages.get_nowait()
            except queue.Empty:
                break

            if kind == "log":
                self.log_message(message)
            elif kind == "done":
                self.log_message(message)
                self.status.set("Done")
                self.run_button.state(["!disabled"])
                messagebox.showinfo("BD / Atera AutoCompare", message)
            elif kind == "error":
                self.log_message(f"ERROR: {message}")
                self.status.set("Error")
                self.run_button.state(["!disabled"])
                messagebox.showerror("BD / Atera AutoCompare", message)

        self.root.after(100, self.drain_messages)

    def log_message(self, message: str) -> None:
        self.log.configure(state="normal")
        self.log.insert("end", message + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")


def main() -> int:
    try:
        load_tkinter()
        root = tk.Tk()
    except Exception as exc:
        show_native_error(
            "BD / Atera AutoCompare",
            (
                "Tkinter is not available in this Python installation. "
                "Install or build with a full Python distribution that includes Tcl/Tk.\n\n"
                f"{exc}"
            ),
        )
        return 1

    AutoCompareApp(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
