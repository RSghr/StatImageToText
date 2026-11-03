"""
history.py - keep every deployment's results across batches.

After each run, hd2stats.py merges output/stats.csv into history/:

    history/stats.csv         one row per player per mission, every deployment ever read
    history/deployments.csv   one row per deployment; set the "keep" column to "no" to leave one out
                              of the report (it stays in the file, and "yes" brings it back)

A deployment is identified by its Deployment ID (Google rename script) or, without one, by its
screenshot file names - so running again, or reading the same screenshots again after a reset,
updates the deployment instead of counting it twice.

    python history.py --import "Archive/reset_2026-10-20/output/stats.csv"   # add an old batch
    python history.py --show                                                 # what's in it
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
from pathlib import Path

import re

import pandas as pd

HERE = Path(__file__).resolve().parent
HISTORY = HERE / "history"
STATS_FILE = HISTORY / "stats.csv"
DEPS_FILE = HISTORY / "deployments.csv"
EXCL_FILE = HISTORY / "excluded.csv"      # player-missions left out of the averages (browser panel -> History)
EXCL_FIELDS = ["uid", "file", "file_hash", "slot", "player"]
OVR_FILE = HISTORY / "edits.csv"          # deployment details fixed by hand (browser panel -> History -> Edit)
EDITABLE = ["date", "operation", "planet", "front"]
FRONT_NAMES = ["Terminids", "Automatons", "Illuminates"]

DEP_COLUMNS = ["uid", "keep", "date", "operation", "planet", "sector", "difficulty", "front", "success",
               "missions", "players", "kills", "deaths", "deployment", "deployment_id",
               "files", "added", "updated", "check"]


def file_uid(files) -> str:
    names = sorted({str(f).strip().lower() for f in files if str(f).strip() and str(f) != "nan"})
    return "F" + hashlib.sha1("|".join(names).encode("utf-8")).hexdigest()[:12]


def add_uids(df: pd.DataFrame) -> pd.DataFrame:
    """uid per deployment: the Deployment ID if there is one, else a fingerprint of its file names."""
    df = df.copy()
    if "deployment_id" not in df.columns:
        df["deployment_id"] = ""
    df["deployment_id"] = df["deployment_id"].astype(object).fillna("").astype(str).replace({"nan": ""})
    uids = {}
    for dep, g in df.groupby("deployment", sort=False):
        did = next((d for d in g["deployment_id"] if d), "")
        uids[dep] = did or file_uid(g["file"])
    if "uid" in df.columns:
        have = df["uid"].astype(object).fillna("").astype(str).replace({"nan": ""})
        df["uid"] = [h if h else uids[d] for h, d in zip(have, df["deployment"])]
    else:
        df["uid"] = df["deployment"].map(uids)
    return df


def _read(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path, dtype={"uid": str, "deployment_id": str, "keep": str})
    except pd.errors.EmptyDataError:
        return pd.DataFrame()


def summarize(stats: pd.DataFrame, old_deps: pd.DataFrame) -> pd.DataFrame:
    """deployments.csv from the player rows, keeping the user's 'keep' choices and first-added dates."""
    if stats.empty:
        return pd.DataFrame(columns=DEP_COLUMNS)
    keep = {}
    added = {}
    if not old_deps.empty and "uid" in old_deps.columns:
        for _, r in old_deps.iterrows():
            keep[str(r["uid"])] = str(r.get("keep", "yes") or "yes")
            added[str(r["uid"])] = str(r.get("added", "") or "")
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    rows = []
    for uid, g in stats.groupby("uid", sort=False):
        first = g.iloc[0]
        get = lambda c: first[c] if c in g.columns and pd.notna(first[c]) else ""
        players = list(dict.fromkeys(str(p) for p in g.sort_values(["mission", "slot"])["player"] if str(p) != "nan"))
        k = keep.get(str(uid), "yes")
        rows.append(dict(
            uid=uid, keep="no" if str(k).strip().lower() in ("no", "n", "0", "false", "x") else "yes",
            date=get("date"), operation=get("operation"), planet=get("planet"), sector=get("sector"),
            difficulty=get("difficulty"), front=get("front"), success=get("success"),
            missions=int(g["mission"].nunique()),
            players=", ".join(players),
            kills=int(pd.to_numeric(g.get("kills"), errors="coerce").fillna(0).sum()),
            deaths=int(pd.to_numeric(g.get("deaths"), errors="coerce").fillna(0).sum()),
            deployment=get("deployment"), deployment_id=get("deployment_id"),
            files=" | ".join(sorted(set(map(str, g["file"])))),
            check=next((x.group(0) for m in g.get("name_check", pd.Series(dtype=str)).astype(object).fillna("").astype(str)
                        if (x := re.search(r"player order[^()]*\([^()]*\)", m))), "")[:400],
            added=added.get(str(uid)) or now, updated=now))
    out = pd.DataFrame(rows, columns=DEP_COLUMNS)
    return out.sort_values(["date", "uid"], na_position="last").reset_index(drop=True)


def merge(batch_csv: Path, quiet: bool = False) -> tuple[int, int, int]:
    """Merge a batch (stats.csv written by hd2stats.py) into history.
    Returns (deployments in the batch, new ones, updated ones)."""
    new = pd.read_csv(batch_csv, dtype={"deployment_id": str, "uid": str})
    if new.empty:
        return 0, 0, 0
    new = add_uids(new)
    HISTORY.mkdir(exist_ok=True)
    hist = _read(STATS_FILE)
    old_uids = set(hist["uid"].astype(str)) if not hist.empty and "uid" in hist.columns else set()
    new_uids = set(new["uid"].astype(str))
    if not hist.empty:
        # drop the old version of the screenshots read again (same file name). Other screenshots of the
        # same deployment stay: a mission sent in a later batch is added, not swapped for the others.
        same_file = hist["file"].astype(str).str.lower().isin(set(new["file"].astype(str).str.lower()))
        if "file_hash" in hist.columns and "file_hash" in new.columns:   # same picture under another name
            hashes = set(new["file_hash"].astype(object).fillna("").astype(str)) - {""}
            same_file |= hist["file_hash"].astype(object).fillna("").astype(str).isin(hashes)
        hist = hist[~same_file]
    merged = pd.concat([hist, new], ignore_index=True, sort=False) if not hist.empty else new
    merged = renumber_missions(merged)
    cols = [c for c in new.columns] + [c for c in merged.columns if c not in new.columns]
    merged = merged[cols]
    sort_cols = [c for c in ("date", "uid", "mission", "slot") if c in merged.columns]
    merged = merged.sort_values(sort_cols, na_position="last").reset_index(drop=True)
    _write(merged, STATS_FILE)
    deps = summarize(merged, _read(DEPS_FILE))
    _write(deps, DEPS_FILE)
    n_new = len(new_uids - old_uids)
    n_upd = len(new_uids & old_uids)
    if not quiet:
        print(f"History: {len(new_uids)} deployment(s) from this run ({n_new} new, {n_upd} updated) - "
              f"{len(deps)} deployments in history ({(deps['keep'] == 'no').sum()} left out)")
    return len(new_uids), n_new, n_upd


def _mission_order(name: str):
    """Sort key for a deployment's screenshots: mission number at the end of the name, then the name."""
    import re
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", str(name)).split(" - ")[0]
    m = re.search(r"(?:^|[_\s\-(])(\d{1,2})\)?\s*$", stem)
    return (int(m.group(1)) if m else 99, str(name).lower())


def renumber_missions(df: pd.DataFrame) -> pd.DataFrame:
    """Mission 1, 2, 3... per deployment from its screenshots (so a mission sent in a later batch
    becomes mission 3 instead of a second 'mission 1')."""
    if df.empty or "file" not in df.columns:
        return df
    df = df.copy()
    for uid, g in df.groupby("uid", sort=False):
        files = sorted(g["file"].astype(str).unique(), key=_mission_order)
        if len(files) > 1 or g["mission"].nunique() != len(files):
            order = {f: i for i, f in enumerate(files, 1)}
            df.loc[g.index, "mission"] = g["file"].astype(str).map(order)
    return df


def _write(df: pd.DataFrame, path: Path):
    tmp = path.with_suffix(".tmp")
    df.to_csv(tmp, index=False, encoding="utf-8-sig")
    try:
        tmp.replace(path)
    except PermissionError:
        tmp.unlink(missing_ok=True)
        raise SystemExit(f"Could not update {path} - is it open in another program? Close it and run again.")


def read_excluded() -> list[dict]:
    if not EXCL_FILE.exists():
        return []
    import csv
    with open(EXCL_FILE, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def excluded_keys() -> set:
    """{(file_hash or file name, slot)} of the player-missions left out of the averages."""
    out = set()
    for r in read_excluded():
        slot = str(r.get("slot", "")).split(".")[0]
        if r.get("file_hash"):
            out.add((r["file_hash"], slot))
        if r.get("file"):
            out.add((r["file"], slot))
    return out


def set_excluded(uid: str, file: str, slot, include: bool) -> int:
    """Leave one player-mission out of the averages (include=False) or count it again. Returns how many are out."""
    import csv
    slot = str(slot).split(".")[0]
    stats = _read(STATS_FILE)
    row = stats[(stats["file"].astype(str) == file) & (stats["slot"].astype(str).str.split(".").str[0] == slot)] \
        if not stats.empty else stats
    if row.empty:
        raise ValueError("That player / mission is not in the history.")
    r = row.iloc[0]
    fh = str(r.get("file_hash", "") or "")
    fh = "" if fh == "nan" else fh
    rows = [x for x in read_excluded() if not (x.get("file") == file and str(x.get("slot")).split(".")[0] == slot)]
    if not include:
        rows.append(dict(uid=uid, file=file, file_hash=fh, slot=slot, player=str(r.get("player", ""))))
    HISTORY.mkdir(exist_ok=True)
    with open(EXCL_FILE, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=EXCL_FIELDS)
        w.writeheader()
        w.writerows({k: x.get(k, "") for k in EXCL_FIELDS} for x in rows)
    return len(rows)


def mission_grid(uid: str) -> list[dict]:
    """The deployment's missions with the 4 player slots, for the History tab (None = empty slot)."""
    stats = apply_edits(_read(STATS_FILE))
    if stats.empty:
        return []
    g = stats[stats["uid"].astype(str) == str(uid)]
    out_keys = excluded_keys()
    missions = []
    for (m, file), mg in g.sort_values(["mission", "slot"]).groupby(["mission", "file"], sort=False):
        fh = str(mg["file_hash"].iloc[0]) if "file_hash" in mg.columns else ""
        slots = [None] * 4
        for _, r in mg.iterrows():
            s = int(float(r["slot"]))
            if 0 <= s < 4:
                key = str(s)
                k = pd.to_numeric(r.get("kills"), errors="coerce")
                slots[s] = dict(slot=s, player=str(r["player"]), kills=0 if pd.isna(k) else int(k),
                                left_out=(fh, key) in out_keys or (str(file), key) in out_keys)
        missions.append(dict(mission=int(float(m)), file=str(file), slots=slots))
    return missions


def read_edits() -> dict:
    """{uid: {field: value}} - details fixed by hand; they win over the form / register on every run."""
    if not OVR_FILE.exists():
        return {}
    import csv
    out: dict = {}
    with open(OVR_FILE, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            f = r.get("field", "")
            if f in EDITABLE or f.startswith("player:") or f == "names_ok":      # player:<name read> = the right callsign
                out.setdefault(r.get("uid", ""), {})[f] = r.get("value", "")
    return out


def sector_of(planet: str) -> str:
    f = HERE / "google_apps_script" / "planets_and_sectors.tsv"
    try:
        for line in f.read_text(encoding="utf-8").splitlines()[1:]:
            p, _, s = line.partition("\t")
            if p.strip().lower() == str(planet).strip().lower():
                return s.strip()
    except OSError:
        pass
    return ""


def set_edits(uid: str, values: dict) -> dict:
    """Save the fixed details of one deployment. An empty value (or the original one) removes the fix."""
    import csv
    deps = _read(DEPS_FILE)
    orig = deps[deps["uid"].astype(str) == str(uid)] if not deps.empty else deps
    if orig.empty:
        raise ValueError("That deployment is not in the history.")
    o = orig.iloc[0]
    edits = read_edits()
    cur = dict(edits.get(str(uid), {}))
    for f in EDITABLE:
        if f not in values:
            continue
        v = " ".join(str(values[f] or "").split())
        if f == "date" and v:
            try:
                v = pd.Timestamp(v.replace("T", " ")).strftime("%Y-%m-%d %H:%M")
            except ValueError:
                raise ValueError(f"'{v}' is not a date and time.") from None
        if f == "front" and v and v not in FRONT_NAMES:
            raise ValueError("The front must be Terminids, Automatons or Illuminates.")
        was = str(o.get(f, "") if pd.notna(o.get(f, "")) else "")
        if f == "date":
            was = was[:16]
        if not v or v == was:
            cur.pop(f, None)
        else:
            cur[f] = v
    if "names_ok" in values:                       # "the names are right": hides the History warning
        if values["names_ok"]:
            cur["names_ok"] = "yes"
        else:
            cur.pop("names_ok", None)
    for old_name, new_name in (values.get("players") or {}).items():
        k, v = "player:" + str(old_name).strip(), " ".join(str(new_name or "").split())
        if not v or v == str(old_name).strip():
            cur.pop(k, None)
        else:
            cur[k] = v
    if cur:
        edits[str(uid)] = cur
    else:
        edits.pop(str(uid), None)
    HISTORY.mkdir(exist_ok=True)
    with open(OVR_FILE, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["uid", "field", "value"])
        w.writeheader()
        for u, d in edits.items():
            for f, v in d.items():
                w.writerow(dict(uid=u, field=f, value=v))
    return cur


def apply_edits(stats: pd.DataFrame) -> pd.DataFrame:
    edits = read_edits()
    if stats.empty or not edits:
        return stats
    stats = stats.copy()
    uid = stats["uid"].astype(str)
    for u, d in edits.items():
        m = uid == u
        if not m.any():
            continue
        for f, v in d.items():
            if f == "names_ok":
                continue
            if f.startswith("player:"):                       # rename one player in this deployment only
                pm = m & (stats["player"].astype(str) == f[7:])
                stats.loc[pm, "player"] = v
                if "ocr_name" in stats.columns:               # (so the in-game name can't bring the old one back)
                    stats["ocr_name"] = stats["ocr_name"].astype(object)
                    stats.loc[pm, "ocr_name"] = v
                continue
            if f not in stats.columns:
                stats[f] = ""
            stats[f] = stats[f].astype(object)
            stats.loc[m, f] = v
            if f == "planet" and "sector" in stats.columns:
                stats["sector"] = stats["sector"].astype(object)
                stats.loc[m, "sector"] = sector_of(v)
    return stats


def report_rows() -> pd.DataFrame:
    """History rows for the report: deployments marked keep = no are left out, details fixed by hand applied."""
    stats = apply_edits(_read(STATS_FILE))
    if stats.empty:
        return stats
    deps = _read(DEPS_FILE)
    if not deps.empty and "keep" in deps.columns:
        out = set(deps.loc[deps["keep"].astype(str).str.strip().str.lower() == "no", "uid"].astype(str))
        stats = stats[~stats["uid"].astype(str).isin(out)]
    return stats


def main(argv=None):
    ap = argparse.ArgumentParser(description="505th stats history")
    ap.add_argument("--import", dest="imp", nargs="+", help="stats.csv file(s) of old batches to add")
    ap.add_argument("--show", action="store_true", help="print a summary")
    a = ap.parse_args(argv)
    if a.imp:
        for f in a.imp:
            p = Path(f)
            if p.is_dir():
                p = p / "stats.csv"
            if not p.exists():
                print(f"{p}: not found")
                continue
            print(f"Importing {p}")
            merge(p)
    if a.show or not a.imp:
        deps = _read(DEPS_FILE)
        if deps.empty:
            print("History is empty.")
            return
        kept = deps[deps["keep"] != "no"]
        print(f"{len(deps)} deployments in history ({len(deps) - len(kept)} left out), "
              f"{pd.to_datetime(kept['date'], errors='coerce').min():%d %b %Y} - "
              f"{pd.to_datetime(kept['date'], errors='coerce').max():%d %b %Y}")


if __name__ == "__main__":
    main()
