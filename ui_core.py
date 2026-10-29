"""
ui_core.py - what the control panels do, without any window: shared by stats_ui.pyw (desktop window)
and stats_web.py (browser panel). Paths, settings, counts, importing the Drive zip / form file, reset.
"""
from __future__ import annotations

import csv
import datetime
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
TO_PROCESS = HERE / "To_Process"
OUTPUT = HERE / "output"
HTML_DIR = HERE / "htmlReport"
CORR = HERE / "corrections.csv"
HISTORY = HERE / "history"
PLAYERS = HERE / "players.csv"
SETTINGS = HERE / "settings.json"
DISCORD = OUTPUT / "discord_post.txt"
PUBLISHED = HERE / "published_address.txt"
ARCHIVE = HERE / "Archive"
IMG_EXT = {".png", ".jpg", ".jpeg", ".bmp", ".webp", ".tif", ".tiff", ".gif"}
FORM_EXT = {".xlsx", ".csv"}


# --------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------
def python_exe() -> str:
    """The Python that has the packages: .venv first, then the one running this window (console version)."""
    if os.environ.get("HD2_PYTHON"):
        return os.environ["HD2_PYTHON"]
    for p in (HERE / ".venv" / "Scripts" / "python.exe", HERE / ".venv" / "bin" / "python"):
        if p.exists():
            return str(p)
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and (exe.parent / "python.exe").exists():
        return str(exe.parent / "python.exe")
    return str(exe)


def open_path(p: Path):
    if sys.platform.startswith("win"):
        os.startfile(str(p))  # noqa: S606 - opens with the default program / Explorer
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(p)])
    else:
        subprocess.Popen(["xdg-open", str(p)])


def load_settings() -> dict:
    try:
        import json
        return json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        return {}


def save_settings(d: dict):
    import json
    SETTINGS.write_text(json.dumps(d, indent=2), encoding="utf-8")


def drive_folder() -> Path | None:
    f = str(load_settings().get("drive_folder") or "").strip()
    return Path(f) if f and Path(f).is_dir() else None


def _count(folder: Path | None) -> int:
    if not folder or not folder.exists():
        return 0
    try:
        return sum(1 for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in IMG_EXT)
    except OSError:
        return 0


def count_images() -> int:
    return _count(TO_PROCESS)


def history_count() -> int:
    f = HISTORY / "deployments.csv"
    if not f.exists():
        return 0
    try:
        with open(f, encoding="utf-8-sig", newline="") as fh:
            return sum(1 for r in csv.DictReader(fh) if (r.get("keep") or "yes").strip().lower() != "no")
    except Exception:  # noqa: BLE001
        return 0


def open_corrections() -> int:
    if not CORR.exists():
        return 0
    try:
        with open(CORR, encoding="utf-8-sig", newline="") as f:
            return sum(1 for r in csv.DictReader(f) if not (r.get("correct_value") or "").strip())
    except Exception:
        return 0


NOT_FORMS = {"corrections.csv", "players.csv"}


def form_files() -> list[Path]:
    """Form-answer files next to the program (newest first): only .xlsx/.csv that really contain the form's
    answers (a 'Host Callsign' column) - never players.csv, corrections.csv or other spreadsheets."""
    out = []
    for p in HERE.iterdir():
        if not (p.is_file() and p.suffix.lower() in (".xlsx", ".csv")) or p.name.lower() in NOT_FORMS \
                or p.name.startswith("~$"):
            continue
        try:
            if is_form_bytes(p.name, p.read_bytes()):
                out.append(p)
        except OSError:
            continue
    return sorted(out, key=lambda p: p.stat().st_mtime, reverse=True)


def current_form() -> Path | None:
    """The form file the report will use: the newest form file next to the program or in the Drive folder."""
    cands = list(form_files())
    drv = drive_folder()
    if drv:
        for p in drv.iterdir():
            if p.is_file() and p.suffix.lower() in (".xlsx", ".csv") and p.name.lower() not in NOT_FORMS:
                try:
                    if is_form_bytes(p.name, p.read_bytes()):
                        cands.append(p)
                except OSError:
                    continue
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def last_report() -> str:
    r = OUTPUT / "report.html"
    if not r.exists():
        return "never"
    return datetime.datetime.fromtimestamp(r.stat().st_mtime).strftime("%d %b %Y %H:%M")


def items_to_clear(with_forms: bool, with_history: bool = False, with_players: bool = False) -> list[Path]:
    """What a reset moves away. History, players.csv and corrections.csv stay unless asked:
    the history keeps every deployment, players.csv knows who is who, and corrections.csv keeps the
    values fixed by hand (lines for screenshots that are gone are dropped automatically)."""
    items: list[Path] = []
    if TO_PROCESS.exists():
        items += [p for p in TO_PROCESS.iterdir() if p.name != "PUT_SCREENSHOTS_HERE.txt"]
    for p in (OUTPUT, HTML_DIR / "index.html", HTML_DIR / "players.html", HTML_DIR / "units.html"):
        if p.exists():
            items.append(p)
    if with_forms:
        items += form_files()
    if with_history:
        for p in (HISTORY, CORR, HERE / "raids.csv"):
            if p.exists():
                items.append(p)
    if with_players and PLAYERS.exists():
        items.append(PLAYERS)
    return items


# --------------------------------------------------------------------------
# importing files (zip from Drive, form export, loose screenshots)
# --------------------------------------------------------------------------
def _norm(text: str) -> str:
    return re.sub(r"\W", "", text).lower()


def is_form_bytes(name: str, data: bytes) -> bool:
    """True if this .csv/.xlsx is the form export (has a 'Host Callsign' column). Standard library only."""
    if name.lower().endswith(".csv"):
        head = data[:4000].decode("utf-8-sig", "ignore").splitlines()[:1]
        return bool(head) and "hostcallsign" in _norm(head[0])
    try:
        import io
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            for member in z.namelist():
                if member.startswith("xl/") and member.endswith(".xml") and (
                        "sharedStrings" in member or member.startswith("xl/worksheets/")):
                    if "hostcallsign" in _norm(z.read(member).decode("utf-8", "ignore")[:2_000_000]):
                        return True
    except (zipfile.BadZipFile, OSError, KeyError):
        return False
    return False


def safe_name(name: str) -> str:
    """Only the file name (no folders from inside the zip), without characters Windows refuses."""
    base = name.replace("\\", "/").rsplit("/", 1)[-1]
    base = re.sub(r'[<>:"|?*\x00-\x1f]', "_", base).strip(" .")
    return base or "file"


DRIVE_ZIP_SUFFIX = re.compile(r"-\d{8}T\d{6}Z(?:-\d+-\d+)?$")   # "505th To_Process-20261025T215301Z-1-001"


def existing_images() -> set[tuple[str, int]]:
    """(lower-case name, size) of every screenshot already somewhere in To_Process."""
    if not TO_PROCESS.exists():
        return set()
    return {(p.name.lower(), p.stat().st_size) for p in TO_PROCESS.rglob("*")
            if p.is_file() and p.suffix.lower() in IMG_EXT}


def unique_target(folder: Path, name: str, data_len: int) -> Path | None:
    """Where to write; None if the same file (same name and size) is already there."""
    target = folder / name
    if not target.exists():
        return target
    if target.stat().st_size == data_len:
        return None
    stem, ext = os.path.splitext(name)
    n = 2
    while (folder / f"{stem} ({n}){ext}").exists():
        if (folder / f"{stem} ({n}){ext}").stat().st_size == data_len:
            return None
        n += 1
    return folder / f"{stem} ({n}){ext}"


def install_form(name: str, data: bytes) -> tuple[str, list[str]]:
    """Put the form next to the scripts (fresh date = the one used) and move older form files to Archive."""
    name = safe_name(name)
    moved = []
    for old in form_files():
        if old.name == name:
            continue
        try:
            if is_form_bytes(old.name, old.read_bytes()):
                dest = ARCHIVE / "old_forms"
                dest.mkdir(parents=True, exist_ok=True)
                stamp = datetime.datetime.fromtimestamp(old.stat().st_mtime).strftime("%Y%m%d_%H%M%S")
                shutil.move(str(old), str(dest / f"{stamp}_{old.name}"))
                moved.append(old.name)
        except OSError:
            pass
    (HERE / name).write_bytes(data)
    return name, moved


def import_paths(paths: list[Path], say) -> None:
    """Import dropped/chosen files. say(text, tag) writes to the log (called from a worker thread)."""
    TO_PROCESS.mkdir(exist_ok=True)
    added = skipped = 0
    forms: list[tuple[str, bytes]] = []
    have = existing_images()          # re-downloading the whole Drive folder each week is fine
    for path in paths:
        try:
            if path.is_dir():
                say(f"{path.name}: folders aren't imported - drop the .zip or the files themselves.\n", "warn")
                continue
            ext = path.suffix.lower()
            if ext == ".zip":
                folder = TO_PROCESS / (safe_name(DRIVE_ZIP_SUFFIX.sub("", path.stem)) or "import")
                n_add = n_skip = n_other = 0
                with zipfile.ZipFile(path) as z:
                    for info in z.infolist():
                        if info.is_dir() or "__MACOSX" in info.filename:
                            continue
                        name = safe_name(info.filename)
                        mext = os.path.splitext(name)[1].lower()
                        if mext in IMG_EXT:
                            if (name.lower(), info.file_size) in have:
                                n_skip += 1
                                continue
                            data = z.read(info)
                            folder.mkdir(parents=True, exist_ok=True)
                            target = unique_target(folder, name, len(data))
                            if target is None:
                                n_skip += 1
                                continue
                            target.write_bytes(data)
                            have.add((name.lower(), len(data)))
                            n_add += 1
                        elif mext in FORM_EXT:
                            data = z.read(info)
                            if is_form_bytes(name, data):
                                forms.append((name, data))
                            else:
                                n_other += 1
                        else:
                            n_other += 1
                added += n_add
                skipped += n_skip
                msg = f"{path.name}: {n_add} screenshot(s) added to To_Process\\{folder.name}"
                if n_skip:
                    msg += f", {n_skip} already there"
                if n_other:
                    msg += f", {n_other} other file(s) ignored"
                say(msg + "\n", "ok" if n_add or n_skip else "warn")
            elif ext in IMG_EXT:
                data = path.read_bytes()
                target = (None if (safe_name(path.name).lower(), len(data)) in have
                          else unique_target(TO_PROCESS, safe_name(path.name), len(data)))
                if target is None:
                    skipped += 1
                else:
                    target.write_bytes(data)
                    have.add((safe_name(path.name).lower(), len(data)))
                    added += 1
                    say(f"{path.name}: added to To_Process\n", "ok")
            elif ext in FORM_EXT:
                data = path.read_bytes()
                if is_form_bytes(path.name, data):
                    forms.append((path.name, data))
                elif path.name.lower() == "corrections.csv":
                    say("corrections.csv is opened with the Corrections button, not imported.\n", "warn")
                else:
                    say(f"{path.name}: not the old form export (no 'Host Callsign' column) - not needed, ignored.\n", "warn")
            else:
                say(f"{path.name}: not a .zip, form (.xlsx/.csv) or screenshot - ignored.\n", "warn")
        except zipfile.BadZipFile:
            say(f"{path.name}: damaged or incomplete zip - download it again.\n", "err")
        except OSError as e:
            say(f"{path.name}: could not import ({e}).\n", "err")
    if forms:
        name, data = forms[-1]
        try:
            name, moved = install_form(name, data)
            say(f"Form file: {name} saved next to run.bat - it will be used for the next report.\n", "ok")
            if moved:
                say(f"  older form file(s) moved to Archive\\old_forms: {', '.join(moved)}\n")
        except OSError as e:
            say(f"Form file: could not save it ({e}) - is it open in another program?\n", "err")
    if len(paths) > 1 or added or skipped:
        say(f"Import done: {added} new screenshot(s)" + (f", {skipped} already there" if skipped else "") + ".\n",
            "ok")





# --------------------------------------------------------------------------
# reset (archive / delete)
# --------------------------------------------------------------------------
def do_reset(action: str, items: list[Path]) -> str:
    """Archive (move to Archive/reset_<date>) or delete the given items. Returns a short report."""
    if action == "archive":
        dest = HERE / "Archive" / ("reset_" + datetime.datetime.now().strftime("%Y-%m-%d_%H%M%S"))
        for p in items:
            target = dest / p.relative_to(HERE)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(target))
        msg = f"Archived {len(items)} item(s) to {dest}"
    elif action == "delete":
        for p in items:
            if p.is_dir():
                shutil.rmtree(p)
            else:
                p.unlink()
        msg = f"Deleted {len(items)} item(s)."
    else:
        raise ValueError(action)
    TO_PROCESS.mkdir(exist_ok=True)
    return msg
