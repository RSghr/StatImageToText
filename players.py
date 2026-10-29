"""
players.py - who is who: one callsign per Helldiver, any number of other names.

players.csv (next to run.bat), editable in any spreadsheet program or Notepad:

    callsign,also_known_as
    Pengus,PenguinGod; PaniniManuel
    Dune,InkTea; [nkTea

* callsign       the name used in the reports (the form callsign - it never changes)
* also_known_as  in-game names (as read from the stat screens), old names, Discord names...
                 separated by ";"

The list fills itself: every time a stat screen is linked to a form answer and an in-game name is
matched to a callsign with confidence, the in-game name is added. Fix a wrong one by moving or
deleting it; add a missing one by typing it. Matching ignores case, spaces and symbols, and allows
small reading mistakes ("[nkTea" = "InkTea").
"""
from __future__ import annotations

import csv
import difflib
import re
import unicodedata
from pathlib import Path

PLAYERS_FILE = Path(__file__).resolve().parent / "players.csv"
# names the game (or a misread) can show for anyone: never linked to one callsign
GENERIC = {"unknown", "player", "helldiver", "anonymous", "nan", "none", "505th", "505", "the505th",
           "505thregiment", "regiment"}


def is_generic(k: str) -> bool:
    """A name that says nothing about who it is: 'Unknown', a clan tag, a bare rank ('SGM-6666')."""
    return k in GENERIC or bool(re.fullmatch(r"(pvt|pfc|spc|cpl|sgt|ssg|sfc|msg|sgm|csm|lt|\dlt|cpt|maj|col|gen)\d*", k))


def norm(name) -> str:
    s = unicodedata.normalize("NFKD", str(name or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", s)


# characters the screen reader mixes up: compared as the same letter
_FOLD = str.maketrans({"0": "o", "1": "l", "i": "l", "5": "s", "8": "b"})


def fold(k: str) -> str:
    return k.translate(_FOLD)


class Roster:
    def __init__(self, path: Path = PLAYERS_FILE):
        self.path = path
        self.order: list[str] = []                  # callsigns in file order
        self.aka: dict[str, list[str]] = {}         # callsign -> other names
        self.changed = False
        self.learned: list[tuple[str, str]] = []    # (name, callsign) added this run
        if path.exists():
            self._load()
        self._index()

    # ---- file ---------------------------------------------------------------
    def _load(self):
        try:
            with open(self.path, encoding="utf-8-sig", newline="") as f:
                sample = f.read(2048)
                f.seek(0)
                try:
                    dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
                except csv.Error:
                    dialect = csv.excel
                for r in csv.DictReader(f, dialect=dialect):
                    r = {str(k).strip().lower(): (v or "").strip() for k, v in r.items() if k}
                    cs = r.get("callsign", "")
                    if not cs:
                        continue
                    names = [n.strip() for n in r.get("also_known_as", "").split(";") if n.strip()]
                    if cs not in self.aka:
                        self.order.append(cs)
                        self.aka[cs] = []
                    for n in names:
                        if norm(n) not in {norm(x) for x in self.aka[cs]}:
                            self.aka[cs].append(n)
        except OSError:
            pass

    def save(self):
        if not self.changed:
            return
        try:
            with open(self.path, "w", encoding="utf-8-sig", newline="") as f:
                w = csv.writer(f)
                w.writerow(["callsign", "also_known_as"])
                for cs in sorted(self.order, key=str.lower):
                    w.writerow([cs, "; ".join(self.aka.get(cs, []))])
            self.changed = False
        except PermissionError:
            print(f"Could not update {self.path.name} - is it open in another program? Close it and run again.")

    def _index(self):
        self.by_norm: dict[str, str] = {}
        for cs in self.order:
            self.by_norm.setdefault(norm(cs), cs)
            for n in self.aka.get(cs, []):
                if not is_generic(norm(n)):
                    self.by_norm.setdefault(norm(n), cs)

    # ---- lookups ------------------------------------------------------------
    def callsign_for(self, name, fuzzy: bool = True) -> str | None:
        """The callsign of a name (callsign itself or any other name), or None."""
        k = norm(name)
        if len(k) < 3 or is_generic(k):
            return None
        if k in self.by_norm:
            return self.by_norm[k]
        if fuzzy:
            # same name with mixed-up characters ('la0999' = 'lao999'), or followed by reading noise
            # ('la0999 - id' starts with 'lao999'); only when exactly one callsign fits
            fk = fold(k)
            hits = {cs for n, cs in self.by_norm.items() if len(n) >= 5 and
                    (fold(n) == fk or fk.startswith(fold(n)))}
            if len(hits) == 1:
                return hits.pop()
            if not hits:                         # one character misread / added: 'lao9399' ~ 'lao999'
                hits = {cs for n, cs in self.by_norm.items() if len(n) >= 6 and difflib.SequenceMatcher(
                        None, fold(n), fk[:len(n) + 1]).ratio() >= 0.9}
                if len(hits) == 1:
                    return hits.pop()
        if fuzzy and len(k) >= 5:
            best = difflib.get_close_matches(k, [x for x in self.by_norm if len(x) >= 5], n=2, cutoff=0.86)
            if best:
                cands = {self.by_norm[b] for b in best}
                if len(cands) == 1:              # only when it isn't ambiguous
                    return cands.pop()
        return None

    def canonical(self, callsign) -> str:
        """A callsign written the way players.csv writes it ('pengus' -> 'Pengus')."""
        return self.callsign_for(callsign, fuzzy=False) or str(callsign)

    # ---- learning -----------------------------------------------------------
    def add_callsign(self, cs: str):
        cs = str(cs).strip()
        if not cs or self.callsign_for(cs, fuzzy=False):
            return
        self.order.append(cs)
        self.aka[cs] = []
        self.by_norm.setdefault(norm(cs), cs)
        self.changed = True

    def learn(self, name, callsign) -> bool:
        """Remember that `name` (e.g. an in-game name) is `callsign`. Never moves a name that already
        belongs to someone else. Returns True if something was added."""
        name = str(name or "").strip().strip(" '\"\u2018\u2019\u201c\u201d|,.;:-\u2014_[](){}")
        callsign = str(callsign or "").strip()
        k = norm(name)
        if len(k) < 3 or is_generic(k) or not norm(callsign):
            return False
        self.add_callsign(callsign)
        cs = self.canonical(callsign)
        owner = self.by_norm.get(k)
        if owner is not None:
            return False                       # known already (for this or another callsign)
        self.aka.setdefault(cs, []).append(name)
        self.by_norm[k] = cs
        self.changed = True
        self.learned.append((name, cs))
        return True
