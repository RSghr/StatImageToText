"""
make_report.py - turn the stats into the server report.

    python make_report.py                 # every deployment in history/ (falls back to output/stats.csv)
    python make_report.py --batch         # only the last run (output/stats.csv)
    python make_report.py -i output -t "505th Regiment - December report"

Writes, in the output folder:
  report.html        open with any browser (works offline): headline numbers, the three
                     "over time" charts from the registry sheet, fronts, difficulty,
                     planets, highlights and the deployment log
  players.html       player lookup: type a callsign, see that Helldiver's card (totals, fronts,
                     best moments, the 3 Helldivers they deploy with most, recent deployments)
  report_data.xlsx   the same numbers as tables (Over time = the "Treated Data" tab layout),
                     ready to paste into the Google Sheet / LibreOffice / Excel
"""
from __future__ import annotations

import argparse
import html
import json
import math
from datetime import datetime
from pathlib import Path

import pandas as pd

STATS = ["kills", "accuracy", "shots_fired", "shots_hit", "deaths", "stims_used",
         "accidentals", "samples_extracted", "stratagems_used", "melee_kills",
         "times_reinforcing", "friendly_fire_damage"]
SUMMABLE = [s for s in STATS if s != "accuracy"]
FRONTS = ["Terminids", "Automatons", "Illuminates"]
MIN_SHOTS_FOR_ACCURACY = 200


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------
def load(stats_csv: Path) -> pd.DataFrame:
    return load_df(pd.read_csv(stats_csv))


def load_df(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    if "uid" in df.columns:
        # history: the same squad name can be several deployments -> one display name per uid
        df["uid"] = df["uid"].fillna(df["deployment"]).astype(str)
        names, seen = {}, {}
        for uid, dep in df.drop_duplicates("uid")[["uid", "deployment"]].itertuples(index=False):
            n = seen.get(dep, 0) + 1
            seen[dep] = n
            names[uid] = dep if n == 1 else f"{dep} ({n})"
        df["deployment"] = df["uid"].map(names)
    for c in ("date", "operation", "planet", "sector", "difficulty", "front", "success", "missions_affected", "raid"):
        if c not in df.columns:
            df[c] = None
    df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df["raid"] = df["raid"].astype(object).fillna("").astype(str).replace({"nan": ""})
    df["front"] = df["front"].astype(object).fillna("").astype(str).str.strip().replace({"": "Unknown", "nan": "Unknown"})
    df["front"] = df["front"].map(lambda f: next((F for F in FRONTS if F.lower() == f.lower()), f))
    df["difficulty"] = pd.to_numeric(df["difficulty"], errors="coerce")
    df["player"] = df["player"].astype(object).fillna(df.get("ocr_name")).fillna("?").astype(str)
    try:                                   # one callsign per Helldiver (players.csv)
        from players import Roster
        roster = Roster()
        ocr = df["ocr_name"] if "ocr_name" in df.columns else pd.Series("", index=df.index)
        df["player"] = [roster.callsign_for(p, fuzzy=False) or roster.callsign_for(o) or p
                        for p, o in zip(df["player"], ocr.astype(object).fillna("").astype(str))]
    except Exception:
        pass
    df["player_key"] = df["player"].str.lower().str.replace(r"[^a-z0-9]", "", regex=True)
    for c in SUMMABLE:
        df[c] = pd.to_numeric(df[c], errors="coerce").fillna(0)
    df["accuracy"] = pd.to_numeric(df["accuracy"], errors="coerce")
    return df


def deployments(df: pd.DataFrame) -> pd.DataFrame:
    g = df.groupby("deployment", sort=False)
    dep = g.agg(date=("date", "first"), operation=("operation", "first"), planet=("planet", "first"),
                sector=("sector", "first"), difficulty=("difficulty", "first"), front=("front", "first"),
                success=("success", "first"), missions_affected=("missions_affected", "first"),
                missions=("mission", "nunique"), **{c: (c, "sum") for c in SUMMABLE})
    dep["squad"] = g["player"].apply(lambda s: ", ".join(dict.fromkeys(s)))
    dep["kd"] = dep["kills"] / dep["deaths"].where(dep["deaths"] > 0)
    dep["success"] = dep["success"].astype(object).fillna("").astype(str).str.strip().replace({"nan": ""})
    dep["missions_affected"] = dep["missions_affected"].astype(object).fillna("").astype(str).str.strip().replace({"nan": ""})
    dep = dep.reset_index().sort_values(["date", "deployment"], na_position="last").reset_index(drop=True)
    return dep


def ratio(a, b):
    return float(a) / float(b) if b else None


def over_time(dep: pd.DataFrame) -> pd.DataFrame:
    """One row per dated deployment, cumulative columns like the 'Treated Data' tab."""
    d = dep[dep["date"].notna()].sort_values("date").copy()
    out = pd.DataFrame({
        "Deployment start": d["date"].dt.strftime("%Y-%m-%d %H:%M"),
        "Operation": d["operation"].fillna(d["deployment"]),
        "Front": d["front"],
        "Total Kill count": d["kills"].cumsum(),
        "Total Casualties": d["deaths"].cumsum(),
    })
    out["Kill/Casualty ratio"] = [ratio(k, c) for k, c in zip(out["Total Kill count"], out["Total Casualties"])]
    for f in FRONTS:
        k = d["kills"].where(d["front"] == f, 0).cumsum()
        c = d["deaths"].where(d["front"] == f, 0).cumsum()
        out[f"Total {f} Kill count"] = k.values
        out[f"Total {f} Casualties"] = c.values
        out[f"{f} Kill/Casualty ratio"] = [ratio(a, b) for a, b in zip(k, c)]
    out["Kill Count per Operation"] = d["kills"].values
    out["Casualties per Operation"] = d["deaths"].values
    out["Kill/Casualty rate per Operation"] = [ratio(a, b) for a, b in zip(d["kills"], d["deaths"])]
    return out.reset_index(drop=True)


def by_front(dep: pd.DataFrame) -> pd.DataFrame:
    g = dep.groupby("front")
    t = pd.DataFrame({"Deployments": g.size(), "Missions": g["missions"].sum(),
                      "Kills": g["kills"].sum(), "Casualties": g["deaths"].sum(),
                      "Shots fired": g["shots_fired"].sum(), "Shots hit": g["shots_hit"].sum(),
                      "Avg difficulty": g["difficulty"].mean().round(1)})
    t["K/D"] = [ratio(a, b) for a, b in zip(t["Kills"], t["Casualties"])]
    t["Accuracy %"] = [round(100 * ratio(h, f), 1) if f else None for h, f in zip(t["Shots hit"], t["Shots fired"])]
    t["Kills per mission"] = (t["Kills"] / t["Missions"]).round(0)
    order = [f for f in FRONTS if f in t.index] + sorted(i for i in t.index if i not in FRONTS)
    return t.loc[order].reset_index().rename(columns={"front": "Front"})


def by_difficulty(dep: pd.DataFrame) -> pd.DataFrame:
    d = dep[dep["difficulty"].notna()]
    g = d.groupby(d["difficulty"].astype(int))
    t = pd.DataFrame({"Deployments": g.size(), "Missions": g["missions"].sum(), "Kills": g["kills"].sum(),
                      "Casualties": g["deaths"].sum()})
    t["K/D"] = [ratio(a, b) for a, b in zip(t["Kills"], t["Casualties"])]
    t["Kills per mission"] = (t["Kills"] / t["Missions"]).round(0)
    return t.reset_index().rename(columns={"difficulty": "Difficulty"})


def by_planet(dep: pd.DataFrame) -> pd.DataFrame:
    d = dep[dep["planet"].notna() & (dep["planet"].astype(str).str.strip() != "")]
    if d.empty:
        return pd.DataFrame(columns=["Planet", "Sector", "Front", "Deployments", "Kills", "Casualties", "K/D"])
    g = d.groupby("planet")
    t = pd.DataFrame({"Sector": g["sector"].first(), "Front": g["front"].agg(lambda s: s.mode().iat[0]),
                      "Deployments": g.size(), "Kills": g["kills"].sum(), "Casualties": g["deaths"].sum()})
    t["K/D"] = [ratio(a, b) for a, b in zip(t["Kills"], t["Casualties"])]
    return t.sort_values(["Deployments", "Kills"], ascending=False).reset_index().rename(columns={"planet": "Planet"})


def planet_shares(dep: pd.DataFrame, top: int = 5) -> dict:
    """Deployments per planet for the pie: the top planets, the rest grouped as 'Other'."""
    p = dep["planet"].astype(object).fillna("").astype(str).str.strip()
    p = p[(p != "") & (p != "nan")]
    if p.empty:
        return dict(labels=[], deployments=[])
    c = p.value_counts()
    labels, values = list(c.index[:top]), [int(v) for v in c.values[:top]]
    if len(c) > top:
        labels.append("Other")
        values.append(int(c.values[top:].sum()))
    return dict(labels=labels, deployments=values)


def weekly(dep: pd.DataFrame) -> pd.DataFrame:
    d = dep[dep["date"].notna()]
    if d.empty:
        return pd.DataFrame(columns=["Week", "Deployments", "Kills"])
    wk = d["date"].dt.to_period("W-SUN").dt.start_time
    g = d.groupby(wk)
    t = pd.DataFrame({"Deployments": g.size(), "Kills": g["kills"].sum()})
    full = pd.date_range(t.index.min(), t.index.max(), freq="7D")
    t = t.reindex(full, fill_value=0)
    t.index = t.index.strftime("%d %b")
    return t.reset_index().rename(columns={"index": "Week"})


def highlights(df: pd.DataFrame, dep: pd.DataFrame) -> list[dict]:
    """Fun outliers: one card each. Mission-level unless stated."""
    rows = df.copy()
    rows["where"] = rows["operation"].astype(object).fillna("").astype(str)
    rows.loc[rows["where"].isin(["", "nan"]), "where"] = rows["deployment"]
    out = []

    def card(title, icon, sub, r, value, unit):
        out.append(dict(title=title, icon=icon, sub=sub, player=str(r["player"]), value=value, unit=unit,
                        where=f"{r['where']} - mission {int(r['mission'])}",
                        date=r["date"].strftime("%d %b %Y") if pd.notna(r["date"]) else ""))

    def best(col, title, icon, sub, unit, data=None, fmt=lambda v: f"{int(v):,}"):
        d = rows if data is None else data
        if d.empty or d[col].max() <= 0:
            return
        r = d.loc[d[col].idxmax()]
        card(title, icon, sub, r, fmt(r[col]), unit)

    best("kills", "Top gun", "crosshair", "Most kills in a single mission", "kills")
    sharp = rows[(rows["shots_fired"] >= MIN_SHOTS_FOR_ACCURACY) & rows["accuracy"].notna()]
    best("accuracy", "Sharpshooter", "target", f"Best accuracy (at least {MIN_SHOTS_FOR_ACCURACY} shots fired)",
         "accuracy", sharp, fmt=lambda v: f"{v:.1f}%")
    clean = rows[rows["deaths"] == 0]
    best("kills", "Untouchable", "shield", "Most kills without dying once", "kills", clean)
    best("stratagems_used", "Stratagem hero", "signal", "Most stratagems called in a mission", "stratagems")
    best("times_reinforcing", "Guardian angel", "wing", "Most reinforcements called in a mission", "reinforces")
    best("samples_extracted", "Sample hoarder", "flask", "Most samples extracted in a mission", "samples")
    best("melee_kills", "Melee maniac", "fist", "Most melee kills in a mission", "melee kills")
    best("stims_used", "Stim enthusiast", "syringe", "Most stims used in a mission", "stims")
    best("friendly_fire_damage", "Oops", "warning", "Most friendly-fire damage in a mission", "damage")
    best("accidentals", "Accident report", "skull", "Most accidental team kills in a mission", "accidentals")

    full = dep[dep["missions"] >= 3]
    if not full.empty:
        r = full.loc[full["kills"].idxmax()]
        out.append(dict(title="Deadliest deployment", icon="star", sub="Most squad kills in one deployment",
                        player=r["squad"], value=f"{int(r['kills']):,}", unit="kills",
                        where=str(r["operation"]) if pd.notna(r["operation"]) else r["deployment"],
                        date=r["date"].strftime("%d %b %Y") if pd.notna(r["date"]) else ""))
        r = full.loc[full["deaths"].idxmin()]
        out.append(dict(title="Flawless execution", icon="medal", sub="Fewest squad casualties over a full deployment",
                        player=r["squad"], value=f"{int(r['deaths'])}", unit="casualties",
                        where=str(r["operation"]) if pd.notna(r["operation"]) else r["deployment"],
                        date=r["date"].strftime("%d %b %Y") if pd.notna(r["date"]) else ""))
    return out


def headline(df: pd.DataFrame, dep: pd.DataFrame) -> dict:
    t = {c: int(df[c].sum()) for c in SUMMABLE}
    dated = dep["date"].dropna()
    return dict(
        deployments=len(dep), missions=int(dep["missions"].sum()),
        helldivers=int(df["player_key"].nunique()),
        kills=t["kills"], deaths=t["deaths"], kd=ratio(t["kills"], t["deaths"]),
        accuracy=100 * ratio(t["shots_hit"], t["shots_fired"]) if t["shots_fired"] else None,
        shots=t["shots_fired"], stratagems=t["stratagems_used"], samples=t["samples_extracted"],
        reinforcements=t["times_reinforcing"], stims=t["stims_used"], ff=t["friendly_fire_damage"],
        melee=t["melee_kills"], accidentals=t["accidentals"],
        deathless=int((df["deaths"] == 0).sum()), player_missions=len(df),
        first=dated.min().strftime("%d %b %Y") if len(dated) else "",
        last=dated.max().strftime("%d %b %Y") if len(dated) else "",
        undated=int(dep["date"].isna().sum()), unknown_front=int((dep["front"] == "Unknown").sum()),
        incomplete=int((dep["missions"] < 3).sum()),
        flagged=int(df.get("flagged_stats", pd.Series(dtype=str)).astype(object).fillna("").astype(str).ne("").sum()),
        success_known=int(dep["success"].str.lower().isin(["yes", "no"]).sum()),
        success_yes=int((dep["success"].str.lower() == "yes").sum()),
        crash_hit=int((dep["missions_affected"] != "").sum()),
        first_ts=_epoch(dated.min()) if len(dated) else None,
        last_ts=_epoch(dated.max()) if len(dated) else None,
    )


TZ = "Europe/Paris"


def _epoch(t) -> int | None:
    """Local (TZ) naive time -> unix seconds, for Discord <t:...> timestamps."""
    try:
        return int(pd.Timestamp(t).tz_localize(TZ).timestamp())
    except Exception:
        try:
            return int(pd.Timestamp(t).tz_localize("UTC").timestamp())
        except Exception:
            return None


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------
def fmt_num(v, dec=0):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return "-"
    return f"{v:,.{dec}f}"


def table_html(df: pd.DataFrame, num_cols=(), dec=None, cls="") -> str:
    dec = dec or {}
    if df.empty:
        return '<p class="muted">No data yet.</p>'
    head = "".join(f'<th class="{"num" if c in num_cols else ""}">{html.escape(str(c))}</th>' for c in df.columns)
    body = []
    for _, r in df.iterrows():
        cells = []
        for c in df.columns:
            v = r[c]
            if c in num_cols:
                txt = fmt_num(None if pd.isna(v) else float(v), dec.get(c, 0))
                cells.append(f'<td class="num">{txt}</td>')
            else:
                txt = "" if (not isinstance(v, str) and pd.isna(v)) else str(v)
                if c == "Front" and txt in FRONTS:
                    cells.append(f'<td><span class="sw f-{txt.lower()}"></span>{html.escape(txt)}</td>')
                else:
                    cells.append(f"<td>{html.escape(txt)}</td>")
        body.append("<tr>" + "".join(cells) + "</tr>")
    return f'<div class="tw"><table class="{cls}"><thead><tr>{head}</tr></thead><tbody>{"".join(body)}</tbody></table></div>'


ICONS = {  # tiny inline line icons (24x24, stroke = currentColor)
    "crosshair": '<circle cx="12" cy="12" r="8"/><path d="M12 2v5M12 17v5M2 12h5M17 12h5"/>',
    "target": '<circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1"/>',
    "shield": '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/>',
    "signal": '<path d="M12 20V10M8 14l4-4 4 4M5 7a10 10 0 0 1 14 0"/>',
    "wing": '<path d="M3 15c4 0 7-3 9-8 2 5 5 8 9 8M7 19h10"/>',
    "flask": '<path d="M9 3h6M10 3v6l-5 9a2 2 0 0 0 2 3h10a2 2 0 0 0 2-3l-5-9V3"/>',
    "fist": '<path d="M6 11V7a2 2 0 0 1 4 0v3M10 10V6a2 2 0 0 1 4 0v4M14 10V7a2 2 0 0 1 4 0v6a7 7 0 0 1-7 7H9a3 3 0 0 1-3-3v-3"/>',
    "syringe": '<path d="M18 2l4 4M15 5l4 4M17 7l-9 9-3 1 1-3 9-9M4 20l2-2"/>',
    "warning": '<path d="M12 3l10 18H2z"/><path d="M12 10v5M12 18v.5"/>',
    "skull": '<path d="M12 3a8 8 0 0 0-5 14v3h10v-3a8 8 0 0 0-5-14z"/><circle cx="9" cy="12" r="1.5"/><circle cx="15" cy="12" r="1.5"/>',
    "star": '<path d="M12 3l2.8 5.8 6.2.9-4.5 4.4 1 6.2L12 17.4 6.5 20.3l1-6.2L3 9.7l6.2-.9z"/>',
    "medal": '<circle cx="12" cy="15" r="6"/><path d="M8 3l4 6 4-6"/>',
}


def icon(name):
    return f'<svg viewBox="0 0 24 24" aria-hidden="true">{ICONS.get(name, "")}</svg>'


def build_html(title, h, ot, fr, dif, pl, wk, hl, dep, chart_js: str) -> str:
    frk = fr[fr["Front"] != "Unknown"]           # charts show known fronts; the table shows all
    data = dict(
        time=dict(labels=list(ot["Deployment start"].str[:10]), ops=list(ot["Operation"]),
                  kills=list(map(int, ot["Total Kill count"])), deaths=list(map(int, ot["Total Casualties"])),
                  kd=[round(v, 2) if v is not None else None for v in ot["Kill/Casualty ratio"]]),
        fronts=dict(labels=list(frk["Front"]), deployments=list(map(int, frk["Deployments"])),
                    kd=[round(v, 2) if v is not None else None for v in frk["K/D"]]),
        diff=dict(labels=[str(int(d)) for d in dif["Difficulty"]], deployments=list(map(int, dif["Deployments"]))),
        planets=planet_shares(dep),
        weekly=dict(labels=list(wk["Week"]), deployments=list(map(int, wk["Deployments"]))),
    )
    tiles = [
        ("Confirmed kills", fmt_num(h["kills"]), "across all fronts"),
        ("Casualties", fmt_num(h["deaths"]), f"K/D {fmt_num(h['kd'], 1)}"),
        ("Deployments", fmt_num(h["deployments"]), f"{fmt_num(h['missions'])} missions"),
        ("Helldivers", fmt_num(h["helldivers"]), "took part"),
        ("Accuracy", (fmt_num(h["accuracy"], 1) + "%") if h["accuracy"] else "-", f"{fmt_num(h['shots'])} shots fired"),
        ("Stratagems", fmt_num(h["stratagems"]), "called in"),
        ("Samples", fmt_num(h["samples"]), "extracted"),
        ("Reinforcements", fmt_num(h["reinforcements"]), "comrades brought back"),
    ]
    tiles_html = "".join(f'<div class="tile"><div class="tl">{html.escape(a)}</div><div class="tv">{b}</div>'
                         f'<div class="ts">{html.escape(c)}</div></div>' for a, b, c in tiles)
    hl_html = "".join(
        f'<div class="hl"><div class="hi">{icon(x["icon"])}</div><div class="hb">'
        f'<div class="ht">{html.escape(x["title"])}</div><div class="hs">{html.escape(x["sub"])}</div>'
        f'<div class="hv"><b>{html.escape(x["value"])}</b> {html.escape(x["unit"])}</div>'
        f'<div class="hp">{html.escape(x["player"])}</div>'
        f'<div class="hw">{html.escape(x["where"])}{" · " + html.escape(x["date"]) if x["date"] else ""}</div>'
        f'</div></div>' for x in hl) or '<p class="muted">No data yet.</p>'

    fr_t = fr[["Front", "Deployments", "Missions", "Kills", "Casualties", "K/D", "Accuracy %", "Kills per mission",
               "Avg difficulty"]]
    dep_t = dep.assign(Date=dep["date"].dt.strftime("%Y-%m-%d").astype(object).fillna(""),
                       Operation=dep["operation"].astype(object).fillna(""), Planet=dep["planet"].astype(object).fillna(""))
    dep_t = dep_t.rename(columns={"front": "Front", "difficulty": "Diff.", "squad": "Squad (host first)",
                                  "missions": "Missions", "kills": "Kills", "deaths": "Casualties", "kd": "K/D",
                                  "success": "Success"})
    dep_t = dep_t[["Date", "Operation", "Planet", "Front", "Diff.", "Success", "Squad (host first)", "Missions",
                   "Kills", "Casualties", "K/D"]].iloc[::-1]

    notes = []
    if h["undated"]:
        notes.append(f'{h["undated"]} deployment(s) have no date (no matching form answer): counted in the totals, '
                     "left out of the charts over time.")
    if h["unknown_front"]:
        notes.append(f'{h["unknown_front"]} deployment(s) have no front.')
    if h["incomplete"]:
        notes.append(f'{h["incomplete"]} deployment(s) have fewer than 3 mission screenshots.')
    if h["flagged"]:
        notes.append(f'{h["flagged"]} player row(s) still have a value marked for review in HD2_stats.xlsx.')
    notes_html = "".join(f"<li>{html.escape(n)}</li>" for n in notes)
    period = f'{h["first"]} - {h["last"]}' if h["first"] else "no dated deployments yet"
    success_fact = ""          # (no "operations completed": only completed operations are logged)
    if h["crash_hit"]:
        success_fact += (f'<div class="fact"><b>{h["crash_hit"]}</b>'
                         f'<span class="muted">deployments hit by crashes or players leaving</span></div>')
    deathless_pct = 100 * h["deathless"] / h["player_missions"] if h["player_missions"] else 0

    return TEMPLATE.replace("{{TITLE}}", html.escape(title)) \
        .replace("{{PERIOD}}", html.escape(period)) \
        .replace("{{GENERATED}}", datetime.now().strftime("%d %b %Y %H:%M")) \
        .replace("{{TILES}}", tiles_html) \
        .replace("{{HIGHLIGHTS}}", hl_html) \
        .replace("{{DEATHLESS}}", f'{h["deathless"]:,} of {h["player_missions"]:,} ({deathless_pct:.0f}%)') \
        .replace("{{FF}}", fmt_num(h["ff"])).replace("{{MELEE}}", fmt_num(h["melee"])) \
        .replace("{{STIMS}}", fmt_num(h["stims"])).replace("{{ACC}}", fmt_num(h["accidentals"])) \
        .replace("{{SUCCESS_FACT}}", success_fact) \
        .replace("{{FRONT_TABLE}}", table_html(fr_t, num_cols=("Deployments", "Missions", "Kills", "Casualties", "K/D",
                                                               "Accuracy %", "Kills per mission", "Avg difficulty"),
                                               dec={"K/D": 2, "Accuracy %": 1, "Avg difficulty": 1})) \
        .replace("{{PLANET_TABLE}}", table_html(pl, num_cols=("Deployments", "Kills", "Casualties", "K/D"),
                                                dec={"K/D": 2})) \
        .replace("{{DEPLOY_TABLE}}", table_html(dep_t, num_cols=("Diff.", "Missions", "Kills", "Casualties", "K/D"),
                                                dec={"K/D": 2}, cls="log")) \
        .replace("{{NOTES}}", f'<ul class="notes">{notes_html}</ul>' if notes else "") \
        .replace("{{DATA}}", json.dumps(data).replace("</", "<\\/")) \
        .replace("{{CHARTJS}}", chart_js)


def write_xlsx(path: Path, h, ot, fr, dif, pl, wk, hl, dep):
    summary = pd.DataFrame([
        ("Period", f'{h["first"]} - {h["last"]}'), ("Deployments", h["deployments"]), ("Missions", h["missions"]),
        ("Helldivers", h["helldivers"]), ("Confirmed kills", h["kills"]), ("Casualties", h["deaths"]),
        ("Kill/Casualty ratio", round(h["kd"], 2) if h["kd"] else None),
        ("Accuracy %", round(h["accuracy"], 1) if h["accuracy"] else None), ("Shots fired", h["shots"]),
        ("Stratagems called", h["stratagems"]), ("Samples extracted", h["samples"]),
        ("Reinforcements", h["reinforcements"]), ("Stims used", h["stims"]), ("Melee kills", h["melee"]),
        ("Friendly fire damage", h["ff"]), ("Accidentals", h["accidentals"]),
        ("Missions without dying (player-missions)", h["deathless"]),
        ("Operations completed", f'{h["success_yes"]}/{h["success_known"]}' if h["success_known"] else ""),
        ("Deployments hit by crashes / players leaving", h["crash_hit"]),
    ], columns=["Metric", "Value"])
    ot = ot.copy()
    for c in ot.columns:
        if "ratio" in c.lower() or "rate" in c.lower():
            ot[c] = pd.to_numeric(ot[c], errors="coerce").round(2)
    fr = fr.assign(**{"K/D": pd.to_numeric(fr["K/D"], errors="coerce").round(2)})
    dif = dif.assign(**{"K/D": pd.to_numeric(dif["K/D"], errors="coerce").round(2)})
    pl = pl.assign(**{"K/D": pd.to_numeric(pl["K/D"], errors="coerce").round(2)}) if len(pl) else pl
    deps = dep.rename(columns={"kd": "K/D"}).copy()
    deps["K/D"] = deps["K/D"].round(2)
    deps["date"] = deps["date"].dt.strftime("%Y-%m-%d %H:%M")
    with pd.ExcelWriter(path, engine="openpyxl") as xw:
        summary.to_excel(xw, sheet_name="Summary", index=False)
        ot.to_excel(xw, sheet_name="Over time", index=False)
        fr.to_excel(xw, sheet_name="By front", index=False)
        dif.to_excel(xw, sheet_name="By difficulty", index=False)
        pl.to_excel(xw, sheet_name="By planet", index=False)
        wk.to_excel(xw, sheet_name="Per week", index=False)
        pd.DataFrame(hl).drop(columns=["icon"], errors="ignore").to_excel(xw, sheet_name="Highlights", index=False)
        deps.to_excel(xw, sheet_name="Deployments", index=False)
        for ws in xw.book.worksheets:
            ws.freeze_panes = "A2"
            for col in ws.columns:
                w = max(len(str(c.value)) if c.value is not None else 0 for c in col[:200])
                ws.column_dimensions[col[0].column_letter].width = min(max(9, w + 2), 50)


EMOJI = {"crosshair": "\U0001F3AF", "target": "\U0001F52D", "shield": "\U0001F6E1\uFE0F",
         "signal": "\U0001F4E1", "wing": "\U0001F607", "flask": "\U0001F9EA", "fist": "\U0001F44A",
         "syringe": "\U0001F489", "warning": "\U0001F4A5", "skull": "\u2620\uFE0F", "star": "\u2B50",
         "medal": "\U0001F396\uFE0F"}
FRONT_EMOJI = {"Terminids": "\U0001F41B", "Automatons": "\U0001F916", "Illuminates": "\U0001F991"}


def discord_text(title: str, h: dict, fr: pd.DataFrame, hl: list[dict], limit: int) -> list[str]:
    """Discord-ready announcement (markdown), split into messages of at most `limit` characters."""
    def n(v):
        return f"{int(v):,}"
    lines = [f"# {title}"]
    if h.get("first_ts") and h.get("last_ts"):
        lines.append(f"-# <t:{h['first_ts']}:D> - <t:{h['last_ts']}:D>")
    elif h["first"]:
        lines.append(f"-# {h['first']} - {h['last']}")
    lines += ["", f"**{n(h['deployments'])}** deployments · **{n(h['missions'])}** missions · "
                  f"**{n(h['helldivers'])}** helldivers answered the call", "",
              f"\u2694\uFE0F **{n(h['kills'])}** confirmed kills  \u00B7  \U0001FAA6 **{n(h['deaths'])}** casualties"
              + (f"  \u00B7  K/D **{h['kd']:.1f}**" if h["kd"] else ""),
              f"\U0001F4E1 **{n(h['stratagems'])}** stratagems  \u00B7  \U0001F9EA **{n(h['samples'])}** samples  "
              f"\u00B7  \U0001F607 **{n(h['reinforcements'])}** reinforcements"]
    if h.get("success_known"):
        lines.append(f"\u2705 **{round(100 * h['success_yes'] / h['success_known'])}%** of operations completed "
                     f"({h['success_yes']}/{h['success_known']})")
    known = fr[fr["Front"] != "Unknown"]
    if len(known):
        tot = known["Deployments"].sum()
        parts = [f"{FRONT_EMOJI.get(f, '')} {f} {round(100 * d / tot)}%" for f, d in zip(known["Front"], known["Deployments"])]
        lines += ["", "**Fronts:** " + "  \u00B7  ".join(parts)]
    lines += ["", "## \U0001F3C5 Highlights"]
    for x in hl:
        where = x["where"] + (f", {x['date']}" if x["date"] else "")
        emo = EMOJI.get(x["icon"], "-")
        lines.append(f"{emo} **{x['title']}** - {x['player']}: **{x['value']}** {x['unit']}")
        lines.append(f"-# {x['sub']} · {where}")
    lines += ["", "-# Server-wide stats from your end-of-mission screenshots - keep sending them in! o7"]

    msgs, cur = [], ""
    for ln in lines:
        add = ln + "\n"
        if len(cur) + len(add) > limit and cur:
            msgs.append(cur.rstrip())
            cur = ""
        cur += add
    if cur.strip():
        msgs.append(cur.rstrip())
    return msgs


# --------------------------------------------------------------------------
# Player lookup page
# --------------------------------------------------------------------------
def player_cards(df: pd.DataFrame, dep: pd.DataFrame) -> list[dict]:
    """One card per Helldiver (all their logged deployments)."""
    dinfo = dep.set_index("deployment")
    members = df.groupby("deployment")["player_key"].apply(lambda s: set(s))
    cards = []
    for key, g in df.groupby("player_key"):
        if not key:
            continue
        name = g["player"].mode().iat[0]
        deps = list(dict.fromkeys(g["deployment"]))
        t = {c: int(g[c].sum()) for c in SUMMABLE}
        di = dinfo.loc[[d for d in deps if d in dinfo.index]]
        fronts = []
        for f in FRONTS + ["Unknown"]:
            ds = [d for d in deps if d in dinfo.index and dinfo.at[d, "front"] == f]
            if ds:
                fronts.append(dict(front=f, deployments=len(ds),
                                   kills=int(g[g["deployment"].isin(ds)]["kills"].sum())))
        mates: dict[str, int] = {}
        for d in deps:
            for k in members.get(d, set()):
                if k != key:
                    mates[k] = mates.get(k, 0) + 1
        top = sorted(mates.items(), key=lambda kv: (-kv[1], kv[0]))[:3]
        name_of = df.groupby("player_key")["player"].agg(lambda s: s.mode().iat[0])
        best = g.loc[g["kills"].idxmax()] if len(g) else None

        def where(r):
            op = r["operation"] if isinstance(r["operation"], str) and r["operation"] not in ("", "nan") else r["deployment"]
            return dict(op=str(op), mission=int(r["mission"]),
                        date=r["date"].strftime("%d %b %Y") if pd.notna(r["date"]) else "")
        moments = []
        for col, label, unit in (("kills", "Most kills in a mission", "kills"),
                                 ("stims_used", "Most stims in a mission", "stims"),
                                 ("stratagems_used", "Most stratagems in a mission", "stratagems"),
                                 ("times_reinforcing", "Most reinforcements in a mission", "reinforces")):
            if len(g) and g[col].max() > 0:
                r = g.loc[g[col].idxmax()]
                moments.append(dict(label=label, value=int(r[col]), unit=unit, **where(r)))
        recent = []
        for d in sorted(deps, key=lambda d: (dinfo.at[d, "date"] if d in dinfo.index and pd.notna(dinfo.at[d, "date"])
                                             else pd.Timestamp.min), reverse=True)[:10]:
            if d not in dinfo.index:
                continue
            r = dinfo.loc[d]
            mine = g[g["deployment"] == d]
            recent.append(dict(date=r["date"].strftime("%Y-%m-%d") if pd.notna(r["date"]) else "",
                               op=str(r["operation"]) if isinstance(r["operation"], str) and r["operation"] != "nan" else d,
                               planet=str(r["planet"]) if isinstance(r["planet"], str) and r["planet"] != "nan" else "",
                               front=str(r["front"]), diff=int(r["difficulty"]) if pd.notna(r["difficulty"]) else None,
                               missions=int(mine["mission"].nunique()), kills=int(mine["kills"].sum()),
                               deaths=int(mine["deaths"].sum())))
        dates = di["date"].dropna() if len(di) else pd.Series(dtype="datetime64[ns]")
        fav = max(fronts, key=lambda f: (f["deployments"], f["kills"]))["front"] if [f for f in fronts if f["front"] != "Unknown"] else ""
        if fav == "Unknown":
            known = [f for f in fronts if f["front"] != "Unknown"]
            fav = max(known, key=lambda f: (f["deployments"], f["kills"]))["front"] if known else ""
        cards.append(dict(
            key=key, name=name, deployments=len(deps), missions=int(len(g)),
            kills=t["kills"], deaths=t["deaths"], kd=round(ratio(t["kills"], t["deaths"]), 2) if t["deaths"] else None,
            accuracy=round(100 * ratio(t["shots_hit"], t["shots_fired"]), 1) if t["shots_fired"] else None,
            shots=t["shots_fired"], stims=t["stims_used"], stratagems=t["stratagems_used"],
            samples=t["samples_extracted"], reinforcing=t["times_reinforcing"], melee=t["melee_kills"],
            ff=t["friendly_fire_damage"], accidentals=t["accidentals"],
            deathless=int((g["deaths"] == 0).sum()),
            kills_per_mission=round(t["kills"] / len(g), 1) if len(g) else 0,
            avg_diff=round(float(di["difficulty"].mean()), 1) if len(di) and di["difficulty"].notna().any() else None,
            first=dates.min().strftime("%d %b %Y") if len(dates) else "",
            last=dates.max().strftime("%d %b %Y") if len(dates) else "",
            favourite=fav, fronts=fronts, moments=moments,
            radar=[round(t["kills"] / len(g), 2),
                   round(100 * ratio(t["shots_hit"], t["shots_fired"]), 2) if t["shots_fired"] else None,
                   round(t["melee_kills"] / len(g), 2), round(t["deaths"] / len(g), 2),
                   round(100 * int((g["deaths"] == 0).sum()) / len(g), 2),
                   round(t["stratagems_used"] / len(g), 2), round(t["stims_used"] / len(g), 2),
                   round(t["friendly_fire_damage"] / len(g), 2)],
            mates=[dict(name=str(name_of.get(k, k)), key=k, games=n, pct=round(100 * n / len(deps)))
                   for k, n in top],
            recent=recent))
    cards.sort(key=lambda c: c["name"].lower())
    return cards


RADAR_AXES = ["Kills", "Accuracy", "Melee kills", "Deaths", "Deathless", "Stratagems", "Stims used", "Friendly fire dmg"]
RADAR_UNITS = ["per mission", "% of shots", "per mission", "per mission", "% of missions", "per mission",
               "per mission", "per mission"]


def radar_scale(cards: list[dict], min_missions: int = 3) -> dict:
    """Axis ranges for the profile chart: lowest and highest value recorded among Helldivers with at least
    `min_missions` missions (all of them if too few), and the average Helldiver."""
    ref = [c for c in cards if c["missions"] >= min_missions]
    if len(ref) < 3:
        ref = cards
    mins, maxs, avgs = [], [], []
    for i in range(len(RADAR_AXES)):
        vals = [c["radar"][i] for c in ref if c["radar"][i] is not None]
        mins.append(min(vals) if vals else 0)
        maxs.append(max(vals) if vals else 1)
        avgs.append(round(sum(vals) / len(vals), 2) if vals else None)
    return dict(axes=RADAR_AXES, units=RADAR_UNITS, min=mins, max=maxs, avg=avgs, based_on=len(ref),
                min_missions=min_missions if ref is not cards else 0)


def build_players_html(title: str, cards: list[dict], chart_js: str = "") -> str:
    style = TEMPLATE[TEMPLATE.index("<style>") + 7:TEMPLATE.index("</style>")]
    return PLAYERS_TEMPLATE.replace("{{STYLE}}", style) \
        .replace("{{RADAR}}", json.dumps(radar_scale(cards) if cards else {})) \
        .replace("{{CHARTJS}}", chart_js) \
        .replace("{{TITLE}}", html.escape(title)) \
        .replace("{{GENERATED}}", datetime.now().strftime("%d %b %Y %H:%M")) \
        .replace("{{COUNT}}", str(len(cards))) \
        .replace("{{DATA}}", json.dumps(cards, ensure_ascii=False).replace("</", "<\\/"))


def main(argv=None):
    ap = argparse.ArgumentParser(description="Build the 505th server report from output/stats.csv")
    ap.add_argument("-i", "--input", default="output", help="output folder (default: output)")
    ap.add_argument("--batch", action="store_true",
                    help="report only the last run (output/stats.csv) instead of the whole history")
    ap.add_argument("-t", "--title", default="505th Regiment - Galactic War Report")
    ap.add_argument("--timezone", default="Europe/Paris", help="time zone of the dates (default: Europe/Paris)")
    ap.add_argument("--discord-limit", type=int, default=4000,
                    help="max characters per Discord message (4000 with Nitro, 2000 without)")
    a = ap.parse_args(argv)
    global TZ
    TZ = a.timezone
    src = Path(a.input) / "stats.csv"
    hist = None
    if not a.batch:
        try:
            import history
            hist = history.report_rows()
        except Exception as e:  # noqa: BLE001 - fall back to the last run
            print(f"History not used ({e})")
            hist = None
    if hist is not None and len(hist):
        df = load_df(hist)
        print(f"Report from history: {df['deployment'].nunique()} deployments")
    else:
        if not src.exists():
            raise SystemExit(f"{src} not found - run hd2stats.py first")
        df = load(src)
    dep = deployments(df)
    ot, fr, dif, pl, wk = over_time(dep), by_front(dep), by_difficulty(dep), by_planet(dep), weekly(dep)
    hl = highlights(df, dep)
    h = headline(df, dep)
    chart_js = (Path(__file__).resolve().parent / "vendor" / "chart.umd.js").read_text(encoding="utf-8")
    out_html = Path(a.input) / "report.html"
    out_html.write_text(build_html(a.title, h, ot, fr, dif, pl, wk, hl, dep, chart_js), encoding="utf-8")
    write_xlsx(Path(a.input) / "report_data.xlsx", h, ot, fr, dif, pl, wk, hl, dep)
    cards = player_cards(df, dep)
    (Path(a.input) / "players.html").write_text(build_players_html(a.title, cards, chart_js), encoding="utf-8")
    # companies / platoons / squads (from the roster tabs of the answers spreadsheet)
    try:
        import units
        try:
            st = json.loads((Path(__file__).resolve().parent / "settings.json").read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            st = {}
        style = TEMPLATE[TEMPLATE.index("<style>") + 7:TEMPLATE.index("</style>")]
        print(units.build_pages(Path(a.input), a.title, df, cards, style, chart_js, build_players_html,
                                [st.get("drive_folder", "")]))
    except Exception as e:  # noqa: BLE001 - the unit page must never break the normal report
        print(f"Companies & squads page not built: {e}")
    # BETA section: local test copies (index_beta / players_beta / units_beta), never published - see beta.py
    try:
        import beta
        print(beta.build(Path(a.input), dict(df=df, dep=dep, cards=cards, title=a.title, chart_js=chart_js)))
    except Exception as e:  # noqa: BLE001 - the beta must never break the normal report
        print(f"Beta pages not built: {e}")
    msgs = discord_text(a.title, h, fr, hl, a.discord_limit)
    sep = "\n\n" + "=" * 20 + " NEXT MESSAGE " + "=" * 20 + "\n\n"
    (Path(a.input) / "discord_post.txt").write_text(sep.join(msgs), encoding="utf-8")
    print(f"Discord post: {Path(a.input) / 'discord_post.txt'}  ({len(msgs)} message(s), "
          f"{max(len(m) for m in msgs)} chars max)")
    print(f"Report: {out_html}  (+ report_data.xlsx)  - {h['deployments']} deployments, "
          f"{h['kills']:,} kills, {h['helldivers']} helldivers")


# --------------------------------------------------------------------------
TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{{TITLE}}</title>
<style>
:root{color-scheme:dark;
 --bg:#121211;--surface:#1a1a19;--surface2:#232321;--line:#33332f;--grid:#2b2b28;
 --text:#f0efec;--text2:#c3c2b7;--muted:#8f8e85;--accent:#ffe14d;--accent-ink:#121211;
 --s1:#3987e5;--terminids:#c98500;--automatons:#d64545;--illuminates:#9085e9;--unknown:#77766f;
 --c1:#3987e5;--c2:#d95926;--c3:#199e70;--c4:#c98500;--c5:#d55181;--other:#4a4a46}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){color-scheme:light;
 --bg:#f4f3ef;--surface:#fcfcfb;--surface2:#f0efea;--line:#dcdad3;--grid:#e9e7e1;
 --text:#0b0b0b;--text2:#52514e;--muted:#77766f;--accent:#e8c400;--accent-ink:#0b0b0b;
 --s1:#2a78d6;--terminids:#eda100;--automatons:#e34948;--illuminates:#6250d6;--unknown:#9b9a92;
 --c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#eda100;--c5:#e87ba4;--other:#5d5c57}}
:root[data-theme="light"]{color-scheme:light;
 --bg:#f4f3ef;--surface:#fcfcfb;--surface2:#f0efea;--line:#dcdad3;--grid:#e9e7e1;
 --text:#0b0b0b;--text2:#52514e;--muted:#77766f;--accent:#e8c400;--accent-ink:#0b0b0b;
 --s1:#2a78d6;--terminids:#eda100;--automatons:#e34948;--illuminates:#6250d6;--unknown:#9b9a92;
 --c1:#2a78d6;--c2:#eb6834;--c3:#1baf7a;--c4:#eda100;--c5:#e87ba4;--other:#5d5c57}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--text);font:15px/1.45 "Segoe UI",system-ui,-apple-system,Roboto,sans-serif}
.wrap{max-width:1180px;margin:0 auto;padding:0 16px 48px}
header{background:var(--accent);color:var(--accent-ink);border-bottom:4px solid var(--text)}
header .wrap{padding:22px 16px 18px;display:flex;flex-wrap:wrap;gap:6px 24px;align-items:flex-end;justify-content:space-between}
h1{margin:0;font-size:clamp(22px,3.4vw,34px);letter-spacing:.04em;text-transform:uppercase;font-weight:800}
.period{font-weight:600;font-size:14px;letter-spacing:.06em;text-transform:uppercase}
h2{font-size:13px;letter-spacing:.14em;text-transform:uppercase;color:var(--text2);margin:34px 0 12px;
 display:flex;align-items:center;gap:10px}
h2::before{content:"";width:14px;height:14px;background:var(--accent);display:inline-block}
.tiles{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:22px}
@media (max-width:820px){.tiles{grid-template-columns:repeat(2,1fr)}.tv{font-size:24px}}
.tile{background:var(--surface);border:1px solid var(--line);border-left:4px solid var(--accent);padding:14px 16px}
.tl{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--text2)}
.tv{font-size:30px;font-weight:800;margin:2px 0;font-variant-numeric:tabular-nums}
.ts{font-size:13px;color:var(--muted)}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:12px}
.card{background:var(--surface);border:1px solid var(--line);padding:16px;min-width:0}
.card h3{margin:0 0 2px;font-size:15px}.card .sub{color:var(--muted);font-size:13px;margin-bottom:10px}
.chart{position:relative;height:260px}
.hls{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,250px),1fr));gap:10px}
.hl{background:var(--surface);border:1px solid var(--line);padding:14px;display:flex;gap:12px}
.hi svg{width:34px;height:34px;fill:none;stroke:var(--accent);stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}
.ht{font-weight:800;text-transform:uppercase;letter-spacing:.06em;font-size:14px}
.hs{color:var(--muted);font-size:12.5px}
.hv{margin-top:6px;color:var(--text2)}.hv b{font-size:24px;color:var(--text);font-variant-numeric:tabular-nums}
.hp{font-weight:700}.hw{color:var(--muted);font-size:12.5px}
.tw{overflow-x:auto;border:1px solid var(--line);background:var(--surface)}
table{border-collapse:collapse;width:100%;font-size:14px}
th,td{padding:8px 10px;text-align:left;border-bottom:1px solid var(--grid);white-space:nowrap}
th{font-size:12px;text-transform:uppercase;letter-spacing:.08em;color:var(--text2);background:var(--surface2);position:sticky;top:0}
td.num,th.num{text-align:right;font-variant-numeric:tabular-nums}
table.log td:nth-child(7){white-space:normal;min-width:220px}
tbody tr:hover td{background:var(--surface2)}
.sw{display:inline-block;width:10px;height:10px;margin-right:7px;border-radius:2px;vertical-align:baseline}
.f-terminids{background:var(--terminids)}.f-automatons{background:var(--automatons)}.f-illuminates{background:var(--illuminates)}
.legend{display:flex;flex-direction:column;gap:6px;margin-top:10px;font-size:14px}
.legend div{display:flex;align-items:center;gap:8px}.legend .v{margin-left:auto;font-variant-numeric:tabular-nums;color:var(--text2)}
.split{display:grid;grid-template-columns:minmax(160px,220px) 1fr;gap:16px;align-items:center}
@media (max-width:520px){.split{grid-template-columns:1fr}}
.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:10px}
.fact{background:var(--surface);border:1px solid var(--line);padding:12px 14px}
.fact b{font-size:20px;display:block;font-variant-numeric:tabular-nums}
.muted{color:var(--muted)}.notes{color:var(--muted);font-size:13px;padding-left:18px}
footer{color:var(--muted);font-size:12.5px;margin-top:36px;border-top:1px solid var(--line);padding-top:12px}
details summary{cursor:pointer;color:var(--text2);margin:8px 0}
.topnav{display:flex;justify-content:flex-end;padding-top:12px;padding-bottom:0}
.navlink{color:var(--text);font-weight:700;text-decoration:none;border:1px solid var(--line);background:var(--surface);
 padding:7px 12px;font-size:14px}
.navlink:hover{border-color:var(--accent)}
</style></head>
<body>
<header><div class="wrap"><h1>{{TITLE}}</h1><div class="period">{{PERIOD}}</div></div></header>
<nav class="wrap topnav"><a class="navlink" href="players.html">Player lookup &rarr;</a></nav>
<main class="wrap">
<div class="tiles">{{TILES}}</div>
{{NOTES}}

<h2>The war over time</h2>
<div class="grid">
 <div class="card"><h3>Confirmed kills</h3><div class="sub">Cumulative, per deployment</div><div class="chart"><canvas id="cKills" role="img" aria-label="Cumulative kills over time"></canvas></div></div>
 <div class="card"><h3>Casualties</h3><div class="sub">Cumulative, per deployment</div><div class="chart"><canvas id="cDeaths" role="img" aria-label="Cumulative casualties over time"></canvas></div></div>
 <div class="card"><h3>Kill / casualty ratio</h3><div class="sub">Running ratio since the first deployment</div><div class="chart"><canvas id="cKD" role="img" aria-label="Kill to casualty ratio over time"></canvas></div></div>
 <div class="card"><h3>Deployments per week</h3><div class="sub">Weeks start on Monday</div><div class="chart"><canvas id="cWeek" role="img" aria-label="Deployments per week"></canvas></div></div>
</div>

<h2>Fronts</h2>
<div class="grid">
 <div class="card"><h3>Where we fight</h3><div class="sub">Share of deployments per front (deployments with a known front)</div>
  <div class="split"><div class="chart" style="height:200px"><canvas id="cFront" role="img" aria-label="Deployments per front"></canvas></div><div class="legend" id="frontLegend"></div></div></div>
 <div class="card"><h3>Kill / casualty ratio per front</h3><div class="sub">Who gives us the hardest time</div><div class="chart"><canvas id="cFrontKD" role="img" aria-label="Kill to casualty ratio per front"></canvas></div></div>
</div>
<div style="margin-top:12px">{{FRONT_TABLE}}</div>

<h2>Planets &amp; fun facts</h2>
<div class="grid">
 <div class="card"><h3>Where we deploy</h3><div class="sub">Share of deployments per planet (top 5, the rest grouped as Other)</div>
  <div class="split"><div class="chart" style="height:220px"><canvas id="cPlanet" role="img" aria-label="Share of deployments per planet"></canvas></div><div class="legend" id="planetLegend"></div></div></div>
 <div class="card"><h3>Server fun facts</h3><div class="sub">Totals across every mission</div>
  <div class="facts">
   <div class="fact"><b>{{DEATHLESS}}</b><span class="muted">missions where a helldiver never died</span></div>
   <div class="fact"><b>{{MELEE}}</b><span class="muted">melee kills</span></div>
   <div class="fact"><b>{{STIMS}}</b><span class="muted">stims used</span></div>
   <div class="fact"><b>{{FF}}</b><span class="muted">friendly fire damage</span></div>
   <div class="fact"><b>{{ACC}}</b><span class="muted">accidental team kills</span></div>
   {{SUCCESS_FACT}}
  </div></div>
</div>

<h2>Planets</h2>
{{PLANET_TABLE}}

<h2>Highlights</h2>
<div class="hls">{{HIGHLIGHTS}}</div>

<h2>Deployment log</h2>
<details open><summary>Most recent first</summary>{{DEPLOY_TABLE}}</details>

<footer>Generated {{GENERATED}} by the 505th Stat Department · numbers read from end-of-mission stat screens.
Server-wide view, not a leaderboard. Charts: Chart.js (MIT).</footer>
</main>
<script>{{CHARTJS}}</script>
<script>
const D = {{DATA}};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const charts = [];
const fmt = v => v == null ? '-' : Number(v).toLocaleString('en-US');
function frontColor(f){ return css('--' + String(f).toLowerCase()) || css('--unknown'); }
function base(extra){
  return Object.assign({responsive:true, maintainAspectRatio:false, animation:false,
    interaction:{mode:'index', intersect:false},
    plugins:{legend:{display:false}, tooltip:{backgroundColor:css('--surface2'), titleColor:css('--text'),
      bodyColor:css('--text'), borderColor:css('--line'), borderWidth:1, padding:10, displayColors:true,
      boxWidth:10, boxHeight:2}},
    scales:{x:{grid:{display:false}, border:{color:css('--line')}, ticks:{color:css('--muted'), maxRotation:0, autoSkip:true, maxTicksLimit:7}},
            y:{beginAtZero:true, grid:{color:css('--grid')}, border:{display:false}, ticks:{color:css('--muted')}}}}, extra||{});
}
function empty(id, msg){ const c=document.getElementById(id); const p=document.createElement('p');
  p.className='muted'; p.textContent=msg; c.parentNode.replaceChild(p, c); }
function line(id, label, values, opts){
  if(!D.time.labels.length){ empty(id, 'No dated deployments yet - add the form file to get charts over time.'); return; }
  const col = css('--s1');
  charts.push(new Chart(document.getElementById(id), {type:'line',
    data:{labels:D.time.labels, datasets:[{label, data:values, borderColor:col, backgroundColor:col,
      borderWidth:2, pointRadius: values.length>40?0:3, pointHoverRadius:5, tension:0.15, spanGaps:true}]},
    options:base({plugins:Object.assign(base().plugins,{tooltip:Object.assign(base().plugins.tooltip,{
      callbacks:{title:i=>D.time.labels[i[0].dataIndex]+' · '+D.time.ops[i[0].dataIndex],
                 label:i=>' '+label+': '+(opts&&opts.dec?Number(i.raw).toFixed(2):fmt(i.raw))}})})})}));
}
function bars(id, labels, values, colors, label, dec){
  if(!labels.length){ empty(id, 'No data yet.'); return; }
  const o = base(); if(!dec){ o.scales.y.ticks.precision = 0; }
  charts.push(new Chart(document.getElementById(id), {type:'bar',
    data:{labels, datasets:[{label, data:values, backgroundColor:colors, borderRadius:{topLeft:4, topRight:4},
      borderSkipped:'bottom', maxBarThickness:46, borderColor:css('--surface'), borderWidth:{left:1,right:1}}]},
    options:Object.assign(o, {interaction:{mode:'nearest', intersect:true},
      plugins:Object.assign(base().plugins,{tooltip:Object.assign(base().plugins.tooltip,{displayColors:false,
        callbacks:{label:i=>' '+label+': '+(dec?Number(i.raw).toFixed(2):fmt(i.raw))}})})})}));
}
// names written on slices of 15% or more (dark or light ink, whichever reads on the slice)
const sliceLabels = {id:'sliceLabels', afterDatasetsDraw(chart){
  const ds = chart.data.datasets[0], meta = chart.getDatasetMeta(0), tot = ds.data.reduce((a,b)=>a+b,0) || 1;
  const ctx = chart.ctx; ctx.save(); ctx.textAlign='center'; ctx.textBaseline='middle';
  meta.data.forEach((arc,i)=>{ const share = ds.data[i]/tot; if(share < 0.15) return;
    const p = arc.tooltipPosition(); const col = ds.backgroundColor[i];
    const rgb = (col.match(/\w\w/g)||['77','77','77']).slice(-3).map(h=>parseInt(h,16));
    const lum = (0.2126*rgb[0]+0.7152*rgb[1]+0.0722*rgb[2])/255;
    ctx.fillStyle = lum > 0.55 ? '#121211' : '#ffffff';
    ctx.font = '700 12px ' + Chart.defaults.font.family;
    ctx.fillText(chart.data.labels[i], p.x, p.y - 7);
    ctx.font = '12px ' + Chart.defaults.font.family;
    ctx.fillText(Math.round(100*share)+'%', p.x, p.y + 8); });
  ctx.restore(); }};
function planetPie(){
  const el = document.getElementById('cPlanet'); if(!el) return;
  const P = D.planets; const lg = document.getElementById('planetLegend'); lg.textContent='';
  if(!P.labels.length){ empty('cPlanet','No planets yet - they come from the form answers.'); return; }
  const cols = P.labels.map((l,i)=> l==='Other' ? css('--other') : css('--c'+(i+1)));
  charts.push(new Chart(el, {type:'pie', data:{labels:P.labels, datasets:[{data:P.deployments, backgroundColor:cols,
      borderColor:css('--surface'), borderWidth:2}]},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      plugins:{legend:{display:false}, tooltip:Object.assign(base().plugins.tooltip,{callbacks:{label:i=>' '+i.label+': '+i.raw+' deployment'+(i.raw>1?'s':'')}})}},
    plugins:[sliceLabels]}));
  const total = P.deployments.reduce((a,b)=>a+b,0) || 1;
  P.labels.forEach((f,i)=>{ const row=document.createElement('div'); const sw=document.createElement('span');
    sw.className='sw'; sw.style.background=cols[i]; const n=document.createElement('span'); n.textContent=f;
    const v=document.createElement('span'); v.className='v';
    v.textContent=P.deployments[i]+' · '+Math.round(100*P.deployments[i]/total)+'%';
    row.append(sw,n,v); lg.append(row); });
}
function draw(){
  charts.splice(0).forEach(c=>c.destroy());
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  line('cKills', 'Kills', D.time.kills);
  line('cDeaths', 'Casualties', D.time.deaths);
  line('cKD', 'K/D', D.time.kd, {dec:true});
  bars('cWeek', D.weekly.labels, D.weekly.deployments, css('--s1'), 'Deployments');
  planetPie();
  const fc = D.fronts.labels.map(frontColor);
  bars('cFrontKD', D.fronts.labels, D.fronts.kd, fc, 'K/D', true);
  const el = document.getElementById('cFront');
  if (el) {
    if (!D.fronts.labels.length) empty('cFront','No data yet.');
    else charts.push(new Chart(el, {type:'doughnut', data:{labels:D.fronts.labels,
      datasets:[{data:D.fronts.deployments, backgroundColor:fc, borderColor:css('--surface'), borderWidth:2}]},
      options:{responsive:true, maintainAspectRatio:false, animation:false, cutout:'58%',
        plugins:{legend:{display:false}, tooltip:base().plugins.tooltip}}}));
  }
  const total = D.fronts.deployments.reduce((a,b)=>a+b,0) || 1;
  const lg = document.getElementById('frontLegend'); lg.textContent='';
  D.fronts.labels.forEach((f,i)=>{ const row=document.createElement('div'); const sw=document.createElement('span');
    sw.className='sw'; sw.style.background=fc[i]; const n=document.createElement('span'); n.textContent=f;
    const v=document.createElement('span'); v.className='v';
    v.textContent=D.fronts.deployments[i]+' · '+Math.round(100*D.fronts.deployments[i]/total)+'%';
    row.append(sw,n,v); lg.append(row); });
}
draw();
matchMedia('(prefers-color-scheme: light)').addEventListener('change', draw);
</script>
</body></html>
"""

PLAYERS_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Player lookup - {{TITLE}}</title>
<style>{{STYLE}}
:root{--cc-mix:35%}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--cc-mix:0%}}
:root[data-theme="light"]{--cc-mix:0%}
.cc{--ccl:color-mix(in srgb, var(--cc) calc(100% - var(--cc-mix)), white)}
.search{display:flex;gap:8px;margin-top:22px}
.search input{flex:1;min-width:0;font:inherit;font-size:18px;padding:12px 14px;background:var(--surface);color:var(--text);
 border:2px solid var(--line);outline:none}
.search input:focus{border-color:var(--accent)}
.search button{font:inherit;font-weight:700;padding:0 18px;background:var(--accent);color:var(--accent-ink);border:0;cursor:pointer}
.hint{color:var(--muted);font-size:13px;margin-top:6px}
.chips{display:flex;flex-wrap:wrap;gap:6px;margin-top:10px}
.chip{font:inherit;font-size:13px;padding:4px 10px;background:var(--surface);color:var(--text2);border:1px solid var(--line);cursor:pointer}
.chip:hover,.chip.on{border-color:var(--accent);color:var(--text)}
.pc{margin-top:22px}
.pname{font-size:clamp(28px,5vw,44px);font-weight:800;letter-spacing:.02em;margin:0}
.psub{color:var(--muted);margin-top:2px}
.tiles6{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:16px}
@media (max-width:640px){.tiles6{grid-template-columns:repeat(2,1fr)}}
.fbar{display:flex;height:16px;border:1px solid var(--line);margin:8px 0 10px;background:var(--surface2)}
.fbar span{display:block;height:100%}
.f-unknown{background:var(--unknown)}
.mate{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:10px 0;border-bottom:1px solid var(--grid)}
.mate:last-child{border-bottom:0}
.mate a{color:var(--text);font-weight:700;text-decoration:none;font-size:16px}
.mate a:hover{color:var(--accent)}
.mate .g{color:var(--text2);text-align:right;font-variant-numeric:tabular-nums}
.mate .bar{grid-column:1/-1;height:6px;background:var(--surface2)}
.mate .bar i{display:block;height:100%;background:var(--s1)}
.mom{display:flex;justify-content:space-between;gap:12px;padding:8px 0;border-bottom:1px solid var(--grid)}
.mom:last-child{border-bottom:0}
.mom b{font-size:20px;font-variant-numeric:tabular-nums}
.empty{margin-top:30px;color:var(--muted)}
.prof{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:16px;align-items:center}
@media (max-width:760px){.prof{grid-template-columns:1fr}}
.prof .chart{height:340px}
.ptab td,.ptab th{padding:5px 8px}
.ptab .me{font-weight:700}
@media (max-width:520px){.ptab td:last-child,.ptab th:last-child{display:none}}
.pc .facts{grid-template-columns:repeat(auto-fit,minmax(130px,1fr))}
</style></head>
<body>
<header><div class="wrap"><h1>Player lookup</h1><div class="period">{{TITLE}}</div></div></header>
<nav class="wrap topnav"><a class="navlink" href="index.html">&larr; Regiment report</a></nav>
<main class="wrap">
<form class="search" id="f" autocomplete="off">
 <input id="q" list="names" placeholder="Type your callsign..." aria-label="Callsign">
 <datalist id="names"></datalist>
 <button type="submit">Show</button>
</form>
<div class="hint">{{COUNT}} Helldivers with logged deployments.</div>
<details><summary>All Helldivers</summary><div class="chips" id="chips"></div></details>
<div id="card"></div>
<footer>Generated {{GENERATED}} by the 505th Stat Department · every logged deployment, read from end-of-mission
stat screens. Personal stats, not a leaderboard.</footer>
</main>
<script>{{CHARTJS}}</script>
<script>
const P = {{DATA}};
const R = {{RADAR}};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
let radarChart = null;
const byKey = {}; P.forEach(p => byKey[p.key] = p);
const norm = s => String(s||'').normalize('NFKD').replace(/[^\w]/g,'').toLowerCase().replace(/_/g,'');
const fmt = v => v == null ? '-' : Number(v).toLocaleString('en-US');
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e; }
const dl = document.getElementById('names'), chips = document.getElementById('chips');
P.forEach(p => { const o=el('option'); o.value=p.name; dl.appendChild(o);
  const c=el('button','chip',p.name); c.type='button'; c.onclick=()=>show(p.key,true); c.dataset.key=p.key; chips.appendChild(c); });
function find(q){ const n=norm(q); if(!n) return null;
  return P.find(p=>norm(p.name)===n) || P.find(p=>norm(p.name).startsWith(n)) || P.find(p=>norm(p.name).includes(n)) || null; }
function tile(label, value, sub){ const t=el('div','tile'); t.appendChild(el('div','tl',label)); t.appendChild(el('div','tv',value));
  if(sub) t.appendChild(el('div','ts',sub)); return t; }
function card(h, sub){ const c=el('div','card'); c.appendChild(el('h3',null,h)); if(sub) c.appendChild(el('div','sub',sub)); return c; }
// average Helldiver = the middle ring (0.5); the edge = 2x the average
function ratioOf(v, i){ const a=R.avg[i]; if(v==null || a==null) return null; return a>0 ? v/a : (v>0 ? 2 : 1); }
function rnorm(v, i){ const r=ratioOf(v, i); return r==null ? null : Math.max(0, Math.min(1, r/2)); }
function fmtv(v, i){ if(v==null) return '-'; return (R.units[i].startsWith('%') ? v.toFixed(1)+'%' : (v>=100 ? Math.round(v).toLocaleString('en-US') : v.toFixed(1))); }
function profileCard(p){
  const c = card('Helldiver profile', 'Per mission. Ring = average Helldiver · edge = 2× the average · based on ' +
    p.missions + ' mission' + (p.missions>1?'s':'') + '.');
  c.style.marginTop = '12px';
  if(!R.axes){ c.appendChild(el('p','muted','Not enough data yet.')); return c; }
  const wrap = el('div','prof'); const box = el('div','chart'); const cv = el('canvas'); cv.setAttribute('role','img');
  cv.setAttribute('aria-label', p.name+' compared with the average Helldiver'); box.appendChild(cv); wrap.appendChild(box);
  // the numbers behind the chart
  const tw = el('div','tw'); const t = el('table','ptab'); const th = el('tr');
  ['', p.name, 'Average', ''].forEach((h,i)=>th.appendChild(el('th', i?'num':null, h))); const thead=el('thead'); thead.appendChild(th); t.appendChild(thead);
  const tb = el('tbody');
  R.axes.forEach((a,i)=>{ const tr=el('tr'); tr.appendChild(el('td',null,a)); tr.appendChild(el('td','num me',fmtv(p.radar[i],i)));
    tr.appendChild(el('td','num',fmtv(R.avg[i],i))); tr.appendChild(el('td','muted small',R.units[i])); tb.appendChild(tr); });
  t.appendChild(tb); tw.appendChild(t); wrap.appendChild(tw); c.appendChild(wrap);
  setTimeout(()=>drawRadar(cv, p), 0);
  return c;
}
function drawRadar(cv, p){
  if(typeof Chart === 'undefined') return;
  if(radarChart){ radarChart.destroy(); radarChart = null; }
  const me = css('--s1'), avg = css('--muted');
  const narrow = cv.parentNode.clientWidth < 460;
  const SHORT = {'Friendly fire dmg':'FF dmg', 'Melee kills':'Melee', 'Stratagems':'Strat.', 'Stims used':'Stims', 'Accuracy':'Acc.', 'Deathless':'No death'};
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  radarChart = new Chart(cv, {type:'radar',
    data:{labels:R.axes.map((a,i)=>{ const r=ratioOf(p.radar[i], i); const n = narrow ? (SHORT[a]||a) : a;
      return r==null ? n : n+(narrow?' ':'  ')+r.toFixed(1)+'×'; }), datasets:[
      {label:p.name, data:p.radar.map(rnorm), borderColor:me, backgroundColor:me+'40', borderWidth:2, pointRadius:4,
       pointBackgroundColor:me, pointBorderColor:css('--surface'), pointBorderWidth:2, spanGaps:true},
      {label:'Average Helldiver', data:R.avg.map(()=>0.5), borderColor:avg, backgroundColor:avg+'26', borderWidth:2,
       borderDash:[5,4], pointRadius:0, spanGaps:true}]},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      scales:{r:{min:0, max:1, ticks:{display:false, stepSize:0.25}, grid:{color:css('--grid')}, angleLines:{color:css('--grid')},
        pointLabels:{color:css('--text2'), font:{size: narrow ? 11 : 12}}}},
      plugins:{legend:{display:true, position:'bottom', labels:{color:css('--text2'), boxWidth:14, boxHeight:2}},
        tooltip:{backgroundColor:css('--surface2'), titleColor:css('--text'), bodyColor:css('--text'), borderColor:css('--line'), borderWidth:1,
          callbacks:{title:it=>R.axes[it[0].dataIndex],
            label:i=>{ const k=i.dataIndex, v = i.datasetIndex===0 ? p.radar[k] : R.avg[k];
              const unit = R.units[k].startsWith('%') ? '' : ' '+R.units[k];
              const r = ratioOf(p.radar[k], k);
              return ' '+i.dataset.label+': '+fmtv(v, k)+unit+(i.datasetIndex===0 && r!=null ? '  ('+r.toFixed(1)+'× average)' : ''); }}}}}});
}
function show(key, push){
  const p = byKey[key]; const root = document.getElementById('card'); root.innerHTML='';
  document.querySelectorAll('.chip').forEach(c=>c.classList.toggle('on', c.dataset.key===key));
  if(!p){ root.appendChild(el('p','empty','No Helldiver with that callsign yet - check the spelling, or pick a name from the list.')); return; }
  document.getElementById('q').value = p.name;
  if(push) history.replaceState(null,'','#'+encodeURIComponent(p.name));
  const pc = el('section','pc');
  pc.appendChild(el('h2',null,'Helldiver file'));
  pc.appendChild(el('div','pname',p.name));
  const bits = [];
  if(p.first) bits.push(p.first===p.last ? 'Deployed '+p.first : 'Deploying since '+p.first+' · last seen '+p.last);
  if(p.favourite) bits.push('favourite front: '+p.favourite);
  if(p.avg_diff!=null) bits.push('average difficulty '+p.avg_diff);
  pc.appendChild(el('div','psub',bits.join(' · ')));
  if(p.unit){ const u=el('div','psub'); u.style.color='var(--text)'; u.style.fontWeight='700';
    if(p.unit_color){ const d=el('span','cc'); d.style.setProperty('--cc', p.unit_color); d.style.cssText+=';display:inline-block;width:12px;height:12px;margin-right:8px;background:var(--ccl)'; u.appendChild(d); }
    u.appendChild(document.createTextNode(p.unit)); pc.appendChild(u); }
  const tiles = el('div','tiles6');
  tiles.appendChild(tile('Deployments', fmt(p.deployments), fmt(p.missions)+' missions'));
  tiles.appendChild(tile('Kills', fmt(p.kills), p.kills_per_mission+' per mission'));
  tiles.appendChild(tile('Casualties', fmt(p.deaths), 'K/D '+(p.kd==null?'-':p.kd.toFixed(2))));
  tiles.appendChild(tile('Accuracy', p.accuracy==null?'-':p.accuracy.toFixed(1)+'%', fmt(p.shots)+' shots fired'));
  tiles.appendChild(tile('Never died', fmt(p.deathless), 'of '+fmt(p.missions)+' missions'));
  tiles.appendChild(tile('Stratagems', fmt(p.stratagems), fmt(p.reinforcing)+' reinforcements'));
  pc.appendChild(tiles);
  pc.appendChild(profileCard(p));

  const grid = el('div','grid'); grid.style.marginTop='12px';
  // squadmates
  const m = card('Deploys most with', 'Share of '+p.name+"'s deployments");
  if(!p.mates.length) m.appendChild(el('p','muted','No squadmates logged yet.'));
  p.mates.forEach(x => { const r=el('div','mate'); const a=el('a',null,x.name); a.href='#'+encodeURIComponent(x.name);
    a.onclick=e=>{e.preventDefault(); show(x.key,true); window.scrollTo({top:0});};
    r.appendChild(a); r.appendChild(el('div','g', x.pct+'% · '+x.games+' deployment'+(x.games>1?'s':'')+' together'));
    const b=el('div','bar'); const i=el('i'); i.style.width=Math.min(100,x.pct)+'%'; b.appendChild(i); r.appendChild(b); m.appendChild(r); });
  grid.appendChild(m);
  // fronts
  const f = card('Fronts', 'Deployments per front');
  const tot = p.fronts.reduce((a,x)=>a+x.deployments,0) || 1;
  const bar = el('div','fbar'); p.fronts.forEach(x=>{ const s=el('span','f-'+x.front.toLowerCase()); s.style.width=(100*x.deployments/tot)+'%'; s.title=x.front; bar.appendChild(s); });
  f.appendChild(bar);
  const lg = el('div','legend'); p.fronts.forEach(x=>{ const d=el('div'); d.appendChild(el('span','sw f-'+x.front.toLowerCase()));
    d.appendChild(el('span',null,x.front)); d.appendChild(el('span','v', x.deployments+' deployment'+(x.deployments>1?'s':'')+' · '+fmt(x.kills)+' kills')); lg.appendChild(d); });
  f.appendChild(lg); grid.appendChild(f);
  // best moments
  const b = card('Best moments', 'Personal records in a single mission');
  if(!p.moments.length) b.appendChild(el('p','muted','Nothing yet.'));
  p.moments.forEach(x=>{ const r=el('div','mom'); const l=el('div'); l.appendChild(el('div',null,x.label));
    l.appendChild(el('div','muted',x.op+' · mission '+x.mission+(x.date?' · '+x.date:''))); r.appendChild(l);
    const v=el('div'); v.appendChild(el('b',null,fmt(x.value))); v.appendChild(document.createTextNode(' '+x.unit)); r.appendChild(v); b.appendChild(r); });
  grid.appendChild(b);
  // career totals
  const t = card('Career totals', 'Every logged mission');
  const facts = el('div','facts');
  [['Samples extracted',p.samples],['Stims used',p.stims],['Melee kills',p.melee],['Friendly fire damage',p.ff],['Accidental team kills',p.accidentals]]
    .forEach(([k,v])=>{ const d=el('div','fact'); d.appendChild(el('b',null,fmt(v))); d.appendChild(el('span','muted',k)); facts.appendChild(d); });
  t.appendChild(facts); grid.appendChild(t);
  pc.appendChild(grid);

  pc.appendChild(el('h2',null,'Recent deployments'));
  const tw = el('div','tw'); const tb = el('table'); const th = el('thead'); const tr = el('tr');
  ['Date','Operation','Planet','Front','Diff.','Missions','Kills','Casualties'].forEach((h,i)=>{ const x=el('th',i>3?'num':null,h); tr.appendChild(x); });
  th.appendChild(tr); tb.appendChild(th); const body = el('tbody');
  p.recent.forEach(r=>{ const row=el('tr'); row.appendChild(el('td',null,r.date)); row.appendChild(el('td',null,r.op)); row.appendChild(el('td',null,r.planet));
    const fc=el('td'); fc.appendChild(el('span','sw f-'+String(r.front).toLowerCase())); fc.appendChild(document.createTextNode(r.front)); row.appendChild(fc);
    [r.diff,r.missions,r.kills,r.deaths].forEach(v=>row.appendChild(el('td','num',v==null?'-':fmt(v)))); body.appendChild(row); });
  tb.appendChild(body); tw.appendChild(tb); pc.appendChild(tw);
  if(p.deployments>p.recent.length) pc.appendChild(el('p','muted','Showing the last '+p.recent.length+' of '+p.deployments+' deployments.'));
  root.appendChild(pc);
}
document.getElementById('f').onsubmit = e => { e.preventDefault(); const p=find(document.getElementById('q').value); show(p?p.key:null, true); };
document.getElementById('q').addEventListener('change', e => { const p=P.find(x=>norm(x.name)===norm(e.target.value)); if(p) show(p.key,true); });
function fromHash(){ const h=decodeURIComponent(location.hash.slice(1)); if(h){ const p=find(h); show(p?p.key:null,false); } }
window.addEventListener('hashchange', fromHash); fromHash();
</script>
</body></html>
"""

if __name__ == "__main__":
    main()
