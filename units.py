"""
units.py - company / platoon / squad page.

make_report.py calls build_pages() after the normal pages:
  units.html         one card per company: participation, profile vs the regiment, platoons & squads
  report.html        + a link to the unit page
  players.html       + each Helldiver's rank and unit

Fair comparisons although reporting is optional: per-mission numbers only (never totals), participation
shown as its own number, and units with fewer than MIN_MISSIONS logged missions say "not enough data".
Each player's missions count for the unit they were in on the day of the deployment (history/roster_log.csv).
"""
from __future__ import annotations

import html
import json
from datetime import datetime, timedelta

import pandas as pd

import roster

MIN_MISSIONS = 10


def assign(df: pd.DataFrame, units: "roster.Units") -> pd.DataFrame:
    """Add rank / company / platoon / detachment / squad to every player-mission row (unit on that day)."""
    df = df.copy()
    cols = {c: [] for c in ("rank", "company", "platoon", "detachment", "squad", "level")}
    for p, d in zip(df["player"], df["date"]):
        u = units.unit_at(p, d)
        for c in cols:
            cols[c].append((u or {}).get(c, "") if u else ("Guests" if c == "company" else ""))
    for c, v in cols.items():
        df[c] = v
    return df


def group_stats(rows: pd.DataFrame) -> dict:
    n = len(rows)
    if not n:
        return dict(missions=0, reporters=0)
    k, d = rows["kills"].sum(), rows["deaths"].sum()
    hit, fired = rows["shots_hit"].sum(), rows["shots_fired"].sum()
    return dict(missions=int(n), reporters=int(rows["player_key"].nunique()),
                deployments=int(rows["deployment"].nunique()),
                kpm=round(k / n, 1), kd=round(k / d, 2) if d else None,
                acc=round(100 * hit / fired, 1) if fired else None,
                deathless=round(100 * (rows["deaths"] == 0).sum() / n, 1),
                radar=[round(k / n, 2), round(100 * hit / fired, 2) if fired else None,
                       round(rows["melee_kills"].sum() / n, 2), round(d / n, 2),
                       round(100 * (rows["deaths"] == 0).sum() / n, 2), round(rows["stratagems_used"].sum() / n, 2),
                       round(rows["stims_used"].sum() / n, 2), round(rows["friendly_fire_damage"].sum() / n, 2)])


def build_units_data(df: pd.DataFrame, units: "roster.Units") -> dict:
    cur = units.current()
    recent = datetime.now() - timedelta(days=30)
    a = assign(df, units)
    a_recent = a[a["date"] >= recent] if a["date"].notna().any() else a.iloc[0:0]
    regiment = group_stats(a)

    def members_of(**flt):
        return [m for m in cur if all(m.get(k) == v for k, v in flt.items())]

    def part(members, rows, rows_recent):
        keys = {roster.key(m["callsign"]) for m in members}
        logged = set(rows["player"].map(roster.key))
        logged_recent = set(rows_recent["player"].map(roster.key))
        return dict(members=len(keys), reporting=len(keys & logged), recent=len(keys & logged_recent))

    def ranks(members):
        order = {r: i for i, r in enumerate(roster.RANK_ORDER)}
        return sorted(members, key=lambda m: (order.get(m.get("rank", ""), 99), m["callsign"].lower()))

    companies = []
    for comp in sorted({m["company"] for m in cur}, key=lambda c: roster.sheet_pos(c)):
        rows = a[a["company"] == comp]
        rr = a_recent[a_recent["company"] == comp]
        mem = members_of(company=comp)
        tab = next((m.get("company_tab", "") for m in mem if m.get("company_tab")), "")
        lead = [m for m in mem if m["level"] == "company"]
        platoons = []
        for pl in sorted({m["platoon"] for m in mem if m["platoon"]}, key=lambda p: roster.sheet_pos(comp, p)):
            prow = rows[rows["platoon"] == pl]
            pm = members_of(company=comp, platoon=pl)
            squads = []
            for sq in sorted({m["squad"] for m in pm if m["squad"]},
                             key=lambda s: roster.sheet_pos(comp, pl, s)):
                srow = prow[prow["squad"] == sq]
                sm = members_of(company=comp, platoon=pl, squad=sq)
                squads.append(dict(name=sq, detachment=next((m["detachment"] for m in sm), ""),
                                   **part(sm, srow, rr[(rr["platoon"] == pl) & (rr["squad"] == sq)]),
                                   **group_stats(srow)))
            platoons.append(dict(name=pl, leaders=[f'{m["rank"]} {m["callsign"]}'.strip() for m in ranks(pm)
                                                   if m["level"] == "platoon"],
                                 **part(pm, prow, rr[rr["platoon"] == pl]), **group_stats(prow), squads=squads))
        top = (rows.groupby("player").size().sort_values(ascending=False).head(3) if len(rows) else pd.Series(dtype=int))
        fronts = rows.drop_duplicates("deployment")["front"].value_counts().to_dict() if len(rows) else {}
        companies.append(dict(name=comp, tab=tab, leaders=[f'{m["rank"]} {m["callsign"]}'.strip() for m in lead],
                              **part(mem, rows, rr), **group_stats(rows), platoons=platoons,
                              active=[dict(name=k, missions=int(v)) for k, v in top.items()],
                              fronts={k: int(v) for k, v in fronts.items()}))
    guests = a[a["company"] == "Guests"]
    return dict(companies=companies, regiment=regiment, min_missions=MIN_MISSIONS,
                guests=dict(players=int(guests["player_key"].nunique()), missions=int(len(guests))),
                roster_members=len(cur), generated=datetime.now().strftime("%d %b %Y %H:%M"))


def unit_line(units: "roster.Units", name: str) -> str:
    u = units.unit_at(name, None)
    if not u:
        return ""
    parts = [u.get("rank", "")]
    if u.get("squad"):
        parts.append(u["squad"])
    elif u.get("detachment"):
        parts.append(u["detachment"] + " CO")
    if u.get("platoon"):
        parts.append(u["platoon"])
    parts.append(u.get("company", ""))
    return " · ".join(p for p in parts if p)


UNITS_LINK = '<a class="navlink" href="units.html" style="margin-right:8px">Companies &amp; squads &rarr;</a>'


def add_units_link(page: str, kind: str) -> str:
    """Add the 'Companies & squads' link to the report / player lookup navigation."""
    if kind == "report":
        return page.replace('<a class="navlink" href="players.html">', UNITS_LINK + '<a class="navlink" href="players.html">', 1)
    return page.replace('<nav class="wrap topnav">', '<nav class="wrap topnav">' + UNITS_LINK, 1)


def build_pages(out_dir, title: str, df: pd.DataFrame, cards: list[dict], style: str, chart_js: str,
                players_builder, drive_dirs=()) -> str:
    """Read the company roster (roster_raw.csv), log transfers, then write units.html and add the unit link
    + each Helldiver's rank and unit to report.html / players.html. Returns a one-line summary for the log."""
    raw = roster.find_raw(drive_dirs)
    n_members, changes = roster.update(drive_dirs)
    units = roster.Units()
    if not units:
        (out_dir / "units.html").unlink(missing_ok=True)
        return "Companies & squads: no roster_raw.csv yet (answers spreadsheet: 505th Stats -> Write roster_raw.csv now)"
    rep = out_dir / "report.html"
    rep.write_text(add_units_link(rep.read_text(encoding="utf-8"), "report"), encoding="utf-8")
    ucards = [dict(c, unit=unit_line(units, c["name"])) for c in cards]
    (out_dir / "players.html").write_text(add_units_link(players_builder(title, ucards, chart_js), "players"),
                                          encoding="utf-8")
    data = build_units_data(df, units)
    page = UNITS_TEMPLATE.replace("{{STYLE}}", style).replace("{{TITLE}}", html.escape(title)) \
        .replace("{{CHARTJS}}", chart_js).replace("{{DATA}}", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
    (out_dir / "units.html").write_text(page, encoding="utf-8")
    msg = f"Companies & squads: units.html - roster {n_members} members"
    moved = [c for c in changes if c["event"] in ("moved", "joined", "left")]
    if moved and changes[0]["date"] != roster.FIRST_DATE:
        msg += f", {len(moved)} change(s) logged today (" + ", ".join(
            f'{c["callsign"]} {c["event"]}' for c in moved[:6]) + ("..." if len(moved) > 6 else "") + ")"
    if raw:
        age = (datetime.now() - datetime.fromtimestamp(raw.stat().st_mtime)).days
        if age >= 2:
            msg += f"\n  Note: roster_raw.csv is {age} days old - is the daily roster update still on in the answers spreadsheet?"
    return msg


UNITS_TEMPLATE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Companies &amp; squads - {{TITLE}}</title>
<style>{{STYLE}}
.co{margin-top:26px}
.small{font-size:13px}
.coh{display:flex;flex-wrap:wrap;align-items:baseline;gap:6px 14px}
.coh h3{margin:0;font-size:clamp(22px,3.4vw,30px);font-weight:800}
.coh .muted{font-size:14px}
.tiles6{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin-top:12px}
@media (max-width:640px){.tiles6{grid-template-columns:repeat(2,1fr)}}
.prof{display:grid;grid-template-columns:minmax(0,360px) minmax(0,1fr);gap:12px;margin-top:12px;align-items:start}
@media (max-width:900px){.prof{grid-template-columns:1fr}}
.prof .chart{height:320px}
table.u{font-size:13.5px}table.u th,table.u td{padding:7px 8px}
table.u td:first-child{white-space:nowrap}
tr.pl td{font-weight:700;background:var(--surface2)}
tr.sq td:first-child{padding-left:24px}
td.na{color:var(--muted);font-style:italic}
.bar{height:6px;background:var(--surface2);margin-top:4px;min-width:60px}.bar i{display:block;height:100%;background:var(--s1)}
.act{display:flex;flex-wrap:wrap;gap:8px;margin-top:6px}
.act span{background:var(--surface2);border:1px solid var(--line);padding:3px 9px;font-size:13px}
</style></head>
<body>
<header><div class="wrap"><h1>Companies &amp; squads</h1><div class="period">{{TITLE}}</div></div></header>
<nav class="wrap topnav"><a class="navlink" href="index.html" style="margin-right:8px">&larr; Regiment report</a><a class="navlink" href="players.html">Player lookup &rarr;</a></nav>
<main class="wrap">
<p class="muted small" id="intro"></p>
<div id="root"></div>
<footer id="foot"></footer>
</main>
<script>{{CHARTJS}}</script>
<script>
const D = {{DATA}};
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const fmt = v => v == null ? '-' : Number(v).toLocaleString('en-US');
function el(tag, cls, text){ const e=document.createElement(tag); if(cls) e.className=cls; if(text!=null) e.textContent=text; return e; }
const AXES = ['Kills','Accuracy','Melee kills','Deaths','Deathless','Stratagems','Stims used','Friendly fire dmg'];
function tile(a,b,c){ const t=el('div','tile'); t.append(el('div','tl',a), el('div','tv',b)); if(c) t.append(el('div','ts',c)); return t; }
function pct(a,b){ return b ? Math.round(100*a/b)+'%' : '-'; }
const enough = u => (u.missions||0) >= D.min_missions;
function radar(cv, u){
  const reg = D.regiment.radar || [];
  const ratio = (v,i) => (v==null||reg[i]==null) ? null : (reg[i]>0 ? v/reg[i] : (v>0?2:1));
  const me = css('--s1'), avg = css('--muted');
  Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
  const narrow = cv.parentNode.clientWidth < 460;
  const SHORT = {'Friendly fire dmg':'FF dmg','Melee kills':'Melee','Stratagems':'Strat.','Stims used':'Stims','Accuracy':'Acc.','Deathless':'No death'};
  new Chart(cv, {type:'radar', data:{labels:AXES.map((a,i)=>{ const r=ratio(u.radar[i],i); const n=narrow?(SHORT[a]||a):a; return r==null?n:n+(narrow?' ':'  ')+r.toFixed(1)+'×'; }),
    datasets:[{label:u.name, data:u.radar.map((v,i)=>{ const r=ratio(v,i); return r==null?null:Math.min(1,r/2); }), borderColor:me, backgroundColor:me+'40',
               borderWidth:2, pointRadius:4, pointBackgroundColor:me, pointBorderColor:css('--surface'), pointBorderWidth:2, spanGaps:true},
              {label:'Regiment average', data:AXES.map(()=>0.5), borderColor:avg, backgroundColor:avg+'26', borderWidth:2, borderDash:[5,4], pointRadius:0}]},
    options:{responsive:true, maintainAspectRatio:false, animation:false,
      scales:{r:{min:0,max:1,ticks:{display:false,stepSize:0.25},grid:{color:css('--grid')},angleLines:{color:css('--grid')},pointLabels:{color:css('--text2'),font:{size:narrow?11:12}}}},
      plugins:{legend:{position:'bottom',labels:{color:css('--text2'),boxWidth:14,boxHeight:2}},
        tooltip:{backgroundColor:css('--surface2'),titleColor:css('--text'),bodyColor:css('--text'),borderColor:css('--line'),borderWidth:1,
          callbacks:{label:i=>{ const k=i.dataIndex, v=i.datasetIndex===0?u.radar[k]:reg[k]; return ' '+i.dataset.label+': '+(v==null?'-':Number(v).toFixed(1)); }}}}}});
}
function row(cls, name, u){
  const tr = el('tr', cls); const n = el('td'); n.textContent = name; tr.appendChild(n);
  const rep = el('td','num'); rep.textContent = `${u.reporting}/${u.members}`; const b=el('div','bar'); const i=el('i'); i.style.width=(u.members?100*u.reporting/u.members:0)+'%'; b.appendChild(i); rep.appendChild(b); tr.appendChild(rep);
  tr.appendChild(el('td','num', fmt(u.missions)));
  if(!enough(u)){ const td=el('td','na','not enough data yet'); td.colSpan=4; tr.appendChild(td); return tr; }
  tr.appendChild(el('td','num', fmt(u.kpm))); tr.appendChild(el('td','num', u.kd==null?'-':u.kd.toFixed(2)));
  tr.appendChild(el('td','num', u.acc==null?'-':u.acc.toFixed(1)+'%')); tr.appendChild(el('td','num', u.deathless==null?'-':u.deathless.toFixed(0)+'%'));
  return tr;
}
const root = document.getElementById('root');
document.getElementById('intro').textContent = D.companies.length
  ? `Reporting = roster members with at least one logged mission. Units with fewer than ${D.min_missions} logged missions show "not enough data yet". Missions count for the unit the player was in on that day.`
  : 'No roster yet: in the answers spreadsheet use 505th Stats -> Write roster_raw.csv now, then Run report.';
D.companies.forEach(c=>{
  const s = el('section','co'); const h = el('div','coh'); h.append(el('h3',null,c.name));
  h.append(el('span','muted', [c.tab, c.leaders.length ? 'led by '+c.leaders.join(', ') : ''].filter(Boolean).join(' · '))); s.append(h);
  const t = el('div','tiles6');
  t.append(tile('Members', fmt(c.members), 'on the roster'), tile('Reporting', pct(c.reporting,c.members), `${c.reporting} have logged missions`),
           tile('Last 30 days', fmt(c.recent), 'members deployed'), tile('Logged missions', fmt(c.missions), `${fmt(c.deployments)} deployments`),
           tile('Kills / mission', enough(c)?fmt(c.kpm):'-', enough(c)?'K/D '+(c.kd==null?'-':c.kd.toFixed(2)):'not enough data yet'),
           tile('Never died', enough(c)?c.deathless.toFixed(0)+'%':'-', 'of missions'));
  s.append(t);
  const prof = el('div','prof');
  const cardR = el('div','card'); cardR.append(el('h3',null,'Company profile'), el('div','sub','Per mission. Ring = regiment average · edge = 2× the average.'));
  if(enough(c)){ const box=el('div','chart'); const cv=el('canvas'); cv.setAttribute('role','img'); cv.setAttribute('aria-label', c.name+' compared with the regiment'); box.append(cv); cardR.append(box); setTimeout(()=>radar(cv,c),0); }
  else cardR.append(el('p','muted','Not enough data yet ('+c.missions+' of '+D.min_missions+' missions).'));
  prof.append(cardR);
  const cardT = el('div','card'); cardT.append(el('h3',null,'Platoons & squads'), el('div','sub','Leaders (SGM and up) count for their platoon, the CPT for the company.'));
  const tw = el('div','tw'); const tb = el('table','u'); const th = el('thead'); const hr = el('tr');
  ['Unit','Reporting','Missions','Kills/mission','K/D','Accuracy','No death'].forEach((x,i)=>hr.append(el('th', i?'num':null, x)));
  th.append(hr); tb.append(th); const body = el('tbody');
  c.platoons.forEach(p=>{ body.append(row('pl', p.name, p)); p.squads.forEach(q=>body.append(row('sq', q.name+(q.detachment?' ('+q.detachment.replace('Detachment ','D')+')':''), q))); });
  if(!c.platoons.length){ const tr=el('tr'); const td=el('td','muted','No platoons on the roster.'); td.colSpan=7; tr.append(td); body.append(tr); }
  tb.append(body); tw.append(tb); cardT.append(tw);
  if(c.active.length){ cardT.append(el('div','sub','Most active (logged missions)')); const a=el('div','act'); c.active.forEach(x=>a.append(el('span',null,`${x.name} · ${x.missions}`))); cardT.append(a); }
  prof.append(cardT); s.append(prof); root.append(s);
});
if(D.guests.players){ const g=el('p','muted small'); g.textContent=`Guests (not on any roster on the day of the deployment): ${D.guests.players} Helldivers, ${D.guests.missions} logged missions - counted in the regiment totals, not in a company.`; root.append(g); }
document.getElementById('foot').textContent = `Generated ${D.generated} · roster: ${D.roster_members} members.`;
</script>
</body></html>
"""
