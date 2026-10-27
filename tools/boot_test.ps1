# boot_test.ps1 - hands-free "does this map boot?" check.
#
#   powershell -File tools/boot_test.ps1 -StartMap RWCORE2.MAP [-WaitSec 30]
#
# Temporarily points sfall's StartingMap at the map, skips the intro movies,
# starts fallout2HR.exe, presses N (new game) and T (take character), waits for
# debug.log's "Total Critter Count" marker, kills the game and restores
# ddraw.ini byte-for-byte. marker=True alive=True is a clean boot; exit=1 with
# an EMPTY debug.log is NOT a crash - it is the launch being refused (sandboxed
# shell, or a previous instance still releasing D3D) - wait a few seconds and
# rerun. A real crash leaves a partial debug.log and an Application Error box.
# Leave the window alone while it runs; clicking through it yourself is fine.
#
#   -Shot out.png [-ShotDelay 6]   after the map loads, wait ShotDelay seconds
#                                  (scripts run, NPCs dress) and save a screenshot
#                                  of the primary screen before the game is killed.
param([string]$StartMap = "", [int]$WaitSec = 25, [string]$Shot = "", [int]$ShotDelay = 6)

$base = "F:\FOCMod\base"
$ini  = Join-Path $base "ddraw.ini"
$bak  = Join-Path $env:TEMP "ddraw.ini.harness.bak"
$log  = Join-Path $base "debug.log"

Copy-Item $ini $bak -Force
try {
    $text = [IO.File]::ReadAllText($ini)
    foreach ($n in 1,2,3,17) {
        $text = [regex]::Replace($text, "(?m)^Movie$n=.*$", "Movie$n=zz_none$n.mve")
    }
    if ($StartMap) {
        $text = [regex]::Replace($text, "(?m)^StartingMap=.*$", "StartingMap=$StartMap")
    }
    [IO.File]::WriteAllText($ini, $text)

    if (Test-Path $log) { Remove-Item $log -Force }
    Get-Process fallout2HR -ErrorAction SilentlyContinue | Stop-Process -Force

    $p = Start-Process -FilePath (Join-Path $base "fallout2HR.exe") -WorkingDirectory $base -PassThru
    Start-Sleep -Seconds 5
    $ws = New-Object -ComObject WScript.Shell
    $null = $ws.AppActivate($p.Id)
    $ws.SendKeys("n")
    Start-Sleep -Seconds 4
    $null = $ws.AppActivate($p.Id)
    $ws.SendKeys("t")

    $deadline = (Get-Date).AddSeconds($WaitSec)
    $marker = $false
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        if (Test-Path $log) {
            $l = Get-Content $log -Raw -ErrorAction SilentlyContinue
            if ($l -match "Total Critter Count|Party Member 0") { $marker = $true; break }
        }
        if ($p.HasExited) { break }
    }
    if ($marker -and $Shot -and -not $p.HasExited) {
        Start-Sleep -Seconds $ShotDelay
        Add-Type -AssemblyName System.Windows.Forms, System.Drawing
        $b = [System.Windows.Forms.Screen]::PrimaryScreen.Bounds
        $bmp = New-Object System.Drawing.Bitmap $b.Width, $b.Height
        $g = [System.Drawing.Graphics]::FromImage($bmp)
        $g.CopyFromScreen($b.Location, [System.Drawing.Point]::Empty, $b.Size)
        $bmp.Save($Shot, [System.Drawing.Imaging.ImageFormat]::Png)
        $g.Dispose(); $bmp.Dispose()
        Write-Output "screenshot: $Shot"
    }
    $alive = -not $p.HasExited
    Write-Output ("RESULT map={0} marker={1} alive={2} exit={3}" -f $StartMap, $marker, $alive, $(if ($p.HasExited) { $p.ExitCode } else { "-" }))
    if (Test-Path $log) {
        $l = Get-Content $log
        Write-Output ("debug.log lines: {0}" -f $l.Count)
        $l | Select-String -Pattern "Error|error|Unable|Total Critter|Party Member|rwcore|RWCORE|map_enter|script" | Select-Object -First 40 | ForEach-Object { "  " + $_.Line }
    } else { Write-Output "debug.log missing" }
}
finally {
    Get-Process fallout2HR -ErrorAction SilentlyContinue | Stop-Process -Force
    Start-Sleep -Milliseconds 500
    # dismiss a Windows "Application Error" box if one is up
    $ws2 = New-Object -ComObject WScript.Shell
    if ($ws2.AppActivate("fallout2HR.exe - Application Error")) { $ws2.SendKeys("{ENTER}") }
    Copy-Item $bak $ini -Force
    Write-Output "ddraw.ini restored"
}
