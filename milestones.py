"""
milestones.py - BETA: regiment, company and player milestones (targets in milestones.csv).

Everything is worked out again from the history on every run, so a milestone always has the real date and
deployment where the total crossed the target, even for deployments logged long ago. The only exception is
"every member of a squad registered": the roster changes, so once reached it is remembered in
history/milestones_reached.csv.

Reported numbers only (sending stats is optional): totals are "logged" totals.
"""
from __future__ import annotations

import csv
import html
import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
SPEC = HERE / "milestones.csv"
KEPT = HERE / "history" / "milestones_reached.csv"
FRONTS = ["Terminids", "Automatons", "Illuminates"]
RECENT_DAYS = 7          # "just reached": shown at the top of the report for this many days
CLOSE = 0.8              # "almost there": at least 80% of the next target
SUMS = {"kills": "kills", "casualties": "deaths", "samples": "samples_extracted", "accidentals": "accidentals",
        "stims": "stims_used"}
DEFAULT_TITLES = {"kills": "{n} {faction} kills", "operations": "{n} {faction} operations",
                  "planets": "{n} different planets", "casualties": "{n} {faction} casualties",
                  "samples": "{n} samples", "deployments_month": "{n} deployments in one month",
                  "participants": "{n} Helldivers registered", "squad_full": "{squad}: every member registered",
                  "accidentals": "{n} accidental team kills", "stims": "{n} stims used"}


# ---------------------------------------------------------------- targets
def load_spec(path: Path = SPEC) -> list[dict]:
    if not path.exists():
        return []
    lines = [l for l in path.read_text(encoding="utf-8-sig").splitlines() if l.strip() and not l.lstrip().startswith("#")]
    tracks = []
    for r in csv.DictReader(lines):
        r = {(k or "").strip().lower(): (v or "").strip() for k, v in r.items()}
        stat = r.get("stat", "").lower()
        if stat not in DEFAULT_TITLES or r.get("level", "").lower() not in ("regiment", "company", "player"):
            continue
        steps = sorted({int(float(s)) for s in re.split(r"[;,\s]+", r.get("steps", "")) if s.strip()
                        and re.fullmatch(r"\d+(\.\d+)?", s.strip())})
        if not steps and stat != "squad_full":
            continue
        fac = r.get("faction", "")
        facs = FRONTS if fac.lower() == "each" else [next((f for f in FRONTS if f.lower().startswith(fac.lower()[:5])), fac)
                                                     if fac else ""]
        for f in facs:
            tracks.append(dict(level=r["level"].lower(), stat=stat, faction=f, steps=steps,
                               title=r.get("title") or DEFAULT_TITLES[stat]))
    return tracks


def title_of(t: dict, n: int, **extra) -> str:
    s = t["title"].replace("{n}", f"{n:,}").replace("{faction}", t["faction"] or "")
    for k, v in extra.items():
        s = s.replace("{" + k + "}", v)
    return " ".join(s.split())


# ---------------------------------------------------------------- per deployment
def dep_table(rows: pd.DataFrame, dinfo: pd.DataFrame) -> list[dict]:
    """The owner's deployments in date order, with the owner's sums."""
    out = []
    for d, g in rows.groupby("deployment", sort=False):
        if d not in dinfo.index:
            continue
        i = dinfo.loc[d]
        date = i["date"] if pd.notna(i["date"]) else None
        out.append(dict(dep=d, date=date, front=str(i["front"]), planet=str(i["planet"] or "").strip(),
                        team=str(i["squad"]), where=where_of(i, d), players=set(g["player_key"]),
                        **{k: int(g[c].sum()) for k, c in SUMS.items()}))
    out.sort(key=lambda x: (x["date"] is None, x["date"] or pd.Timestamp.min, x["dep"]))
    return out


def where_of(i, d) -> str:
    op = i["operation"] if isinstance(i["operation"], str) and i["operation"] not in ("", "nan") else d
    pl = i["planet"] if isinstance(i["planet"], str) and i["planet"] not in ("", "nan") else ""
    return f"{op} on {pl}" if pl else str(op)


def event(level, owner, t, n, d, extra="") -> dict:
    date = d["date"] if d else None
    return dict(level=level, owner=owner, stat=t["stat"], faction=t["faction"], n=n,
                title=title_of(t, n) + (f" ({extra})" if extra else ""),
                date=date.strftime("%d %b %Y") if date is not None else "", ts=date.isoformat() if date is not None else "",
                where=d["where"] if d else "", team=d["team"] if d else "", dep=d["dep"] if d else "")


def run_track(level, owner, t, deps, now) -> tuple[list[dict], dict | None]:
    """-> (reached events, 'almost there' entry or None)."""
    ds = [d for d in deps if not t["faction"] or d["front"] == t["faction"]]
    steps, reached, k = t["steps"], [], 0
    value, seen, months = 0, set(), {}
    for d in ds:
        if t["stat"] in SUMS:
            value += d[t["stat"]]
        elif t["stat"] == "operations":
            value += 1
        elif t["stat"] == "planets":
            if d["planet"] and d["planet"].lower() != "nan":
                seen.add(d["planet"].lower())
            value = len(seen)
        elif t["stat"] == "participants":
            seen |= d["players"]
            value = len(seen)
        elif t["stat"] == "deployments_month":
            if d["date"] is None:
                continue
            m = d["date"].strftime("%Y-%m")
            months[m] = months.get(m, 0) + 1
            value = months[m]
        while k < len(steps) and value >= steps[k]:
            extra = d["date"].strftime("%B %Y") if t["stat"] == "deployments_month" else ""
            reached.append(event(level, owner, t, steps[k], d, extra))
            k += 1
    close = None
    if k < len(steps):
        cur = months.get(now.strftime("%Y-%m"), 0) if t["stat"] == "deployments_month" else value
        if cur >= CLOSE * steps[k]:
            close = dict(level=level, owner=owner, title=title_of(t, steps[k]), value=cur, target=steps[k],
                         pct=round(100 * cur / steps[k]))
    return reached, close


# ---------------------------------------------------------------- squads: every member registered
def read_kept() -> list[dict]:
    if not KEPT.exists():
        return []
    with open(KEPT, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def squad_full(t, a: pd.DataFrame, dinfo, units, now) -> tuple[list[dict], list[dict]]:
    import roster
    kept = {(r["owner"], r["squad"]): r for r in read_kept()}
    first = a.sort_values("date", na_position="last").drop_duplicates("player_key").set_index("player_key")
    reached, close, new = [], [], []
    squads: dict = {}
    for m in units.current():
        if m.get("squad"):
            squads.setdefault((m["company"], m["squad"]), []).append(roster.key(m["callsign"]))
    for (comp, sq), keys in squads.items():
        k = (comp, sq)
        if k in kept:
            r = kept[k]
            reached.append(dict(level="company", owner=comp, stat="squad_full", faction="", n=len(keys),
                                title=title_of(t, 0, squad=sq), date=r["date"], ts=r["ts"], where=r["where"],
                                team=r["team"], dep=r["dep"]))
            continue
        reg = [x for x in keys if x in first.index]
        if keys and len(reg) == len(keys):
            last = first.loc[reg].sort_values("date", na_position="first").iloc[-1]
            d = last["deployment"]
            info = dict(date=last["date"] if pd.notna(last["date"]) else None,
                        where=where_of(dinfo.loc[d], d) if d in dinfo.index else d,
                        team=str(dinfo.loc[d]["squad"]) if d in dinfo.index else "", dep=d)
            e = event("company", comp, t, len(keys), info)
            e["title"] = title_of(t, 0, squad=sq)
            reached.append(e)
            new.append(dict(owner=comp, squad=sq, date=e["date"], ts=e["ts"], where=e["where"], team=e["team"], dep=d))
        elif keys and len(reg) >= CLOSE * len(keys):
            close.append(dict(level="company", owner=comp, title=title_of(t, 0, squad=sq), value=len(reg),
                              target=len(keys), pct=round(100 * len(reg) / len(keys))))
    if new:
        KEPT.parent.mkdir(exist_ok=True)
        fresh = not KEPT.exists()
        with open(KEPT, "a", encoding="utf-8-sig" if fresh else "utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=["owner", "squad", "date", "ts", "where", "team", "dep"])
            if fresh:
                w.writeheader()
            w.writerows(new)
    return reached, close


# ---------------------------------------------------------------- everything
def compute(df: pd.DataFrame, dep: pd.DataFrame, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    tracks = load_spec()
    dinfo = dep.set_index("deployment")
    out = dict(events=[], close=[], players={})
    # regiment
    deps = dep_table(df, dinfo)
    for t in [t for t in tracks if t["level"] == "regiment"]:
        r, c = run_track("regiment", "Regiment", t, deps, now)
        out["events"] += r
        out["close"] += [c] if c else []
    # companies (unit of each player on the day of the deployment)
    try:
        import roster
        import units as U
        un = roster.Units()
    except Exception:  # noqa: BLE001
        un = None
    if un:
        a = U.assign(df, un)
        for comp in sorted({m["company"] for m in un.current()}, key=lambda c: roster.sheet_pos(c)):
            rows = a[a["company"] == comp]
            cdeps = dep_table(rows, dinfo) if len(rows) else []
            for t in [t for t in tracks if t["level"] == "company"]:
                if t["stat"] == "squad_full":
                    continue
                r, c = run_track("company", comp, t, cdeps, now)
                out["events"] += r
                out["close"] += [c] if c else []
        for t in [t for t in tracks if t["level"] == "company" and t["stat"] == "squad_full"][:1]:
            r, c = squad_full(t, df, dinfo, un, now)
            out["events"] += r
            out["close"] += c
    # players
    ptracks = [t for t in tracks if t["level"] == "player"]
    for key, rows in df.groupby("player_key"):
        if not key:
            continue
        pdeps = dep_table(rows, dinfo)
        best, close = {}, []
        n_all = 0
        for t in ptracks:
            r, c = run_track("player", key, t, pdeps, now)
            n_all += len(r)
            if r:
                best[(t["stat"], t["faction"])] = r[-1]          # highest step reached on this track
            if c:
                close.append(c)
        reached = sorted(best.values(), key=lambda e: e["ts"] or "0", reverse=True)
        out["players"][key] = dict(
            reached=[dict(title=e["title"], date=e["date"], where=e["where"]) for e in reached],
            close=[dict(title=c["title"], value=c["value"], target=c["target"], pct=c["pct"])
                   for c in sorted(close, key=lambda c: -c["pct"])],
            total=n_all)
    out["events"].sort(key=lambda e: (e["ts"] or "0", e["level"] == "regiment"), reverse=True)
    cut = (now - timedelta(days=RECENT_DAYS)).isoformat()
    out["recent"] = [e for e in out["events"] if e["ts"] and e["ts"] >= cut]
    out["close"].sort(key=lambda c: -c["pct"])
    return out


# ---------------------------------------------------------------- HTML (report)
TROPHY = ('<svg viewBox="0 0 24 24"><path d="M8 4h8v5a4 4 0 0 1-8 0z"/><path d="M8 6H5a3 3 0 0 0 3 4"/>'
          '<path d="M16 6h3a3 3 0 0 1-3 4"/><path d="M12 13v4"/><path d="M8.5 20h7"/><path d="M10 17h4v3h-4z"/></svg>')
CSS = """<style>
.ms-new{border:2px solid var(--accent)!important;background:linear-gradient(135deg,var(--surface) 60%,color-mix(in srgb,var(--accent) 14%,var(--surface)))!important}
.ms-tag{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;background:var(--accent);color:var(--accent-ink);padding:2px 7px;margin-bottom:4px}
.ms-own{font-size:12px;letter-spacing:.08em;text-transform:uppercase;color:var(--text2)}
#msCards>[hidden]{display:none!important}
.ms-close{margin-top:12px}
.ms-row{display:grid;grid-template-columns:1fr auto;gap:2px 12px;padding:9px 0;border-bottom:1px solid var(--grid)}
.ms-row:last-child{border-bottom:0}
.ms-row .v{color:var(--text2);font-variant-numeric:tabular-nums;text-align:right}
.ms-row .bar{grid-column:1/-1;height:6px;background:var(--surface2)}.ms-row .bar i{display:block;height:100%;background:var(--accent)}
table.mlog td:nth-child(5){white-space:normal;min-width:200px}
</style>"""


FIT_JS = """<script>
(function(){ // at most 2 rows of milestone cards, whatever the screen width
  const box=document.getElementById('msCards'), more=document.getElementById('msMore'); if(!box) return;
  function fit(){ const cards=[...box.children]; cards.forEach(c=>c.hidden=false);
    const tops=[...new Set(cards.map(c=>c.offsetTop))].sort((a,b)=>a-b); let hid=0;
    if(tops.length>2){ cards.forEach(c=>{ if(c.offsetTop>tops[1]){ c.hidden=true; hid++; } }); }
    const rest=Number(more.dataset.total)-cards.length+hid;
    more.hidden=rest<=0; more.textContent=rest>0 ? '+'+rest+' more in the milestone log below' : ''; }
  fit(); let t; addEventListener('resize',()=>{ clearTimeout(t); t=setTimeout(fit,100); });
})();
</script>"""


def _esc(s) -> str:
    return html.escape(str(s or ""))


def _card(e, new=False) -> str:
    return (f'<div class="hl{" ms-new" if new else ""}"><div class="hi">{TROPHY}</div><div class="hb">'
            + ('<div class="ms-tag">Milestone reached!</div>' if new else "")
            + f'<div class="ms-own">{_esc(e["owner"])}</div><div class="ht">{_esc(e["title"])}</div>'
            f'<div class="hw">{_esc(e["where"])}{" · " + _esc(e["date"]) if e["date"] else ""}</div>'
            f'<div class="hp">{_esc(e["team"])}</div></div></div>')


def report_section(ms: dict) -> str:
    recent = ms["recent"]
    shown = (recent or ms["events"])[:16]          # the page then keeps at most 2 rows (see FIT_JS)
    parts = ['<h2>Milestones</h2>']
    if shown:
        parts.append(f'<div class="sub muted" style="margin:-4px 0 10px">'
                     f'{"Reached in the last " + str(RECENT_DAYS) + " days" if recent else "Latest milestones reached"}'
                     ' · the whole team gets the credit</div>')
        parts.append('<div class="hls" id="msCards">' + "".join(_card(e, bool(recent)) for e in shown) + '</div>')
        total = len(recent) if recent else len(ms["events"])
        parts.append(f'<p class="muted small" id="msMore" data-total="{total}" hidden></p>' + FIT_JS)
    else:
        parts.append('<p class="muted">No milestone reached yet.</p>')
    close = ms["close"][:8]
    if close:
        rows = "".join(f'<div class="ms-row"><div><span class="ms-own">{_esc(c["owner"])}</span> · {_esc(c["title"])}</div>'
                       f'<div class="v">{c["value"]:,} / {c["target"]:,}</div>'
                       f'<div class="bar"><i style="width:{min(100, c["pct"])}%"></i></div></div>' for c in close)
        parts.append(f'<div class="card ms-close"><h3>Almost there</h3><div class="sub">At least {int(CLOSE * 100)}% '
                     f'of the way to the next milestone</div>{rows}</div>')
    return "\n".join(parts) + "\n"


def log_section(ms: dict) -> str:
    ev = ms["events"]
    if not ev:
        return ""
    rows = "".join(f'<tr><td>{_esc(e["date"])}</td><td>{_esc(e["title"])}</td><td>{_esc(e["owner"])}</td>'
                   f'<td>{_esc(e["where"])}</td><td>{_esc(e["team"])}</td></tr>' for e in ev)
    return ('<h2>Milestone log</h2><details><summary>' + f'{len(ev)} milestones reached · most recent first</summary>'
            '<div class="tw"><table class="mlog"><thead><tr><th>Date</th><th>Milestone</th><th>Who</th>'
            '<th>Deployment</th><th>Team</th></tr></thead><tbody>' + rows + '</tbody></table></div></details>\n')


def patch_report(page: str, ms: dict) -> str:
    sec = report_section(ms)
    page = page.replace("</head>", CSS + "</head>", 1)
    if ms["recent"]:                                   # just reached: right at the top, before the totals
        page = page.replace('<main class="wrap">', '<main class="wrap">\n' + sec, 1)
    else:                                              # otherwise: just above the highlights
        page = page.replace("<h2>Highlights</h2>", sec + "<h2>Highlights</h2>", 1)
    return page.replace("<h2>Deployment log</h2>", log_section(ms) + "<h2>Deployment log</h2>", 1)


# ---------------------------------------------------------------- player cards
PLAYER_JS = r"""
function msCard(p){
  const m = MS[p.key]; if(!m) return null;
  const c = card('Milestones', m.reached.length ? 'Highest milestone reached on each track' : 'Personal milestones');
  c.style.marginTop = '12px';
  if(!m.reached.length && !m.close.length){ c.appendChild(el('p','muted','No milestone yet - keep deploying!')); return c; }
  if(m.reached.length){ const g=el('div','msg');
    m.reached.forEach(x=>{ const d=el('div','msb'); d.appendChild(el('b',null,x.title)); d.appendChild(el('span','muted',(x.date||'')+(x.where?' · '+x.where:''))); g.appendChild(d); });
    c.appendChild(g); }
  if(m.close.length){ c.appendChild(el('div','sub','Almost there')); m.close.forEach(x=>{ const r=el('div','mate');
    r.appendChild(el('div',null,x.title)); r.appendChild(el('div','g',fmt(x.value)+' / '+fmt(x.target)));
    const b=el('div','bar'); const i=el('i'); i.style.width=Math.min(100,x.pct)+'%'; i.style.background='var(--accent)'; b.appendChild(i); r.appendChild(b); c.appendChild(r); }); }
  return c;
}
"""
PLAYER_CSS = """<style>
.msg{display:grid;grid-template-columns:repeat(auto-fill,minmax(min(100%,230px),1fr));gap:8px;margin-bottom:6px}
.msb{background:var(--surface2);border:1px solid var(--line);border-left:4px solid var(--accent);padding:8px 10px;display:flex;flex-direction:column;gap:2px}
.msb b{font-size:14px}.msb span{font-size:12px}
</style>"""


def patch_players(page: str, ms: dict) -> str:
    data = json.dumps(ms["players"], ensure_ascii=False).replace("</", "<\\/")
    page = page.replace("</head>", PLAYER_CSS + "</head>", 1)
    page = page.replace("<script>\nconst P = ", f"<script>const MS = {data};{PLAYER_JS}</script>\n<script>\nconst P = ", 1)
    anchor = "  t.appendChild(facts); grid.appendChild(t);\n  pc.appendChild(grid);\n"
    if anchor in page:
        page = page.replace(anchor, anchor + "  { const mc = msCard(p); if(mc) pc.appendChild(mc); }\n", 1)
    return page
