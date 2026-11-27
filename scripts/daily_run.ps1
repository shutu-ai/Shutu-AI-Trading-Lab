# Shutu AI Trading Lab — daily operational runner (Windows 11 / PowerShell 7+)
# Task BUSINESS-V03-OPERATIONAL-ACTIVATION-20261127-R1 T3-D.
#
# USAGE (single manual run first — this is the acceptance path):
#   pwsh -File scripts\daily_run.ps1 -Asof 2026-11-27T22:00:00Z `
#        -SnapshotDir C:\shutu\data\historical_research `
#        -StateDir    C:\shutu\state\daily `
#        -OutputDir   C:\shutu\runs\2026-11-27
#
# SCHEDULED-DAILY (schtasks) — install ONLY after the operator has
# separately authorized (1) sustained scheduling and (2) the data-update
# authorization. Task doc §8 card C. Example registration:
#   schtasks /Create /TN "ShutuDailyRun" /SC DAILY /ST 22:30 /TR ^
#     "pwsh -File C:\dev-projects\Shutu-AI-Trading-Lab\scripts\daily_run.ps1 ^
#      -SnapshotDir C:\shutu\data\historical_research ^
#      -StateDir C:\shutu\state\daily -OutputDir C:\shutu\runs" ^
#      /RU "$env:USERNAME"
# The script derives --asof from the current UTC time when not passed.
#
# EXIT CODES (do NOT read 0 as "a trade happened"):
#   0 = cycle completed (action may be PENDING / NO_TRADE / EXECUTED /
#       REJECTED / CALENDAR_BLOCKED — read summary.json .action)
#   2 = usage / argument refusal (fail-closed)
#   4 = HALT (state reconciliation failed; operator decision required)
#   5 = infrastructure failure (missing venv / snapshot dir)
#
# Honesty: the mock account PnL is not strategy effectiveness; real
# broker orders are 0; forward days are counted only from genuinely
# observed sessions (REPLAY_MOCK where applicable).
param(
    [string]$Asof = "",
    [Parameter(Mandatory = $true)][string]$SnapshotDir,
    [Parameter(Mandatory = $true)][string]$StateDir,
    [Parameter(Mandatory = $true)][string]$OutputDir,
    [string]$InfoFile = "",
    [string]$RepoRoot = ""
)

$ErrorActionPreference = "Stop"

# --- resolve repo root & venv -------------------------------------------------
if (-not $RepoRoot) {
    $RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
}
$VenvPython = Join-Path $RepoRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    # fall back to the launcher-created venv at the repo root of the
    # main checkout when running from a worktree
    $Alt = Get-ChildItem -Path (Join-Path $RepoRoot "..") -Filter ".venv" `
        -Directory -ErrorAction SilentlyContinue |
        Select-Object -First 1
    if ($Alt) { $VenvPython = Join-Path $Alt.FullName "Scripts\python.exe" }
}
if (-not (Test-Path $VenvPython)) {
    Write-Error "venv python not found under $RepoRoot — create it first: py -3.13 -m venv .venv; .\.venv\Scripts\pip install -e '.[dev]'"
    exit 5
}
if (-not (Test-Path $SnapshotDir)) {
    Write-Error "snapshot dir not found: $SnapshotDir (run collect_historical_snapshot.py first)"
    exit 5
}

# --- derive asof from current UTC when not supplied ---------------------------
if (-not $Asof) {
    $Asof = (Get-Date).ToUniversalTime().ToString("yyyy-MM-dd'T'HH:mm:ss'Z'")
    Write-Host "[daily_run] asof not supplied; using current UTC: $Asof"
}

# --- build the command --------------------------------------------------------
$ArgList = @(
    (Join-Path $RepoRoot "scripts\run_business_mvp.py"),
    "--mode", "daily",
    "--asof", $Asof,
    "--snapshot-dir", $SnapshotDir,
    "--state-dir", $StateDir,
    "--output-dir", $OutputDir
)
if ($InfoFile) { $ArgList += @("--info-file", $InfoFile) }

Write-Host "[daily_run] $VenvPython $($ArgList -join ' ')"

# --- run (output also appended to a dated log) --------------------------------
$LogDir = Join-Path $OutputDir "logs"
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null
$LogPath = Join-Path $LogDir ("daily_" + (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss") + ".log")

$pending = Start-Process -FilePath $VenvPython -ArgumentList $ArgList `
    -NoNewWindow -Wait -PassThru `
    -RedirectStandardOutput $LogPath -RedirectStandardError "$LogPath.err"

Write-Host "[daily_run] exit=$($pending.ExitCode) log=$LogPath"

# --- summarize what happened (never claim a trade from exit 0) ----------------
$SummaryPath = Join-Path $OutputDir "summary.json"
if (Test-Path $SummaryPath) {
    $summary = Get-Content $SummaryPath -Raw | ConvertFrom-Json
    Write-Host ("[daily_run] action=" + $summary.action +
        " cycle=" + $summary.cycle_id +
        " replayed=" + $summary.idempotent_replay)
    Write-Host ("[daily_run] report: " + (Join-Path $OutputDir "report.html"))
    if ($summary.action -in @("PENDING", "NO_TRADE", "CALENDAR_BLOCKED")) {
        Write-Host "[daily_run] NOTE: no orders this cycle (action=$($summary.action)) — this is a normal outcome."
    }
}

switch ($pending.ExitCode) {
    4 { Write-Warning "HALT: state reconciliation failed — operator decision required (latched)." }
    5 { Write-Warning "infrastructure failure — see log." }
    2 { Write-Warning "usage refusal — fix the arguments." }
}
exit $pending.ExitCode
