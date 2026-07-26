# Atlas nightly autopilot (Windows).
#
# Runs the research lab unattended: refresh data (best-effort), discover new
# forex ideas from the web and test them, then sweep the core hypotheses through
# the governed loop. Everything writes to the vault, so the dashboard shows the
# results in the morning. Nothing here ever promotes to capital — that stays
# human-gated inside Atlas.
#
# Register it to run every night at 02:00 (see scripts/README_nightly.md), or
# run it by hand any time:  powershell -ExecutionPolicy Bypass -File .\scripts\atlas_nightly.ps1
#
# Requirements: ANTHROPIC_API_KEY set (for web discovery). If the key or the
# MetaTrader terminal is missing, those steps are skipped with a note — the loop
# steps still run on the data already on disk.

$ErrorActionPreference = "Continue"

# --- locate the repo root (this script lives in <root>\scripts) ---
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

# --- config (override with env vars if you like) ---
$Offset   = if ($env:ATLAS_DATA_UTC_OFFSET) { $env:ATLAS_DATA_UTC_OFFSET } else { "3" }
$Symbols  = @("GBPUSD", "USDJPY")
$Discover = @(
    "forex opening range breakout intraday strategy rules",
    "forex trend pullback continuation strategy rules",
    "forex mean reversion currency strategy rules"
)
$CoreHyps = @(
    "hypotheses\london_trend_continuation.yaml",
    "hypotheses\meanrev_zscore.yaml",
    "hypotheses\donchian_breakout.yaml"
)

# --- logging ---
$logDir = Join-Path $root "vault\logs"
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$stamp = Get-Date -Format "yyyyMMdd_HHmmss"
$log   = Join-Path $logDir "nightly_$stamp.log"

function Log($msg) {
    $line = "[{0}] {1}" -f (Get-Date -Format "HH:mm:ss"), $msg
    Write-Host $line
    Add-Content -Path $log -Value $line
}

Log "=== Atlas nightly start (root: $root) ==="

# --- 1. refresh data (best-effort; needs the MT5 terminal open) ---
foreach ($sym in $Symbols) {
    Log "export $sym M5 (7y)"
    try {
        py -m atlas.research.fx.cli export $sym M5 7 *>> $log
    } catch {
        Log "  export failed (is MetaTrader open?) — using existing data. $_"
    }
}

# --- 2. discover new forex ideas from the web and test them ---
if ($env:ANTHROPIC_API_KEY) {
    foreach ($q in $Discover) {
        Log "discover: $q"
        try {
            py -m atlas discover "$q" --max 3 --test --data-utc-offset $Offset *>> $log
        } catch {
            Log "  discover failed: $_"
        }
    }
} else {
    Log "ANTHROPIC_API_KEY not set — skipping web discovery this run."
}

# --- 3. sweep the core hypotheses through the governed loop ---
foreach ($h in $CoreHyps) {
    Log "loop: $h"
    try {
        py -m atlas loop $h --autonomy 4 --max-per-cycle 9 --data-utc-offset $Offset *>> $log
    } catch {
        Log "  loop failed for $h : $_"
    }
}

Log "=== Atlas nightly done. Open the dashboard to review. ==="
Log "    py -m atlas dashboard --serve"
