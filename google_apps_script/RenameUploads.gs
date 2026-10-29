/**
 * 505th Stat Department - give every uploaded stat screenshot a unique, clean name.
 *
 * Paste this into the responses spreadsheet: Extensions > Apps Script (see README_apps_script.md).
 *
 * For each form response it MOVES the uploaded screenshots into a Drive folder called
 * "505th To_Process" and renames them (CONFIG.moveOriginals = false makes copies instead):
 *
 *     D<submission time>_<Host>_<Attendee1>_<Attendee2>_<Attendee3>_<mission>.<ext>
 *     e.g.  D20241218052844_Panini_Rampart_Hillbilly_Checknut_2.png
 *
 * - The "D<submission time>" part is unique per response, so the same squad can deploy as often
 *   as it likes, and hd2stats.py links every image to the right form row (date, operation,
 *   planet, difficulty, front) using it.
 * - Names come from the form, so it doesn't matter how the player named the files
 *   ("Screenshot 2024-12-20 004519.png" works).
 * - Mission number: taken from the original file name if it ends with one (_1, _2, _3, " 2"...),
 *   otherwise the upload order is used.
 * - It also keeps "form_answers.csv" up to date in the same folder (no e-mail addresses), so with
 *   Google Drive for desktop the stats PC receives screenshots AND form answers without downloading.
 * - Upload-only form (just the Deployment Register screenshot + the 3 stat screens): works too.
 *   Files are named D<submission time>_Deployment_<n>; hd2stats.py reads date, operation, planet,
 *   difficulty, faction and callsigns from the register screenshot.
 */

var CONFIG = {
  responsesSheet: 'Form Responses 1',     // if not found, the first "Form Responses ..." tab is used
  targetFolderName: '505th To_Process',
  // true = MOVE + rename the uploaded files into the folder (fast, no extra Drive space; the form's
  //        answers keep working - they point to the file, not to its folder or name)
  // false = make renamed COPIES and leave the originals where the form put them (uses twice the space)
  moveOriginals: true,
  answersFileName: 'form_answers.csv',    // written into the folder above, for Drive for desktop to sync
  // columns never written to form_answers.csv (privacy / not needed): matched anywhere in the header
  answersSkip: /mail|suggest|feedback|screenshot|upload|phone/i,
  // company roster tabs (mirrors of the roster sheet) -> roster_raw.csv in the same folder.
  // Only function, callsign, unit and status are written - never the Discord IDs (column E).
  rosterTabs: /company/i,
  rosterFileName: 'roster_raw.csv',
  planetsSheet: 'PlanetsAndSectors',      // planet list: column A = planet, column B = sector (row 1 = headers)
  planetQuestion: 'Planet',               // title of the planet question in the form
  columns: {
    timestamp: 'Timestamp',
    // the callsign headers only have to START with these (you can add "(first from the left)" etc.)
    host: 'Host Callsign',
    a1: 'Attendee 1 Callsign',
    a2: 'Attendee 2 Callsign',
    a3: 'Attendee 3 Callsign',
    screenshots: 'Mission screenshots'   // the header only has to START with this
  }
};

/** Adds a "505th Stats" menu to the spreadsheet. */
function onOpen() {
  SpreadsheetApp.getUi()
    .createMenu('505th Stats')
    .addItem('Copy & rename all screenshots now', 'processAllResponses')
    .addItem('Turn on automatic renaming for new answers', 'installTrigger')
    .addItem('Forget what was already copied (re-copy everything)', 'resetProcessed')
    .addItem('Free Drive space: put originals that were already copied in the bin', 'trashCopiedOriginals')
    .addItem('Write ' + CONFIG.answersFileName + ' now', 'writeAnswersNow')
    .addItem('Write ' + CONFIG.rosterFileName + ' (company rosters) now', 'writeRosterNow')
    .addSeparator()
    .addItem('Update the form\'s planet list from the "' + CONFIG.planetsSheet + '" tab', 'updatePlanetDropdown')
    .addItem('Copy the form\'s current planet list into the "' + CONFIG.planetsSheet + '" tab', 'exportPlanetList')
    .addToUi();
}

/** Run once: every new form answer is then processed automatically. */
function installTrigger() {
  var ss = SpreadsheetApp.getActive();
  ScriptApp.getProjectTriggers().forEach(function (t) {
    var h = t.getHandlerFunction();
    if (h === 'onFormSubmitRename' || h === 'onSheetEdit' || h === 'dailyRoster') ScriptApp.deleteTrigger(t);
  });
  ScriptApp.newTrigger('dailyRoster').timeBased().everyDays(1).atHour(5).create();
  ScriptApp.newTrigger('onFormSubmitRename').forSpreadsheet(ss).onFormSubmit().create();
  // editing an answer directly in the sheet (a typo in a date...) also refreshes form_answers.csv
  ScriptApp.newTrigger('onSheetEdit').forSpreadsheet(ss).onEdit().create();
  processAllResponses();
  ui_('Automatic renaming is on. Existing answers were processed too.\n\nScreenshots go to the Drive folder "' +
      CONFIG.targetFolderName + '".\nEditing an answer in this sheet now updates ' + CONFIG.answersFileName +
      ' automatically.');
}

/** Trigger handler: an answer was edited in the sheet -> rewrite form_answers.csv (answer tabs only). */
function onSheetEdit(e) {
  try {
    var sh = e && e.range ? e.range.getSheet() : null;
    if (sh && CONFIG.rosterTabs.test(sh.getName())) { exportRoster_(); return; }
    if (sh && !/^Form Responses/i.test(sh.getName()) && sh.getName() !== CONFIG.responsesSheet) return;
    exportAnswers_();
  } catch (err) { Logger.log(err); }
}

/** Daily trigger: the roster tabs are mirrors (their updates don't fire edit triggers). */
function dailyRoster() {
  try { exportRoster_(); } catch (err) { Logger.log(err); }
}

/** Menu: write roster_raw.csv now. */
function writeRosterNow() {
  var n = exportRoster_();
  ui_(n + ' roster rows written to "' + CONFIG.rosterFileName + '" in the Drive folder "' + CONFIG.targetFolderName +
      '".\n(Only function, callsign, unit and status - no Discord IDs.)');
}

/**
 * The company roster tabs as a small CSV: tab, row, company title, function (C), callsign (D), unit (G),
 * status (N). Empty slots are skipped. The stats program works out platoon / detachment / squad from it.
 */
function exportRoster_() {
  var ss = SpreadsheetApp.getActive();
  var tz = ss.getSpreadsheetTimeZone();
  var q = function (v) { return '"' + String(v === null || v === undefined ? '' : v).replace(/"/g, '""') + '"'; };
  var lines = [['tab', 'row', 'company', 'function', 'callsign', 'unit', 'status'].map(q).join(',')];
  var n = 0;
  ss.getSheets().forEach(function (sh) {
    if (!CONFIG.rosterTabs.test(sh.getName()) || /^Form Responses/i.test(sh.getName())) return;
    var last = sh.getLastRow();
    if (last < 1) return;
    var v = sh.getRange(1, 1, last, Math.min(sh.getLastColumn(), 14)).getDisplayValues();
    // company name: the first cell near the top that says "company" (e.g. "EU COMPANY 1"), otherwise the tab name
    var title = '';
    for (var r = 0; r < Math.min(6, v.length) && !title; r++) {
      for (var c = 0; c < v[r].length && !title; c++) {
        var t = String(v[r][c]).trim();
        if (/company/i.test(t) && t.length <= 40) title = t;
      }
    }
    if (!title) title = sh.getName();
    for (var i = 0; i < v.length; i++) {
      var fn = String(v[i][2] || '').trim(), cs = String(v[i][3] || '').trim();
      var unit = String(v[i][6] || '').trim(), st = String(v[i][13] || '').trim();
      var header = /platoon/i.test(fn) && !cs;               // "HASTATI PLATOON" rows
      if (!header && (!cs || /^empty$/i.test(st) || /^function$/i.test(fn))) continue;   // empty slot / column titles
      lines.push([sh.getName(), i + 1, title, fn, cs, unit, st].map(q).join(','));
      if (!header) n++;
    }
  });
  lines.push('');
  var csv = lines.join('\r\n');
  var folder = targetFolder_();
  var it = folder.getFilesByName(CONFIG.rosterFileName);
  if (it.hasNext()) it.next().setContent(csv);
  else folder.createFile(CONFIG.rosterFileName, csv, MimeType.CSV);
  return n;
}

/** Trigger handler for new answers. */
function onFormSubmitRename(e) {
  var sheet = e && e.range ? e.range.getSheet() : sheet_();
  processRow_(sheet, e && e.range ? e.range.getRow() : sheet.getLastRow());
  exportAnswers_();
}

/** Process every answer that wasn't processed yet. */
function processAllResponses() {
  var sheet = sheet_();
  var last = sheet.getLastRow();
  var copied = 0, problems = [], started = Date.now(), unfinished = false;
  for (var r = 2; r <= last; r++) {
    if (Date.now() - started > 4.5 * 60 * 1000) { unfinished = true; break; }   // Google stops scripts at 6 min
    var res = processRow_(sheet, r);
    copied += res.copied;
    problems = problems.concat(res.problems);
  }
  var nAns = exportAnswers_();
  try { exportRoster_(); } catch (err) { Logger.log(err); }
  var msg = copied + ' screenshot(s) ' + (CONFIG.moveOriginals ? 'moved' : 'copied') + ' to "' +
            CONFIG.targetFolderName + '".\n' +
            nAns + ' form answers written to ' + CONFIG.answersFileName + ' in the same folder.';
  if (unfinished) msg += '\n\nNot finished yet (Google limits how long a script runs): click the same menu item ' +
                         'again to continue where it stopped.';
  if (problems.length) msg += '\n\nProblems:\n- ' + problems.slice(0, 20).join('\n- ');
  ui_(msg);
}

/** Menu: (re)write form_answers.csv now. */
function writeAnswersNow() {
  var n = exportAnswers_();
  ui_(n + ' form answers written to "' + CONFIG.answersFileName + '" in the Drive folder "' +
      CONFIG.targetFolderName + '".\n\nWith Google Drive for desktop the stats PC gets it automatically.');
}

/**
 * Write the form answers as a CSV file into the "505th To_Process" folder, so the stats PC gets them
 * through Google Drive for desktop together with the screenshots - no download, nothing made public.
 * E-mail addresses, suggestions and upload links are left out (CONFIG.answersSkip).
 */
function exportAnswers_() {
  var sheet = sheet_();
  var data = sheet.getDataRange().getValues();
  if (!data.length) return 0;
  var tz = SpreadsheetApp.getActive().getSpreadsheetTimeZone();
  var keep = [];
  data[0].forEach(function (h, i) { if (String(h).trim() && !CONFIG.answersSkip.test(String(h))) keep.push(i); });
  var cell = function (v) {
    if (v instanceof Date) v = Utilities.formatDate(v, tz, 'yyyy-MM-dd HH:mm:ss');
    v = String(v === null || v === undefined ? '' : v);
    return '"' + v.replace(/"/g, '""') + '"';
  };
  var lines = [keep.map(function (i) { return cell(data[0][i]); }).join(',')];
  var n = 0;
  for (var r = 1; r < data.length; r++) {
    if (!(data[r][0] instanceof Date) && !String(data[r][0]).trim()) continue;   // empty row
    lines.push(keep.map(function (i) { return cell(data[r][i]); }).join(','));
    n++;
  }
  var csv = lines.join('\r\n') + '\r\n';
  var folder = targetFolder_();
  var it = folder.getFilesByName(CONFIG.answersFileName);
  if (it.hasNext()) it.next().setContent(csv);
  else folder.createFile(CONFIG.answersFileName, csv, MimeType.CSV);
  return n;
}

/**
 * Menu: free Drive space after the old "copy" mode. For every answer already handled, an original upload
 * that has a renamed copy (same size) in the 505th To_Process folder is put in the Drive bin
 * (recoverable for 30 days). The copies stay. The form's answer page then can't show those originals.
 */
function trashCopiedOriginals() {
  var ui = null;
  try { ui = SpreadsheetApp.getUi(); } catch (e) {}
  if (ui && ui.alert('Free Drive space', 'Put the original uploads that already have a renamed copy in "' +
      CONFIG.targetFolderName + '" in the Drive bin?\n(Recoverable from the bin for 30 days. The copies stay.)',
      ui.ButtonSet.OK_CANCEL) !== ui.Button.OK) return;
  var sheet = sheet_();
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var data = sheet.getDataRange().getValues();
  var tz = SpreadsheetApp.getActive().getSpreadsheetTimeZone();
  var folder = targetFolder_();
  var folderId = folder.getId();
  var copies = {};                                   // depId -> sizes of its copies
  var it = folder.getFiles();
  while (it.hasNext()) {
    var f = it.next();
    var m = f.getName().match(/^(D\d{14})_/);
    if (m) (copies[m[1]] = copies[m[1]] || []).push(f.getSize());
  }
  var shotCol = -1;
  headers.forEach(function (h, i) { if (shotCol < 0 && String(h).trim().indexOf(CONFIG.columns.screenshots) === 0) shotCol = i; });
  var trashed = 0, freed = 0, started = Date.now(), unfinished = false;
  for (var r = 1; r < data.length; r++) {
    if (Date.now() - started > 4.5 * 60 * 1000) { unfinished = true; break; }
    var ts = data[r][0];
    if (!(ts instanceof Date)) continue;
    var depId = 'D' + Utilities.formatDate(ts, tz, 'yyyyMMddHHmmss');
    var sizes = (copies[depId] || []).slice();
    if (!sizes.length) continue;
    var links = shotCol >= 0 ? String(data[r][shotCol]) :
      data[r].filter(function (v) { return /drive\.google\.com/.test(String(v)); }).join(', ');
    (links.match(/id=[\w-]+/g) || []).forEach(function (s) {
      try {
        var f = DriveApp.getFileById(s.slice(3));
        if (f.isTrashed()) return;
        var parents = f.getParents();
        while (parents.hasNext()) { if (parents.next().getId() === folderId) return; }   // it IS the moved file
        var k = sizes.indexOf(f.getSize());
        if (k < 0) return;
        sizes.splice(k, 1);
        freed += f.getSize();
        f.setTrashed(true);
        trashed++;
      } catch (err) { /* already gone */ }
    });
  }
  ui_(trashed + ' original upload(s) put in the bin (' + Math.round(freed / 1048576) + ' MB freed once the bin is emptied).' +
      (unfinished ? '\n\nNot finished yet: click the same menu item again to continue.' : ''));
}

function resetProcessed() {
  PropertiesService.getDocumentProperties().deleteAllProperties();
  ui_('Done. "Copy & rename" will copy every answer again (delete the old copies in the folder first).');
}

// ---------------------------------------------------------------------------

function processRow_(sheet, row) {
  var out = { copied: 0, problems: [] };
  var headers = sheet.getRange(1, 1, 1, sheet.getLastColumn()).getValues()[0];
  var values = sheet.getRange(row, 1, 1, headers.length).getValues()[0];
  var col = function (name, prefix) {
    for (var i = 0; i < headers.length; i++) {
      var h = String(headers[i]).trim();
      if (prefix ? h.indexOf(name) === 0 : h === name) return values[i];
    }
    return '';
  };

  var ts = col(CONFIG.columns.timestamp);
  if (!(ts instanceof Date)) return out;                     // empty row
  var tz = SpreadsheetApp.getActive().getSpreadsheetTimeZone();
  var depId = 'D' + Utilities.formatDate(ts, tz, 'yyyyMMddHHmmss');

  var props = PropertiesService.getDocumentProperties();
  if (props.getProperty(depId)) return out;                  // already done

  var names = [CONFIG.columns.host, CONFIG.columns.a1, CONFIG.columns.a2, CONFIG.columns.a3]
    .map(function (c) { return clean_(col(c, true)); })     // header only has to START with it ("Host Callsign (left)")
    .filter(function (n) { return n; });
  if (!names.length) names = ['Deployment'];   // upload-only form: the register screenshot has the names

  var links = String(col(CONFIG.columns.screenshots, true) || '');
  if (!/id=/.test(links)) {                     // upload question renamed: take every column with Drive links
    links = values.filter(function (v) { return /drive\.google\.com/.test(String(v)); }).join(', ');
  }
  var ids = (links.match(/id=[\w-]+/g) || []).map(function (s) { return s.slice(3); });
  if (!ids.length) {
    out.problems.push('row ' + row + ' (' + names[0] + '): no screenshots uploaded');
    props.setProperty(depId, 'no files');
    return out;
  }

  var files = [];
  ids.forEach(function (id, i) {
    try {
      var f = DriveApp.getFileById(id);
      files.push({ file: f, order: i + 1, num: missionNumber_(f.getName()), ext: ext_(f.getName()) });
    } catch (err) {
      out.problems.push('row ' + row + ' (' + names[0] + '): cannot open file ' + id + ' (' + err + ')');
    }
  });

  // Numbers from the file names win; files without one get the smallest free number
  // (e.g. "Squad.png", "Squad_2.png", "Squad_3.png" -> 1, 2, 3). If two files claim the same
  // number, fall back to upload order for all of them.
  var nums = files.map(function (x) { return x.num; });
  var given = nums.filter(function (n) { return n !== null; });
  var clash = given.some(function (n, i) { return given.indexOf(n) !== i; });
  var free = 1;
  files.forEach(function (x) {
    if (clash) { x.final = x.order; return; }
    if (x.num !== null) { x.final = x.num; return; }
    while (given.indexOf(free) !== -1) free++;
    x.final = free; given.push(free);
  });

  var folder = targetFolder_();
  files.forEach(function (x) {
    var n = x.final;
    var newName = depId + '_' + names.join('_') + '_' + n + '.' + x.ext;
    if (CONFIG.moveOriginals) {
      try {
        x.file.setName(newName);
        x.file.moveTo(folder);
      } catch (err) {                       // e.g. a file you don't own: fall back to a copy
        x.file.makeCopy(newName, folder);
        out.problems.push('row ' + row + ': could not move ' + newName + ', copied it instead (' + err + ')');
      }
    } else {
      x.file.makeCopy(newName, folder);
    }
    out.copied++;
  });
  props.setProperty(depId, 'done');
  return out;
}

function missionNumber_(name) {
  var stem = name.replace(/\.[^.]+$/, '');          // drop extension
  stem = stem.split(/\s+-\s+/)[0];                  // drop " - Uploader Name"
  stem = stem.replace(/\s*\(\d+\)\s*$/, '');        // drop " (1)" copy marks
  var m = stem.match(/(?:^|[_\s-])(\d{1,2})\s*$/);
  if (!m) return null;
  var n = parseInt(m[1], 10);
  return n >= 1 && n <= 9 ? n : null;               // "Screenshot 2024-12-20 004519" -> null
}

function ext_(name) {
  var m = name.match(/\.([A-Za-z0-9]+)$/);
  return m ? m[1].toLowerCase() : 'png';
}

function clean_(v) {
  return String(v || '').replace(/[^A-Za-z0-9]/g, '');  // "Phoenix warrior" -> "Phoenixwarrior"
}

function sheet_() {
  var ss = SpreadsheetApp.getActive();
  var s = ss.getSheetByName(CONFIG.responsesSheet);
  if (!s) {
    s = ss.getSheets().filter(function (sh) { return /^Form Responses/i.test(sh.getName()); })[0];
  }
  if (!s) throw new Error('No "Form Responses" tab found in this spreadsheet');
  return s;
}

// ---------------------------------------------------------------------------
// Planet dropdown: edit the list in a sheet tab, push it to the form in one click
// ---------------------------------------------------------------------------

/** Replace the choices of the form's planet question with column A of the planets tab. */
function updatePlanetDropdown() {
  var item = planetItem_();
  var sh = SpreadsheetApp.getActive().getSheetByName(CONFIG.planetsSheet);
  if (!sh) {
    ui_('No "' + CONFIG.planetsSheet + '" tab yet.\n\nUse "Copy the form\'s current planet list into the tab" first, ' +
        'edit the list there, then run this again.');
    return;
  }
  var last = sh.getLastRow();
  var raw = last >= 2 ? sh.getRange(2, 1, last - 1, 1).getValues() : [];
  var seen = {}, names = [];
  raw.forEach(function (r) {
    var n = String(r[0] || '').trim();
    var key = n.toLowerCase();
    if (n && !seen[key] && key !== 'other') { seen[key] = true; names.push(n); }
  });
  if (!names.length) { ui_('The "' + CONFIG.planetsSheet + '" tab has no planet names in column A (from row 2).'); return; }
  names.sort(function (a, b) { return a.localeCompare(b); });

  var before = currentChoices_(item);
  var hadOther = before.some(function (c) { return c.toLowerCase() === 'other'; });
  var type = item.getType();
  if (type === FormApp.ItemType.LIST) {
    // dropdowns have no built-in "Other" box: keep a plain "Other" choice if there was one
    item.asListItem().setChoiceValues(hadOther ? names.concat(['Other']) : names);
  } else if (type === FormApp.ItemType.MULTIPLE_CHOICE) {
    var mc = item.asMultipleChoiceItem();
    mc.setChoiceValues(names);
    if (hadOther) mc.showOtherOption(true);
  } else {
    ui_('The "' + CONFIG.planetQuestion + '" question must be a Dropdown or Multiple choice question.');
    return;
  }
  var added = names.filter(function (n) { return before.indexOf(n) === -1; });
  var removed = before.filter(function (n) { return n.toLowerCase() !== 'other' && names.indexOf(n) === -1; });
  ui_('Planet list updated: ' + names.length + ' planets.\n\n' +
      'Added (' + added.length + '): ' + (added.slice(0, 15).join(', ') || '-') + (added.length > 15 ? ', ...' : '') + '\n' +
      'Removed (' + removed.length + '): ' + (removed.slice(0, 15).join(', ') || '-') + (removed.length > 15 ? ', ...' : '') +
      '\n\nOld answers are not changed.');
}

/** Write the form's current planet choices into the planets tab (keeps existing sectors). */
function exportPlanetList() {
  var item = planetItem_();
  var choices = currentChoices_(item).filter(function (c) { return c.toLowerCase() !== 'other'; });
  var ss = SpreadsheetApp.getActive();
  var sh = ss.getSheetByName(CONFIG.planetsSheet);
  var sectors = {};
  if (sh) {
    var last = sh.getLastRow();
    if (last >= 2) sh.getRange(2, 1, last - 1, 2).getValues().forEach(function (r) {
      var k = String(r[0] || '').trim().toLowerCase();
      if (k && (r[1] || !(k in sectors))) sectors[k] = r[1];   // a duplicate row never wipes a sector
    });
    sh.clearContents();
  } else {
    sh = ss.insertSheet(CONFIG.planetsSheet);
  }
  var rows = [['Planet', 'Sector']].concat(choices.map(function (c) { return [c, sectors[c.toLowerCase()] || '']; }));
  sh.getRange(1, 1, rows.length, 2).setValues(rows);
  sh.setFrozenRows(1);
  ui_(choices.length + ' planets copied into the "' + CONFIG.planetsSheet + '" tab.\n\n' +
      'Add / delete / paste rows there (column A), then use "Update the form\'s planet list".');
}

function planetItem_() {
  var url = SpreadsheetApp.getActive().getFormUrl();
  if (!url) throw new Error('This spreadsheet is not linked to a form (Form editor > Responses > Link to Sheets).');
  var form = FormApp.openByUrl(url);
  var want = CONFIG.planetQuestion.trim().toLowerCase();
  var item = form.getItems().filter(function (it) { return it.getTitle().trim().toLowerCase() === want; })[0];
  if (!item) throw new Error('No question titled "' + CONFIG.planetQuestion + '" in the form.');
  return item;
}

function currentChoices_(item) {
  var t = item.getType();
  var choices = [];
  if (t === FormApp.ItemType.LIST) choices = item.asListItem().getChoices();
  else if (t === FormApp.ItemType.MULTIPLE_CHOICE) choices = item.asMultipleChoiceItem().getChoices();
  return choices.map(function (c) { return c.getValue(); });
}

function targetFolder_() {
  var it = DriveApp.getFoldersByName(CONFIG.targetFolderName);
  return it.hasNext() ? it.next() : DriveApp.createFolder(CONFIG.targetFolderName);
}

function ui_(msg) {
  try { SpreadsheetApp.getUi().alert(msg); } catch (e) { Logger.log(msg); }
}
