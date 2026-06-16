@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion
cd /d "%~dp0SSLAB-LIFT_DEVICE"

echo.
echo =======================================
echo   ESP8266 Firmware Batch Flash Tool
echo =======================================
echo.

set /p COM_PORT="Enter COM port (default COM6): "
if "%COM_PORT%"=="" set COM_PORT=COM6

echo.
echo Target Port : %COM_PORT%
echo Environment : nodemcuv2_serial
echo Delay       : 10s between flashes
echo Ctrl+C      : stop anytime
echo =======================================
echo.

echo === Building firmware ===
pio run -e nodemcuv2_serial
if %ERRORLEVEL% neq 0 (
    echo BUILD FAILED !!!
    pause
    exit /b 1
)
echo === Build OK ===
echo.

set /a COUNT=0

:loop
set /a COUNT+=1
echo ---------------------------------------
echo === [%COUNT%] Flashing to %COM_PORT% ===
echo     Connect device, press reset/flash button
echo.
pio run -e nodemcuv2_serial -t upload --upload-port %COM_PORT%
if %ERRORLEVEL% equ 0 (
    echo === [%COUNT%] SUCCESS ! ===
) else (
    echo === [%COUNT%] FAILED ===
)
echo.
echo     Waiting 10s before next flash...
echo     (Swap device now)
timeout /t 10 /nobreak >nul
echo.
goto loop
