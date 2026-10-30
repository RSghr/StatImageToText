# 505th Stat Department - StatImageToText

Turns Helldivers 2 end-of-mission stat screens into one clean spreadsheet **and a server report**
(`report.html`, opens in any browser). It replaces the `StatImageToText/PyProject` pipeline.

| | Old pipeline | This version |
|---|---|---|
| Speed | ~96 s per deployment (3 images) | **~3–4 s per deployment** on a 2-core test machine; faster on a normal PC |
| Stats read | 8 | **all 12** (adds stratagems, melee kills, reinforcing, friendly fire) |
| Accuracy (hand-checked answer key, 372 values) | 62 of 768 values differed from the screenshots on the 8 old deployments I compared | **372 / 372 correct** |
| Doubtful values | silently written as `0` or shifted into the wrong column | **flagged** in a Review sheet with a picture of the crop |
| Screenshots | exact file-name pattern, ~1818 px wide, cropped | any size (tested 1132 → 3629 px wide), cropped or full-screen, PNG/JPEG/WEBP…, 1–4 players |
| Files touched | renames / converts / deletes your images, writes ~100 temp files per image | **read-only** on your screenshots, no temp files |

---

## Folder layout

| What | Files |
|---|---|
| **Double-click these** | `Stats Web UI.bat` (browser panel, recommended) · `Stats UI.bat` (desktop window) · `run.bat` · `publish_site.bat` · `reset.bat` · `setup.bat` (once) |
| Program | `hd2stats.py` (reads the screenshots) · `make_report.py` (website) · `history.py` · `players.py` · `roster.py` · `units.py` · `stats_web.py` + `stats_web.html` · `stats_ui.pyw` · `ui_core.py` · `publish_site.ps1` · `reset.ps1` · `glyphs.npz` (digit shapes) · `vendor/` (Chart.js) |
| Beta (this PC only) | `beta.py` · `milestones.py` · `raids.py` |
| **Your settings** (edit freely) | `settings.json` (Drive folder, options) · `players.csv` (who is who) · `milestones.csv` (targets) · `raids.csv` (made by the Raids tab) · `corrections.csv` (values fixed by hand) |
| Data (made by the program) | `history/` (every deployment, OCR cache, roster & milestone logs) · `output/` (last run) · `htmlReport/` (the pages that get published) · `To_Process/` (screenshots dropped by hand) · `Archive/` (resets, old forms) |
| Publishing setup | `publish_config.txt` (site name) · `published_address.txt` · `.wrangler/` (Cloudflare tool cache) |
| Google side | `google_apps_script/` (the scripts to paste into Apps Script + the planet list) |
| Developer tools | `dev/train_glyphs.py` (rebuild `glyphs.npz` if the game font changes) · `dev/tests/` (accuracy check) |

## 1. Setup (once)

1. **Python 3.10+** – https://www.python.org/downloads/ (tick “Add python.exe to PATH”).
2. **Tesseract OCR** – Windows installer: https://github.com/UB-Mannheim/tesseract/wiki
   (default location `C:\Program Files\Tesseract-OCR\` is found automatically).
3. Double-click **`setup.bat`** (creates a `.venv` folder and installs the Python packages),
   or run `pip install -r requirements.txt` yourself.

## The easy way: the control panel
Double-click **`Stats UI.bat`**. One window with everything:
**Drop zone** (drag the Drive `.zip` and the form `.xlsx`/`.csv` onto the yellow box, or click it: screenshots are
extracted into `To_Process`, screenshots already there are skipped, the form goes next to `run.bat` and older form
files move to `Archive\old_forms`) · **Run report** (live progress in the window) · **Google Drive folder…**
(automatic pickup, see below) · **Corrections** (opens `corrections.csv`, shows how many values are
left to check) · **Who is who (players.csv)** · **Open folder / Open To_Process** · **Open report in browser** ·
**Open player lookup** · **Open / Copy Discord message** · **History (deployments.csv)** ·
**Add an old batch to history…** ·
**Publish online** / **Open public page** (Cloudflare Pages, see *Putting it online*) · **Copy index.html contents** ·
**Reset (new batch)** with **Archive** (timestamped, nothing lost), **Delete permanently**, or **Cancel**.
The batch files below still work if you prefer them.

## The browser panel: `Stats Web UI.bat`

The same control panel in your browser, plus editors. Double-click **`Stats Web UI.bat`**: a small server starts
(only this PC can reach it – 127.0.0.1 – and a secret key made at each start protects every action) and the panel
opens in your browser. Close the console window to stop it.

* **Process** – status, drop zone (drop the zip / form / screenshots anywhere on the page), **Run & publish** (runs
  the report and, if nothing is left to check, publishes the website straight away), Run report only, live log.
* **Check** – the values to check, each with its **screenshot shown next to it** (the slot highlighted); type the
  answers and **Save & run report**. No spreadsheet program needed.
* **Who is who** – edit `players.csv` (search, add, remove).
* **History** – every deployment; untick *Count* to leave one out; add an old batch (stats.csv).
* **Share** – open the report / player lookup, Publish online, copy the Discord message or index.html.
* **Settings & reset** – the Google Drive folder, open folders in Windows, Reset (archive / delete).

`Stats UI.bat` (the desktop window) still works; both use the same files.

### Bookmark it
The panel always uses the same address on this PC. In *Settings & reset -> Bookmark the panel*, drag the button to
your bookmarks bar (or copy the link). Tick **Start the panel with Windows** so it runs in the background (no window)
from the moment you log in - the bookmark then always works. **Stop the panel** is on the same card; double-clicking
`Stats Web UI.bat` while it already runs just opens it. The link holds the panel's key (`.panel_key`): it only works
on this PC, but don't share it.

### Company colours
Each company has its own colour on the report (milestones), the companies page, player cards and raids; the regiment
stays yellow. Change them in *Settings & reset -> Company colours* (type a hex code like `#003478`, Save, Run report).
Saved in `settings.json`.

## Every deployment is kept: the history

Each run adds its deployments to **`history/`**; the report and the player lookup are built from the **whole
history**, not only from what is in `To_Process` right now.

* `history/deployments.csv` – one line per deployment. Put **`no`** in the `keep` column to leave one out of
  the report (a test, a duplicate...). It stays in the file; `yes` brings it back. Run report to apply.
* `history/stats.csv` – one line per player per mission (all the numbers).
* Running again, or reading the same screenshots again after a reset, **updates** a deployment – it is never
  counted twice (it is identified by its Deployment ID, or by its screenshot names). A mission screenshot sent in
  a later batch is **added** to its deployment.
* **Reset** no longer wipes anything important: it clears `To_Process`, `output` and the website copy, and keeps the
  history, `players.csv` and `corrections.csv`. Ticking *Also clear the history* starts from zero.
* Old batches archived before the history existed: **Add an old batch to history…** in Stats UI, pick
  `Archive\reset_<date>\output\stats.csv` (or `python history.py --import <that file>`).
* No new screenshots? Run report just rebuilds the report from the history (e.g. after editing `players.csv`).
* The reading cache now lives in `history/ocr_cache.json`, so a reset doesn't make it re-read every picture.
* `python make_report.py --batch` = report of the last run only.

## Who is who: `players.csv`

Callsigns never change, in-game names do. `players.csv` links them – one line per callsign:

```
callsign,also_known_as
Pengus,PenguinGod; penguincch
Lasar,laserhead1978
```

* **It fills itself.** When a stat screen is linked to its form answer, every in-game name that can be matched with
  confidence is added: the name looks like the callsign (`PaniniManuel` = Panini), it is the last one left, or it
  keeps showing up with the same callsign across several deployments (`laserhead1978` only ever plays when Lasar is
  in the form). The panel with no name (the player who took the screenshot) is matched to the uploader.
* **Form order = screen order.** Hosts type the callsigns in the form in the order the players appear on the stat
  screen, left to right. When the screenshot shows as many players as the form has callsigns, every panel that
  isn't recognised by its in-game name gets the callsign in the same position - no question asked. (Switch:
  Settings in the browser panel, or `"trust_form_order": false` in `settings.json`.)
* **Names on screen win over file names and panel order.** Players can name their screenshots anything, and the
  squad can be in any order in game: a known in-game name always gets its callsign.
* When it can only guess from the panel order, **one line per player per deployment** appears in `corrections.csv`
  (`stat = player`): type the right callsign or `ok`. The answer is remembered in `players.csv` for good, for every
  mission of that deployment and every future one.
* Edit it in Notepad or any spreadsheet program: move a wrong name to the right callsign, add old names, merge two
  callsigns of the same person. Matching ignores case and symbols and allows small reading mistakes
  (`[nkTea` = `InkTea`). Run report to apply – the history is renamed too.

## Player lookup page

`players.html` sits next to the report (link **Player lookup →** at the top of the report; published with it).
Type a callsign (or pick it from the list) to see that Helldiver's file across **all logged deployments**:
deployments, missions, kills, casualties and K/D, accuracy, missions without dying, stratagems, favourite front and
a front breakdown, personal best moments (most kills / stims / stratagems / reinforcements in a mission), career
totals, the **3 Helldivers they deploy with most** (% of their deployments and number of deployments together), and
their recent deployments. A link like `players.html#Pengus` opens a card directly. Personal stats, no rankings.

## Companies, platoons & squads

Every run also builds `units.html` (published with the report) and adds each Helldiver's rank and unit to the
player lookup. Nothing to do by hand: the roster is read on every run.

* **Roster:** the Google script reads the company tabs of the answers spreadsheet (tab name containing
  "Company") and writes `roster_raw.csv` into the Drive folder: function, callsign, unit (column G) and status -
  **never the Discord IDs (column E)**. Refreshed every day at 5:00, when a roster tab is edited, and with every
  form answer; or *505th Stats → Write roster_raw.csv now*.
* **Structure:** a "… PLATOON" row starts a platoon; Detachment 1 = its first two squads, Detachment 2 = the next
  two; SGM and above count for the platoon, the CPT for the company; Empty slots are skipped. Callsigns are
  matched like everywhere else (`SPC-1409 "Gunslinger"` → Gunslinger); the rank is kept separately.
* **Transfers:** each run compares the roster with the last one and writes newcomers, moves and departures with
  the date in `history/roster_log.csv`. A mission counts for the unit the player was in **on that day**; after
  leaving the roster a player counts as a guest.
* **Fair comparisons:** per-mission numbers only, participation shown as its own number ("Reporting 9/16"), units
  with fewer than 10 logged missions show "not enough data yet". Company profile chart = per mission against the
  regiment average (same style as the player card).

## BETA section (local only)

Every run also writes `output/index_beta.html`, `players_beta.html` and `units_beta.html`: copies of the
pages with a red BETA banner, **never copied to htmlReport and never published** (browser panel: Share → Beta).
Future changes are tried there first (hooks in `beta.py`), then moved into the normal pages once they look right.

**Milestones (live since Oct 2026).** Targets are in `milestones.csv` (edit freely: level, stat, faction, steps, title). Best edited in Notepad; if Excel
saves it with its own separators, the program puts the lines back together.
Regiment and company milestones show on the report: "Milestone reached!" cards at the top for 7 days, otherwise
the latest ones above the highlights, plus "Almost there" (80%+ of the next target) and a milestone log.
Personal milestones are on the player card. Everything is worked out from the history on every run (real date,
deployment and team of the crossing); only "every member of a squad registered" is remembered in
`history/milestones_reached.csv`, because the roster changes.

**Now in beta: raids.** Browser panel → *Raids*: name, unit (regiment / company / platoon, from the roster),
planet, start and end in **UTC** (the pages show Paris time). The deployments in the window are found for you:
company / platoon raids keep only squads **hosted** by someone of that unit on that day; other planets and outside
hosts are listed but not ticked; squads answering *Raid = Yes* in the form are ticked even on another planet.
Tick / untick, save (`raids.csv`), Run report → `raids_beta.html` (turnout, guests, totals, records, squads) and a
raid banner on the beta report for 7 days. Form answers tagged *Raid* that fit no declared raid are listed in the
Raids tab with a *Create raid* button. Raid deployments still count in all the normal stats.

## Automatic pickup from Google Drive (no more downloading)

1. Install **Google Drive for desktop** on the stats PC (drive.google.com/drive/download), sign in with the account
   that owns the `505th To_Process` folder. Your Drive appears as a drive letter (e.g. `G:\My Drive`).
2. Paste the updated `google_apps_script/RenameUploads.gs` into the responses spreadsheet's Apps Script (replace the
   old one, save, reload the sheet) and click **505th Stats → Write form_answers.csv now** once. From then on the
   script keeps **`form_answers.csv`** up to date in the `505th To_Process` folder after every form answer – without
   e-mail addresses or suggestions, and nothing is made public.
3. In Stats UI: **Google Drive folder…** → pick `G:\My Drive\505th To_Process` (saved in `settings.json`).

Every Run report then reads the screenshots **and** the form answers straight from that folder. Nothing is ever
deleted there; screenshots already read come from the cache, so it stays fast. Dropping a zip on the yellow box
still works (both are read; the same picture in both places counts once).

## 2. Run – the normal workflow

**Once:** install the Google Sheets script that gives every uploaded screenshot a unique name
(`google_apps_script/README_apps_script.md`, 5 minutes). It solves duplicate names (same squad, two
deployments) and badly named uploads (`Screenshot 2024-12-20 004519.png`).

**Each time** (with the Google Drive folder set): click **Run report**, check `corrections.csv`, run again if you
fixed anything, then **Publish online**.

**Each time** (without it):
1. In Google Drive, download the **`505th To_Process`** folder (Drive makes a .zip).
2. In the responses spreadsheet: **File → Download → Microsoft Excel (.xlsx)**.
3. Drop both files on the yellow box of **Stats UI** (or unzip into `To_Process` and save the .xlsx next to
   `run.bat` yourself - the newest file with a "Host Callsign" column is used).
4. Click **Run report** (or double-click **`run.bat`**). It reads the screenshots, then builds the report and opens it in your browser.

**Form fields used** (new *505th Data Deployment Registry* form): Operation Name, **Operation starting date as a
Discord timestamp** (`<t:1734098400:F>` from sesh.fyi/timestamp – shown in Paris time, change with
`--timezone "Europe/London"`), Difficulty, Planet, Host/Attendee 1–3 Callsign, Enemy, Operation Success, missions
affected by crashes, notes. The **e-mail address and the suggestions box are never read or copied** into any output.
A start date that isn't a valid timestamp falls back to the submission time and is reported in the Deployments sheet.

Without the Sheets script it still works with files named `Host_Player2_Player3_Player4_X.png`; deployments are
then matched to the form by callsigns (same squad twice → matched by order and flagged for you to check).

Command line, if you prefer:

```bat
python hd2stats.py                              :: reads .\To_Process, writes .\output
python hd2stats.py "D:\Form uploads" --form "505th Data Dep Registry sheet v0.xlsx"
python make_report.py                           :: output\stats.csv -> output\report.html
```

Options (`hd2stats.py`): `-o FOLDER` output folder · `--form FILE` form answers (.xlsx or .csv; found automatically
next to the script otherwise) · `--no-form` · `--recursive` also read sub-folders · `--passes 1|2|3` speed vs. care
(default 3) · `--workers N` · `--force` re-read everything (ignore cache) · `--tesseract PATH`.
`make_report.py`: `-i FOLDER` · `-t "Report title"`.

Images already read are cached (`history/ocr_cache.json`), so adding three new screenshots to a folder of 300
only reads the three new ones. More options: `--no-drive` (ignore the Google Drive folder), `--no-history`.

## Sharing it
* **Discord:** paste `output/discord_post.txt` (headline numbers + Highlights).
* **Website:** every run copies `index.html`, `players.html` and `units.html` into **`htmlReport`**;
  **Run & publish** (or `publish_site.bat`) uploads them to Cloudflare Pages - see *Putting it online*.

## Putting it online (Cloudflare Pages, free)

The pages are self-contained files, so no server is needed. `publish_site.bat` / **Publish online** uploads
`htmlReport\index.html`, `players.html` and `units.html` (plus safety headers and a "don't index me" note for search
engines) - nothing else from the folder. Static pages are free and unlimited on Cloudflare's free plan; no card needed.

First time (about 5 minutes): double-click `publish_site.bat` · if Node.js is missing it offers to install it (Y) ·
a browser opens: log in to / create the free Cloudflare account, click **Allow** · pick a site name (it becomes
`https://<name>.pages.dev`, saved in `publish_config.txt`). After that **Run & publish** does it by itself.
In the Cloudflare dashboard: **Workers & Pages** -> the project (every publish is listed and can be rolled back;
*Settings -> Delete* takes the site offline).

## Starting a new batch: `reset.bat`
Double-click **`reset.bat`** (or **Reset** in Stats UI) to get a clean environment before loading new data. It clears
the screenshots in `To_Process`, the `output` folder and the website copy of the report. It **keeps** the history,
`players.csv` and `corrections.csv` unless you say otherwise (and asks about the form file). The Google Drive folder
is never touched. Choose **1 = Archive** (recommended: everything is moved to `Archive\reset_<date>`, nothing is lost) or
**2 = Delete** (permanent, asks you to type DELETE). The program, your settings, the publish setup, `.venv` and
`dev/` are never touched.

## Going live (fresh start for the server)

While testing, keep everything. On launch day:

1. **Form & sheet:** in the Google Form, *Responses -> ⋮ -> Delete all responses*; in the answers spreadsheet, delete
   the test answer rows of the *Form Responses* tab (keep row 1, the headers). Then *505th Stats -> Write
   form_answers.csv now*, so the old file is replaced by an empty one.
2. **Drive folder:** move the test screenshots out of the synced `505th To_Process` folder (to a folder outside it,
   or the Drive bin). Keep `form_answers.csv` and `roster_raw.csv`.
3. **This PC:** browser panel -> *Settings & reset*: tick *Also clear the form file(s)* and *Also clear the history,
   corrections.csv and raids.csv*, leave *players.csv* unticked (the callsign links are real), click **Archive**. That clears
   `To_Process`, `output`, the website copy, the history (deployments, OCR cache, roster log, milestones), corrections
   and raids - all moved to `Archive\reset_<date>`, nothing is lost.
4. **Check the settings you keep:** `players.csv` (remove test names), `milestones.csv`, `settings.json`.
5. **First real run:** *Run & publish*. The roster is read again (everyone starts in their current unit) and the
   published site now only shows real deployments - same address as before.

Optional: delete `Archive\` once you are sure you won't need the test data.

## No Excel? No problem
* **`report.html`** is the main deliverable – double-click it, it opens in any browser, works offline,
  dark/light mode follows your system.
* The `.xlsx` files open in **Google Sheets** (File → Import → Upload), **LibreOffice Calc** (free), or
  Excel for the web (free with a Microsoft account).

## 3. What you get (`output/`)

| File | Content |
|---|---|
| `HD2_stats.xlsx` → **Stats** | one row per player per mission: deployment, date, difficulty, front, mission, file, slot (0 = left / host), player, name read on screen, the 12 stats, flags |
| `HD2_stats.xlsx` → **Review** | only the rows with a doubtful value (yellow cells in Stats) – check these against the screenshot |
| `HD2_stats.xlsx` → **Deployments** | one row per deployment + the matching form entry |
| `HD2_stats.xlsx` → **Errors** | images that could not be read at all (only if any) |
| `stats.csv` | same as the Stats sheet, for pandas / notebooks |
| `review_crops/` | a picture of every flagged value, so checking takes seconds |
| `legacy_All_Operations/` | one file per deployment in the **old All_Operation format** (8 columns, players as rows, 2 blank rows between missions), so `Statsreportv2.ipynb` keeps working |
| **`report.html`** | the server report (see below) |
| **`discord_post.txt`** | ready-to-paste Discord announcement: period as Discord timestamps (each reader sees their own time zone), headline numbers, success rate, front split and the Highlights (fits one Nitro message; `--discord-limit 2000` splits it for non-Nitro) |
| `report_data.xlsx` | the report's numbers as tables: Summary, **Over time** (same columns as the registry's *Treated Data* tab: cumulative kills, casualties, K/C ratio, per front, per operation), By front, By difficulty, By planet, Per week, Highlights, Deployments |

### The report (`report.html`)
Server-wide, not a leaderboard:
* headline numbers: kills, casualties, K/D, deployments, missions, helldivers, accuracy, stratagems, samples, reinforcements;
* **the war over time** – cumulative kills, cumulative casualties, kill/casualty ratio (the three charts of the
  registry's *Graphs* tab) and deployments per week;
* **fronts** – share of deployments (Terminids / Automatons / Illuminates), K/D per front, table with accuracy and
  kills per mission;
* **difficulty** mix, fun totals (missions without dying, melee kills, friendly fire…), **operation success rate**
  and deployments hit by crashes (from the form);
* **highlights** – Top gun, Sharpshooter, Untouchable, Stratagem hero, Guardian angel, Sample hoarder, Melee maniac,
  Stim enthusiast, Oops (friendly fire), Accident report, Deadliest deployment, Flawless execution;
* planets (with sector, from the *PlanetsAndSectors* tab) and the deployment log.

Deployments without a matching form answer are still counted in the totals; the report lists what's missing.

### Checking flagged values (`corrections.csv`)
Some values can't be read with full certainty (blurry digit, number partly hidden, readings that disagree).
They are **never guessed silently**: each run lists them in **`corrections.csv`** (next to `run.bat`).

1. Open `corrections.csv` (Notepad, LibreOffice, Google Sheets…). Each line = one value to check:
   `file, slot (0 = leftmost player), player, stat, value_read, correct_value, readings, screenshot`.
2. Open the `screenshot` (full path of the original image; a close-up of the number is also in `output/review_crops/`).
3. In **`correct_value`** type the right number (e.g. `2073`), or **`ok`** if `value_read` is right. Save.
4. Run `run.bat` again: corrections are applied to every output (Stats, report, Discord post) and the line
   stops showing up as "to check". Your answers stay in the file, so they're re-applied on every future run.

You can also add lines yourself:
* fix any value, even one that wasn't flagged: same columns, `correct_value` filled;
* `stat` = **`form_row`**, `correct_value` = the row number in the form sheet → force which form answer a
  deployment belongs to (put any one file of that deployment in `file`);
* `stat` = **`image`**, `correct_value` = `ok` → clear a "check the whole image" warning.

Mistakes in the **form answers** themselves (wrong date, typo in a callsign) are best fixed directly in the
Google Sheet, then re-download it.

Reading the **notes** column:
* `readings disagree: 12 / 12 / 1 / 2` – the different readings; the majority was kept, please confirm.
* `corrected to 541 by accuracy check` – one reading broke `accuracy = shots_hit / shots_fired`, another reading
  fixed it. Not flagged (the check proves it), listed for transparency.
* `name_check` – the name read on screen looks different from the name in the file name (often just a nickname,
  e.g. *Code* vs *Xcool348_505th*). Informative only.

## 4. Screenshots & file names

* Anything that shows the stat screen works: cropped or **full screen** (tested 1080p and 4K: 48/48 values),
  any resolution, PNG/JPEG/WEBP/BMP/TIFF. Below ~1300 px wide (digits under 14 px tall) every value is double-checked.
* **Tilted images** (e.g. a phone photo of the screen) are straightened automatically (tested up to 6°).
* **Badly used images** never produce silent garbage:
  * not a stat screen → listed in the **Errors** sheet, the other images carry on;
  * only some panels in the picture → those players are read, `name_check` says names don't line up;
  * a panel or the bottom rows cut off → the missing values are flagged, and the whole image is sent to the
    **Review** sheet (`image_check`: "screenshot may be cut off, blurry or tilted").
* The game must be in **English** (the labels *KILLS:*, *ACCURACY:*… are used to find the panels).
* File name: `Host_Player2_Player3_Player4_<mission>.png`, but it is forgiving:
  * `Pengus_Yokai_Inky_Blahaj.PNG`, `..._2.png`, `..._3 .png`, `... (2).png`, `..._2 - Uploader Name.jpg` all work;
    no number = mission 1; missions are ordered by number.
  * Fewer than 4 players on screen (someone left) → names are matched using the names read on screen.
  * Names that don't fit the screen (`Test.png`, `Deploy_A_B_C_D_3.png`) → the names read on screen are used and
    the row says so in `name_check`.
* **Best:** names made by the Google Sheets script (`D20241218052844_Host_P2_P3_P4_1.png`) – exact link to the form answer.
* Otherwise squads are matched with the form by *Host Callsign / Attendee N Callsign*.
  Same squad twice: Windows/Drive copy marks (`... (1).png`) and repeated mission numbers are split into separate
  deployments and matched to the form answers in date order – the Deployments sheet says so in `form_note`.

## 5. How it works (for contributors)

`hd2stats.py`, one process, everything in memory:

1. **Find the layout** – one Tesseract call on a cleaned copy of the image locates the stat labels. Their
   positions give the number of players, panel positions and row spacing, so no pixel coordinates are hard-coded.
2. **Cut each value** – the area right of each label; keep only white/yellow text; keep the right-aligned run of
   digits; drop background noise.
3. **Read the digits** – the game always uses the same font, so each digit is compared with ~2,800 labelled
   samples in `glyphs.npz` (nearest neighbour). That's much faster and more reliable than OCR on 1–3 digit strings
   (Tesseract can't read a lone `0` and misreads `71` as `7`).
4. **Second opinions only when needed** – if a digit is ambiguous, the text is tiny, or the result fails a check,
   the value is re-read (other threshold, 2× upscale, then Tesseract) and the readings vote.
5. **Cross-check** – `accuracy = shots_hit / shots_fired` (to 0.1 %), `shots_hit ≤ shots_fired`, thousands separators
   well-formed. Failing combinations are fixed from the other readings or flagged.

`dev/train_glyphs.py MASS_DEPLOY other_folder` rebuilds `glyphs.npz` (needed only if the game changes its font).
It labels digits automatically: wherever two Tesseract readings agree and the digit count matches, the digits
become samples. Digits smaller than 14 px are skipped because their labels can't be trusted.

**Testing a change:** `dev/tests/answer_key.json` holds 372 values read by eye from 8 screenshots (all in
`Stat Department`: `MASS_DEPLOY`, `Images`, the root folder and `StatImageToText/PyProject/MASS_DEPLOY`).
Run the script on them, then `python dev/tests/check_accuracy.py output/stats.csv`.
Add any screenshot you check by hand to the key.

## 6. Ideas for next steps

* Read the mission / operation name and difficulty if a screenshot of the mission summary is added to the form.
* If people with non-English game clients take part: add their label words to `LABEL_WORDS`.
