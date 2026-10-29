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

import pandas as pd

HERE = Path(__file__).resolve().parent
HISTORY = HERE / "history"
STATS_FILE = HISTORY / "stats.csv"
DEPS_FILE = HISTORY / "deployments.csv"

DEP_COLUMNS = ["uid", "keep", "date", "operation", "planet", "sector", "difficulty", "front", "success",
               "missions_affected", "missions", "players", "kills", "deaths", "deployment", "deployment_id",
               "files", "added", "updated"]


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
            missions_affected=get("missions_affected"), missions=int(g["mission"].nunique()),
            players=", ".join(players),
            kills=int(pd.to_numeric(g.get("kills"), errors="coerce").fillna(0).sum()),
            deaths=int(pd.to_numeric(g.get("deaths"), errors="coerce").fillna(0).sum()),
            deployment=get("deployment"), deployment_id=get("deployment_id"),
            files=" | ".join(sorted(set(map(str, g["file"])))),
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


def report_rows() -> pd.DataFrame:
    """History rows for the report: deployments marked keep = no are left out."""
    stats = _read(STATS_FILE)
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
