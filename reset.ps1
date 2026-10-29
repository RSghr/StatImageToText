# 505th Stat Department - reset: clear the data to start a fresh batch.
# Clears: screenshots in To_Process, the output folder, the website copy of the report
#         (htmlReport\index.html, players.html, units.html) and, if you want,
#         the form file(s), the history (+ corrections.csv, raids.csv, roster & milestone logs) and players.csv.
# Keeps by default: history\ (every deployment), players.csv (who is who), corrections.csv (fixes by hand).
# Never touches the Google Drive folder.
# Never touches the program, glyphs.npz, milestones.csv, settings, the publish setup, .venv or dev\.
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $here

# Form-answer files only: .xlsx, or .csv whose first line has the "Host Callsign" column.
# Never players.csv / corrections.csv / other spreadsheets.
function Get-FormFiles {
  Get-ChildItem -LiteralPath $here -File | Where-Object {
    ($_.Extension -in '.xlsx', '.csv') -and ($_.Name -notin 'corrections.csv', 'players.csv') -and
    ($_.Name -notlike '~$*') -and (
      $_.Extension -eq '.xlsx' -or
      ((Get-Content -LiteralPath $_.FullName -TotalCount 1 -ErrorAction SilentlyContinue) -match 'Host\s*Callsign'))
  }
}

function Items-To-Clear([bool]$withForms, [bool]$withHistory, [bool]$withPlayers) {
  $list = @()
  if (Test-Path -LiteralPath 'To_Process') {
    $list += Get-ChildItem -LiteralPath 'To_Process' -Force | Where-Object { $_.Name -ne 'PUT_SCREENSHOTS_HERE.txt' }
  }
  foreach ($p in @('output', 'htmlReport\index.html', 'htmlReport\players.html', 'htmlReport\units.html')) {
    if (Test-Path -LiteralPath $p) { $list += Get-Item -LiteralPath $p -Force }
  }
  if ($withHistory) {
    foreach ($p in @('history', 'corrections.csv', 'raids.csv')) {
      if (Test-Path -LiteralPath $p) { $list += Get-Item -LiteralPath $p -Force }
    }
  }
  if ($withPlayers -and (Test-Path -LiteralPath 'players.csv')) { $list += Get-Item -LiteralPath 'players.csv' -Force }
  if ($withForms) { $list += @(Get-FormFiles) }
  return $list
}

Write-Host '505th Stat Department - RESET' -ForegroundColor Yellow
Write-Host ''
$forms = @(Get-FormFiles)
$withForms = $false
if ($forms.Count -gt 0) {
  Write-Host 'Form answer file(s) found:'
  $forms | ForEach-Object { Write-Host "   $($_.Name)" }
  $a = Read-Host 'Clear them too? (Y/N - N keeps them, the newest one is used next time)'
  $withForms = ($a -match '^[Yy]')
}

$nHist = 0
if (Test-Path -LiteralPath 'history\deployments.csv') { $nHist = @(Import-Csv -LiteralPath 'history\deployments.csv').Count }
Write-Host "The history has $nHist deployment(s); it is KEPT unless you say so."
$a = Read-Host 'Also clear the history, corrections.csv and raids.csv, to start again from zero? (Y/N)'
$withHistory = ($a -match '^[Yy]')
$withPlayers = $false
if (Test-Path -LiteralPath 'players.csv') {
  $a = Read-Host 'Also forget who is who (players.csv)? (Y/N - N recommended)'
  $withPlayers = ($a -match '^[Yy]')
}

$items = @(Items-To-Clear $withForms $withHistory $withPlayers)
if ($items.Count -eq 0) {
  Write-Host 'Nothing to clear - the environment is already clean.' -ForegroundColor Green
  Read-Host 'Press Enter to close'; exit 0
}

$tp = (Join-Path $here 'To_Process') + [IO.Path]::DirectorySeparatorChar
$shots = @($items | Where-Object { $_.FullName.StartsWith($tp) }).Count
Write-Host ''
Write-Host 'This will clear:'
Write-Host ("   {0} file(s)/folder(s) in To_Process (screenshots)" -f $shots)
foreach ($i in $items | Where-Object { -not $_.FullName.StartsWith($tp) }) {
  Write-Host ("   {0}" -f ($i.FullName.Substring($here.Length).TrimStart('\', '/')))
}
Write-Host ''
Write-Host '  1 = Archive  (move everything to Archive\reset_<date> - recommended, nothing is lost)'
Write-Host '  2 = Delete   (permanently)'
Write-Host '  3 = Cancel'
$choice = Read-Host 'Choice'

if ($choice -eq '1') {
  $dest = Join-Path $here ('Archive\reset_' + (Get-Date -Format 'yyyy-MM-dd_HHmm'))
  New-Item -ItemType Directory -Path $dest -Force | Out-Null
  foreach ($i in $items) {
    $rel = $i.FullName.Substring($here.Length).TrimStart('\', '/')
    $target = Join-Path $dest $rel
    New-Item -ItemType Directory -Path (Split-Path $target -Parent) -Force | Out-Null
    Move-Item -LiteralPath $i.FullName -Destination $target -Force
  }
  Write-Host "Done. Everything was moved to $dest" -ForegroundColor Green
} elseif ($choice -eq '2') {
  $c = Read-Host 'Type DELETE to confirm permanent deletion'
  if ($c -ne 'DELETE') { Write-Host 'Cancelled, nothing was changed.'; Read-Host 'Press Enter to close'; exit 0 }
  foreach ($i in $items) { Remove-Item -LiteralPath $i.FullName -Recurse -Force }
  Write-Host 'Done. Data deleted.' -ForegroundColor Green
} else {
  Write-Host 'Cancelled, nothing was changed.'
  Read-Host 'Press Enter to close'; exit 0
}

if (-not (Test-Path -LiteralPath 'To_Process')) { New-Item -ItemType Directory -Path 'To_Process' | Out-Null }
Write-Host ''
Write-Host 'Clean environment ready: new screenshots in To_Process (or the Google Drive folder), then run.bat.'
Read-Host 'Press Enter to close'
