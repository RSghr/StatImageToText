"""
unit_colors.py - one colour per company (report, milestones, companies page, player cards, raids).

Set in the browser panel (Settings -> Company colours), saved in settings.json as
    "company_colors": {"Emperor Company": "#003478", ...}
Companies without a saved colour get one from the name of their roster tab:
    a tab with "EU" -> #003478, "... 2" -> #F26A00, "... 1" -> #E50102, otherwise a spare colour.
The regiment keeps the site's yellow.
"""
from __future__ import annotations

import json
import re
from pathlib import Path

HERE = Path(__file__).resolve().parent
SETTINGS = HERE / "settings.json"
REGIMENT = "var(--accent)"
TAB_DEFAULTS = [(re.compile(r"\bEU\b", re.I), "#003478"), (re.compile(r"\b2\b"), "#F26A00"),
                (re.compile(r"\b1\b"), "#E50102")]
SPARE = ["#199E70", "#9085E9", "#D55181", "#C98500"]
HEX = re.compile(r"^#?([0-9a-fA-F]{6})$")


def clean_hex(v) -> str | None:
    m = HEX.match(str(v or "").strip())
    return "#" + m.group(1).upper() if m else None


def saved() -> dict:
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8")).get("company_colors") or {}
    except Exception:  # noqa: BLE001
        d = {}
    return {k: c for k, v in d.items() if (c := clean_hex(v))}


def company_colors(companies, tabs: dict | None = None) -> dict:
    """{company: '#RRGGBB'} for every company given (in order)."""
    tabs = tabs or {}
    have, out, spare = saved(), {}, list(SPARE)
    for c in companies:
        if c in have:
            out[c] = have[c]
            continue
        tab = tabs.get(c, "") or c
        col = next((hx for rx, hx in TAB_DEFAULTS if rx.search(tab)), None)
        if col is None or col in out.values():
            col = spare.pop(0) if spare else "#77766F"
        out[c] = col
    return out


def save(colors: dict):
    try:
        d = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001
        d = {}
    d["company_colors"] = {k: c for k, v in colors.items() if (c := clean_hex(v))}
    SETTINGS.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")


def current() -> dict:
    """Colours of the companies on the roster right now (sheet order)."""
    try:
        import roster
        units = roster.Units()
        comps = sorted({m["company"] for m in units.current() if m["company"]}, key=lambda c: roster.sheet_pos(c))
        return company_colors(comps, roster.TABS)
    except Exception:  # noqa: BLE001
        return {}


# Dark backgrounds: a dark blue line would disappear, so the pages lighten the colour there (CSS, not here).
CSS_VARS = """:root{--cc-mix:35%}
@media (prefers-color-scheme: light){:root:not([data-theme="dark"]){--cc-mix:0%}}
:root[data-theme="light"]{--cc-mix:0%}
.cc{--ccl:color-mix(in srgb, var(--cc) calc(100% - var(--cc-mix)), white)}"""
