# SSLAB LAN Deploy Script
# Usage:
#   .\deploy_lan.ps1                         # update APP + Firmware
#   .\deploy_lan.ps1 -Mode app               # APP only
#   .\deploy_lan.ps1 -Mode firmware          # Firmware only
#   .\deploy_lan.ps1 -AndroidTarget 192.168.0.x:PORT  # specify ADB WiFi target

param(
    [ValidateSet("all","app","firmware")]
    [string]$Mode          = "all",
    [string]$ApkPath       = "",
    [string]$BinPath       = "",
    [string]$AndroidTarget = "",
    [string]$FirmwareIP    = "192.168.0.101",
    [string]$OtaPassword   = "changemeOTA",
    [string]$PioEnv        = "nodemcuv2",
    [string]$AdbExe        = "",
    [switch]$SkipBuild,
    [switch]$RestartApp
)

Set-StrictMode -Off
$ErrorActionPreference = "Continue"
$PASS = 0; $FAIL = 0

function Inf([string]$m)  { Write-Host "  $m" -ForegroundColor Cyan }
function Good([string]$m) { Write-Host "  [OK]  $m" -ForegroundColor Green; $script:PASS++ }
function Warn([string]$m) { Write-Host "  [WARN] $m" -ForegroundColor Yellow }
function Bad([string]$m)  { Write-Host "  [FAIL] $m" -ForegroundColor Red; $script:FAIL++ }
function Title([string]$m){ Write-Host "" ; Write-Host "=== $m ===" -ForegroundColor White }

# ─── 0. Locate tools ──────────────────────────────────────────────────────────
Title "0. Tools"

if (-not $AdbExe) {
    foreach ($c in @(
        "adb",
        "$env:LOCALAPPDATA\Android\Sdk\platform-tools\adb.exe",
        "C:\Users\danny\AppData\Local\Android\Sdk\platform-tools\adb.exe"
    )) {
        $found = Get-Command $c -ErrorAction SilentlyContinue
        if ($found) { $AdbExe = $found.Source; break }
    }
}
if ($AdbExe -and (Test-Path $AdbExe -ErrorAction SilentlyContinue)) {
    Inf "ADB: $AdbExe"
} elseif ($Mode -in @("all","app")) {
    Warn "adb not found. APP update skipped."
    $Mode = if ($Mode -eq "app") { "done" } else { "firmware" }
}

$PioExe = ""
$pc = Get-Command "pio" -ErrorAction SilentlyContinue
if ($pc) { $PioExe = $pc.Source }
else {
    $lp = "d:\CODE\SSLAB-WWW\SSLAB-LIFT_DEVICE\.venv\Scripts\pio.exe"
    if (Test-Path $lp) { $PioExe = $lp }
}
if ($PioExe) { Inf "PlatformIO: $PioExe" }
else         { Warn "pio not found; firmware build skipped unless -BinPath provided" }

# ─── 1. Locate APK ────────────────────────────────────────────────────────────
if ($Mode -in @("all","app")) {
    Title "1. APK"
    if (-not $ApkPath) {
        $candidates  = @(Get-ChildItem "d:\CODE\SSLAB-WWW\releases\*.apk" -ErrorAction SilentlyContinue)
        $candidates += @(Get-ChildItem "d:\CODE\SSLAB-WWW\android\platforms\android\app\build\outputs\apk\debug\*.apk" -ErrorAction SilentlyContinue)
        $candidates  = $candidates | Sort-Object LastWriteTime -Descending
        if ($candidates) {
            $ApkPath = $candidates[0].FullName
            $sizeMB  = [math]::Round([long]$candidates[0].Length / 1048576, 1)
            Inf "APK: $ApkPath  (${sizeMB} MB)"
        } else {
            Bad "No APK found. Build first or use -ApkPath."
            $Mode = if ($Mode -eq "app") { "done" } else { "firmware" }
        }
    } else {
        if (Test-Path $ApkPath) { Inf "APK: $ApkPath" }
        else { Bad "APK not found: $ApkPath"; exit 1 }
    }
}

# ─── 2. Connect ADB WiFi ──────────────────────────────────────────────────────
$devList = @()
if ($Mode -in @("all","app")) {
    Title "2. ADB WiFi"

    try {
        $raw = & $AdbExe devices 2>&1 | Select-String "device$"
        foreach ($line in $raw) {
            $serial = ($line.Line -split "\s+")[0]
            if ($serial) { $devList += $serial }
        }
    } catch {}

    if ($AndroidTarget) {
        Inf "Connecting $AndroidTarget ..."
        $out = & $AdbExe connect $AndroidTarget 2>&1
        Inf "$out"
        $devList = (@($AndroidTarget) + $devList) | Select-Object -Unique
    }

    if (-not $devList) {
        $lastLine = Select-String -Path "d:\CODE\SSLAB-WWW\docs\adb_e2e_test.ps1" -Pattern '^\$DEV\s*=' |
                    Select-Object -First 1
        if ($lastLine) {
            $lastDev = ($lastLine.Line -split '"')[1]
            Inf "Trying last known: $lastDev"
            & $AdbExe connect $lastDev 2>&1 | Out-Null
            $ping = & $AdbExe -s $lastDev shell echo "PING" 2>&1
            if ("$ping" -match "PING") { $devList = @($lastDev) }
        }
    }

    if (-not $devList) {
        Bad "No ADB device found. Enable Wireless Debugging and use -AndroidTarget ip:port"
        $Mode = if ($Mode -eq "app") { "done" } else { "firmware" }
    } else {
        foreach ($d in $devList) { Inf "Device: $d" }
    }
}

# ─── 3. Install APK ───────────────────────────────────────────────────────────
if ($Mode -in @("all","app")) {
    Title "3. Install APK"
    foreach ($dev in $devList) {
        Inf "[$dev] Installing..."
        $out = (& $AdbExe -s $dev install -r -d "$ApkPath" 2>&1) | Out-String
        if ($out -match "Success") {
            Good "[$dev] APK installed"
            if ($RestartApp) {
                $pkg = (& $AdbExe -s $dev shell "pm list packages" 2>&1 |
                        Where-Object { "$_" -match "sslab|management" } |
                        ForEach-Object { "$_".Replace("package:","").Trim() } |
                        Select-Object -First 1)
                if (-not $pkg) { $pkg = "com.lab.management" }
                Inf "[$dev] Restarting $pkg ..."
                & $AdbExe -s $dev shell "am force-stop $pkg" 2>&1 | Out-Null
                Start-Sleep -Milliseconds 600
                & $AdbExe -s $dev shell "monkey -p $pkg -c android.intent.category.LAUNCHER 1" 2>&1 | Out-Null
                Inf "[$dev] APP restarted"
            }
        } else {
            Bad "[$dev] Install failed: $($out | Select-String 'Error|Fail|Exception' | Select-Object -First 3)"
        }
    }
}

# ─── 4. Build Firmware ────────────────────────────────────────────────────────
if ($Mode -in @("all","firmware")) {
    Title "4. Build Firmware"
    $projDir = "d:\CODE\SSLAB-WWW\SSLAB-LIFT_DEVICE"
    if (-not $BinPath) { $BinPath = "$projDir\.pio\build\$PioEnv\firmware.bin" }

    if ($SkipBuild -and (Test-Path $BinPath)) {
        Inf "SkipBuild: $BinPath"
    } elseif ($PioExe) {
        Inf "Building env=$PioEnv ..."
        Push-Location $projDir
        $out = & $PioExe run -e $PioEnv 2>&1
        Pop-Location
        if (($LASTEXITCODE -eq 0) -and (Test-Path $BinPath)) {
            Good "Firmware built: $BinPath"
        } else {
            Bad "Build failed:`n$($out | Select-Object -Last 8 | Out-String)"
            if ($Mode -eq "firmware") { exit 1 }
        }
    } else {
        if (Test-Path $BinPath) { Warn "pio not found; using existing $BinPath" }
        else { Bad "pio not found and no firmware.bin"; if ($Mode -eq "firmware") { exit 1 } }
    }
}

# ─── 5. OTA Upload ────────────────────────────────────────────────────────────
if ($Mode -in @("all","firmware")) {
    Title "5. OTA Upload -> $FirmwareIP"
    $online = Test-Connection -ComputerName $FirmwareIP -Count 2 -Quiet -ErrorAction SilentlyContinue
    if (-not $online) {
        Bad "Device $FirmwareIP unreachable"
        if ($Mode -eq "firmware") { exit 1 }
    } else {
        Inf "Device online: $FirmwareIP"
        $projDir = "d:\CODE\SSLAB-WWW\SSLAB-LIFT_DEVICE"
        if ($PioExe) {
            Inf "Uploading via espota (pio) ..."
            Push-Location $projDir
            $out = & $PioExe run -e $PioEnv --target upload 2>&1
            Pop-Location
            if ($LASTEXITCODE -eq 0) { Good "Firmware OTA complete" }
            else { Bad "OTA failed:`n$($out | Select-Object -Last 8 | Out-String)" }
        } else {
            $espota = @(
                "$env:USERPROFILE\.platformio\packages\tool-esptool\espota.py",
                "C:\Users\danny\.platformio\packages\tool-esptool\espota.py"
            ) | Where-Object { Test-Path $_ } | Select-Object -First 1
            if ($espota -and (Test-Path $BinPath)) {
                Inf "Uploading via espota.py ..."
                $out = python $espota -i $FirmwareIP -p 8266 -a $OtaPassword -f $BinPath 2>&1
                if ($LASTEXITCODE -eq 0) { Good "Firmware OTA complete (espota.py)" }
                else { Bad "espota.py failed: $($out | Out-String)" }
            } else {
                Bad "Cannot upload: pio and espota.py both unavailable"
            }
        }
    }
}

# ─── Summary ──────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host ("-" * 56)
if ($FAIL -eq 0) {
    Write-Host "  All done: $PASS step(s) OK" -ForegroundColor Green
} else {
    Write-Host "  Done: $PASS OK, $FAIL FAILED" -ForegroundColor Yellow
}
Write-Host ("-" * 56)
Write-Host ""
if ($FAIL -gt 0) { exit 1 }
