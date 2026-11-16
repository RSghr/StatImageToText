"""
beta.py - the BETA section: local test copies of the website, never published.

Every run, after the normal pages are built, make_report.py calls build() which writes in output/ only
(never copied to htmlReport, never uploaded):
    index_beta.html     report
    players_beta.html   player lookup
    units_beta.html     companies & squads
They start as copies of the normal pages with a red BETA banner and links between the beta pages.

To try a change without touching the live site, put it in the hooks below (each gets the finished page
and the data and returns the page to write). When it looks right, move it into make_report.py / units.py.
A crash here never breaks the normal report.
"""
from __future__ import annotations

from pathlib import Path

PAGES = {"index_beta.html": "report.html", "players_beta.html": "players.html", "units_beta.html": "units.html",
         "raids_beta.html": "raids.html"}
BANNER = ('<div style="background:#c03030;color:#fff;font-weight:700;text-align:center;padding:6px 12px;'
          'letter-spacing:.06em">BETA - LOCAL PREVIEW (NOT PUBLISHED)</div>')


# ---- hooks for future changes: edit these, the live pages stay as they are -------------------------------
def _milestones(ctx: dict) -> dict:
    if "milestones" not in ctx:
        import milestones
        ctx["milestones"] = milestones.compute(ctx["df"], ctx["dep"])
    return ctx["milestones"]


def report(page: str, ctx: dict) -> str:
    return page                             # (milestones and raids are on the live pages now)


WITH_MIN = 4          # deployments together before "with X" shows on a player's card


def with_data(df, min_deps: int = WITH_MIN) -> dict:
    """{player_key: [teammate numbers]} - how a player does in the missions played with each regular teammate.
    Same per-mission numbers as the profile chart, from the missions where both were in the squad."""
    import make_report as mr
    df = df[df["player_key"].astype(bool)]
    name_of = df.groupby("player_key")["player"].agg(lambda s: s.mode().iat[0])
    deps_of = df.groupby("player_key")["deployment"].agg(lambda s: set(s))
    in_mission = df.groupby(["deployment", "mission"])["player_key"].agg(lambda s: set(s))
    out = {}
    for key, g in df.groupby("player_key"):
        rows = []
        for mate, mdeps in deps_of.items():
            if mate == key:
                continue
            shared = deps_of[key] & mdeps
            if len(shared) < min_deps:
                continue
            both = g[[mate in in_mission.get((d, m), ()) for d, m in zip(g["deployment"], g["mission"])]]
            ga = mr.avg_rows(both)
            na = len(ga)
            if not na:
                continue
            t = {c: int(ga[c].sum()) for c in mr.SUMMABLE}
            rows.append(dict(
                key=mate, name=str(name_of.get(mate, mate)), deployments=len(shared), missions=na,
                kpm=round(t["kills"] / na, 1), dpm=round(t["deaths"] / na, 2),
                kd=round(t["kills"] / t["deaths"], 2) if t["deaths"] else None,
                radar=[round(t["kills"] / na, 2),
                       round(100 * t["shots_hit"] / t["shots_fired"], 2) if t["shots_fired"] else None,
                       round(t["melee_kills"] / na, 2), round(t["deaths"] / na, 2),
                       round(100 * int((ga["deaths"] == 0).sum()) / na, 2),
                       round(t["stratagems_used"] / na, 2), round(t["stims_used"] / na, 2),
                       round(t["friendly_fire_damage"] / na, 2)]))
        if rows:
            out[key] = sorted(rows, key=lambda r: (-r["deployments"], r["name"].lower()))
    return out


WITH_JS = r"""<script>
// BETA: "with X" - the profile chart in the missions played with a regular teammate
const W = {{WITH}}; let WSEL = null;
const baseProfile = window.profileCard, baseRadar = window.drawRadar;
window.profileCard = function(p){
  const c = baseProfile(p); const list = W[p.key];
  if(WSEL && !(list||[]).some(x=>x.key===WSEL)) WSEL = null;
  if(!list || !R.axes) return c;
  const bar = el('div','wbar'); bar.appendChild(el('span','muted','Compare with '));
  const sel = el('select'); sel.appendChild(new Option(p.name+' overall', ''));
  list.forEach(x=>sel.appendChild(new Option(x.name+' ('+x.deployments+' deployments)', x.key)));
  sel.value = WSEL || ''; bar.appendChild(sel);
  const note = el('div','wnote muted'); bar.appendChild(note);
  c.insertBefore(bar, c.querySelector('.prof'));
  // a column for the teammate in the numbers table
  const tab = c.querySelector('.ptab'); const hr = tab.querySelector('thead tr');
  const wh = el('th','num wcol',''); hr.insertBefore(wh, hr.children[2]);
  const cells = [...tab.querySelectorAll('tbody tr')].map(tr=>{ const td=el('td','num wcol'); tr.insertBefore(td, tr.children[2]); return td; });
  const pct = (a,b) => (a==null||b==null||!b) ? '' : ' ('+(a>=b?'+':'')+Math.round(100*(a-b)/b)+'%)';
  const fill = () => {
    const w = list.find(x=>x.key===WSEL);
    c.querySelectorAll('.wcol').forEach(e=>e.hidden=!w);
    if(w){ wh.textContent='With '+w.name; cells.forEach((td,i)=>td.textContent=fmtv(w.radar[i],i));
      note.textContent = w.missions+' mission'+(w.missions>1?'s':'')+' together · '+w.kpm+' kills/mission'+pct(w.kpm,p.radar[0])+
        ' · '+w.dpm+' deaths/mission'+pct(w.dpm,p.radar[3])+(w.kd!=null?' · K/D '+w.kd.toFixed(2):'');
    } else note.textContent = list.length+' regular teammate'+(list.length>1?'s':'')+' (at least '+{{MIN}}+' deployments together)';
  };
  sel.onchange = () => { WSEL = sel.value || null; fill(); const cv=c.querySelector('canvas'); if(cv) window.drawRadar(cv, p); };
  fill();
  return c;
};
window.drawRadar = function(cv, p){
  baseRadar(cv, p);
  const w = (W[p.key]||[]).find(x=>x.key===WSEL);
  if(!w || !radarChart) return;
  const col = css('--accent') || '#e0b000';
  radarChart.data.datasets.splice(1, 0, {label:p.name+' with '+w.name, data:w.radar.map(rnorm), borderColor:col,
    backgroundColor:col+'30', borderWidth:2, pointRadius:3, pointBackgroundColor:col, spanGaps:true});
  radarChart.options.plugins.tooltip.callbacks.label = i => { const k=i.dataIndex;
    const v = i.datasetIndex===0 ? p.radar[k] : i.datasetIndex===1 ? w.radar[k] : R.avg[k];
    const unit = R.units[k].startsWith('%') ? '' : ' '+R.units[k];
    return ' '+i.dataset.label+': '+fmtv(v, k)+unit; };
  radarChart.update();
};
fromHash();
</script>
<style>.wbar{display:flex;flex-wrap:wrap;align-items:center;gap:6px 10px;margin:4px 0 12px}
.wbar select{font:inherit;padding:4px 8px;background:var(--surface2);color:var(--text);border:1px solid var(--line)}
.wnote{flex-basis:100%;font-size:13px}</style>
"""


def players(page: str, ctx: dict) -> str:
    if "df" not in ctx:
        return page
    import json
    data = json.dumps(with_data(ctx["df"]), ensure_ascii=False, indent=1)
    js = WITH_JS.replace("{{WITH}}", data).replace("{{MIN}}", str(WITH_MIN))
    return page.replace("</body>", js + "</body>", 1)


def units(page: str, ctx: dict) -> str:
    return page


def raids_page(page: str, ctx: dict) -> str:
    return page


HOOKS = {"index_beta.html": report, "players_beta.html": players, "units_beta.html": units,
         "raids_beta.html": raids_page}
# -----------------------------------------------------------------------------------------------------------


def _links(page: str) -> str:
    for beta, live in PAGES.items():
        live_href = "index.html" if live == "report.html" else live
        page = page.replace(f'href="{live_href}"', f'href="{beta}"')
    return page.replace("<body>", "<body>" + BANNER, 1)


def build(out_dir: Path, ctx: dict | None = None) -> str:
    ctx = ctx or {}
    made = []
    for beta, live in PAGES.items():
        src = out_dir / live
        if not src.exists():
            (out_dir / beta).unlink(missing_ok=True)
            continue
        page = src.read_text(encoding="utf-8")
        try:
            page = HOOKS[beta](page, ctx)
        except Exception as e:  # noqa: BLE001 - a broken experiment still gives a plain beta copy
            print(f"Beta change on {beta} failed: {e}")
        (out_dir / beta).write_text(_links(page), encoding="utf-8")
        made.append(beta)
    return "Beta (local only): " + (", ".join(made) if made else "nothing to copy")
