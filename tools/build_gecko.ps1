# build_gecko.ps1 - build the Gecko Fallout 2 map editor from source.
#
#   powershell -ExecutionPolicy Bypass -File tools\build_gecko.ps1
#
# Gecko is a third-party editor (github.com/JanSimek/gecko, Apache-2.0) cloned
# into reference/gecko. It needs Qt6 and a C++20 MSVC toolchain; everything
# else (SFML, zlib, spdlog, nlohmann_json) CMake fetches on its own, because
# gecko's cmake/dependencies.cmake falls back to FetchContent when a system
# library is missing.
#
# Follows gecko's own CI (.github/workflows/ci.yml) rather than the README's
# vcpkg route: the CI installs prebuilt Qt 6.9.3 and builds with Ninja + MSVC,
# which is the configuration they actually test, and it avoids compiling Qt
# from source (20+ GB, hours).

$ErrorActionPreference = 'Stop'

$Root    = Split-Path -Parent $PSScriptRoot
$Gecko   = Join-Path $Root 'reference\gecko'
$Build   = Join-Path $Gecko 'build'
$QtDir   = 'F:\Qt\6.9.3\msvc2022_64'

if (-not (Test-Path $Gecko)) { throw "gecko not cloned at $Gecko" }
if (-not (Test-Path $QtDir)) { throw "Qt not found at $QtDir" }

# --- locate the MSVC environment -------------------------------------------
$vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
if (-not (Test-Path $vswhere)) { throw "vswhere.exe not found - Visual Studio Build Tools are not installed" }
$vsPath = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
if (-not $vsPath) { throw "no MSVC C++ toolchain found - install the 'Desktop development with C++' workload" }
$vcvars = Join-Path $vsPath 'VC\Auxiliary\Build\vcvars64.bat'
if (-not (Test-Path $vcvars)) { throw "vcvars64.bat not found under $vsPath" }
Write-Host "MSVC : $vsPath"
Write-Host "Qt   : $QtDir"

# vcvars64 only exports into its own cmd session, so run the whole build inside
# one cmd invocation rather than trying to import the environment back.
$cfg = "cmake -S . -B build -G Ninja -DCMAKE_BUILD_TYPE=Release " +
       "-DCMAKE_PREFIX_PATH=$($QtDir -replace '\\','/') -DGECK_BUILD_TESTS=OFF " +
       "-DGECK_ENABLE_SCRIPTING=ON"
# gecko-cli / gecko-mcp are the headless surface: Luau map generation,
# palette analysis, PNG rendering and reachability checks, no GUI needed.
# NOTE: linking gecko.exe fails with LNK1104 if the editor is running.
$bld = "cmake --build build --target gecko-cli gecko-mcp gecko --parallel"

# cmake and ninja were installed into PATH entries this session never saw, so
# rebuild PATH from the registry before handing it to the build shell.
$env:Path = [Environment]::GetEnvironmentVariable('Path','Machine') + ';' +
            [Environment]::GetEnvironmentVariable('Path','User')
foreach ($t in @('cmake','ninja')) {
    if (-not (Get-Command $t -ErrorAction SilentlyContinue)) { throw "$t not on PATH" }
}

$script = @"
@echo off
call "$vcvars" >nul
if errorlevel 1 exit /b 1
cd /d "$Gecko"
echo === configure ===
$cfg
if errorlevel 1 exit /b 1
echo === build ===
$bld
if errorlevel 1 exit /b 1
"@

$bat = Join-Path $env:TEMP 'gecko_build.bat'
Set-Content -Path $bat -Value $script -Encoding ascii
& cmd.exe /c $bat
if ($LASTEXITCODE -ne 0) { throw "build failed with exit code $LASTEXITCODE" }

# --- find what we built and give it its Qt runtime -------------------------
$exe = Get-ChildItem -Path $Build -Filter 'gecko.exe' -Recurse -ErrorAction SilentlyContinue |
       Select-Object -First 1
if (-not $exe) { throw "build reported success but gecko.exe was not found under $Build" }
Write-Host "built: $($exe.FullName)"

$windeploy = Join-Path $QtDir 'bin\windeployqt.exe'
if (Test-Path $windeploy) {
    Write-Host "=== windeployqt ==="
    & $windeploy --release --no-translations --no-system-d3d-compiler $exe.FullName
}

# gecko reads master.dat / critter.dat from a 'resources' folder beside itself
$res = Join-Path $exe.DirectoryName 'resources'
New-Item -ItemType Directory -Force -Path $res | Out-Null
foreach ($d in @('master.dat','critter.dat')) {
    $src = Join-Path $Gecko "resources\$d"
    $dst = Join-Path $res $d
    if ((Test-Path $src) -and -not (Test-Path $dst)) {
        Write-Host "  staging $d"
        Copy-Item $src $dst
    }
}

Write-Host ""
Write-Host "gecko.exe -> $($exe.FullName)"
