# Force gecko's settings.json back to the FOC editing profile. Normally
# _swap_and_launch.ps1 restores it automatically when a TC browser window
# closes; this is the manual fallback for when that didn't happen (gecko
# was killed some other way, crashed, etc).
$d = "$env:LOCALAPPDATA\gecko\gecko"
$s = Join-Path $d "settings.json"
$b = Join-Path $d "settings.json.foc-live"

if (Test-Path $b) {
    Copy-Item $b $s -Force
    Remove-Item $b -Force
    Write-Host "Restored the FOC profile from backup."
} else {
    $foc = [ordered]@{
        dataPaths       = @(
            'F:\FOCMod\base\master.dat',
            'F:\FOCMod\base\critter.dat',
            # The .dat mods the game loads, in base\mods\mods_order.txt order.
            # Without rpu.dat gecko sees master.dat's 3102-entry tiles.lst while
            # the game (and every FOC tool) uses RPU's 4077 - a map with any
            # tile id >= 3102 then crashes gecko on load (invalid vector subscript).
            'F:\FOCMod\base\mods\rpu.dat',
            'F:\FOCMod\base\mods\rpu_enhanced_worldmap.dat',
            'F:\FOCMod\base\mods\rpu_extended_flamer.dat',
            'F:\FOCMod\base\mods\rpu_rifle_animations.dat',
            'F:\FOCMod\base\mods\rpu_wakizashi_animations.dat',
            'F:\FOCMod\base\mods\npc_armor.dat',
            'F:\FOCMod\base\mods\party_orders.dat',
            'F:\FOCMod\base\mods\cassidy_head.dat',
            'F:\FOCMod\base',
            'F:\FOCMod\base\mods\foc'
        )
        gameLocation    = @{}
        selectionColors = @{}
        textEditor      = @{ mode = "system" }
        ui              = @{ edgeScrollEnabled = $true; mergeSelectionOutlines = $true; windowMaximized = $true }
        version         = "1.1"
    }
    $foc | ConvertTo-Json -Depth 8 | Set-Content $s -Encoding utf8
    Write-Host "No backup found - wrote the known FOC profile directly (this loses"
    Write-Host "gecko's saved window layout, nothing else)."
}
