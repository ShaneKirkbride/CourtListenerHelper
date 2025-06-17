import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk
from typing import List, Optional

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

JURISDICTIONS = [
    ("All", None),
    ("CO Court of Appeals (coloctapp)", "coloctapp"),
    ("CO Supreme Court (colo)", "colo"),
    ("CO District Court (cod)", "cod"),
    ("10th Circ. (circtdco)", "circtdco"),
]

class GuiApplication:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("CourtListener Helper")
        self.client = ApiClient(API_BASE, TOKEN or "")
        self.searcher = CaseSearcher(self.client)
        self.downloader = CaseDownloader(self.client)

        tk.Label(root, text="Keywords (comma separated):").pack(anchor="w", padx=5)
        self.keyword_entry = tk.Entry(root, width=50)
        self.keyword_entry.pack(fill="x", padx=5)

        tk.Label(root, text="Start Date (YYYY-MM-DD):").pack(anchor="w", padx=5, pady=(5, 0))
        self.start_date_var = tk.StringVar()
        self.start_date_entry = tk.Entry(root, textvariable=self.start_date_var)
        self.start_date_entry.pack(fill="x", padx=5)

        tk.Label(root, text="End Date (YYYY-MM-DD):").pack(anchor="w", padx=5, pady=(5, 0))
        self.end_date_var = tk.StringVar()
        self.end_date_entry = tk.Entry(root, textvariable=self.end_date_var)
        self.end_date_entry.pack(fill="x", padx=5)

        tk.Label(root, text="Jurisdiction:").pack(anchor="w", padx=5, pady=(5, 0))
        self.jur_var = tk.StringVar(value=JURISDICTIONS[0][0])
        options = [name for name, _ in JURISDICTIONS]
        self.jur_menu = ttk.OptionMenu(root, self.jur_var, options[0], *options)
        self.jur_menu.pack(fill="x", padx=5)

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
        directory = filedialog.askdirectory()
        if directory:
            self.out_entry.delete(0, tk.END)
            self.out_entry.insert(0, directory)

    def start(self) -> None:
        keywords = [k.strip() for k in self.keyword_entry.get().split(",") if k.strip()]
        out_dir = self.out_entry.get() or "cases"
        if not keywords:
            messagebox.showerror("Error", "Please enter at least one keyword.")
            return

        jur_name = self.jur_var.get()
        jurisdiction = next(code for name, code in JURISDICTIONS if name == jur_name)

        start_date = self.start_date_var.get().strip() or None
        end_date = self.end_date_var.get().strip() or None

        os.makedirs(out_dir, exist_ok=True)
        self.start_button.config(state="disabled")
        self.progress.config(value=0)
        threading.Thread(
            target=self.download_cases,
            args=(keywords, out_dir, jurisdiction, start_date, end_date),
            daemon=True,
        ).start()

    def log_message(self, msg: str) -> None:
        self.log.configure(state="normal")
        self.log.insert(tk.END, msg + "\n")
        self.log.configure(state="disabled")
        self.log.see(tk.END)

    def download_cases(
        self,
        keywords: List[str],
        out_dir: str,
        jurisdiction: Optional[str] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> None:
        total = 0
        for kw in keywords:
            self.log_message(
                f"Searching cases for '{kw}'" + (f" in {jurisdiction}" if jurisdiction else "") + " …"
            )
            for case_meta in self.searcher.search(
                kw,
                jurisdictions=jurisdiction,
                start_date=start_date,
                end_date=end_date,
            ):
                total += 1
                case_id = get_case_id(case_meta)
                name = case_meta.get("name", f"case_{case_id}")
                self.log_message(f"Processing '{name}' (ID: {case_id}) …")
            
                safe = sanitize_filename(name)
            
                # Save raw metadata JSON no matter what:
                json_path = os.path.join(out_dir, f"{safe}_{case_id}.json")
                try:
                    with open(json_path, "w", encoding="utf-8") as f:
                        import json
                        json.dump(case_meta, f, indent=2)
                except Exception as e:
                    self.log_message(f"❌ Failed writing JSON for {case_id}: {e}")
                    continue  # skip this case
            
                # Try to fetch full case details if URL exists
                case_url = get_case_url(case_meta)
                if not case_url:
                    self.log_message(f"⚠️ No detailed URL for case {case_id}; saved metadata only")
                    self.progress.step(1)
                    continue
            
                try:
                    res = self.downloader.download(case_url)
                except Exception as e:
                    self.log_message(f"❌ Error downloading case URL for {case_id}: {e}")
                    self.progress.step(1)
                    continue
            
                # Overwrite metadata with full response metadata
                full_meta = res.get("metadata", {})
                try:
                    with open(json_path, "w", encoding="utf-8") as f:
                        json.dump(full_meta, f, indent=2)
                except Exception as e:
                    self.log_message(f"❌ Failed overwriting JSON with full meta {case_id}: {e}")

                # Optional: save opinions
                opinions = res.get("opinions", [])
                if opinions:
                    ops_path = os.path.join(out_dir, f"{safe}_{case_id}_opinions.json")
                    try:
                        with open(ops_path, "w", encoding="utf-8") as fo:
                            json.dump(opinions, fo, indent=2)
                    except Exception as e:
                        self.log_message(f"⚠️ Failed saving opinions for {case_id}: {e}")
            
                # Save PDF if any
                pdf_bytes = res.get("pdf_bytes")
                if pdf_bytes:
                    try:
                        pdf_path = os.path.join(out_dir, f"{safe}_{case_id}.pdf")
                        if not os.path.exists(pdf_path):
                            with open(pdf_path, "wb") as pf:
                                pf.write(pdf_bytes)
                            self.log_message(f"✅ PDF saved: {pdf_path}")
                        else:
                            self.log_message("→ PDF already exists, skipping")
                    except Exception as e:
                        self.log_message(f"⚠️ Failed saving PDF for {case_id}: {e}")
                else:
                    self.log_message("→ No PDF available for this case")

                self.progress.step(1)

        metrics = self.client.get_metrics()
        self.log_message(f"🏁 Completed. Total cases processed: {total}")
        self.log_message(f"API calls: {metrics['call_count']} | Bytes downloaded: {metrics['total_bytes']} | Time: {metrics['total_time']:.2f}s")
        self.start_button.config(state="normal")

def run() -> None:
    root = tk.Tk()
    GuiApplication(root)
    root.mainloop()

if __name__ == "__main__":
    run()
