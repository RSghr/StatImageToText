"""
505th Stat Department - control panel.

Double-click "Stats UI.bat" (or this file). Buttons:
  Drop zone         drag the Drive .zip (screenshots) and the form .xlsx/.csv onto the window, or click it:
                    images go to To_Process, the form next to this file (older forms -> Archive)
  Run report        reads To_Process + the Google Drive folder, adds the results to the history, builds
                    the spreadsheets, report, player lookup page, Discord post and website copy
  Corrections       opens corrections.csv (values to check)
  Open folder       opens this folder
  Website           publish online (Cloudflare Pages) / open the public page /
                    copy index.html contents / copy the htmlReport folder to another place
  Discord           open / copy the Discord announcement
  Reset             archive (with timestamp), delete, or cancel
Only the Python standard library is used (tkinter ships with Python on Windows).
"""
from __future__ import annotations

import csv
import datetime
import os
import queue
import shutil
import subprocess
import sys
import re
import threading
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:  # optional: drag & drop onto the window (pip install tkinterdnd2 - setup.bat does it)
    from tkinterdnd2 import DND_FILES, TkinterDnD
    BaseTk = TkinterDnD.Tk
    HAS_DND = True
except Exception:  # noqa: BLE001 - any import problem just means "no drag & drop"
    BaseTk = tk.Tk
    HAS_DND = False

from ui_core import *  # noqa: F401,F403 - paths, settings, counts, import, reset
from ui_core import _count, _norm, current_form, do_reset  # noqa: F401
YELLOW = "#ffe14d"
INK = "#121211"


# --------------------------------------------------------------------------
# reset dialog: Archive / Delete / Cancel
# --------------------------------------------------------------------------
class ResetDialog(tk.Toplevel):
    def __init__(self, master):
        super().__init__(master)
        self.title("Reset - start a new batch")
        self.resizable(False, False)
        self.transient(master)
        self.result = None
        self.with_forms = tk.BooleanVar(value=False)
        self.with_history = tk.BooleanVar(value=False)
        self.with_players = tk.BooleanVar(value=False)

        frm = ttk.Frame(self, padding=16)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text="Clear the data to start a new batch", style="H.TLabel").pack(anchor="w")
        n_img = count_images()
        lines = [f"{n_img} screenshot(s) in To_Process",
                 "the output folder (spreadsheets, report, Discord post)",
                 "the website copy of the report (htmlReport\\index.html, players.html)"]
        ttk.Label(frm, text="This clears:\n  - " + "\n  - ".join(lines), justify="left").pack(anchor="w", pady=(8, 6))
        ttk.Label(frm, text=f"Kept: the history ({history_count()} deployments), players.csv (who is who), "
                            "corrections.csv\nand the Google Drive folder (never touched).",
                  style="Muted.TLabel", justify="left").pack(anchor="w", pady=(0, 6))
        forms = form_files()
        if forms:
            ttk.Checkbutton(frm, variable=self.with_forms,
                            text="Also clear the form file(s): " + ", ".join(p.name for p in forms)[:90]).pack(anchor="w")
        ttk.Checkbutton(frm, variable=self.with_history,
                        text="Also clear the history, corrections.csv and raids.csv (start again from zero)").pack(anchor="w")
        ttk.Checkbutton(frm, variable=self.with_players,
                        text="Also forget who is who (players.csv)").pack(anchor="w")
        ttk.Label(frm, text="The program, .venv, tests and website scripts are never touched.",
                  style="Muted.TLabel").pack(anchor="w", pady=(6, 12))

        btns = ttk.Frame(frm)
        btns.pack(fill="x")
        ttk.Button(btns, text="Archive (recommended)", style="Accent.TButton",
                   command=lambda: self.done("archive")).pack(side="left")
        ttk.Button(btns, text="Delete permanently", command=lambda: self.done("delete")).pack(side="left", padx=8)
        ttk.Button(btns, text="Cancel", command=lambda: self.done(None)).pack(side="right")
        ttk.Label(frm, text="Archive moves everything to Archive\\reset_<date time> - nothing is lost.",
                  style="Muted.TLabel").pack(anchor="w", pady=(10, 0))
        self.protocol("WM_DELETE_WINDOW", lambda: self.done(None))
        self.grab_set()
        self.update_idletasks()
        x = master.winfo_rootx() + (master.winfo_width() - self.winfo_width()) // 2
        y = master.winfo_rooty() + 60
        self.geometry(f"+{max(0, x)}+{max(0, y)}")

    def done(self, action):
        self.result = (action, self.with_forms.get(), self.with_history.get(), self.with_players.get())
        self.destroy()


# --------------------------------------------------------------------------
# main window
# --------------------------------------------------------------------------
class App(BaseTk):
    def __init__(self):
        super().__init__()
        self.title("505th Stat Department")
        self.geometry("880x640")
        self.minsize(720, 520)
        self.q: queue.Queue = queue.Queue()
        self.proc = None
        self.running = False
        self.importing = False
        self._style()
        self._build()
        self.refresh()
        self.after(100, self._drain)

    # ---- look -------------------------------------------------------------
    def _style(self):
        st = ttk.Style(self)
        try:
            st.theme_use("vista" if sys.platform.startswith("win") else "clam")
        except tk.TclError:
            st.theme_use("clam")
        st.configure("H.TLabel", font=("Segoe UI", 12, "bold"))
        st.configure("Muted.TLabel", foreground="#6b6a63")
        st.configure("Stat.TLabel", font=("Segoe UI", 10))
        st.configure("Big.TButton", font=("Segoe UI", 11, "bold"), padding=(14, 10))
        st.configure("Accent.TButton", font=("Segoe UI", 10, "bold"))
        st.configure("TButton", padding=(10, 6))

    def _build(self):
        head = tk.Frame(self, bg=YELLOW)
        head.pack(fill="x")
        tk.Label(head, text="505TH STAT DEPARTMENT", bg=YELLOW, fg=INK,
                 font=("Segoe UI", 16, "bold")).pack(side="left", padx=16, pady=10)
        tk.Label(head, text="screenshots -> report", bg=YELLOW, fg=INK,
                 font=("Segoe UI", 10)).pack(side="right", padx=16)

        body = ttk.Frame(self, padding=(16, 12))
        body.pack(fill="both", expand=True)

        # drop zone: Drive zip + form file
        hint = ("Drop the Drive .zip and the form .xlsx here  -  or click to choose files" if HAS_DND else
                "Click to add the Drive .zip and the form .xlsx")
        self.drop = tk.Label(body, text=hint, font=("Segoe UI", 11, "bold"), fg=INK, bg="#fff6c2",
                             relief="ridge", bd=2, pady=14, cursor="hand2")
        self.drop.pack(fill="x", pady=(0, 4))
        self.drop.bind("<Button-1>", lambda e: self.choose_files())
        if HAS_DND:
            for w in (self, self.drop):
                w.drop_target_register(DND_FILES)
                w.dnd_bind("<<Drop>>", self.on_drop)
                w.dnd_bind("<<DropEnter>>", lambda e: (self.drop.configure(bg=YELLOW), e.action)[1])
                w.dnd_bind("<<DropLeave>>", lambda e: (self.drop.configure(bg="#fff6c2"), e.action)[1])
        else:
            self.dnd_link = ttk.Label(body, text="Want drag & drop? Click here once (installs a small add-on).",
                                      style="Muted.TLabel", cursor="hand2")
            self.dnd_link.pack(anchor="w")
            self.dnd_link.bind("<Button-1>", lambda e: self.enable_dnd())

        # status line
        self.status = ttk.Label(body, style="Stat.TLabel", justify="left")
        self.status.pack(anchor="w", pady=(8, 10))

        grid = ttk.Frame(body)
        grid.pack(fill="x")
        for c in range(3):
            grid.columnconfigure(c, weight=1, uniform="col")

        def group(col, title):
            f = ttk.LabelFrame(grid, text=title, padding=10)
            f.grid(row=0, column=col, sticky="nsew", padx=(0 if col == 0 else 6, 0))
            return f

        g1 = group(0, "1. Process")
        self.pub_btn = ttk.Button(g1, text="Run & publish", style="Big.TButton",
                                  command=lambda: self.run_report(publish=True))
        self.pub_btn.pack(fill="x")
        self.run_btn = ttk.Button(g1, text="Run report only", command=self.run_report)
        self.run_btn.pack(fill="x", pady=(4, 0))
        self.force_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(g1, text="Re-read every screenshot (--force)", variable=self.force_var).pack(anchor="w", pady=(6, 0))
        ttk.Button(g1, text="Google Drive folder...", command=self.choose_drive).pack(fill="x", pady=(8, 0))
        self.drive_lbl = ttk.Label(g1, style="Muted.TLabel", wraplength=230, justify="left")
        self.drive_lbl.pack(anchor="w", pady=(2, 0))
        ttk.Button(g1, text="Open folder", command=lambda: open_path(HERE)).pack(fill="x", pady=(8, 0))
        ttk.Button(g1, text="Open To_Process", command=self.open_to_process).pack(fill="x", pady=(4, 0))

        g2 = group(1, "2. Check & share")
        self.corr_btn = ttk.Button(g2, text="Corrections (corrections.csv)", command=self.open_corr)
        self.corr_btn.pack(fill="x")
        ttk.Button(g2, text="Who is who (players.csv)", command=self.open_players).pack(fill="x", pady=(4, 0))
        ttk.Button(g2, text="Open report in browser", command=self.open_report).pack(fill="x", pady=(8, 0))
        ttk.Button(g2, text="Open player lookup", command=self.open_lookup).pack(fill="x", pady=(4, 0))
        ttk.Button(g2, text="Open Discord message", command=self.open_discord).pack(fill="x", pady=(8, 0))
        ttk.Button(g2, text="Copy Discord message", command=self.copy_discord).pack(fill="x", pady=(4, 0))

        g3 = group(2, "3. Website, history & reset")
        ttk.Button(g3, text="Publish online", style="Accent.TButton", command=self.publish).pack(fill="x")
        ttk.Button(g3, text="Open public page", command=self.open_public).pack(fill="x", pady=(4, 0))
        ttk.Button(g3, text="Copy index.html contents", command=self.copy_index).pack(fill="x", pady=(8, 0))
        ttk.Button(g3, text="Open htmlReport folder", command=lambda: open_path(HTML_DIR)).pack(fill="x", pady=(4, 0))
        ttk.Button(g3, text="History (deployments.csv)", command=self.open_history).pack(fill="x", pady=(8, 0))
        ttk.Button(g3, text="Add an old batch to history...", command=self.import_batch).pack(fill="x", pady=(4, 0))
        ttk.Button(g3, text="Reset (new batch)...", command=self.reset).pack(fill="x", pady=(8, 0))

        ttk.Label(body, text="Log", style="H.TLabel").pack(anchor="w", pady=(14, 4))
        logf = ttk.Frame(body)
        logf.pack(fill="both", expand=True)
        self.log = tk.Text(logf, height=12, wrap="word", font=("Consolas", 9), bg="#1a1a19", fg="#f0efec",
                           insertbackground="#f0efec", relief="flat", padx=8, pady=6)
        sb = ttk.Scrollbar(logf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set, state="disabled")
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log.tag_configure("ok", foreground="#7ee787")
        self.log.tag_configure("warn", foreground=YELLOW)
        self.log.tag_configure("err", foreground="#ff7b72")

        self.write("Ready. Click Run report (screenshots + form answers come from the Google Drive folder if it's set; "
                   "otherwise drop the Drive .zip and the form file on the yellow box).\n")

    # ---- status / log ------------------------------------------------------
    def refresh(self):
        forms = form_files()
        n_open = open_corrections()
        drv = drive_folder()
        set_drv = str(load_settings().get("drive_folder") or "")
        shots = f"Screenshots: {count_images()} in To_Process" + (f" + {_count(drv)} in the Drive folder" if drv else "")
        cf = current_form()
        form = ((cf.name + (" (Drive folder)" if drv and cf.parent.resolve() == drv.resolve() else ""))
                if cf else "none (dates / fronts will be missing)")
        txt = (f"{shots}     Form: {form}\n"
               f"History: {history_count()} deployments     Last report: {last_report()}     Values to check: {n_open}")
        self.drive_lbl.configure(text=(f"Drive: {drv}" if drv else
                                       (f"Drive folder not found: {set_drv}" if set_drv else "Drive: not set (optional)")))
        self.status.configure(text=txt)
        self.corr_btn.configure(text=f"Corrections ({n_open} to check)" if n_open else "Corrections (corrections.csv)")

    def write(self, text, tag=None):
        self.log.configure(state="normal")
        self.log.insert("end", text, tag)
        self.log.see("end")
        self.log.configure(state="disabled")

    def _drain(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "line":
                    low = payload.lower()
                    tag = ("ok" if "nothing left to check" in low else
                           "err" if ("error" in low or "traceback" in low or "failed" in low) else
                           "warn" if ("to check" in low or "need review" in low or "warning" in low) else None)
                    self.write(payload, tag)
                elif kind == "log":
                    self.write(payload[0], payload[1])
                elif kind == "imported":
                    self.importing = False
                    self.drop.configure(bg="#fff6c2")
                    self.refresh()
                elif kind == "done":
                    self.running = False
                    self.run_btn.configure(state="normal", text="Run report only")
                    self.pub_btn.configure(state="normal", text="Run & publish")
                    self.write(payload[1] + "\n", "ok" if payload[0] == 0 else "err")
                    self.refresh()
        except queue.Empty:
            pass
        self.after(100, self._drain)

    # ---- actions -----------------------------------------------------------
    def choose_files(self):
        files = filedialog.askopenfilenames(
            title="Add the Drive .zip, the form export and/or screenshots",
            filetypes=[("Zip, form, screenshots", "*.zip *.xlsx *.csv *.png *.jpg *.jpeg *.webp *.bmp"),
                       ("All files", "*.*")])
        if files:
            self.import_files([Path(f) for f in files])

    def on_drop(self, event):
        self.drop.configure(bg="#fff6c2")
        self.import_files([Path(p) for p in self.tk.splitlist(event.data)])
        return event.action

    def import_files(self, paths: list[Path]):
        if self.running or self.importing:
            messagebox.showinfo("Busy", "Wait until the current run / import has finished.")
            return
        self.importing = True
        self.drop.configure(bg=YELLOW)
        self.write("\n=== Import " + datetime.datetime.now().strftime("%H:%M:%S") + " ===\n", "warn")

        def work():
            try:
                import_paths(paths, lambda text, tag=None: self.q.put(("log", (text, tag))))
            except Exception as e:  # noqa: BLE001 - never leave the UI stuck
                self.q.put(("log", (f"Import failed: {e}\n", "err")))
            self.q.put(("imported", None))
        threading.Thread(target=work, daemon=True).start()

    def enable_dnd(self):
        py = python_exe()
        self.write("Installing the drag & drop add-on (tkinterdnd2)...\n")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0

        def work():
            try:
                r = subprocess.run([py, "-m", "pip", "install", "tkinterdnd2"], capture_output=True, text=True,
                                   creationflags=flags)
                ok = r.returncode == 0
                self.q.put(("log", ("Done - close and reopen Stats UI to drag & drop files.\n" if ok else
                                    f"Could not install it:\n{(r.stdout + r.stderr)[-800:]}\n",
                                    "ok" if ok else "err")))
            except OSError as e:
                self.q.put(("log", (f"Could not run pip ({py}): {e}\n", "err")))
        threading.Thread(target=work, daemon=True).start()

    def run_report(self, publish: bool = False):
        if self.running or self.importing:
            return
        has_images = count_images() > 0 or _count(drive_folder()) > 0
        if not has_images and not history_count():
            messagebox.showinfo("Nothing to read", "No screenshots yet: drop the Drive zip on the yellow box, "
                                                   "or set the Google Drive folder.")
            return
        self.running = True
        self.run_btn.configure(state="disabled", text="Running...")
        self.pub_btn.configure(state="disabled")
        self.write("\n=== Run report " + datetime.datetime.now().strftime("%H:%M:%S") + " ===\n", "warn")
        if not has_images:
            self.write("No new screenshots - rebuilding the report from the history.\n")
        threading.Thread(target=self._run_worker, args=(self.force_var.get(), has_images, publish), daemon=True).start()

    def _run_worker(self, force: bool, read_images: bool = True, publish: bool = False):
        py = python_exe()
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
        flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        steps = ([[py, "hd2stats.py", "To_Process", "--recursive"] + (["--force"] if force else [])]
                 if read_images else []) + [[py, "make_report.py", "-i", "output"]]
        for cmd in steps:
            try:
                p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                     creationflags=flags)
            except OSError as e:
                self.q.put(("done", (1, f"Could not start Python ({py}): {e}\nRun setup.bat first.")))
                return
            for raw in iter(p.stdout.readline, b""):
                self.q.put(("line", raw.decode("utf-8", "replace").replace("\r", "")))
            p.wait()
            if p.returncode != 0:
                self.q.put(("done", (p.returncode, f"Stopped: {Path(cmd[1]).name} failed (code {p.returncode}).")))
                return
        try:
            HTML_DIR.mkdir(exist_ok=True)
            shutil.copyfile(OUTPUT / "report.html", HTML_DIR / "index.html")
            if (OUTPUT / "players.html").exists():
                shutil.copyfile(OUTPUT / "players.html", HTML_DIR / "players.html")
            for extra in ("units.html",):
                if (OUTPUT / extra).exists():
                    shutil.copyfile(OUTPUT / extra, HTML_DIR / extra)
                else:
                    (HTML_DIR / extra).unlink(missing_ok=True)
            self.q.put(("line", "Website copy updated: htmlReport\\index.html + players.html + units.html\n"))
        except OSError as e:
            self.q.put(("line", f"Could not update htmlReport\\index.html: {e}\n"))
        if publish:
            n = open_corrections()
            if n:
                self.q.put(("done", (0, f"Report done, NOT published: {n} value(s) to check first (Corrections), "
                                        "then Run & publish again.")))
                return
            self.q.put(("line", "\n=== Publishing online ===\n"))
            ps = "powershell" if sys.platform.startswith("win") else "pwsh"
            try:
                p = subprocess.Popen([ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File",
                                      str(HERE / "publish_site.ps1"), "-Auto"], cwd=HERE, stdout=subprocess.PIPE,
                                     stderr=subprocess.STDOUT, env=env, creationflags=flags)
                for raw in iter(p.stdout.readline, b""):
                    self.q.put(("line", raw.decode("utf-8", "replace").replace("\r", "")))
                p.wait()
            except OSError as e:
                self.q.put(("done", (1, f"Could not start the publishing: {e}")))
                return
            if p.returncode != 0:
                self.q.put(("done", (p.returncode, "Report done, but publishing failed (see above).")))
                return
            url = PUBLISHED.read_text(encoding="utf-8").strip() if PUBLISHED.exists() else ""
            self.q.put(("done", (0, f"Done and published: {url}" if url else "Done and published.")))
            return
        self.q.put(("done", (0, "Done. Check 'Values to check' above, then share the report / Discord message.")))

    def choose_drive(self):
        cur = str(load_settings().get("drive_folder") or "")
        d = filedialog.askdirectory(title="The '505th To_Process' folder synced by Google Drive for desktop "
                                          "(e.g. G:\\My Drive\\505th To_Process) - Cancel to keep / clear",
                                    initialdir=cur or str(Path.home()))
        st = load_settings()
        if d:
            st["drive_folder"] = d
            save_settings(st)
            self.write(f"Google Drive folder set: {d} - screenshots and form_answers.csv are read from it on every run.\n",
                       "ok")
        elif cur and messagebox.askyesno("Google Drive folder", f"Stop using the Drive folder?\n{cur}"):
            st.pop("drive_folder", None)
            save_settings(st)
            self.write("Google Drive folder no longer used.\n")
        self.refresh()

    def open_players(self):
        if not PLAYERS.exists():
            PLAYERS.write_text("callsign,also_known_as\n", encoding="utf-8-sig")
        open_path(PLAYERS)
        self.write("players.csv: one line per callsign; in-game / old names in also_known_as, separated by ';'. "
                   "Filled automatically - fix or add names, save, Run report.\n")

    def open_lookup(self):
        f = OUTPUT / "players.html"
        if not f.exists():
            messagebox.showinfo("Player lookup", "No report yet - click Run report first.")
            return
        open_path(f)

    def open_history(self):
        f = HISTORY / "deployments.csv"
        if not f.exists():
            messagebox.showinfo("History", "The history is empty - it fills on every Run report.")
            return
        open_path(f)
        self.write("History: one line per deployment. Put 'no' in the keep column to leave one out of the report "
                   "(save, then Run report).\n")

    def import_batch(self):
        f = filedialog.askopenfilename(title="stats.csv of an old batch (e.g. Archive\\reset_...\\output\\stats.csv)",
                                       initialdir=str(HERE / "Archive") if (HERE / "Archive").exists() else str(HERE),
                                       filetypes=[("stats.csv", "stats.csv"), ("CSV", "*.csv")])
        if not f:
            return
        py = python_exe()
        flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
        self.write(f"\nAdding {f} to the history...\n", "warn")

        def work():
            try:
                r = subprocess.run([py, "history.py", "--import", f], cwd=HERE, capture_output=True, text=True,
                                   creationflags=flags, env=dict(os.environ, PYTHONIOENCODING="utf-8"))
                self.q.put(("log", ((r.stdout + r.stderr).strip() + "\n", "ok" if r.returncode == 0 else "err")))
                if r.returncode == 0:
                    self.q.put(("log", ("Click Run report to include it in the report.\n", None)))
            except OSError as e:
                self.q.put(("log", (f"Could not run history.py: {e}\n", "err")))
            self.q.put(("imported", None))
        threading.Thread(target=work, daemon=True).start()

    def open_to_process(self):
        TO_PROCESS.mkdir(exist_ok=True)
        open_path(TO_PROCESS)

    def open_corr(self):
        if not CORR.exists():
            messagebox.showinfo("Corrections", "No corrections.csv yet - it is created by Run report "
                                               "when some values need checking.")
            return
        open_path(CORR)
        self.write("Opened corrections.csv - fill 'correct_value' (number or ok), save, then Run report again.\n")

    def open_report(self):
        r = OUTPUT / "report.html"
        if r.exists():
            open_path(r)
        else:
            messagebox.showinfo("Report", "No report yet - click Run report first.")

    def open_discord(self):
        if DISCORD.exists():
            open_path(DISCORD)
        else:
            messagebox.showinfo("Discord", "No Discord message yet - click Run report first.")

    def copy_discord(self):
        if not DISCORD.exists():
            messagebox.showinfo("Discord", "No Discord message yet - click Run report first.")
            return
        text = DISCORD.read_text(encoding="utf-8")
        parts = [t.strip() for t in text.split("=" * 20 + " NEXT MESSAGE " + "=" * 20)]
        self.clipboard_clear()
        self.clipboard_append(parts[0])
        self.update()
        extra = f" (message 1 of {len(parts)} - open the file for the others)" if len(parts) > 1 else ""
        self.write(f"Discord message copied to the clipboard{extra}. Paste it in Discord with Ctrl+V.\n", "ok")

    def copy_index(self):
        f = HTML_DIR / "index.html"
        if not f.exists():
            f = OUTPUT / "report.html"
        if not f.exists():
            messagebox.showinfo("Website", "No report yet - click Run report first.")
            return
        self.clipboard_clear()
        self.clipboard_append(f.read_text(encoding="utf-8"))
        self.update()
        self.write(f"Contents of {f.name} ({f.stat().st_size // 1024} KB) copied to the clipboard.\n", "ok")

    def publish(self):
        if not ((HTML_DIR / "index.html").exists() or (OUTPUT / "report.html").exists()):
            messagebox.showinfo("Publish", "No report yet - click Run report first.")
            return
        ps1 = HERE / "publish_site.ps1"
        try:
            if sys.platform.startswith("win"):
                # Own console window (the first time it asks questions and opens the Cloudflare login).
                # PowerShell is started directly, NOT through "cmd /c": cmd breaks paths containing "&".
                subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                                 cwd=str(HERE), creationflags=subprocess.CREATE_NEW_CONSOLE)
            else:
                subprocess.Popen(["pwsh", "-File", str(HERE / "publish_site.ps1")], cwd=str(HERE))
        except OSError as e:
            messagebox.showerror("Publish", f"Could not start publish_site.ps1: {e}")
            return
        self.write("Publishing in a separate window - the address is shown there and copied to the clipboard.\n", "ok")

    def open_public(self):
        url = PUBLISHED.read_text(encoding="utf-8").strip() if PUBLISHED.exists() else ""
        if not url.startswith("https://"):
            messagebox.showinfo("Website", "Not published yet - click Publish online first.")
            return
        import webbrowser
        webbrowser.open(url)
        self.clipboard_clear()
        self.clipboard_append(url)
        self.write(f"Public page: {url}  (address copied to the clipboard)\n", "ok")

    def reset(self):
        if self.running:
            messagebox.showwarning("Reset", "Wait until the report has finished.")
            return
        dlg = ResetDialog(self)
        self.wait_window(dlg)
        action, with_forms, with_history, with_players = dlg.result or (None, False, False, False)
        if not action:
            self.write("Reset cancelled - nothing changed.\n")
            return
        items = items_to_clear(with_forms, with_history, with_players)
        if not items:
            self.write("Nothing to clear - already clean.\n", "ok")
            return
        try:
            if action == "archive":
                dest = HERE / "Archive" / ("reset_" + datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
                for p in items:
                    target = dest / p.relative_to(HERE)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(p), str(target))
                self.write(f"Archived {len(items)} item(s) to {dest}\n", "ok")
            else:
                if not messagebox.askyesno("Delete permanently",
                                           f"Permanently delete {len(items)} item(s)?\nThis cannot be undone.",
                                           icon="warning"):
                    self.write("Delete cancelled - nothing changed.\n")
                    return
                for p in items:
                    if p.is_dir():
                        shutil.rmtree(p)
                    else:
                        p.unlink()
                self.write(f"Deleted {len(items)} item(s).\n", "ok")
        except OSError as e:
            messagebox.showerror("Reset", f"Could not finish (is a file open in another program?)\n{e}")
        TO_PROCESS.mkdir(exist_ok=True)
        self.write("Clean environment ready" + ("" if with_history else f" - the history still has {history_count()} "
                   "deployments") + ". Add new screenshots, then Run report.\n")
        self.refresh()


if __name__ == "__main__":
    App().mainloop()
