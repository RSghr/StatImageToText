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


def players(page: str, ctx: dict) -> str:
    return page


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
