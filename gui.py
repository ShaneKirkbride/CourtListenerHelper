import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import List

from CourtListenerHelper import (
    ApiClient,
    CaseSearcher,
    CaseDownloader,
    sanitize_filename,
    get_case_id,
    get_case_url,
    API_BASE,
    TOKEN,
)


class GuiApplication:
    """Simple Tkinter GUI for CourtListenerHelper."""

    def __init__(self, root: tk.Tk) -> None:
        """Initialise widgets and API helpers."""
        self.root = root
        self.root.title("CourtListener Helper")
        self.client = ApiClient(API_BASE, TOKEN or "")
        self.searcher = CaseSearcher(self.client)
        self.downloader = CaseDownloader(self.client)

        tk.Label(root, text="Keywords (comma separated):").pack(anchor="w", padx=5)
        self.keyword_entry = tk.Entry(root, width=50)
        self.keyword_entry.pack(fill="x", padx=5)

        tk.Label(root, text="Output Directory:").pack(anchor="w", padx=5, pady=(5, 0))
        out_frame = tk.Frame(root)
        out_frame.pack(fill="x", padx=5)
        self.out_entry = tk.Entry(out_frame)
        self.out_entry.pack(side="left", fill="x", expand=True)
        tk.Button(out_frame, text="Browse", command=self.browse).pack(side="left", padx=5)

        self.start_button = tk.Button(root, text="Start", command=self.start)
        self.start_button.pack(pady=5)

        self.progress = ttk.Progressbar(root, mode="determinate")
        self.progress.pack(fill="x", padx=5)

        self.log = scrolledtext.ScrolledText(root, height=10, state="disabled")
        self.log.pack(fill="both", expand=True, padx=5, pady=5)

    def browse(self) -> None:
        """Ask the user for an output directory."""
        directory = filedialog.askdirectory()
        if directory:
            self.out_entry.delete(0, tk.END)
            self.out_entry.insert(0, directory)

    def start(self) -> None:
        """Kick off the download in a background thread."""
        keywords = [k.strip() for k in self.keyword_entry.get().split(",") if k.strip()]
        out_dir = self.out_entry.get() or "cases"
        if not keywords:
            messagebox.showerror("Error", "Please enter at least one keyword.")
            return
        os.makedirs(out_dir, exist_ok=True)
        self.start_button.config(state="disabled")
        self.progress.config(value=0)
        threading.Thread(target=self.download_cases, args=(keywords, out_dir), daemon=True).start()

    def log_message(self, msg: str) -> None:
        """Append a message to the log textbox."""
        self.log.configure(state="normal")
        self.log.insert(tk.END, msg + "\n")
        self.log.configure(state="disabled")
        self.log.see(tk.END)

    def download_cases(self, keywords: List[str], out_dir: str) -> None:
        """Perform the actual search and download operations."""
        total = 0
        for kw in keywords:
            self.log_message(f"Searching cases for '{kw}' ...")
            for case_meta in self.searcher.search(kw):
                total += 1
                case_id = get_case_id(case_meta)
                name = case_meta.get("name", f"case_{case_id}")
                self.log_message(f"Downloading '{name}' ...")
                data = self.downloader.download(get_case_url(case_meta))
                safe = sanitize_filename(name)
                path = os.path.join(out_dir, f"{safe}_{case_id}.json")
                with open(path, "w", encoding="utf-8") as f:
                    import json
                    json.dump(data, f, indent=2)
                pdf_url = data.get("download_url")
                if pdf_url:
                    pdf_path = os.path.join(out_dir, f"{safe}_{case_id}.pdf")
                    if not os.path.exists(pdf_path):
                        pdf_bytes = self.downloader.download_pdf(pdf_url)
                        with open(pdf_path, "wb") as pf:
                            pf.write(pdf_bytes)
                self.progress.step(1)
        metrics = self.client.get_metrics()
        self.log_message(f"Completed. Total cases: {total}")
        self.log_message(f"API calls: {metrics['call_count']}")
        self.log_message(f"Bytes downloaded: {metrics['total_bytes']}")
        self.log_message(f"Elapsed time: {metrics['total_time']:.2f}s")
        self.start_button.config(state="normal")


def run() -> None:
    """Entry point for launching the GUI application."""
    root = tk.Tk()
    GuiApplication(root)
    root.mainloop()


if __name__ == "__main__":
    run()
