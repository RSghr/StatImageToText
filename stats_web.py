"""
stats_web.py - the 505th control panel in your browser (same buttons as Stats UI, plus editors).

    Double-click "Stats Web UI.bat"  (or: python stats_web.py)

It starts a small web server that ONLY this PC can reach (127.0.0.1) and opens the panel in your
browser. A secret key made at each start is needed for every action, so no other website or
computer can use it. Close the console window to stop it.

Only the Python standard library is used.
"""
from __future__ import annotations

import csv
import io
import json
import mimetypes
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.parse
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from ui_core import (ARCHIVE, CORR, DISCORD, HERE, HISTORY, HTML_DIR, IMG_EXT, OUTPUT, PLAYERS, PUBLISHED,
                     TO_PROCESS, _count, count_images, current_form, do_reset, drive_folder, history_count,
                     import_paths, items_to_clear, last_report, load_settings, open_corrections, open_path,
                     python_exe, save_settings)

UPLOADS = HERE / ".uploads"
PAGE = HERE / "stats_web.html"
PORT = 8765                         # fixed, so the panel address can be bookmarked
KEY_FILE = HERE / ".panel_key"      # the panel's secret key (kept, so a bookmark keeps working)
STARTUP_NAME = "505th Stats Panel.vbs"


def panel_key() -> str:
    try:
        k = KEY_FILE.read_text(encoding="utf-8").strip()
        if len(k) >= 24:
            return k
    except OSError:
        pass
    k = secrets.token_urlsafe(24)
    try:
        KEY_FILE.write_text(k, encoding="utf-8")
    except OSError:
        pass
    return k


TOKEN = panel_key()
SERVER = None                       # set in main(), used by "Stop the panel"


def bookmark_url(port: int | None = None) -> str:
    return f"http://127.0.0.1:{port or PORT}/?k={TOKEN}"


def startup_file() -> Path | None:
    appdata = os.environ.get("APPDATA")
    if not appdata:
        return None
    return Path(appdata) / "Microsoft" / "Windows" / "Start Menu" / "Programs" / "Startup" / STARTUP_NAME


def set_autostart(on: bool) -> bool:
    """Start the panel (hidden, no window) when Windows starts: a small .vbs in the Startup folder."""
    f = startup_file()
    if f is None:
        raise ValueError("Only available on Windows.")
    if not on:
        f.unlink(missing_ok=True)
        return False
    py = Path(python_exe())
    pyw = py.with_name("pythonw.exe")
    exe = pyw if pyw.exists() else py
    q = lambda s: '""' + str(s).replace('"', '') + '""'     # noqa: E731 - VBScript quoting
    f.write_text('Set sh = CreateObject("WScript.Shell")\r\n'
                 f'sh.CurrentDirectory = "{str(HERE).replace(chr(34), "")}"\r\n'
                 f'sh.Run "{q(exe)} {q(HERE / "stats_web.py")} --background", 0, False\r\n', encoding="utf-8")
    return True


# --------------------------------------------------------------------------
# background jobs + log
# --------------------------------------------------------------------------
class Jobs:
    def __init__(self):
        self.lock = threading.Lock()
        self.log: list[tuple[str, str | None]] = []
        self.running: str | None = None

    def say(self, text: str, tag: str | None = None):
        with self.lock:
            self.log.append((text, tag))
            if len(self.log) > 5000:
                self.log = self.log[-4000:]

    def start(self, name: str, fn) -> bool:
        with self.lock:
            if self.running:
                return False
            self.running = name

        def work():
            try:
                fn()
            except Exception as e:  # noqa: BLE001 - never leave the panel stuck
                self.say(f"{name} failed: {e}\n", "err")
            finally:
                with self.lock:
                    self.running = None
        threading.Thread(target=work, daemon=True).start()
        return True


JOBS = Jobs()


def tag_for(line: str) -> str | None:
    low = line.lower()
    if "nothing left to check" in low:
        return "ok"
    if "error" in low or "traceback" in low or "failed" in low:
        return "err"
    if "to check" in low or "need review" in low or "warning" in low:
        return "warn"
    return None


def run_steps(steps: list[list[str]]) -> int:
    env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    flags = subprocess.CREATE_NO_WINDOW if sys.platform.startswith("win") else 0
    for cmd in steps:
        try:
            p = subprocess.Popen(cmd, cwd=HERE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=env,
                                 creationflags=flags)
        except OSError as e:
            JOBS.say(f"Could not start Python ({cmd[0]}): {e}\nRun setup.bat first.\n", "err")
            return 1
        for raw in iter(p.stdout.readline, b""):
            line = raw.decode("utf-8", "replace").replace("\r", "")
            JOBS.say(line, tag_for(line))
        p.wait()
        if p.returncode != 0:
            script = next((Path(a).name for a in cmd if str(a).lower().endswith((".py", ".ps1"))), Path(cmd[0]).name)
            JOBS.say(f"Stopped: {script} failed (code {p.returncode}).\n", "err")
            return p.returncode
    return 0


def job_run(force: bool) -> bool:
    py = python_exe()
    has_images = count_images() > 0 or _count(drive_folder()) > 0
    JOBS.say("\n=== Run report " + time.strftime("%H:%M:%S") + " ===\n", "warn")
    if not has_images:
        JOBS.say("No new screenshots - rebuilding the report from the history.\n")
    steps = ([[py, "hd2stats.py", "To_Process", "--recursive"] + (["--force"] if force else [])]
             if has_images else []) + [[py, "make_report.py", "-i", "output"]]
    if run_steps(steps) != 0:
        return False
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
        JOBS.say("Website copy updated: htmlReport\\index.html + players.html + units.html\n")
    except OSError as e:
        JOBS.say(f"Could not update htmlReport: {e}\n", "err")
    JOBS.say("Done. Check 'Values to check', then share the report / Discord message.\n", "ok")
    return True


def job_run_publish(force: bool):
    """Run report; if nothing is left to check, publish the new pages straight away (no window)."""
    if not job_run(force):
        return
    n = open_corrections()
    if n:
        JOBS.say(f"\nNot published: {n} value(s) to check first. Open the Check tab, answer them, then "
                 "Run & publish again.\n", "warn")
        return
    JOBS.say("\n=== Publishing online ===\n", "warn")
    ps = "powershell" if sys.platform.startswith("win") else "pwsh"
    if run_steps([[ps, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(HERE / "publish_site.ps1"),
                   "-Auto"]]) == 0:
        url = PUBLISHED.read_text(encoding="utf-8").strip() if PUBLISHED.exists() else ""
        JOBS.say(f"Published: {url}\n" if url else "Published.\n", "ok")


# --------------------------------------------------------------------------
# CSV helpers (corrections.csv, players.csv, history/deployments.csv)
# --------------------------------------------------------------------------
def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with open(path, encoding="utf-8-sig", newline="") as f:
        sample = f.read(4096)
        f.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        return [{(k or "").strip(): (v or "") for k, v in r.items() if k} for r in csv.DictReader(f, dialect=dialect)]


def write_csv(path: Path, rows: list[dict], fields: list[str]):
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=fields, extrasaction="ignore")
    w.writeheader()
    w.writerows(rows)
    try:
        with open(path, "w", encoding="utf-8-sig", newline="") as f:
            f.write(buf.getvalue())
    except PermissionError:
        raise RuntimeError(f"{path.name} is open in another program (LibreOffice / Excel?) - close it and save again.")


# --------------------------------------------------------------------------
# screenshots: only files inside To_Process or the Google Drive folder are ever served
# --------------------------------------------------------------------------
_SHOTS = {"t": 0.0, "map": {}}


def shot_index() -> dict:
    if time.time() - _SHOTS["t"] < 20:
        return _SHOTS["map"]
    m = {}
    for root in (drive_folder(), TO_PROCESS):
        if root and root.exists():
            for p in root.rglob("*"):
                if p.is_file() and p.suffix.lower() in IMG_EXT:
                    m.setdefault(p.name, p)
    _SHOTS.update(t=time.time(), map=m)
    return m


def status() -> dict:
    drv = drive_folder()
    set_drv = str(load_settings().get("drive_folder") or "")
    cf = current_form()
    form = (cf.name + (" (Drive folder)" if drv and cf.parent.resolve() == drv.resolve() else "")) if cf else ""
    url = PUBLISHED.read_text(encoding="utf-8").strip() if PUBLISHED.exists() else ""
    return dict(shots_local=count_images(), shots_drive=_count(drv) if drv else 0, drive=str(drv or ""),
                drive_setting=set_drv, drive_ok=bool(drv), form=form, history=history_count(),
                last_report=last_report(), to_check=open_corrections(), running=JOBS.running,
                published=url if url.startswith("https://") else "",
                has_report=(OUTPUT / "report.html").exists(), has_players=(OUTPUT / "players.html").exists(),
                trust_form_order=bool(load_settings().get("trust_form_order", True)))


# --------------------------------------------------------------------------
# HTTP
# --------------------------------------------------------------------------
class Handler(BaseHTTPRequestHandler):
    server_version = "505th"

    def log_message(self, *a):  # keep the console quiet
        pass

    # ---- plumbing -------------------------------------------------------------
    def _host_ok(self) -> bool:
        host = (self.headers.get("Host") or "").lower()
        port = self.server.server_address[1]
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def _cookie_ok(self) -> bool:
        for part in (self.headers.get("Cookie") or "").split(";"):
            k, _, v = part.strip().partition("=")
            if k == "k505" and secrets.compare_digest(v, TOKEN):
                return True
        return False

    def _send(self, code: int, body: bytes, ctype: str, extra: dict | None = None):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def _json(self, obj, code: int = 200):
        self._send(code, json.dumps(obj, ensure_ascii=False).encode("utf-8"), "application/json; charset=utf-8")

    def _err(self, msg: str, code: int = 400):
        self._json({"error": msg}, code)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if n > 2_000_000:
            raise ValueError("request too large")
        return json.loads(self.rfile.read(n) or b"{}")

    # ---- GET ------------------------------------------------------------------
    def do_GET(self):
        if not self._host_ok():
            return self._send(403, b"Forbidden", "text/plain")
        url = urllib.parse.urlsplit(self.path)
        q = urllib.parse.parse_qs(url.query)
        if url.path == "/ping":                   # "is the panel already running?" (no data, no key)
            return self._send(200, b"505th-panel", "text/plain")
        if url.path == "/":
            if q.get("k", [""])[0] == TOKEN:      # first visit from the launcher: remember the key, clean URL
                return self._send(303, b"", "text/plain", {
                    "Location": "/", "Set-Cookie": f"k505={TOKEN}; HttpOnly; SameSite=Strict; Path=/; Max-Age=31536000"})
            if not self._cookie_ok():
                return self._send(403, "Open the panel with Stats Web UI.bat or your bookmark (this page needs its key).".encode(),
                                  "text/plain; charset=utf-8")
            return self._send(200, PAGE.read_bytes(), "text/html; charset=utf-8")
        if not self._cookie_ok():
            return self._send(403, b"Forbidden", "text/plain")
        try:
            if url.path == "/api/status":
                return self._json(status())
            if url.path == "/api/log":
                since = int(q.get("since", ["0"])[0])
                with JOBS.lock:
                    lines = JOBS.log[since:]
                    total = len(JOBS.log)
                return self._json({"lines": lines, "next": total, "running": JOBS.running})
            if url.path == "/api/corrections":
                return self._json({"rows": read_csv(CORR)})
            if url.path == "/api/players":
                return self._json({"rows": read_csv(PLAYERS)})
            if url.path == "/api/panel":
                f = startup_file()
                return self._json({"bookmark": bookmark_url(self.server.server_address[1]),
                                   "fixed_port": self.server.server_address[1] == PORT,
                                   "autostart": bool(f and f.exists()), "windows": f is not None})
            if url.path == "/api/raids":
                import raids
                return self._json(raids.panel_state())
            if url.path == "/api/history":
                return self._json({"rows": read_csv(HISTORY / "deployments.csv")})
            if url.path == "/api/discord":
                return self._json({"text": DISCORD.read_text(encoding="utf-8") if DISCORD.exists() else ""})
            if url.path == "/api/index_html":
                f = HTML_DIR / "index.html"
                f = f if f.exists() else OUTPUT / "report.html"
                return self._json({"text": f.read_text(encoding="utf-8") if f.exists() else ""})
            if url.path == "/api/shot":
                p = shot_index().get(q.get("f", [""])[0])
                if not p or not p.exists():
                    return self._send(404, b"Not found", "text/plain")
                ctype = mimetypes.guess_type(p.name)[0] or "application/octet-stream"
                return self._send(200, p.read_bytes(), ctype)
            if url.path in ("/view/report.html", "/view/players.html", "/view/index.html", "/view/units.html",
                            "/view/index_beta.html", "/view/players_beta.html", "/view/units_beta.html",
                            "/view/raids_beta.html"):
                name = url.path.rsplit("/", 1)[1]
                f = OUTPUT / {"index.html": "report.html"}.get(name, name)
                if not f.exists():
                    return self._send(404, b"No report yet - Run report first.", "text/plain")
                return self._send(200, f.read_bytes(), "text/html; charset=utf-8")
        except Exception as e:  # noqa: BLE001
            return self._err(str(e), 500)
        return self._send(404, b"Not found", "text/plain")

    # ---- POST -----------------------------------------------------------------
    def do_POST(self):
        if not self._host_ok() or not self._cookie_ok() or self.headers.get("X-505") != "1":
            return self._send(403, b"Forbidden", "text/plain")
        path = urllib.parse.urlsplit(self.path).path
        try:
            if path == "/api/upload":
                return self._upload()
            b = self._body()
            if path == "/api/run":
                fn = job_run_publish if b.get("publish") else job_run
                ok = JOBS.start("Run & publish" if b.get("publish") else "Run report",
                                lambda: fn(bool(b.get("force"))))
                return self._json({"ok": ok, "busy": not ok})
            if path == "/api/panel/autostart":
                try:
                    return self._json({"ok": True, "autostart": set_autostart(bool(b.get("on")))})
                except (ValueError, OSError) as e:
                    return self._err(str(e))
            if path == "/api/panel/stop":
                if JOBS.running:
                    return self._err("Wait until the current job has finished.")
                threading.Timer(0.3, lambda: SERVER and SERVER.shutdown()).start()
                return self._json({"ok": True})
            if path.startswith("/api/raids/"):
                import raids
                try:
                    if path == "/api/raids/preview":
                        return self._json({"candidates": raids.preview(b.get("raid") or {})})
                    if path == "/api/raids/save":
                        r = raids.save_one(b.get("raid") or {}, list(b.get("ticked") or []))
                        return self._json({"ok": True, "raid": r})
                    if path == "/api/raids/delete":
                        raids.delete(str(b.get("id", "")))
                        return self._json({"ok": True})
                except ValueError as e:
                    return self._err(str(e))
            if path == "/api/import":
                return self._import(b)
            if path == "/api/corrections":
                return self._save_corrections(b)
            if path == "/api/players":
                rows = [dict(callsign=str(r.get("callsign", "")).strip(),
                             also_known_as=str(r.get("also_known_as", "")).strip())
                        for r in b.get("rows", []) if str(r.get("callsign", "")).strip()]
                write_csv(PLAYERS, rows, ["callsign", "also_known_as"])
                return self._json({"ok": True, "saved": len(rows)})
            if path == "/api/history/keep":
                f = HISTORY / "deployments.csv"
                rows = read_csv(f)
                if not rows:
                    return self._err("The history is empty.")
                fields = list(rows[0].keys())
                for r in rows:
                    if r.get("uid") == b.get("uid"):
                        r["keep"] = "yes" if b.get("keep") else "no"
                write_csv(f, rows, fields)
                return self._json({"ok": True})
            if path == "/api/settings":
                st = load_settings()
                if "trust_form_order" in b:
                    st["trust_form_order"] = bool(b["trust_form_order"])
                if "drive_folder" in b:
                    d = str(b.get("drive_folder") or "").strip().strip('"')
                    if d and not Path(d).is_dir():
                        return self._err(f"Folder not found: {d}")
                    if d:
                        st["drive_folder"] = d
                    else:
                        st.pop("drive_folder", None)
                save_settings(st)
                _SHOTS["t"] = 0
                return self._json({"ok": True})
            if path == "/api/reset":
                return self._reset(b)
            if path == "/api/open":
                return self._open(b.get("what", ""))
            if path == "/api/publish":
                return self._publish()
        except RuntimeError as e:
            return self._err(str(e), 409)
        except Exception as e:  # noqa: BLE001
            return self._err(str(e), 500)
        return self._send(404, b"Not found", "text/plain")

    # ---- actions ----------------------------------------------------------------
    def _upload(self):
        """One file per request (raw body), into .uploads/<batch>/ - imported later by /api/import."""
        batch = "".join(c for c in (self.headers.get("X-Batch") or "") if c.isalnum())[:32]
        name = Path(urllib.parse.unquote(self.headers.get("X-Name") or "")).name
        n = int(self.headers.get("Content-Length") or 0)
        if not batch or not name or n <= 0:
            return self._err("bad upload")
        if n > 4 * 1024 ** 3:
            return self._err("file too large")
        folder = UPLOADS / batch
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / name, "wb") as f:
            left = n
            while left > 0:
                chunk = self.rfile.read(min(left, 1 << 20))
                if not chunk:
                    break
                f.write(chunk)
                left -= len(chunk)
        return self._json({"ok": True})

    def _import(self, b: dict):
        batch = "".join(c for c in str(b.get("batch", "")) if c.isalnum())[:32]
        folder = UPLOADS / batch
        if not batch or not folder.is_dir():
            return self._err("nothing uploaded")
        kind = b.get("kind", "files")

        def work():
            try:
                files = sorted(p for p in folder.iterdir() if p.is_file())
                if kind == "history":
                    JOBS.say("\n=== Add an old batch to history ===\n", "warn")
                    for p in files:
                        run_steps([[python_exe(), "history.py", "--import", str(p)]])
                    JOBS.say("Click Run report to include it in the report.\n", "ok")
                else:
                    JOBS.say("\n=== Import " + time.strftime("%H:%M:%S") + " ===\n", "warn")
                    import_paths(files, lambda text, tag=None: JOBS.say(text, tag))
            finally:
                shutil.rmtree(folder, ignore_errors=True)
                _SHOTS["t"] = 0
        ok = JOBS.start("Import", work)
        return self._json({"ok": ok, "busy": not ok})

    def _save_corrections(self, b: dict):
        rows = read_csv(CORR)
        if not rows:
            return self._err("corrections.csv is empty - run the report first.")
        fields = list(rows[0].keys())
        answers = {(a.get("file"), str(a.get("slot", "")), a.get("stat")): str(a.get("correct_value", "")).strip()
                   for a in b.get("answers", [])}
        n = 0
        for r in rows:
            k = (r.get("file"), str(r.get("slot", "")).split(".")[0], r.get("stat"))
            if k in answers and r.get("correct_value", "") != answers[k]:
                r["correct_value"] = answers[k]
                n += 1
        write_csv(CORR, rows, fields)
        return self._json({"ok": True, "changed": n})

    def _reset(self, b: dict):
        action = b.get("action")
        if action not in ("archive", "delete"):
            return self._err("choose archive or delete")
        if JOBS.running:
            return self._err("Wait until the current job has finished.", 409)
        items = items_to_clear(bool(b.get("forms")), bool(b.get("history")), bool(b.get("players")))
        if not items:
            return self._json({"ok": True, "message": "Nothing to clear - already clean."})
        msg = do_reset(action, items)
        JOBS.say(f"Reset: {msg}\n", "ok")
        _SHOTS["t"] = 0
        return self._json({"ok": True, "message": msg})

    def _open(self, what: str):
        targets = {"folder": HERE, "to_process": TO_PROCESS, "htmlreport": HTML_DIR, "corrections": CORR,
                   "players": PLAYERS, "history": HISTORY / "deployments.csv", "archive": ARCHIVE,
                   "drive": drive_folder() or HERE}
        p = targets.get(what)
        if p is None:
            return self._err("unknown")
        if what == "to_process":
            TO_PROCESS.mkdir(exist_ok=True)
        if not p.exists():
            return self._err(f"{p.name} doesn't exist yet.")
        open_path(p)
        return self._json({"ok": True})

    def _publish(self):
        if not ((HTML_DIR / "index.html").exists() or (OUTPUT / "report.html").exists()):
            return self._err("No report yet - Run report first.")
        ps1 = HERE / "publish_site.ps1"
        if sys.platform.startswith("win"):
            # own console window; PowerShell started directly (cmd breaks paths with '&')
            subprocess.Popen(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(ps1)],
                             cwd=str(HERE), creationflags=subprocess.CREATE_NEW_CONSOLE)
        else:
            subprocess.Popen(["pwsh", "-File", str(ps1)], cwd=str(HERE))
        JOBS.say("Publishing in a separate window - the address is shown there and copied to the clipboard.\n", "ok")
        return self._json({"ok": True})


def free_port(preferred: int = 8765) -> int:
    for p in [preferred] + list(range(preferred + 1, preferred + 30)):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", p))
                return p
            except OSError:
                continue
    return 0


def already_running(port: int) -> bool:
    import urllib.request
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/ping", timeout=1.5) as r:
            return r.read(32) == b"505th-panel"
    except Exception:  # noqa: BLE001
        return False


def main():
    global SERVER
    try:
        sys.stdout.reconfigure(errors="replace")
    except Exception:  # noqa: BLE001
        pass
    background = "--background" in sys.argv
    if already_running(PORT):                    # one panel only: just open it
        if not background:
            print("The panel is already running - opening it in the browser.")
            webbrowser.open(bookmark_url())
        return
    shutil.rmtree(UPLOADS, ignore_errors=True)
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    except OSError:
        srv = ThreadingHTTPServer(("127.0.0.1", free_port(PORT + 1)), Handler)
        print(f"Port {PORT} is used by another program - using {srv.server_address[1]} this time "
              "(the bookmark only works on 8765).")
    SERVER = srv
    port = srv.server_address[1]
    url = bookmark_url(port)
    print("505th Stat Department - browser panel")
    print(f"Open / bookmark: {url}")
    print("Only this PC can reach it. Close this window (or Settings -> Stop the panel) to stop it.")
    if not background and "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
        shutil.rmtree(UPLOADS, ignore_errors=True)


if __name__ == "__main__":
    main()
