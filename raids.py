"""
raids.py - BETA: regiment / company / platoon raids.

You declare a raid (browser panel -> Raids, saved in raids.csv): name, unit, planet, start and end in UTC.
The deployments are then found automatically:
  * inside the time window (UTC, shown in Paris time on the pages)
  * regiment raid: any host - company / platoon raid: the HOST was in that unit on that day
  * on the raid planet (if one is set) - deployments elsewhere are listed but not ticked
  * deployments tagged "Raid" in the Google Form are ticked even if the planet differs
You can tick / untick any deployment in the panel (saved as include / exclude). Players in the squads who
are not in the unit count as guests. Raid deployments still count in all the normal stats.
"""
from __future__ import annotations

import csv
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
RAIDS = HERE / "raids.csv"
FIELDS = ["id", "name", "level", "unit", "start_utc", "end_utc", "planet", "include", "exclude", "notes"]
LOCAL_TZ = "Europe/Paris"
RECENT_DAYS = 7
YES = re.compile(r"^\s*(y|yes|oui|true|1|x|raid)\b", re.I)


# ---------------------------------------------------------------- the raid list
def load() -> list[dict]:
    if not RAIDS.exists():
        return []
    with open(RAIDS, encoding="utf-8-sig", newline="") as f:
        return [{k: (r.get(k) or "").strip() for k in FIELDS} for r in csv.DictReader(f)]


def save(raids: list[dict]):
    with open(RAIDS, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS)
        w.writeheader()
        for r in raids:
            w.writerow({k: str(r.get(k, "") or "").strip() for k in FIELDS})


def split(s: str) -> set:
    return {x for x in str(s or "").split(";") if x}


def to_local(utc: str):
    """'2026-11-14T20:00' (UTC) -> naive Paris time (the deployment dates are stored that way)."""
    if not utc:
        return None
    try:
        from zoneinfo import ZoneInfo
        t = datetime.fromisoformat(utc.replace(" ", "T")[:16]).replace(tzinfo=timezone.utc)
        return pd.Timestamp(t.astimezone(ZoneInfo(LOCAL_TZ)).replace(tzinfo=None))
    except Exception:  # noqa: BLE001
        return None


def to_utc(local) -> str:
    """naive Paris time -> 'YYYY-MM-DDTHH:MM' UTC."""
    try:
        from zoneinfo import ZoneInfo
        t = pd.Timestamp(local).to_pydatetime().replace(tzinfo=ZoneInfo(LOCAL_TZ)).astimezone(timezone.utc)
        return t.strftime("%Y-%m-%dT%H:%M")
    except Exception:  # noqa: BLE001
        return ""


def unit_options(units) -> list[dict]:
    """Dropdown: Regiment, then each company and its platoons (in the order of the roster sheet)."""
    import roster
    opts = [dict(value="regiment|", label="Regiment")]
    if not units:
        return opts
    cur = units.current()
    for comp in sorted({m["company"] for m in cur if m["company"]}, key=lambda c: roster.sheet_pos(c)):
        opts.append(dict(value=f"company|{comp}", label=comp))
        for pl in sorted({m["platoon"] for m in cur if m["company"] == comp and m["platoon"]},
                         key=lambda p: roster.sheet_pos(comp, p)):
            opts.append(dict(value=f"platoon|{comp} / {pl}", label=f"{comp} · {pl}"))
    return opts


def in_unit(u: dict | None, level: str, unit: str) -> bool:
    if level == "regiment":
        return u is not None
    if not u:
        return False
    if level == "company":
        return u.get("company") == unit
    comp, _, pl = unit.partition(" / ")
    return u.get("company") == comp and u.get("platoon") == pl


def unit_label(level: str, unit: str) -> str:
    if level == "regiment":
        return "Regiment raid"
    if level == "company":
        return f"{unit} raid"
    comp, _, pl = unit.partition(" / ")
    return f"{pl} raid · {comp}"


# ---------------------------------------------------------------- data
def load_history():
    import history
    import make_report as M
    rows = history.report_rows()
    if rows is None or not len(rows):
        return None, None
    df = M.load_df(rows)
    return df, M.deployments(df)


def dep_rows(df: pd.DataFrame, dep: pd.DataFrame) -> list[dict]:
    """One line per deployment: uid, date, planet, host, team, raid tag."""
    first = df.drop_duplicates("deployment").set_index("deployment")
    raid_col = "raid" in df.columns
    out = []
    for _, r in dep.iterrows():
        d = r["deployment"]
        f = first.loc[d] if d in first.index else None
        team = [x.strip() for x in str(r["squad"]).split(",") if x.strip()]
        tag = bool(raid_col and f is not None and YES.match(str(f.get("raid", "") or "")))
        op = r["operation"] if isinstance(r["operation"], str) and r["operation"] not in ("", "nan") else d
        out.append(dict(uid=str(f["uid"]) if f is not None and "uid" in first.columns else d, deployment=d,
                        date=r["date"] if pd.notna(r["date"]) else None, op=str(op),
                        planet=str(r["planet"]) if isinstance(r["planet"], str) and r["planet"] != "nan" else "",
                        host=team[0] if team else "", team=team, tagged=tag))
    return out


def candidates(raid: dict, rows: list[dict], units) -> list[dict]:
    """Deployments in the raid window, with the default tick and the reasons."""
    a, b = to_local(raid.get("start_utc", "")), to_local(raid.get("end_utc", ""))
    if a is None or b is None:
        return []
    inc, exc = split(raid.get("include")), split(raid.get("exclude"))
    level, unit, planet = raid.get("level", "regiment"), raid.get("unit", ""), raid.get("planet", "").lower()
    out = []
    for r in rows:
        if r["date"] is None or not (a <= r["date"] <= b):
            if r["uid"] not in inc:
                continue
        hu = units.unit_at(r["host"], r["date"]) if units else None
        host_ok = level == "regiment" or in_unit(hu, level, unit)
        planet_ok = not planet or r["planet"].lower() == planet
        default = host_ok and (planet_ok or r["tagged"])
        ticked = (default or r["uid"] in inc) and r["uid"] not in exc
        why = [] if default else (["host not in " + (unit or "the unit")] if not host_ok else []) + \
            (["other planet"] if not planet_ok else [])
        out.append(dict(uid=r["uid"], deployment=r["deployment"], op=r["op"], planet=r["planet"], host=r["host"],
                        team=", ".join(r["team"]), tagged=r["tagged"], default=default, ticked=ticked,
                        date=r["date"].strftime("%d %b %Y %H:%M") if r["date"] is not None else "",
                        why=", ".join(why)))
    return out


def overrides(raid: dict, rows: list[dict], units, ticked: set) -> dict:
    """The panel sends the ticked uids -> store only the differences from the default."""
    cand = candidates(dict(raid, include="", exclude=""), rows, units)
    default = {c["uid"] for c in cand if c["default"]}
    raid = dict(raid)
    raid["include"] = ";".join(sorted(ticked - default))
    raid["exclude"] = ";".join(sorted(default - ticked))
    return raid


def untagged(raids: list[dict], rows: list[dict], units) -> list[dict]:
    """Deployments tagged 'Raid' in the form that are in no declared raid."""
    used = set()
    for rd in raids:
        used |= {c["uid"] for c in candidates(rd, rows, units) if c["ticked"]}
    return [dict(uid=r["uid"], op=r["op"], planet=r["planet"], host=r["host"], team=", ".join(r["team"]),
                 date=r["date"].strftime("%d %b %Y %H:%M") if r["date"] is not None else "",
                 date_utc=to_utc(r["date"]) if r["date"] is not None else "")
            for r in rows if r["tagged"] and r["uid"] not in used]


# ---------------------------------------------------------------- the raid page data
def unit_size(units, level, unit, date) -> int:
    if not units:
        return 0
    return sum(1 for hist in units.by_key.values() if in_unit(units.unit_at(hist[0]["callsign"], date), level, unit))


def raid_data(raid: dict, df: pd.DataFrame, rows: list[dict], units) -> dict | None:
    ticked = [c for c in candidates(raid, rows, units) if c["ticked"]]
    if not ticked:
        return None
    deps = {c["deployment"] for c in ticked}
    g = df[df["deployment"].isin(deps)]
    level, unit = raid.get("level", "regiment"), raid.get("unit", "")
    a, b = to_local(raid["start_utc"]), to_local(raid["end_utc"])
    people = g.drop_duplicates("player_key")
    members, guests = [], []
    for _, p in people.iterrows():
        u = units.unit_at(p["player"], p["date"]) if units else None
        (members if in_unit(u, level, unit) else guests).append(p["player"])
    size = unit_size(units, level, unit, a)
    k, d = int(g["kills"].sum()), int(g["deaths"].sum())
    succ = [str(s).strip().lower() for s in g.drop_duplicates("deployment")["success"].astype(object).fillna("")]
    known = [s for s in succ if s in ("yes", "no", "oui", "non", "true", "false")]
    rec = []
    ops = {c["deployment"]: c["op"] for c in ticked}

    def best(col, title, sub, unit_, data=None):
        x = g if data is None else data
        if len(x) and x[col].max() > 0:
            r = x.loc[x[col].idxmax()]
            rec.append(dict(title=title, sub=sub, value=f"{int(r[col]):,}", unit=unit_, player=str(r["player"]),
                            where=f'{ops.get(r["deployment"], r["deployment"])} - mission {int(r["mission"])}'))
    best("kills", "Top gun", "Most kills in a mission", "kills")
    best("kills", "Untouchable", "Most kills without dying", "kills", g[g["deaths"] == 0])
    best("stratagems_used", "Stratagem hero", "Most stratagems in a mission", "stratagems")
    best("melee_kills", "Melee maniac", "Most melee kills in a mission", "melee kills")
    squads = []
    for c in ticked:
        s = g[g["deployment"] == c["deployment"]]
        sk, sd = int(s["kills"].sum()), int(s["deaths"].sum())
        squads.append(dict(op=c["op"], date=c["date"], planet=c["planet"], host=c["host"], team=c["team"],
                           missions=int(s["mission"].nunique()), kills=sk, deaths=sd,
                           kd=round(sk / sd, 2) if sd else None,
                           success=str(s["success"].iloc[0]) if len(s) and str(s["success"].iloc[0]) != "nan" else ""))
    if len(squads) > 1:
        top = max(squads, key=lambda s: s["kills"])
        rec.append(dict(title="Deadliest squad", sub="Most kills in one deployment", value=f'{top["kills"]:,}',
                        unit="kills", player=top["team"], where=top["op"]))
    return dict(id=raid["id"], name=raid["name"] or "Raid", level=level, unit=unit, label=unit_label(level, unit),
                planet=raid.get("planet", ""), notes=raid.get("notes", ""),
                start=a.strftime("%d %b %Y %H:%M"), end=b.strftime("%d %b %Y %H:%M") if b.date() != a.date()
                else b.strftime("%H:%M"), ts=a.isoformat(), end_ts=b.isoformat(),
                squads_n=len(squads), helldivers=len(people), members=len(members), guests=sorted(guests),
                size=size, turnout=round(100 * len(members) / size) if size else None,
                kills=k, deaths=d, kd=round(k / d, 2) if d else None, samples=int(g["samples_extracted"].sum()),
                stratagems=int(g["stratagems_used"].sum()),
                success=sum(1 for s in known if s in ("yes", "oui", "true")), success_known=len(known),
                records=rec, squads=sorted(squads, key=lambda s: s["date"]))


def build(df: pd.DataFrame, dep: pd.DataFrame, units, now: datetime | None = None) -> dict:
    now = now or datetime.now()
    rows = dep_rows(df, dep)
    out = [r for r in (raid_data(rd, df, rows, units) for rd in load()) if r]
    out.sort(key=lambda r: r["ts"], reverse=True)
    # records against earlier raids of the same level
    for r in out:
        same = [x for x in out if x["level"] == r["level"] and x["ts"] < r["ts"]]
        badges = []
        if same:
            for key, txt in (("kills", "Most kills of any {lvl} raid"), ("helldivers", "Biggest {lvl} raid yet"),
                             ("turnout", "Best turnout of any {lvl} raid")):
                if r[key] is not None and all((x[key] or 0) < r[key] for x in same):
                    badges.append(txt.format(lvl=r["level"]))
        r["badges"] = badges
    cut = (now - timedelta(days=RECENT_DAYS)).isoformat()
    return dict(raids=out, recent=[r for r in out if r["end_ts"] >= cut and r["ts"] <= now.isoformat()],
                generated=now.strftime("%d %b %Y %H:%M"))


# ---------------------------------------------------------------- HTML
PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Raids - {{TITLE}}</title>
<style>{{STYLE}}
.raid{margin-top:30px}
.rh{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}
.rh h3{margin:0;font-size:clamp(22px,3.4vw,30px);font-weight:800}
.rlab{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;background:var(--accent);color:var(--accent-ink);padding:2px 8px}
.rmeta{color:var(--muted);font-size:14px;margin-top:4px}
.badges{display:flex;flex-wrap:wrap;gap:6px;margin-top:8px}
.badges span{border:1px solid var(--accent);color:var(--text);font-size:12.5px;font-weight:700;padding:3px 9px}
.tiles6{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:12px}
@media (max-width:820px){.tiles6{grid-template-columns:repeat(2,1fr)}}
.raid .hls{margin-top:12px}
table.sq td:nth-child(3){white-space:normal;min-width:200px}
.guests{color:var(--muted);font-size:13px;margin-top:8px}
.raid .hw,.raid .hp{overflow-wrap:anywhere}
</style></head>
<body>
<header><div class="wrap"><h1>Raids</h1><div class="period">{{TITLE}}</div></div></header>
<nav class="wrap topnav"><a class="navlink" href="index.html" style="margin-right:8px">&larr; Regiment report</a><a class="navlink" href="units.html" style="margin-right:8px">Companies &amp; squads</a><a class="navlink" href="players.html">Player lookup &rarr;</a></nav>
<main class="wrap">
<p class="muted" id="intro"></p>
<div id="root"></div>
<footer id="foot"></footer>
</main>
<script>
const D = {{DATA}};
const fmt = v => v == null ? '-' : Number(v).toLocaleString('en-US');
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e; }
function tile(a,b,c){ const t=el('div','tile'); t.append(el('div','tl',a), el('div','tv',b)); if(c) t.append(el('div','ts',c)); return t; }
document.getElementById('intro').textContent = D.raids.length
  ? 'Grand occasions: a unit deploys together on the same planet. Times in Paris time. Squadmates from outside the unit count as guests.'
  : 'No raid yet.';
const root = document.getElementById('root');
D.raids.forEach(r=>{
  const s = el('section','raid'); s.id = 'raid-'+r.id;
  const h = el('div','rh'); h.append(el('span','rlab', r.label), el('h3',null,r.name)); s.append(h);
  s.append(el('div','rmeta', [r.start+(r.end?' - '+r.end:''), r.planet, r.notes].filter(Boolean).join(' · ')));
  if(r.badges.length){ const b=el('div','badges'); r.badges.forEach(x=>b.append(el('span',null,'★ '+x))); s.append(b); }
  const t = el('div','tiles6');
  t.append(tile('Squads', fmt(r.squads_n), 'deployed'),
           tile('Helldivers', fmt(r.helldivers), r.guests.length ? r.guests.length+' guest'+(r.guests.length>1?'s':'') : 'no guests'),
           tile('Turnout', r.turnout==null ? '-' : r.turnout+'%', r.size ? r.members+' of '+r.size+' members' : 'members of the unit'),
           tile('Kills', fmt(r.kills), 'K/D '+(r.kd==null?'-':r.kd.toFixed(2))),
           tile('Casualties', fmt(r.deaths), 'Helldivers fallen'),
           tile('Samples', fmt(r.samples), 'extracted'),
           tile('Stratagems', fmt(r.stratagems), 'called in'),
           tile('Operations', r.success_known ? r.success+'/'+r.success_known : '-', 'completed'));
  s.append(t);
  if(r.records.length){ const g=el('div','hls'); r.records.forEach(x=>{ const c=el('div','hl'); const b=el('div','hb');
      b.append(el('div','ht',x.title), el('div','hs',x.sub)); const v=el('div','hv'); v.append(el('b',null,x.value), document.createTextNode(' '+x.unit)); b.append(v);
      b.append(el('div','hp',x.player), el('div','hw',x.where)); c.append(b); g.append(c); }); s.append(g); }
  const tw = el('div','tw'); tw.style.marginTop='12px'; const tb = el('table','sq'); const th=el('thead'); const tr=el('tr');
  ['Start','Operation','Squad (host first)','Planet','Missions','Kills','Casualties','K/D'].forEach((x,i)=>tr.append(el('th', i>3?'num':null, x)));
  th.append(tr); tb.append(th); const body=el('tbody');
  r.squads.forEach(q=>{ const row=el('tr'); [q.date.slice(-5), q.op, q.team, q.planet].forEach(v=>row.append(el('td',null,v)));
    [q.missions,q.kills,q.deaths].forEach(v=>row.append(el('td','num',fmt(v)))); row.append(el('td','num', q.kd==null?'-':q.kd.toFixed(2))); body.append(row); });
  tb.append(body); tw.append(tb); s.append(tw);
  if(r.guests.length) s.append(el('div','guests','Guests: '+r.guests.join(', ')));
  root.append(s);
});
document.getElementById('foot').textContent = 'Generated '+D.generated+' by the 505th Stat Department.';
</script>
</body></html>
"""

BANNER_CSS = """<style>
.raidnow{margin-top:22px;border:2px solid var(--accent);background:var(--surface);padding:14px 16px;display:flex;flex-wrap:wrap;gap:8px 18px;align-items:center}
.raidnow .rlab{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.1em;text-transform:uppercase;background:var(--accent);color:var(--accent-ink);padding:2px 8px}
.raidnow b{font-size:20px}.raidnow .m{color:var(--muted);font-size:13.5px}
.raidnow a{margin-left:auto;color:var(--text);font-weight:700}
</style>"""


def banner(data: dict, href: str) -> str:
    import html as H
    out = []
    for r in data["recent"][:2]:
        bits = [f'{r["squads_n"]} squads', f'{r["helldivers"]} Helldivers', f'{r["kills"]:,} kills']
        if r["turnout"] is not None:
            bits.append(f'{r["turnout"]}% turnout')
        out.append(f'<div class="raidnow"><span class="rlab">{H.escape(r["label"])}</span><div><b>{H.escape(r["name"])}</b>'
                   f'<div class="m">{H.escape(r["start"])} · {H.escape(r["planet"])} · {" · ".join(bits)}</div></div>'
                   f'<a href="{href}#raid-{H.escape(r["id"])}">See the raid &rarr;</a></div>')
    return "".join(out)


def page(data: dict, title: str, style: str) -> str:
    import html as H
    import json
    return PAGE.replace("{{STYLE}}", style).replace("{{TITLE}}", H.escape(title)) \
        .replace("{{DATA}}", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


# ---------------------------------------------------------------- browser panel (Raids tab)
_CACHE: dict = {}


def _data():
    """History + roster, re-read only when the files change."""
    import roster
    f1, f2 = HERE / "history" / "stats.csv", roster.LOG
    key = tuple(p.stat().st_mtime if p.exists() else 0 for p in (f1, f2, HERE / "history" / "deployments.csv"))
    if _CACHE.get("key") != key:
        df, dep = load_history()
        units = roster.Units()
        _CACHE.update(key=key, rows=dep_rows(df, dep) if df is not None else [], units=units)
    return _CACHE["rows"], _CACHE["units"]


def planets(rows=()) -> list[str]:
    f = HERE / "google_apps_script" / "planets_for_dropdown.txt"
    names = [l.strip() for l in f.read_text(encoding="utf-8").splitlines() if l.strip()] if f.exists() else []
    seen = {n.lower() for n in names}
    names += sorted({r["planet"] for r in rows if r["planet"] and r["planet"].lower() not in seen})
    return sorted(names, key=str.lower)


def clean(raid: dict, units) -> dict:
    """Check what the panel sent (it only comes from this PC, but keep the file tidy)."""
    level = str(raid.get("level", "regiment")).strip().lower()
    unit = str(raid.get("unit", "")).strip()
    if level not in ("regiment", "company", "platoon"):
        raise ValueError("Unknown unit level.")
    if level != "regiment" and f"{level}|{unit}" not in {o["value"] for o in unit_options(units)}:
        raise ValueError(f"'{unit}' is not on the roster.")
    out = dict(id=re.sub(r"[^A-Za-z0-9]", "", str(raid.get("id", "")))[:20],
               name=" ".join(str(raid.get("name", "")).split())[:80] or "Raid", level=level,
               unit="" if level == "regiment" else unit, planet=" ".join(str(raid.get("planet", "")).split())[:60],
               notes=" ".join(str(raid.get("notes", "")).split())[:200])
    for k in ("start_utc", "end_utc"):
        v = str(raid.get(k, "")).strip()[:16]
        try:
            datetime.fromisoformat(v)
        except ValueError:
            raise ValueError("Start and end need a date and a time (UTC).")
        out[k] = v
    if out["end_utc"] <= out["start_utc"]:
        raise ValueError("The end must be after the start.")
    return out


def panel_state() -> dict:
    rows, units = _data()
    lst = []
    for rd in load():
        c = candidates(rd, rows, units)
        a = to_local(rd["start_utc"])
        lst.append(dict(rd, label=unit_label(rd["level"], rd["unit"]), squads=sum(1 for x in c if x["ticked"]),
                        start_local=a.strftime("%d %b %Y %H:%M") if a is not None else ""))
    lst.sort(key=lambda r: r["start_utc"], reverse=True)
    return dict(raids=lst, units=unit_options(units), planets=planets(rows), untagged=untagged(load(), rows, units),
                has_history=bool(rows))


def preview(raid: dict) -> list[dict]:
    rows, units = _data()
    return candidates(clean(raid, units) | {"include": raid.get("include", ""), "exclude": raid.get("exclude", "")},
                      rows, units)


def save_one(raid: dict, ticked: list[str]) -> dict:
    rows, units = _data()
    r = clean(raid, units)
    raids = load()
    if not r["id"]:
        n = 1 + max([int(x["id"][1:]) for x in raids if re.fullmatch(r"r\d+", x["id"])] or [0])
        r["id"] = f"r{n}"
    r = overrides(r, rows, units, {str(t) for t in ticked})
    raids = [x for x in raids if x["id"] != r["id"]] + [r]
    save(sorted(raids, key=lambda x: x["start_utc"]))
    return r


def delete(raid_id: str):
    save([x for x in load() if x["id"] != raid_id])
