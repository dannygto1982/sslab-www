# SSLAB Device Firmware Template

This is a template project for developing firmware for SSLAB devices (e.g., Power Controllers, Curtains, Sensors) based on the ESP8266/ESP32 platform.

## Getting Started

1.  **Copy this folder** and rename it to your new device project name (e.g., `SSLAB-CURTAIN`).
2.  **Open the project** in VS Code with PlatformIO.
3.  **Modify `include/DeviceConfig.h`**:
    *   Change `deviceType` default value (e.g., `"CURTAIN"`).
    *   Change `tcpServerPort` default value (refer to `TCP_PROTOCOL_GUIDE.md`).
4.  **Modify `src/main.cpp`**:
    *   Update `kModelName` and `kFirmwareVersion`.
    *   Implement hardware control logic in `setup()` (GPIO initialization).
    *   Implement control logic in `protocolHandler.setLightControlCallback` (rename or add new callbacks in `ProtocolHandler` as needed).
    *   Update `publishDiscoveryMessage` capabilities list.
    *   Update `renderConfigPage` to show relevant status (e.g., Curtain Position instead of On/Off).

## Project Structure

*   `src/main.cpp`: Main application logic, Web Server, MQTT handling.
*   `src/ConfigStorage.cpp`: Handles saving/loading configuration to LittleFS.
*   `src/ProtocolHandler.cpp`: Handles SSLAB Protocol (RPC) logic.
*   `include/DeviceConfig.h`: Configuration structure definition.
*   `include/WebPageAssets.h`: CSS and JS for the configuration web page.

## Features Included

*   **Wi-Fi Manager**: Auto-connects to configured AP, falls back to AP mode (`SSLAB-SETUP`) if connection fails.
*   **MQTT Client**: Connects to SSLAB-HMI, handles RPC requests, publishes telemetry.
*   **TCP Transparent Bridge**: Bridges Serial port to TCP server (for legacy device support).
*   **Web Configuration**: Modern UI for configuring Wi-Fi, MQTT, and Device ID.
*   **OTA Update**: Supports HTTP OTA (`/update`) and ArduinoOTA (Port 8266).
*   **Device ID Generation**: Automatically generates ID from MAC address (e.g., `DEV-A1B2`).

## Protocol Reference

See `TCP_PROTOCOL_GUIDE.md` and `DEVICE_PROTOCOL.md` in the `SSLAB-LIGHTING` project for protocol details.
