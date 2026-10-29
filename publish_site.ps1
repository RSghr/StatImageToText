# 505th report - publish the report online (free static hosting on Cloudflare Pages).
# Permanent address like https://505th-stats.pages.dev - no server, no tunnel, the PC can be off.
# Only index.html, players.html and units.html (+ a few safety headers) are uploaded; nothing else from this folder.
# First run: installs Node.js if needed (winget), then a browser opens to log in to your free
# Cloudflare account once. Log of the last publish: output\publish.log
# -Auto: no questions, no "press Enter" (used by "Run & publish"); stops with a message if the
#        one-time setup (Node.js, Cloudflare login, site name) hasn't been done with a normal publish.
param([string]$Project = '', [switch]$Auto)

$ErrorActionPreference = 'Continue'
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location -LiteralPath $here
try { $Host.UI.RawUI.WindowTitle = '505th report - publish online' } catch {}
$env:WRANGLER_SEND_METRICS = 'false'
$cfgFile  = Join-Path $here 'publish_config.txt'
$addrFile = Join-Path $here 'published_address.txt'
$stage    = Join-Path $here 'output\publish'
$wrangler = 'wrangler@4'

function Fail([string]$msg) {
  Write-Host $msg -ForegroundColor Red
  if (-not $Auto) { Read-Host 'Press Enter to close' }
  exit 1
}
$setupFirst = 'Do one normal "Publish online" first (it sets up Node.js, the Cloudflare login and the site name), then Run & publish works by itself.' 

Write-Host '505th report - publish online' -ForegroundColor Yellow

# 1. the report
$index = Join-Path $here 'htmlReport\index.html'
if (-not (Test-Path -LiteralPath $index)) { $index = Join-Path $here 'output\report.html' }
if (-not (Test-Path -LiteralPath $index)) { Fail 'No report yet - run the report first (Run report / run.bat).' }

Write-Host '[1/4] Preparing the upload (index.html + players.html + units.html only)...'
if (Test-Path -LiteralPath $stage) { Remove-Item -LiteralPath $stage -Recurse -Force }
New-Item -ItemType Directory -Path $stage -Force | Out-Null
Copy-Item -LiteralPath $index -Destination (Join-Path $stage 'index.html')
$players = Join-Path (Split-Path -Parent $index) 'players.html'
if (-not (Test-Path -LiteralPath $players)) { $players = Join-Path $here 'output\players.html' }
if (Test-Path -LiteralPath $players) { Copy-Item -LiteralPath $players -Destination (Join-Path $stage 'players.html') }
$units = Join-Path (Split-Path -Parent $index) 'units.html'
if (-not (Test-Path -LiteralPath $units)) { $units = Join-Path $here 'output\units.html' }
if (Test-Path -LiteralPath $units) { Copy-Item -LiteralPath $units -Destination (Join-Path $stage 'units.html') }
# Safety headers + keep the page out of search engines (only people with the link find it).
Set-Content -LiteralPath (Join-Path $stage '_headers') -Encoding ASCII -Value @'
/*
  X-Frame-Options: DENY
  X-Content-Type-Options: nosniff
  Referrer-Policy: no-referrer
  X-Robots-Tag: noindex, nofollow
'@
Set-Content -LiteralPath (Join-Path $stage 'robots.txt') -Encoding ASCII -Value "User-agent: *`r`nDisallow: /"

# 2. Node.js (wrangler, Cloudflare's upload tool, runs on it)
Write-Host '[2/4] Looking for Node.js...'
function Find-Npx {
  $c = Get-Command npx.cmd -ErrorAction SilentlyContinue
  if ($c) { return $c.Source }
  foreach ($p in @("$env:ProgramFiles\nodejs\npx.cmd", "${env:ProgramFiles(x86)}\nodejs\npx.cmd", "$env:LOCALAPPDATA\Programs\nodejs\npx.cmd")) {
    if ($p -and (Test-Path -LiteralPath $p)) { return $p }
  }
  return $null
}
$npx = Find-Npx
if (-not $npx -and $Auto) { Fail ('Node.js is not installed. ' + $setupFirst) }
if (-not $npx) {
  Write-Host 'Node.js is not installed (needed once, for the upload tool).' -ForegroundColor Yellow
  $ans = Read-Host 'Install Node.js LTS now with winget? (Y/N)'
  if ($ans -match '^[Yy]') {
    winget install --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements
    $env:Path = [Environment]::GetEnvironmentVariable('Path', 'Machine') + ';' + [Environment]::GetEnvironmentVariable('Path', 'User')
    $npx = Find-Npx
  }
  if (-not $npx) { Fail 'Install Node.js LTS from https://nodejs.org , then start publish_site.bat again.' }
}
Write-Host "      found: $npx"

function Wr {
  # run wrangler; output shown live AND returned. Exit code in $LASTEXITCODE.
  & $npx --yes $wrangler @args 2>&1 | ForEach-Object { "$_" } | Tee-Object -Variable lines | Out-Host
  return ($lines -join "`n")
}
function Wr-Quiet {
  $lines = & $npx --yes $wrangler @args 2>&1 | ForEach-Object { "$_" }
  return ($lines -join "`n")
}

# 3. Cloudflare account + project
Write-Host '[3/4] Checking the Cloudflare login (first time: a browser window opens)...'
$who = Wr-Quiet whoami
if ($Auto -and ($LASTEXITCODE -ne 0 -or $who -match 'not authenticated|not logged in|wrangler login')) {
  Fail ('Not logged in to Cloudflare. ' + $setupFirst)
}
if ($LASTEXITCODE -ne 0 -or $who -match 'not authenticated|not logged in|wrangler login') {
  Write-Host '      Log in to (or create) your free Cloudflare account in the browser, then come back here.' -ForegroundColor Yellow
  & $npx --yes $wrangler login
  $who = Wr-Quiet whoami
  if ($LASTEXITCODE -ne 0 -or $who -match 'not authenticated|not logged in') { Fail 'Cloudflare login did not finish. Start publish_site.bat again.' }
}
$acct = ([regex]::Match($who, '(?im)associated with the email\s+(\S+)')).Groups[1].Value.TrimEnd('.')
if ($acct) { Write-Host "      logged in as $acct" }

if (-not $Project -and (Test-Path -LiteralPath $cfgFile)) {
  $m = Select-String -LiteralPath $cfgFile -Pattern '^\s*project\s*=\s*(\S+)' | Select-Object -First 1
  if ($m) { $Project = $m.Matches[0].Groups[1].Value }
}
if (-not $Project -and $Auto) { Fail ('No site name yet. ' + $setupFirst) }
if (-not $Project) {
  Write-Host ''
  Write-Host 'Pick a name for the site. It becomes the address: https://<name>.pages.dev'
  Write-Host '(lowercase letters, digits and dashes; if the name is taken worldwide, Cloudflare adds a few letters)'
  do {
    $Project = (Read-Host 'Site name [505th-stats]').Trim().ToLower()
    if (-not $Project) { $Project = '505th-stats' }
    $ok = $Project -match '^[a-z0-9][a-z0-9-]{0,56}[a-z0-9]$'
    if (-not $ok) { Write-Host '  Only a-z, 0-9 and dashes, 2 to 58 characters, not starting/ending with a dash.' -ForegroundColor Yellow }
  } until ($ok)
}

function Get-Projects {
  $j = Wr-Quiet pages project list --json
  $a = $j.IndexOf('['); $b = $j.LastIndexOf(']')
  if ($a -lt 0 -or $b -le $a) { return @() }
  try { return @($j.Substring($a, $b - $a + 1) | ConvertFrom-Json) } catch { return @() }
}
$projects = Get-Projects
$mine = $projects | Where-Object { $_.'Project Name' -eq $Project } | Select-Object -First 1
if (-not $mine) {
  Write-Host "      creating the site '$Project'..."
  Wr pages project create $Project --production-branch=main | Out-Null
  if ($LASTEXITCODE -ne 0) { Fail "Could not create the site '$Project' (see the message above). Try another name: delete publish_config.txt and start again." }
  $mine = Get-Projects | Where-Object { $_.'Project Name' -eq $Project } | Select-Object -First 1
}
Set-Content -LiteralPath $cfgFile -Value "project=$Project"

# 4. upload
Write-Host '[4/4] Uploading...'
# Relative path on purpose: npx is a .cmd file and cmd.exe breaks full paths containing '&'.
$log = Wr pages deploy 'output/publish' --project-name=$Project --branch=main --commit-dirty=true
$log | Set-Content -LiteralPath (Join-Path $here 'output\publish.log')
if ($LASTEXITCODE -ne 0) { Fail 'The upload failed (see the message above, also in output\publish.log).' }

$domain = ''
if ($mine -and $mine.'Project Domains') { $domain = (("$($mine.'Project Domains')" -split '[,\s]+') | Where-Object { $_ -match '\.pages\.dev$' } | Select-Object -First 1) }
if (-not $domain) { $domain = "$Project.pages.dev" }
$url = "https://$domain"
Set-Content -LiteralPath $addrFile -Value $url
try { Set-Clipboard -Value $url } catch {}

Write-Host ''
Write-Host '  ============================================================' -ForegroundColor Yellow
Write-Host '   THE REPORT IS PUBLISHED AT:' -ForegroundColor Yellow
Write-Host ''
Write-Host "     $url" -ForegroundColor Cyan
Write-Host ''
Write-Host '   (copied to the clipboard - this address never changes)' -ForegroundColor Yellow
Write-Host '  ============================================================' -ForegroundColor Yellow
Write-Host ''
Write-Host 'Next time: run the report, then publish again - same address, new content.'
Write-Host '(A brand-new site can take a minute or two before the address works.)'
if (-not $Auto) { Read-Host 'Press Enter to close' }
