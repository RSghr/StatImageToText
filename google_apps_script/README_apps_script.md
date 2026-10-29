# Google Sheets script: unique names for every uploaded screenshot

**Why:** Google Forms keeps whatever name the player gave the file and adds " - Uploader Name"
(`Screenshot 2024-12-20 004519 - Player M.png`, `Pengus_Yokai_Inky_Blahaj_2 - Player N.PNG`…).
Two deployments by the same squad end up with the same names, and badly named files can't be
linked to their form answer at all.

**What the script does:** for every form answer it **copies** the uploaded screenshots (the originals
stay untouched) into a Drive folder called **`505th To_Process`**, renamed from the form itself:

```
D20241218052844_Panini_Rampart_Hillbilly_Checknut_1.png
│               │                                  └ mission number (from the file name, else upload order)
│               └ Host + attendees, exactly as typed in the form
└ submission time of the form answer = unique deployment ID
```

`hd2stats.py` reads the `D…` ID and takes date, operation, planet, difficulty and front from that exact
form answer, so the same squad can deploy as often as it wants.

## Moving, not copying (no double space)

The script **moves and renames** the uploaded screenshots into `505th To_Process` (`moveOriginals: true` in
`CONFIG`). That's fast and takes no extra Drive space; the form's answers still open the files (they point to the
file itself, not to its folder or name). Set `moveOriginals: false` to make copies instead.

If an earlier version already **copied** screenshots: **505th Stats → Free Drive space: put originals that were
already copied in the bin** puts each original that has a renamed copy in the Drive bin (recoverable for 30 days).

Long lists stop after about 4.5 minutes (Google's limit is 6): click the same menu item again to continue.

## form_answers.csv: the form answers without downloading

The script also writes **`form_answers.csv`** into the `505th To_Process` folder and keeps it up to date after every
form answer (and after "Copy & rename"). With **Google Drive for desktop** on the stats PC, that file and the
screenshots arrive by themselves; set the folder once in Stats UI (**Google Drive folder…**).

* Columns whose title contains *mail*, *suggest*, *feedback*, *screenshot*, *upload* or *phone* are left out
  (change `answersSkip` in `CONFIG` if needed). Nothing is published or shared.
* After pasting this new version: reload the sheet, then **505th Stats → Write form_answers.csv now** once.
  The automatic trigger you installed before keeps working (it now also refreshes the file).

## Set it up (5 minutes, once)

> **New form = new responses spreadsheet.** The script lives in the spreadsheet the form writes to. For the new
> *505th Data Deployment Registry* form: in the form editor → **Responses → Link to Sheets** (create a new sheet),
> and install the script there. If you link it to an existing spreadsheet, Google adds a tab like
> *Form Responses 2* – then change `responsesSheet` at the top of the script to that name.

1. Open the **responses spreadsheet** linked to the form (the one with the *Form Responses 1* tab).
2. **Extensions → Apps Script**.
3. Delete what's in the editor, paste the whole content of `RenameUploads.gs`, click **Save** (disk icon).
4. Go back to the spreadsheet and **reload the page**. A **505th Stats** menu appears.
5. **505th Stats → Turn on automatic renaming for new answers**.
   Google asks for permission the first time: *Review permissions* → pick your account →
   "Google hasn't verified this app" → **Advanced → Go to (project name)** → **Allow**.
   (It's your own script; it needs Drive access to copy the screenshots and Sheets access to read the answers.)
6. Done. Existing answers are copied right away, and every new answer is copied automatically.

## Every time you want a report

1. In Google Drive, right-click the **`505th To_Process`** folder → **Download** (Drive makes a .zip).
2. Unzip it into the `To_Process` folder of the program (sub-folders are fine).
3. In the spreadsheet: **File → Download → Microsoft Excel (.xlsx)**, save it next to `run.bat`
   (any name containing `Registry`, or `FormResponses.xlsx`).
4. Double-click **`run.bat`**. The report opens in your browser.

Images already read are remembered, so re-downloading the whole folder each time is fine.

## Menu items

| Item | What it does |
|---|---|
| Copy & rename all screenshots now | processes every answer not copied yet (safe to run any time) |
| Turn on automatic renaming for new answers | installs the on-submit trigger (run once) |
| Forget what was already copied | makes the next "Copy & rename" copy everything again (delete the old copies first) |

## Notes
* Callsigns are cleaned for file names (`Phoenix warrior` → `Phoenixwarrior`), only letters and digits kept.
* If two files of one answer claim the same mission number, upload order is used for all of them.
* Answers without screenshots are listed in the pop-up after "Copy & rename".
* If you rename the *Form Responses 1* tab or the questions, adjust `CONFIG` at the top of the script.

## Planet list for the form (no more one-by-one editing)

The menu also has two planet items. The list lives in the **`PlanetsAndSectors`** tab (column A = planet,
column B = sector, row 1 = headers) – the same tab the report uses to show sectors.

1. First time: **505th Stats → Copy the form's current planet list into the "PlanetsAndSectors" tab**.
2. Edit the tab like any sheet: paste a whole list, delete rows, sort… (duplicates and empty rows are ignored).
3. **505th Stats → Update the form's planet list from the "PlanetsAndSectors" tab**. The dropdown is replaced in one
   go (sorted A→Z, "Other" kept if the question had it) and a pop-up lists what was added / removed.

It edits the existing question, so the responses column stays the same and old answers are untouched.
(Don't delete and re-create the Planet question in the form: that creates a new column in the responses sheet.)
If you already pasted the script before, paste the new version over it and save – the new menu items appear
after reloading the sheet. The first time, Google asks for one more permission (editing your forms).
