# ============================================================
# ESP8266 Firmware Batch Flash Script
# Usage: .\flash_loop.ps1
# ============================================================

$ErrorActionPreference = "Continue"
$DEVICE_DIR = Join-Path $PSScriptRoot "SSLAB-LIFT_DEVICE"

# -- Interactive COM port selection --
$defaultPort = "COM6"
Write-Host ""
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host "  ESP8266 Firmware Batch Flash Tool" -ForegroundColor Yellow
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

$portInput = Read-Host "Enter COM port (default: $defaultPort)"
if ([string]::IsNullOrWhiteSpace($portInput)) {
    $COM_PORT = $defaultPort
} else {
    $COM_PORT = $portInput.ToUpper()
}

if ($COM_PORT -notmatch '^COM\d+$') {
    Write-Host "ERROR: Invalid COM port (expect COM1-COM256)" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Target Port : $COM_PORT" -ForegroundColor Green
Write-Host "Environment : nodemcuv2_serial" -ForegroundColor Green
Write-Host "Delay       : 10s between flashes" -ForegroundColor Green
Write-Host "Ctrl+C      : stop anytime" -ForegroundColor DarkGray
Write-Host "=======================================" -ForegroundColor Cyan
Write-Host ""

# -- Build once --
Write-Host ">>> Building firmware..." -ForegroundColor Yellow
Push-Location $DEVICE_DIR
try {
    pio run -e nodemcuv2_serial
    if ($LASTEXITCODE -ne 0) {
        Write-Host "BUILD FAILED !!!" -ForegroundColor Red
        Pop-Location
        exit 1
    }
} finally {
    Pop-Location
}
Write-Host ">>> Build OK" -ForegroundColor Green
Write-Host ""

# -- Continuous flash loop --
$count = 0
while ($true) {
    $count++
    Write-Host "---------------------------------------" -ForegroundColor DarkGray
    Write-Host ">>> [$count] Flashing to $COM_PORT ..." -ForegroundColor Yellow
    Write-Host "    Connect device, press reset/flash button" -ForegroundColor DarkGray

    Push-Location $DEVICE_DIR
    try {
        pio run -e nodemcuv2_serial -t upload --upload-port $COM_PORT
        if ($LASTEXITCODE -eq 0) {
            Write-Host ">>> [$count] SUCCESS !" -ForegroundColor Green
        } else {
            Write-Host ">>> [$count] FAILED (code: $LASTEXITCODE)" -ForegroundColor Red
        }
    } finally {
        Pop-Location
    }

    Write-Host "    Waiting 10s before next flash..." -ForegroundColor DarkGray
    Write-Host "    (Swap device now)" -ForegroundColor DarkGray

    for ($i = 10; $i -gt 0; $i--) {
        $msg = "    Countdown: " + $i + "s  "
        Write-Host -NoNewline "`r$msg"
        Start-Sleep -Seconds 1
    }
    Write-Host ""
    Write-Host ""
}
