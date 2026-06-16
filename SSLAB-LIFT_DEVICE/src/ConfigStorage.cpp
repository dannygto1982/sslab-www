#include <LittleFS.h>
#include <ArduinoJson.h>

#include "DeviceConfig.h"

namespace {
constexpr const char *kConfigPath = "/config.json";
}

void applyFactoryDefaults(DeviceSettings &settings) {
    DeviceSettings defaults;
    defaults.wifiList.push_back({"SSKJ-4G", "xszn486020zcs"});
    settings = defaults;
}

bool loadSettings(DeviceSettings &settings) {
    if (!LittleFS.exists(kConfigPath)) {
        applyFactoryDefaults(settings);
        return false;
    }

    File file = LittleFS.open(kConfigPath, "r");
    if (!file) {
        applyFactoryDefaults(settings);
        return false;
    }

    JsonDocument doc;
    DeserializationError error = deserializeJson(doc, file);
    file.close();

    if (error) {
        applyFactoryDefaults(settings);
        return false;
    }

    if (doc["deviceId"].is<String>()) {
        settings.deviceId = doc["deviceId"].as<String>();
    }
    if (doc["deviceType"].is<String>()) {
        settings.deviceType = doc["deviceType"].as<String>();
    }
    if (doc["classroomZone"].is<String>()) {
        settings.classroomZone = doc["classroomZone"].as<String>();
    }
    if (doc["studentGroup"].is<String>()) {
        settings.studentGroup = doc["studentGroup"].as<String>();
    }
    if (doc["mqttEnabled"].is<bool>()) {
        settings.mqttEnabled = doc["mqttEnabled"].as<bool>();
    }
    if (doc["mqttHost"].is<String>()) {
        settings.mqttHost = doc["mqttHost"].as<String>();
    }
    if (doc["mqttPort"].is<uint16_t>()) {
        settings.mqttPort = doc["mqttPort"].as<uint16_t>();
    }
    if (doc["mqttUsername"].is<String>()) {
        settings.mqttUsername = doc["mqttUsername"].as<String>();
    }
    if (doc["mqttPassword"].is<String>()) {
        settings.mqttPassword = doc["mqttPassword"].as<String>();
    }
    if (doc["otaPassword"].is<String>()) {
        settings.otaPassword = doc["otaPassword"].as<String>();
    }
    if (doc["tcpServerHost"].is<String>()) {
        settings.tcpServerHost = doc["tcpServerHost"].as<String>();
    }
    if (doc["tcpServerPort"].is<uint16_t>()) {
        settings.tcpServerPort = doc["tcpServerPort"].as<uint16_t>();
    }
    if (doc["controlIpStart"].is<uint8_t>()) {
        settings.controlIpStart = doc["controlIpStart"].as<uint8_t>();
    }
    if (doc["controlIpEnd"].is<uint8_t>()) {
        settings.controlIpEnd = doc["controlIpEnd"].as<uint8_t>();
    }
    if (doc["controlSendRounds"].is<uint8_t>()) {
        settings.controlSendRounds = doc["controlSendRounds"].as<uint8_t>();
    }
    if (doc["controlBatchSize"].is<uint8_t>()) {
        settings.controlBatchSize = doc["controlBatchSize"].as<uint8_t>();
    }
    if (doc["controlBatchIntervalMs"].is<unsigned long>()) {
        settings.controlBatchIntervalMs = doc["controlBatchIntervalMs"].as<unsigned long>();
    }
    if (doc["telemetryIntervalMs"].is<unsigned long>()) {
        settings.telemetryIntervalMs = doc["telemetryIntervalMs"].as<unsigned long>();
    }
    if (doc["heartbeatIntervalMs"].is<unsigned long>()) {
        settings.heartbeatIntervalMs = doc["heartbeatIntervalMs"].as<unsigned long>();
    }
    if (doc["discoveryIntervalMs"].is<unsigned long>()) {
        settings.discoveryIntervalMs = doc["discoveryIntervalMs"].as<unsigned long>();
    }
    if (doc["liftTimeoutSec"].is<uint16_t>()) {
        settings.liftTimeoutSec = doc["liftTimeoutSec"].as<uint16_t>();
    }

    std::vector<WifiCredential> sanitized;
    bool updated = false;

    auto ensureDefaultCredential = [&](WifiCredential &cred) {
        if (cred.ssid == "SSKJ-4" || cred.ssid == "SSKJ-4G") {
            if (cred.ssid == "SSKJ-4") {
                cred.ssid = "SSKJ-4G";
                updated = true;
            }
        }
        if (cred.ssid == "SSKJ-4G" && cred.password.isEmpty()) {
            cred.password = "xszn486020zcs";
            updated = true;
        }
    };

    if (doc["wifi"].is<JsonArray>()) {
        JsonArray wifiArray = doc["wifi"].as<JsonArray>();
        for (JsonObject obj : wifiArray) {
            WifiCredential cred;
            cred.ssid = obj["ssid"].as<String>();
            cred.password = obj["password"].as<String>();
            if (cred.ssid.isEmpty()) {
                continue;
            }
            ensureDefaultCredential(cred);
            if (cred.password.isEmpty()) {
                // skip empty-password WiFi entries silently
                updated = true;
                continue;
            }
            sanitized.push_back(cred);
        }
    }

    // Ensure mandatory networks exist
    bool hasSskj4g = false;
    for (const auto &cred : sanitized) {
        if (cred.ssid == "SSKJ-4G") hasSskj4g = true;
    }

    if (!hasSskj4g) {
        sanitized.push_back({"SSKJ-4G", "xszn486020zcs"});
        updated = true;
    }

    if (settings.controlIpStart > settings.controlIpEnd) {
        uint8_t temp = settings.controlIpStart;
        settings.controlIpStart = settings.controlIpEnd;
        settings.controlIpEnd = temp;
        updated = true;
    }
    if (settings.controlIpStart < 1 || settings.controlIpStart > 254) {
        settings.controlIpStart = 100;
        updated = true;
    }
    if (settings.controlIpEnd < 1 || settings.controlIpEnd > 254) {
        settings.controlIpEnd = 130;
        updated = true;
    }
    if (settings.controlSendRounds == 0) {
        settings.controlSendRounds = 2;
        updated = true;
    }
    if (settings.controlBatchSize == 0) {
        settings.controlBatchSize = 2;
        updated = true;
    }
    if (settings.controlBatchIntervalMs < 10) {
        settings.controlBatchIntervalMs = 50;
        updated = true;
    }

    settings.wifiList = sanitized;

    if (updated) {
        saveSettings(settings);
    }

    return true;
}

bool saveSettings(const DeviceSettings &settings) {
    JsonDocument doc;
    doc["deviceId"] = settings.deviceId;
    doc["deviceType"] = settings.deviceType;
    doc["classroomZone"] = settings.classroomZone;
    doc["studentGroup"] = settings.studentGroup;
    doc["mqttEnabled"] = settings.mqttEnabled;
    doc["mqttHost"] = settings.mqttHost;
    doc["mqttPort"] = settings.mqttPort;
    doc["mqttUsername"] = settings.mqttUsername;
    doc["mqttPassword"] = settings.mqttPassword;
    doc["otaPassword"] = settings.otaPassword;
    doc["tcpServerHost"] = settings.tcpServerHost;
    doc["tcpServerPort"] = settings.tcpServerPort;
    doc["controlIpStart"] = settings.controlIpStart;
    doc["controlIpEnd"] = settings.controlIpEnd;
    doc["controlSendRounds"] = settings.controlSendRounds;
    doc["controlBatchSize"] = settings.controlBatchSize;
    doc["controlBatchIntervalMs"] = settings.controlBatchIntervalMs;
    doc["telemetryIntervalMs"] = settings.telemetryIntervalMs;
    doc["heartbeatIntervalMs"] = settings.heartbeatIntervalMs;
    doc["discoveryIntervalMs"] = settings.discoveryIntervalMs;
    doc["liftTimeoutSec"] = settings.liftTimeoutSec;

    JsonArray wifiArray = doc["wifi"].to<JsonArray>();
    for (const auto &cred : settings.wifiList) {
        JsonObject obj = wifiArray.add<JsonObject>();
        obj["ssid"] = cred.ssid;
        obj["password"] = cred.password;
    }

    File file = LittleFS.open(kConfigPath, "w");
    if (!file) {
        return false;
    }

    serializeJson(doc, file);
    file.close();
    return true;
}
