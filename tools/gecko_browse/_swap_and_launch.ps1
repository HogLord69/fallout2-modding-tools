# _swap_and_launch.ps1 - open gecko against one game's data, in total isolation
# from the FOC editing profile, then restore FOC automatically when it closes.
#
# WHY THIS EXISTS RATHER THAN JUST ADDING MORE --data PATHS TO SETTINGS.JSON:
# see tools/build_gecko_browsers.py's module docstring for the full reasoning
# (name collisions between unrelated games' art/tiles, no safe priority order).
#
# Also worth knowing: gecko's own --data command-line flag is ONLY honoured when
# settings.json has no data paths yet (first run) - Application.cpp checks
# settings.getDataPaths().empty() before ever looking at --data. Once you have a
# saved profile (you do, for FOC), passing --data on the command line does
# nothing. That is why this swaps the file on disk rather than passing flags.

param(
    [Parameter(Mandatory = $true)][string]$Name,
    [Parameter(Mandatory = $true)][string[]]$DataPaths,
    # tools/sources.json key for this game. When set, stamps saved during the
    # session are converted to FOC's ID space when gecko closes (see below).
    [string]$Source = ''
)

$ErrorActionPreference = 'Stop'
$settingsDir  = "$env:LOCALAPPDATA\gecko\gecko"
$settingsPath = Join-Path $settingsDir "settings.json"
$focBackup    = Join-Path $settingsDir "settings.json.foc-live"
$geckoExe     = 'F:\FOCMod\reference\gecko\build\gecko.exe'

if (-not (Test-Path $geckoExe)) { throw "gecko.exe not found at $geckoExe - build it first (tools\build_gecko.ps1)" }

# REFUSE rather than kill: an earlier version force-closed any running gecko.exe
# here, which meant double-clicking a second launcher (or opening one while FOC
# editing was open) silently killed that other session and raced it for
# settings.json/settings.json.foc-live - confirmed to actually corrupt the swap
# (settings.json left pointed at a TC with no backup left to restore from).
# Only one gecko session - browsing or FOC editing - can exist at a time, because
# there is only one settings.json; enforce that instead of trying to be clever.
$existing = Get-Process gecko -ErrorAction SilentlyContinue
if ($existing) {
    Write-Host ""
    Write-Host "gecko is already running (PID $($existing.Id -join ', '))." -ForegroundColor Red
    Write-Host "Close that window first - opening a second one here would race it for" -ForegroundColor Red
    Write-Host "the one shared settings.json and can leave things pointed at the wrong" -ForegroundColor Red
    Write-Host "game with no way back. Close gecko, then run this launcher again." -ForegroundColor Red
    Write-Host ""
    exit 1
}

# Keep exactly one FOC backup. If one already exists we are almost certainly being
# re-run from a previous TC session that did not get to restore (e.g. gecko crashed) -
# overwriting it with THIS run's already-swapped TC file would lose the real FOC
# profile for good, so never re-back-up over an existing one.
if ((Test-Path $settingsPath) -and -not (Test-Path $focBackup)) {
    Copy-Item $settingsPath $focBackup -Force
    Write-Host "Backed up the FOC editing profile."
} elseif (Test-Path $focBackup) {
    Write-Host "FOC profile already backed up from an earlier session - leaving it as is."
}

# A tile id a game's own tiles.lst doesn't cover needs SOME art (blank.frm),
# or gecko hard-fails instead of degrading - NOT auto-added the way
# loadDataPaths()'s ensureFallbackDataPath comment implies; confirmed against
# the actual gecko.log (browsing Sonora mounted master.dat/critter.dat/data
# only, no "Mounted 'resources'" line at all).
#
# This deliberately does NOT point at reference\gecko\build\resources. That
# folder looks like gecko's own small bundled placeholder set but is not -
# early in this project master.dat (333MB) and critter.dat (166MB) were
# copied into gecko's SOURCE resources\ for FOC's own convenience (harmless
# there: same vanilla FO2 data either way), and someone later saved three
# Redwell maps directly into its maps\ folder. Mounting that whole folder
# into every TC session was exactly the cross-game leak this whole per-TC
# isolation scheme exists to prevent - confirmed live: `resource list` for
# Nevada Mod (Extended) returned Redwell's own REDWELL.MAP, sourced from
# "Native (resources)", inside what was meant to be an isolated Nevada
# session. _fallback_art\ is the real minimal set (6 small .frm overlay
# files - art/tiles/blank.frm + 5 in art/misc/), copied once from gecko's
# clean *source* resources\ (not the polluted build\ copy) and nothing else.
$resourcesPath = "$PSScriptRoot\_fallback_art"
$allPaths = @($resourcesPath) + $DataPaths

$tcSettings = [ordered]@{
    dataPaths        = $allPaths
    gameLocation     = @{}
    selectionColors  = @{}
    textEditor       = @{ mode = "system" }
    ui               = @{ edgeScrollEnabled = $true; mergeSelectionOutlines = $true; windowMaximized = $true }
    version          = "1.1"
}
$tcSettings | ConvertTo-Json -Depth 8 | Set-Content $settingsPath -Encoding utf8

Write-Host ""
Write-Host "Opening gecko on: $Name"
Write-Host "  (this is a READ-ONLY look for browsing/reference - gecko can still save"
Write-Host "   maps if you tell it to, and that would write into that game's own"
Write-Host "   install; if you only want to look, don't use File > Save)"
Write-Host "Close the gecko window when you're done to return to FOC editing."
Write-Host ""

$sessionStart = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds() - 5
Start-Process -FilePath $geckoExe -Wait

if (Test-Path $focBackup) {
    Copy-Item $focBackup $settingsPath -Force
    Remove-Item $focBackup -Force
    Write-Host "Restored the FOC editing profile."
} else {
    Write-Host "WARNING: no FOC backup was found to restore - settings.json is still" -ForegroundColor Yellow
    Write-Host "pointed at $Name. Run 'Back To FOC Editing.bat' to fix this." -ForegroundColor Yellow
}

# Stamps saved in this session hold THIS game's proto/art/tile numbers, and every
# gecko session shares one patterns folder - stamped in the FOC profile they draw
# a random mess. Convert them now (originals kept in
# F:\FOCMod\_safety_backups\stamp_originals\, never inside patterns\),
# then repack so any art they use sits below the engine's 4096 cap. Both steps
# are no-ops when nothing was saved; a failure here never blocks the restore.
if ($Source) {
    $tools = Split-Path $PSScriptRoot -Parent
    $py = Get-Command python -ErrorAction SilentlyContinue
    if (-not $py) {
        Write-Host "python not found - convert this session's stamps by hand:" -ForegroundColor Yellow
        Write-Host "  python tools\port_stamp.py --all --since $sessionStart --source $Source" -ForegroundColor Yellow
    } else {
        Write-Host ""
        Write-Host "Converting stamps saved this session to FOC's IDs (takes a minute or two)..."
        try {
            & $py.Source "$tools\port_stamp.py" --all --since $sessionStart --source $Source
            if ($LASTEXITCODE -eq 0) { & $py.Source "$tools\repack_art.py" }
        } catch {
            Write-Host "Stamp conversion failed: $_" -ForegroundColor Yellow
        }
    }
    Write-Host ""
    Read-Host "Done - press Enter to close this window"
}
