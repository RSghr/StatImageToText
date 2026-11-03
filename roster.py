"""
roster.py - who belongs to which company / platoon / detachment / squad, and since when.

Input: roster_raw.csv (written by the Google script from the company roster tabs, into the Drive folder):
    tab, row, company, function, callsign, unit, status
  - a "... PLATOON" row starts a platoon
  - unit (column G of the roster): "Company CO", "Platoon CO", "Detachment 1 CO", "Sekhmet Squad", ...
  - Detachment 1 = the first two squads of the platoon, Detachment 2 = the next two
  - SGM and above belong to their platoon (not a squad), the CPT to the company

The roster changes (newcomers, transfers), so every run compares it with the last one and writes the
changes with their date in history/roster_log.csv. A deployment counts for the unit the player was in
ON THAT DAY: a transfer never moves old stats to the new squad.
"""
from __future__ import annotations

import csv
import datetime
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
LOG = HERE / "history" / "roster_log.csv"
LOG_FIELDS = ["date", "callsign", "rank", "company", "platoon", "detachment", "squad", "level", "event"]
FIRST_DATE = "2000-01-01"          # the first roster ever read applies to all older deployments
RANK_ORDER = ["CPT", "1LT", "2LT", "SGM", "1SG", "SSG", "SGT", "CPL", "SPC", "PFC", "PVT"]


ORDER: dict = {}    # (company,), (company, platoon), (company, platoon, squad) -> position in the sheet
TABS: dict = {}     # company -> name of its roster tab ("EU COMPANY 1")


def sheet_pos(*unit) -> tuple:
    """Sort key that follows the order of the roster sheet (unknown names last, alphabetically)."""
    return (ORDER.get(tuple(unit), 10 ** 6), unit[-1].lower() if unit else "")


def key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", str(name or "").lower())


def split_callsign(raw: str) -> tuple[str, str]:
    """'SPC-1409 "Gunslinger"' -> ('Gunslinger', 'SPC'). Without quotes: the text after the rank."""
    s = str(raw or "").strip()
    rank = ""
    m = re.match(r"^\s*([0-9]?[A-Za-z]{2,4})\s*-\s*\d+", s)
    if m:
        rank = m.group(1).upper()
    q = re.findall(r'["“”]([^"“”]+)["“”]', s)
    if q:
        return q[0].strip(), rank
    rest = re.sub(r"^\s*[0-9]?[A-Za-z]{2,4}\s*-\s*\d+\s*", "", s).strip()
    return rest or s, rank


def nice(title: str) -> str:
    """'HASTATI PLATOON' -> 'Hastati Platoon'."""
    t = " ".join(str(title or "").split())
    if not t.isupper():
        return t
    return " ".join(w if len(w) <= 2 else w.title() for w in t.split())    # "EU COMPANY 1" -> "EU Company 1"


def find_raw(extra_dirs=()) -> Path | None:
    cands = [HERE / "roster_raw.csv"] + [Path(d) / "roster_raw.csv" for d in extra_dirs if d]
    cands = [p for p in cands if p.exists()]
    return max(cands, key=lambda p: p.stat().st_mtime) if cands else None


def parse(raw_csv: Path) -> dict:
    """roster_raw.csv -> {callsign key: member dict}."""
    with open(raw_csv, encoding="utf-8-sig", newline="") as f:
        rows = [{(k or "").strip().lower(): (v or "").strip() for k, v in r.items()} for r in csv.DictReader(f)]
    members: dict = {}
    platoon = {}                       # tab -> current platoon
    squads: dict = {}                  # (tab, platoon) -> squad names in order of appearance
    tabs: list = []                    # tab order of the spreadsheet (the script writes the tabs in that order)
    for r in rows:
        if r.get("tab", "") not in tabs:
            tabs.append(r.get("tab", ""))
    ORDER.clear()
    TABS.clear()
    for r in sorted(rows, key=lambda r: (tabs.index(r.get("tab", "")), int(r.get("row") or 0))):
        tab, fn, raw, unit = r.get("tab", ""), r.get("function", ""), r.get("callsign", ""), r.get("unit", "")
        title = r.get("company", "")
        company = nice(title if re.search(r"company", title, re.I) else tab)   # never a stray cell ("dis", "ed")
        if re.search(r"platoon", fn, re.I) and not raw:
            platoon[tab] = nice(fn)
            continue
        if not raw or r.get("status", "").lower() == "empty" or fn.lower() == "function":
            continue
        name, rank = split_callsign(raw)
        pl = platoon.get(tab, "")
        m = dict(callsign=name, rank=rank, function=fn, company=company, company_tab=tab, platoon="", detachment="",
                 squad="", level="", status=r.get("status", ""))
        u = unit.lower()
        if "company" in u:
            m["level"] = "company"
        elif "platoon" in u:
            m.update(level="platoon", platoon=pl)
        elif re.match(r"detachment\s*(\d)", u):
            m.update(level="platoon", platoon=pl, detachment=f"Detachment {re.match(r'detachment\s*(\d)', u).group(1)}")
        elif "squad" in u or unit:
            sq = nice(unit)
            order = squads.setdefault((tab, pl), [])
            if sq not in order:
                order.append(sq)
            m.update(level="squad", platoon=pl, squad=sq,
                     detachment=f"Detachment {1 if order.index(sq) < 2 else 2}")
        TABS.setdefault(m["company"], tab)
        for o in [(m["company"],), (m["company"], m["platoon"]), (m["company"], m["platoon"], m["squad"])]:
            ORDER.setdefault(o, len(ORDER))
        k = key(name)
        if k and k not in members:
            members[k] = m
    return members


def unit_tuple(m: dict) -> tuple:
    return (m.get("company", ""), m.get("platoon", ""), m.get("detachment", ""), m.get("squad", ""), m.get("level", ""))


def read_log() -> list[dict]:
    if not LOG.exists():
        return []
    with open(LOG, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def sync(members: dict, today: str | None = None) -> list[dict]:
    """Compare with the last roster; write newcomers, transfers and departures with today's date."""
    today = today or datetime.date.today().isoformat()
    log = fix_company_names(read_log(), members)
    first = not log
    last: dict = {}
    for e in log:
        last[key(e["callsign"])] = e
    changes = []
    for k, m in members.items():
        prev = last.get(k)
        if prev and prev["event"] != "left" and unit_tuple(prev) == unit_tuple(m) and prev.get("rank") == m["rank"]:
            continue
        if not prev or prev["event"] == "left":
            ev = "joined"
        elif unit_tuple(prev)[:2] + unit_tuple(prev)[3:] != unit_tuple(m)[:2] + unit_tuple(m)[3:]:
            ev = "moved"
        elif unit_tuple(prev) != unit_tuple(m):
            ev = "reorganised"          # same squad, its detachment changed (squads reordered in the sheet)
        else:
            ev = "rank"
        changes.append(dict(date=FIRST_DATE if first else today, callsign=m["callsign"], rank=m["rank"],
                            company=m["company"], platoon=m["platoon"], detachment=m["detachment"],
                            squad=m["squad"], level=m["level"], event="joined" if first else ev))
    for k, prev in last.items():
        if k not in members and prev["event"] != "left":
            changes.append(dict(date=today, callsign=prev["callsign"], rank=prev.get("rank", ""), company="",
                                platoon="", detachment="", squad="", level="", event="left"))
    if changes:
        LOG.parent.mkdir(exist_ok=True)
        new = not LOG.exists()
        with open(LOG, "a", encoding="utf-8-sig" if new else "utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
            if new:
                w.writeheader()
            w.writerows(changes)
    renamed = repair_renames()
    if renamed:                                  # a renamed unit is not a transfer: drop those "moved" lines
        moved_away = {(r["old"], r["new"], r["date"]) for r in renamed}
        changes = [c for c in changes if not any(c["date"] == d and c["event"] == "moved"
                                                 and new_name in (c["company"], c["platoon"], c["squad"])
                                                 for _, new_name, d in moved_away)]
    return changes


UNIT_LEVELS = [("company",), ("company", "platoon"), ("company", "platoon", "squad")]
LAST_RENAMES: list = []       # renames found by the last sync (shown in the run log)
RENAMES = HERE / "history" / "unit_renames.csv"


def repair_renames(log: list[dict] | None = None) -> list[dict]:
    """A company / platoon / squad that changes name in the roster sheet shows up as everyone "moving" on the
    same day. Detect it (most of the old unit moved to one new name, nobody left under the old name) and rename
    the unit in the whole log instead, so past deployments follow the new name. Returns the renames done."""
    log = read_log() if log is None else log
    LAST_RENAMES.clear()
    if not log:
        return []
    done = []
    relabel = sum(1 for e in log if e["event"] == "moved")
    for fields in UNIT_LEVELS:
        f = fields[-1]
        hist: dict = {}
        for i, e in enumerate(log):
            hist.setdefault(key(e["callsign"]), []).append(i)
        pairs: dict = {}          # (date, old unit, new unit) -> callsigns that "moved"
        before: dict = {}         # (date, old unit) -> members in it just before that date
        dates = sorted({e["date"] for e in log if e["event"] == "moved"})
        for idxs in hist.values():
            for j in range(1, len(idxs)):
                a, b = log[idxs[j - 1]], log[idxs[j]]
                if b["event"] != "moved" or a["event"] == "left" or not a.get(f):
                    continue
                ua, ub = tuple(a.get(x, "") for x in fields), tuple(b.get(x, "") for x in fields)
                if ua[:-1] == ub[:-1] and ua[-1] != ub[-1] and ub[-1]:
                    pairs.setdefault((b["date"], ua, ub), set()).add(key(b["callsign"]))
        if not pairs:
            continue
        for d in dates:
            for idxs in hist.values():
                prev = [log[i] for i in idxs if log[i]["date"] < d]
                if prev and prev[-1]["event"] != "left" and prev[-1].get(f):
                    u = tuple(prev[-1].get(x, "") for x in fields)
                    before[(d, u)] = before.get((d, u), 0) + 1
        for (d, ua, ub), who in sorted(pairs.items(), key=lambda kv: -len(kv[1])):
            n_before = before.get((d, ua), 0)
            still = sum(1 for idxs in hist.values()
                        if (cur := [log[i] for i in idxs if log[i]["date"] <= d]) and cur[-1]["event"] != "left"
                        and tuple(cur[-1].get(x, "") for x in fields) == ua)
            if not n_before or len(who) < max(2, 0.5 * n_before) or still:
                continue
            for e in log:                                   # rename the unit in everything before that day
                if e["date"] < d and tuple(e.get(x, "") for x in fields) == ua:
                    e[f] = ub[-1]
            done.append(dict(date=d, level=f, old=ua[-1], new=ub[-1], parent=" / ".join(ub[:-1]), members=len(who)))
        # moves that are now identical to the line before them are not changes any more
        keep, last = [], {}
        for e in log:
            k = key(e["callsign"])
            p = last.get(k)
            if (e["event"] == "moved" and p and p["event"] != "left" and unit_tuple(p) == unit_tuple(e)
                    and p.get("rank") == e.get("rank")):
                continue
            if (e["event"] == "moved" and p and p["event"] != "left"
                    and unit_tuple(p)[:2] + unit_tuple(p)[3:] == unit_tuple(e)[:2] + unit_tuple(e)[3:]):
                e["event"] = "reorganised"                 # only the detachment changed: not a transfer
            keep.append(e)
            last[k] = e
        log[:] = keep
    relabel -= sum(1 for e in log if e["event"] == "moved")
    if relabel and not done:
        with open(LOG, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
            w.writeheader()
            w.writerows(log)
    LAST_RENAMES.extend(done)
    if done:
        with open(LOG, "w", encoding="utf-8-sig", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=LOG_FIELDS)
            w.writeheader()
            w.writerows(log)
        new_file = not RENAMES.exists()
        with open(RENAMES, "a", encoding="utf-8-sig" if new_file else "utf-8", newline="") as fh:
            w = csv.DictWriter(fh, fieldnames=["date", "level", "old", "new", "parent", "members"])
            if new_file:
                w.writeheader()
            w.writerows(done)
        try:                                                # keep the company colour with the new name
            import unit_colors
            cols = unit_colors.saved()
            changed = False
            for r in done:
                if r["level"] == "company" and r["old"] in cols and r["new"] not in cols:
                    cols[r["new"]] = cols.pop(r["old"])
                    changed = True
            if changed:
                unit_colors.save(cols)
        except Exception:  # noqa: BLE001
            pass
    return done


def fix_company_names(log: list[dict], members: dict) -> list[dict]:
    """Older versions sometimes took a stray cell ("dis", "ed") as the company name. Rename those in the log
    to the real company (by majority of the members in it) so nobody is logged as 'moved'."""
    bad = {e["company"] for e in log if e.get("company") and not re.search(r"company", e["company"], re.I)}
    if not bad:
        return log
    votes: dict = {}
    for e in log:
        m = members.get(key(e["callsign"]))
        if e.get("company") in bad and m:
            votes.setdefault(e["company"], {}).setdefault(m["company"], 0)
            votes[e["company"]][m["company"]] += 1
    ren = {old: max(v, key=v.get) for old, v in votes.items()}
    for e in log:
        if e.get("company") in ren:
            e["company"] = ren[e["company"]]
    with open(LOG, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=LOG_FIELDS)
        w.writeheader()
        w.writerows(log)
    return log


class Units:
    """unit_at(callsign, date) -> the member's unit on that date (None = not on the roster then: guest)."""

    def __init__(self):
        self.by_key: dict = {}
        for e in read_log():
            self.by_key.setdefault(key(e["callsign"]), []).append(e)
        for v in self.by_key.values():
            v.sort(key=lambda e: e["date"])

    def __bool__(self):
        return bool(self.by_key)

    def unit_at(self, name: str, date) -> dict | None:
        hist = self.by_key.get(key(name))
        if not hist:
            return None
        d = str(date)[:10] if date is not None and str(date) not in ("", "NaT", "nan") else "9999-12-31"
        cur = None
        for e in hist:
            if e["date"] <= d:
                cur = e
        if cur is None:
            cur = hist[0]                   # before the first record we know of: their first known unit
        return None if cur["event"] == "left" else cur

    def current(self) -> list[dict]:
        out = []
        for hist in self.by_key.values():
            if hist[-1]["event"] != "left":
                out.append(hist[-1])
        return out


def update(extra_dirs=()) -> tuple[int, list[dict]]:
    """Read the newest roster_raw.csv (program folder or Drive folder) and log the changes."""
    raw = find_raw(extra_dirs)
    if not raw:
        return 0, []
    members = parse(raw)
    return len(members), sync(members)
