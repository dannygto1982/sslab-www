#pragma once

#include <Arduino.h>
#include <vector>

struct WifiCredential {
    String ssid;
    String password;
};

struct DeviceSettings {
    String deviceId;
    String deviceType = "LIFT_DEVICE"; // Change this for each device type
    String classroomZone = "ENTIRE_ROOM";
    String studentGroup = "GROUP_1"; // Added for protocol compliance
    String mqttHost = "192.168.0.110";
    uint16_t mqttPort = 1883;
    bool mqttEnabled = false;   // disabled by default — enable in web config
    String mqttUsername;
    String mqttPassword;
    String otaPassword = "changemeOTA";
    
    // TCP Transparent Transmission Settings
    String tcpServerHost = "192.168.0.110";
    uint16_t tcpServerPort = 1053;
    uint8_t controlIpStart = 100;
    uint8_t controlIpEnd = 130;
    uint8_t controlSendRounds = 2;
    uint8_t controlBatchSize = 2;
    unsigned long controlBatchIntervalMs = 50;
    
    unsigned long telemetryIntervalMs = 10000;
    unsigned long heartbeatIntervalMs = 15000;
    unsigned long discoveryIntervalMs = 60000;
    uint16_t liftTimeoutSec = 20;  // 升降自动停止时长，0=不自动停
    std::vector<WifiCredential> wifiList;
};

void applyFactoryDefaults(DeviceSettings &settings);
bool loadSettings(DeviceSettings &settings);
bool saveSettings(const DeviceSettings &settings);
