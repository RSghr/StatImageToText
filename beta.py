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

PAGES = {"index_beta.html": "report.html", "players_beta.html": "players.html", "units_beta.html": "units.html"}
RAIDS_LINK = '<a class="navlink" href="raids_beta.html" style="margin-right:8px">Raids &rarr;</a>'
BANNER = ('<div style="background:#c03030;color:#fff;font-weight:700;text-align:center;padding:6px 12px;'
          'letter-spacing:.06em">BETA - LOCAL PREVIEW (NOT PUBLISHED)</div>')


# ---- hooks for future changes: edit these, the live pages stay as they are -------------------------------
def _milestones(ctx: dict) -> dict:
    if "milestones" not in ctx:
        import milestones
        ctx["milestones"] = milestones.compute(ctx["df"], ctx["dep"])
    return ctx["milestones"]


def _raids(ctx: dict) -> dict:
    if "raids" not in ctx:
        import raids
        import roster
        ctx["raids"] = raids.build(ctx["df"], ctx["dep"], roster.Units())
    return ctx["raids"]


def _nav(page: str) -> str:
    return page.replace('<nav class="wrap topnav">', '<nav class="wrap topnav">' + RAIDS_LINK, 1)


def report(page: str, ctx: dict) -> str:
    import milestones                       # milestones section + milestone log (regiment & companies)
    page = milestones.patch_report(page, _milestones(ctx))
    try:                                    # raids: banner for 7 days + link to the raid page
        import raids
        rd = _raids(ctx)
        if rd["recent"]:
            page = page.replace("</head>", raids.BANNER_CSS + "</head>", 1)
            page = page.replace('<main class="wrap">', '<main class="wrap">\n' + raids.banner(rd, "raids_beta.html"), 1)
    except Exception as e:  # noqa: BLE001
        print(f"Raids not added to the report: {e}")
    return _nav(page)


def players(page: str, ctx: dict) -> str:
    import milestones                       # personal milestones under best moments / career totals
    return _nav(milestones.patch_players(page, _milestones(ctx)))


def units(page: str, ctx: dict) -> str:
    return _nav(page)


def extra_pages(out_dir: Path, ctx: dict) -> list[str]:
    """Pages that only exist in the beta."""
    import raids
    src = out_dir / "report.html"
    rep = src.read_text(encoding="utf-8")
    style = rep[rep.index("<style>") + 7:rep.index("</style>")]
    page = raids.page(_raids(ctx), ctx.get("title", ""), style)
    (out_dir / "raids_beta.html").write_text(_links(page), encoding="utf-8")
    return ["raids_beta.html"]


HOOKS = {"index_beta.html": report, "players_beta.html": players, "units_beta.html": units}
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
    try:
        made += extra_pages(out_dir, ctx)
    except Exception as e:  # noqa: BLE001
        print(f"Beta-only pages failed: {e}")
    return "Beta (local only): " + (", ".join(made) if made else "nothing to copy")
