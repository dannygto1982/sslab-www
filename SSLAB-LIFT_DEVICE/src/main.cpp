#include <Arduino.h>
#include <LittleFS.h>
#include <ESP8266WiFi.h>
#include <ESP8266WiFiMulti.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPUpdateServer.h>
#include <ArduinoOTA.h>
#include <AsyncMqttClient.h>
#include <ArduinoJson.h>
#include <time.h>
#include <user_interface.h>
#include <stdio.h>
#include <deque>

#include "DeviceConfig.h"
#include "ProtocolHandler.h"
#include "WebPageAssets.h"

namespace {
constexpr char kFirmwareVersion[] = "1.0.0";
constexpr unsigned long kWifiConnectTimeoutMs = 20000;
constexpr unsigned long kMqttReconnectDelayMs = 5000;
constexpr char kConfigApPassword[] = "LiftDeviceAP";
constexpr char kConfigFilePath[] = "/config.json";
constexpr uint8_t kConfigButtonPin = 0;  // GPIO0 (Flash Button)
constexpr uint8_t kLiftUpPin = 12;        // GPIO12 (E_IO_1), active low lift up
constexpr uint8_t kLiftDownPin = 13;      // GPIO13 (E_IO_1b), active low lift down
constexpr uint8_t kComputerPowerPin = 14; // GPIO14 (E_IO_0), active low computer switch
constexpr uint8_t kLightingPin = 5;       // GPIO5  (E_IO_3), active low light switch
constexpr bool kOutputsActiveLow = true;
constexpr unsigned long kControlConnectTimeoutMs = 120;
constexpr size_t kLegacyQueueMaxTasks = 8;
constexpr unsigned long kConfigButtonHoldMs = 3000;
constexpr unsigned long kConfigButtonHoldToExitMs = 6000;
constexpr uint8_t kStatusLedPin = LED_BUILTIN;
constexpr bool kStatusLedActiveLow = true;
constexpr char kManufacturerName[] = "SSLAB";
constexpr char kModelName[] = "LIFT_DEVICE";
constexpr char kHardwareVersion[] = "1.0";

// SSLAB Protocol Topics (v3.2)
constexpr char kTopicDiscovery[] = "v1/devices/me/attributes";
constexpr char kTopicTelemetry[] = "v1/devices/me/telemetry";
constexpr char kTopicRpcRequestPrefix[] = "sslab/rpc/request/";
constexpr char kTopicRpcResponsePrefix[] = "v1/devices/me/rpc/response/";
}

struct DeviceRuntimeState {
    bool isOn = false; // General power
    bool lampStatus = false;
    bool computerStatus = false;
    bool motorFwdStatus = false;
    bool motorBwdStatus = false;
    String liftingState = "stop";
    String deviceStatus = "IDLE";
    String lastErrorCode;
    unsigned long lastUpdateMs = 0;
};

struct LegacyBroadcastTask {
    String payload;
    String tag;
    uint8_t currentHost = 100;
    uint8_t round = 0;
    uint16_t sentCount = 0;
    uint16_t successCount = 0;
    uint16_t failedCount = 0;
};

DeviceRuntimeState runtimeState;
DeviceSettings settings;
ProtocolHandler protocolHandler;

ESP8266WiFiMulti wifiMulti;
ESP8266WebServer webServer(80);
ESP8266HTTPUpdateServer httpUpdater;
AsyncMqttClient mqttClient;
WiFiClient tcpClient;

bool configPortalActive = false;
bool wifiEverConnected = false;
unsigned long wifiAttemptStartedAt = 0;
unsigned long lastMqttReconnectAttempt = 0;
unsigned long lastTcpReconnectAttempt = 0;
unsigned long lastTelemetrySent = 0;
unsigned long lastDiscoverySent = 0;
bool shouldReboot = false;
unsigned long rebootScheduledAt = 0;
bool ntpConfigured = false;
wl_status_t lastWifiStatus = WL_IDLE_STATUS;
bool configPortalSticky = false;
bool configButtonPrevPressed = false;
unsigned long configButtonPressStartedAt = 0;
bool statusLedCurrentlyOn = false;
bool statusLedBlinkEnabled = true;
unsigned long statusLedBlinkIntervalMs = 400;
unsigned long lastStatusLedToggleAt = 0;
uint8_t wifiAuthFailureCount = 0;
String wifiLastDisconnectReason;
String currentWifiSsid;
WiFiEventHandler stationDisconnectedHandler;
WiFiEventHandler stationGotIpHandler;

// Web log buffer
const size_t MAX_LOG_ENTRIES = 50;  // 扩大日志缓冲（原15）
struct LogEntry {
    String timestamp;
    String level;
    String message;
};
std::deque<LogEntry> webLogBuffer;
std::deque<LegacyBroadcastTask> legacyTaskQueue;
LegacyBroadcastTask activeLegacyTask;
bool legacyTaskInProgress = false;
unsigned long lastLegacyBatchSentAt = 0;
unsigned long mqttConnectedAt = 0;
unsigned long mqttLastDisconnectedAt = 0;
String mqttLastError;

// Forward declarations
String renderConfigPage();
uint8_t currentSignalQuality();
void handleRoot();
void handleConfigPost();
void handleStatus();
void handleApiStatus();
void handleSimulationAction();
void addWebLog(const String &level, const String &message);
void setupWiFiStation();
void maintainWiFi();
void startConfigPortal(bool sticky = false);
void stopConfigPortal();
void setupWebServer();
void setupOta();
void setupMqtt();
void attemptMqttReconnect();
void publishDiscoveryMessage();
void publishStateTelemetry();
void subscribeToRpcTopics();
// void maintainTcpConnection();
// void handleTransparentSerial();
void handleSerialCommand();
String getMacAddressString();
void logMqttMessage(const char *direction, const String &topic, const String &payload);
void handleConfigButton();
void updateStatusLedState(wl_status_t wifiStatus);
void processStatusLedBlink();
const char *decodeWifiDisconnectReason(uint8_t reason);
void clearWifiErrorState();
String computeDeviceIdFromMac();
void ensureDeviceIdFromMac(DeviceSettings &config, bool persistToFs);
bool publishJson(const char *topic, JsonDocument &doc, uint8_t qos, bool retain, const char *logDirection);
bool mapLiftingValueToRelays(const String &value, bool &motorFwd, bool &motorBwd);
String buildLegacyComputerPayload(bool status);
String buildLegacyLiftingPayload(bool motorFwd, bool motorBwd);
bool enqueueLegacyBroadcastTask(const String &payload, const String &tag, String &error);
bool sendLegacyPayloadToHost(uint8_t host, const String &payload);
void processLegacyTcpQueue();
bool executeComputerControl(bool status, JsonObject &result);
bool executeLiftingControl(const String &value, JsonObject &result);

// --- Implementation ---

void onMqttConnect(bool sessionPresent) {
    (void)sessionPresent;
    runtimeState.deviceStatus = "IDLE";
    mqttConnectedAt = millis();
    mqttLastError = "";
    addWebLog("INFO", "MQTT 已连接到 " + settings.mqttHost + ":" + String(settings.mqttPort));
    subscribeToRpcTopics();
    publishDiscoveryMessage();
    publishStateTelemetry();
}

void onMqttDisconnect(AsyncMqttClientDisconnectReason reason) {
    // runtimeState.deviceStatus = "OFFLINE";
    mqttLastDisconnectedAt = millis();
    mqttLastError = "断开原因: " + String(static_cast<int>(reason));
    addWebLog("WARN", "MQTT 连接断开 (reason: " + String(static_cast<int>(reason)) + ")");
}

void onMqttMessage(char *topic, char *payload, AsyncMqttClientMessageProperties properties,
                   size_t len, size_t index, size_t total) {
    (void)properties; (void)index; (void)total;

    if (topic == nullptr || payload == nullptr || len == 0) return;

    String topicStr(topic);
    String message;
    message.reserve(len + 1);
    for (size_t i = 0; i < len; ++i) message += static_cast<char>(payload[i]);

    if (topicStr.startsWith(kTopicRpcRequestPrefix)) {
        int lastSlashIndex = topicStr.lastIndexOf('/');
        String requestId = topicStr.substring(lastSlashIndex + 1);
        
        logMqttMessage("IN", topicStr, message);
        addWebLog("INFO", "收到 RPC [" + requestId + "]: " + message.substring(0, 80));

        JsonDocument doc;
        DeserializationError err = deserializeJson(doc, message);
        if (err) {
            addWebLog("WARN", "RPC 收到无效 JSON");
            return;
        }

        String method = doc["method"] | "";
        JsonObject params = doc["params"];

        JsonDocument responseDoc;
        responseDoc["deviceId"] = settings.deviceId;
        responseDoc["requestId"] = requestId;
        
        protocolHandler.processRequest(requestId, method, params, responseDoc);

        String responseTopic = String(kTopicRpcResponsePrefix) + requestId;
        publishJson(responseTopic.c_str(), responseDoc, 1, false, "RPC-RESPONSE");
        return;
    }

    logMqttMessage("IN", topicStr, message);
}

void setupWiFiStation() {
    WiFi.persistent(false);
    WiFi.mode(WIFI_STA);
    WiFi.setAutoConnect(false);
    WiFi.setAutoReconnect(true);

    ensureDeviceIdFromMac(settings, true);
    if (!settings.deviceId.isEmpty()) {
        WiFi.hostname(settings.deviceId);
    }

    wifiAuthFailureCount = 0;
    wifiLastDisconnectReason = String();
    currentWifiSsid = String();
    clearWifiErrorState();

    wifiMulti = ESP8266WiFiMulti();
    bool hasCandidate = false;
    for (const auto &cred : settings.wifiList) {
        if (!cred.ssid.isEmpty()) {
            wifiMulti.addAP(cred.ssid.c_str(), cred.password.c_str());
            hasCandidate = true;
        }
    }

    if (!hasCandidate) {
        startConfigPortal(true);
    }

    stationGotIpHandler = WiFi.onStationModeGotIP([](const WiFiEventStationModeGotIP &event) {
        currentWifiSsid = WiFi.SSID();
        wifiAuthFailureCount = 0;
        clearWifiErrorState();
        runtimeState.deviceStatus = "ONLINE";
        addWebLog("INFO", "WiFi 连接到 " + currentWifiSsid + " IP: " + event.ip.toString());
    });

    stationDisconnectedHandler = WiFi.onStationModeDisconnected([](const WiFiEventStationModeDisconnected &event) {
        wifiLastDisconnectReason = decodeWifiDisconnectReason(event.reason);
        runtimeState.lastErrorCode = wifiLastDisconnectReason;
        runtimeState.deviceStatus = "OFFLINE";
        addWebLog("WARN", "WiFi 断开: " + wifiLastDisconnectReason);

        if (event.reason == WIFI_DISCONNECT_REASON_AUTH_FAIL || event.reason == WIFI_DISCONNECT_REASON_NO_AP_FOUND) {
             if (wifiAuthFailureCount < 255) ++wifiAuthFailureCount;
        } else {
            wifiAuthFailureCount = 0;
        }

        if (wifiAuthFailureCount >= 3 && !configPortalActive) {
            startConfigPortal(true);
        }
    });

    wifiAttemptStartedAt = millis();
}

void startConfigPortal(bool sticky) {
    addWebLog("INFO", "配置门户已启动");
    configPortalActive = true;
    configPortalSticky = sticky;

    WiFi.mode(WIFI_AP_STA);
    ensureDeviceIdFromMac(settings, false);
    String apName = settings.deviceId;
    if (apName.length() < 3) apName = computeDeviceIdFromMac();
    if (apName.length() < 3) apName = "SSLAB-SETUP";

    WiFi.softAP(apName.c_str(), kConfigApPassword);
    updateStatusLedState(WiFi.status());
}

void stopConfigPortal() {
    addWebLog("INFO", "配置门户已关闭");
    WiFi.softAPdisconnect(true);
    WiFi.mode(WIFI_STA);
    configPortalActive = false;
    configPortalSticky = false;
    wifiAttemptStartedAt = millis();
    updateStatusLedState(WiFi.status());
}

void maintainWiFi() {
    // When already connected, just check status without blocking.
    // When not connected, call run() every 3s with default timeout to allow
    // enough time for association + DHCP (~2-3s needed).
    static unsigned long lastRunAttemptMs = 0;
    wl_status_t status = WiFi.status();
    if (status != WL_CONNECTED) {
        unsigned long now = millis();
        if (now - lastRunAttemptMs >= 3000) {
            lastRunAttemptMs = now;
            status = wifiMulti.run();  // default 5000ms per AP, enough for DHCP
        }
    }
    if (status == WL_CONNECTED) {
        if (lastWifiStatus != WL_CONNECTED) {
            wifiEverConnected = true;
        }
        wifiAttemptStartedAt = millis();
        // runtimeState.deviceStatus = "ONLINE"; // Removed: deviceStatus is for operational state (IDLE/RUNNING)
        if (configPortalActive && !configPortalSticky) {
            stopConfigPortal();
        }
    } else {
        // runtimeState.deviceStatus = "OFFLINE"; // Removed
        if (!configPortalActive && (millis() - wifiAttemptStartedAt > kWifiConnectTimeoutMs)) {
            startConfigPortal(false);
        }
    }
    lastWifiStatus = status;
    updateStatusLedState(status);
}

void setupWebServer() {
    webServer.on("/", HTTP_GET, handleRoot);
    webServer.on("/config", HTTP_POST, handleConfigPost);
    webServer.on("/status", HTTP_GET, handleStatus);
    webServer.on("/api/status", HTTP_GET, handleApiStatus);
    webServer.on("/simulate", HTTP_POST, handleSimulationAction);
    webServer.onNotFound([] { webServer.send(404, "application/json", "{\"error\":\"Not Found\"}"); });

    httpUpdater.setup(&webServer, "/update", "admin", settings.otaPassword.c_str());
    webServer.begin();
}

void setupOta() {
    ArduinoOTA.setHostname(settings.deviceId.c_str());
    if (!settings.otaPassword.isEmpty()) ArduinoOTA.setPassword(settings.otaPassword.c_str());
    ArduinoOTA.begin();
}

void setupMqtt() {
    mqttClient.onConnect(onMqttConnect);
    mqttClient.onDisconnect(onMqttDisconnect);
    mqttClient.onMessage(onMqttMessage);

    if (!settings.mqttHost.isEmpty()) {
        mqttClient.setServer(settings.mqttHost.c_str(), settings.mqttPort);
    }
    if (!settings.mqttUsername.isEmpty()) {
        mqttClient.setCredentials(settings.mqttUsername.c_str(), settings.mqttPassword.c_str());
    }
    // Protocol suggests {deviceType}_{deviceId} for Client ID
    String clientId = settings.deviceType + "_" + settings.deviceId;
    mqttClient.setClientId(clientId.c_str());
    mqttClient.setKeepAlive(60);
}

void attemptMqttReconnect() {
    if (settings.mqttHost.isEmpty()) return;
    unsigned long now = millis();
    if (now - lastMqttReconnectAttempt < kMqttReconnectDelayMs) return;
    lastMqttReconnectAttempt = now;
    mqttClient.connect();
}

void setup() {
    Serial.begin(9600);  // 串口转TCP服务器波特率 9600

    if (!LittleFS.begin()) {
        LittleFS.format();
        LittleFS.begin();
        addWebLog("ERROR", "LittleFS 挂载失败，已格式化");
    }

    if (loadSettings(settings)) {
        addWebLog("INFO", "配置已加载");
    } else {
        addWebLog("WARN", "使用出厂默认配置");
    }

    pinMode(kConfigButtonPin, INPUT_PULLUP);
    pinMode(kStatusLedPin, OUTPUT);
    digitalWrite(kStatusLedPin, kStatusLedActiveLow ? HIGH : LOW);

    pinMode(kLiftUpPin, OUTPUT);
    pinMode(kLiftDownPin, OUTPUT);
    pinMode(kComputerPowerPin, OUTPUT);
    pinMode(kLightingPin, OUTPUT);
    
    // Initialize outputs to OFF state
    digitalWrite(kLiftUpPin, kOutputsActiveLow ? HIGH : LOW);
    digitalWrite(kLiftDownPin, kOutputsActiveLow ? HIGH : LOW);
    digitalWrite(kComputerPowerPin, kOutputsActiveLow ? HIGH : LOW);
    digitalWrite(kLightingPin, kOutputsActiveLow ? HIGH : LOW);

    // Register Protocol Callbacks
    protocolHandler.setComputerControlCallback([](bool status, JsonObject& result) -> bool {
        return executeComputerControl(status, result);
    });

    protocolHandler.setLampControlCallback([](bool status, int brightness, JsonObject& result) -> bool {
        runtimeState.lampStatus = status;
        digitalWrite(kLightingPin, (status ^ kOutputsActiveLow) ? HIGH : LOW);
        addWebLog("INFO", String("灯光: ") + (status ? "ON" : "OFF"));
        result["status"] = status;
        if (brightness >= 0) result["brightness"] = brightness;
        publishStateTelemetry();
        return true;
    });

    protocolHandler.setLiftingControlCallback([](const String& value, JsonObject& result) -> bool {
        return executeLiftingControl(value, result);
    });

    protocolHandler.setGroupCallback([](const String& group, JsonObject& result) -> bool {
        settings.studentGroup = group;
        saveSettings(settings);
        addWebLog("INFO", "分组更新: " + group);
        result["studentGroup"] = group;
        publishDiscoveryMessage(); 
        publishStateTelemetry();
        return true;
    });

    setupWiFiStation();
    setupMqtt();
    setupWebServer();
    setupOta();
}

void updateHardwareOutputs() {
    digitalWrite(kLiftUpPin, (runtimeState.motorFwdStatus ^ kOutputsActiveLow) ? HIGH : LOW);
    digitalWrite(kLiftDownPin, (runtimeState.motorBwdStatus ^ kOutputsActiveLow) ? HIGH : LOW);
    digitalWrite(kComputerPowerPin, (runtimeState.computerStatus ^ kOutputsActiveLow) ? HIGH : LOW);
    digitalWrite(kLightingPin, (runtimeState.lampStatus ^ kOutputsActiveLow) ? HIGH : LOW);
}

void loop() {
    updateHardwareOutputs();
    handleConfigButton();
    maintainWiFi();
    handleSerialCommand(); // Handle JSON commands via Serial
    processLegacyTcpQueue();

    if (WiFi.status() == WL_CONNECTED) {
        if (!ntpConfigured) {
            configTime(8 * 3600, 0, "cn.pool.ntp.org", "pool.ntp.org");
            ntpConfigured = true;
        }
        if (!mqttClient.connected()) {
            attemptMqttReconnect();
        }
    } else {
        ntpConfigured = false;
    }

    ArduinoOTA.handle();
    webServer.handleClient();
    processStatusLedBlink();

    unsigned long now = millis();
    if (now - lastDiscoverySent >= settings.discoveryIntervalMs) {
        publishDiscoveryMessage();
        lastDiscoverySent = now;
    }
    if (now - lastTelemetrySent >= settings.telemetryIntervalMs) {
        publishStateTelemetry();
    }

    // Resource Monitor
    static unsigned long lastResourceLog = 0;
    if (now - lastResourceLog > 30000) {
        lastResourceLog = now;
        uint32_t freeHeap = ESP.getFreeHeap();
        uint8_t frag = ESP.getHeapFragmentation();
        addWebLog("INFO", "堆: " + String(freeHeap) + "B 碎片:" + String(frag) + "%");
        if (freeHeap < 10000) {
            addWebLog("WARN", "Low Memory: " + String(freeHeap) + "B");
        }
    }

    if (shouldReboot && (millis() - rebootScheduledAt > 3000)) {
        ESP.restart();
    }
}

// --- Helper Functions ---

int32_t currentSignalStrengthDbm() {
    return (WiFi.status() == WL_CONNECTED) ? WiFi.RSSI() : -100;
}

uint8_t currentSignalQuality() {
    int32_t rssi = currentSignalStrengthDbm();
    if (rssi >= -30) return 100;
    if (rssi <= -90) return 0;
    if (rssi >= -50) return static_cast<uint8_t>(100 - ((50 + rssi) * 10 / 20));
    else if (rssi >= -60) return static_cast<uint8_t>(90 - ((60 + rssi) * 15 / 10));
    else if (rssi >= -67) return static_cast<uint8_t>(75 - ((67 + rssi) * 25 / 7));
    else if (rssi >= -70) return static_cast<uint8_t>(50 - ((70 + rssi) * 10 / 3));
    else if (rssi >= -80) return static_cast<uint8_t>(40 - ((80 + rssi) * 20 / 10));
    else return static_cast<uint8_t>(20 - ((90 + rssi) * 20 / 10));
}

String renderConfigPage() {
    String page = WebPageAssets::getHeader("升降设备 (LIFT_DEVICE)");
    
    page += F("<form method=\"POST\" action=\"/config\">");
    page += F("<section class=\"card\"><h2>设备状态</h2>");
    page += F("<div class=\"status-grid\">");
    page += F("<div class=\"status-pill\"><strong>Wi-Fi</strong><span>");
    page += (WiFi.status() == WL_CONNECTED) ? ("已连接 " + currentWifiSsid) : "未连接";
    page += F("</span></div>");
    page += F("<div class=\"status-pill\"><strong>运行状态</strong><span>");
    page += runtimeState.deviceStatus;
    page += F("</span></div>");
    page += F("<div class=\"status-pill\"><strong>信号质量</strong><span>");
    page += String(currentSignalQuality()) + "% (" + String(currentSignalStrengthDbm()) + " dBm)";
    page += F("</span></div></div></section>");

    page += F("<section class=\"card\"><h2>基本配置</h2>");
    page += F("<div class=\"grid-two\">");
    page += F("<label>Device ID<input name=\"deviceId\" value=\"");
    page += settings.deviceId;
    page += F("\" readonly></label>");
    page += F("<label>Device Type<input name=\"deviceType\" value=\"");
    page += settings.deviceType;
    page += F("\"></label>");
    page += F("<label>Classroom Zone<input name=\"classroomZone\" value=\"");
    page += settings.classroomZone;
    page += F("\"></label>");
    page += F("<label>Student Group<input name=\"studentGroup\" value=\"");
    page += settings.studentGroup;
    page += F("\"></label>");
    page += F("<label>MQTT Host<input name=\"mqttHost\" value=\"");
    page += settings.mqttHost;
    page += F("\"></label>");
    page += F("<label>MQTT Port<input type=\"number\" name=\"mqttPort\" value=\"");
    page += settings.mqttPort;
    page += F("\"></label>");
    page += F("<label>TCP Server Port<input type=\"number\" name=\"tcpServerPort\" value=\"");
    page += settings.tcpServerPort;
    page += F("\"></label></div>");
    
    page += F("<button class=\"primary-btn\" type=\"submit\">💾 保存并重启</button>");
    page += F("</section></form>");

    page += F("<section class=\"card\"><h2>模拟控制</h2>");
    page += F("<div class=\"simulate-grid\">");
    page += F("<button type=\"button\" data-action=\"LIFT_UP\">上升 (Up)</button>");
    page += F("<button type=\"button\" data-action=\"LIFT_DOWN\">下降 (Down)</button>");
    page += F("<button type=\"button\" data-action=\"LIFT_STOP\">停止 (Stop)</button>");
    page += F("<button type=\"button\" data-action=\"LAMP_TOGGLE\">灯光开关</button>");
    page += F("<button type=\"button\" data-action=\"PC_TOGGLE\">电脑开关</button></div>");
    page += F("<pre id=\"simulateResult\">等待操作...</pre></section>");

    page += F("<section class=\"card\"><h2>系统日志</h2>");
    page += F("<div id=\"mqttStatus\" class=\"status-grid\" style=\"margin-bottom:1rem;\">");
    page += F("<div class=\"status-pill\"><strong>MQTT</strong><span id=\"mqttState\">-</span></div>");
    page += F("<div class=\"status-pill\"><strong>Uptime</strong><span id=\"mqttUptime\">-</span></div>");
    page += F("<div class=\"status-pill\"><strong>Last Error</strong><span id=\"mqttError\">-</span></div></div>");
    page += F("<div style=\"max-height:300px;overflow-y:auto;padding:1rem;border-radius:12px;background:#f8fafc;border:1px solid var(--border);\">");
    page += F("<div id=\"logContainer\">正在加载日志...</div></div></section>");

    page += WebPageAssets::getFooter();
    return page;
}

void handleRoot() {
    webServer.send(200, "text/html", renderConfigPage());
}

void handleConfigPost() {
    DeviceSettings newSettings = settings;
    if (webServer.hasArg("deviceId")) newSettings.deviceId = webServer.arg("deviceId");
    if (webServer.hasArg("deviceType")) newSettings.deviceType = webServer.arg("deviceType");
    if (webServer.hasArg("classroomZone")) newSettings.classroomZone = webServer.arg("classroomZone");
    if (webServer.hasArg("studentGroup")) newSettings.studentGroup = webServer.arg("studentGroup");
    if (webServer.hasArg("mqttHost")) newSettings.mqttHost = webServer.arg("mqttHost");
    if (webServer.hasArg("mqttPort")) newSettings.mqttPort = webServer.arg("mqttPort").toInt();
    if (webServer.hasArg("tcpServerPort")) newSettings.tcpServerPort = webServer.arg("tcpServerPort").toInt();

    ensureDeviceIdFromMac(newSettings, false);
    if (saveSettings(newSettings)) {
        settings = newSettings;
        webServer.send(200, "text/html", "<html><body><h2>Saved. Rebooting...</h2></body></html>");
        shouldReboot = true;
        rebootScheduledAt = millis();
    } else {
        webServer.send(500, "text/html", "Failed to save");
    }
}

void handleStatus() {
    JsonDocument doc;
    doc["deviceId"] = settings.deviceId;
    doc["firmwareVersion"] = kFirmwareVersion;
    doc["wifiConnected"] = (WiFi.status() == WL_CONNECTED);
    doc["ipAddress"] = WiFi.localIP().toString();
    doc["deviceStatus"] = runtimeState.deviceStatus;
    String payload;
    serializeJson(doc, payload);
    webServer.send(200, "application/json", payload);
}

void addWebLog(const String &level, const String &message) {
    LogEntry entry;
    unsigned long now = millis();
    unsigned long seconds = now / 1000;
    entry.timestamp = String(seconds / 3600) + ":" + String((seconds % 3600) / 60) + ":" + String(seconds % 60);
    entry.level = level;
    entry.message = message;
    webLogBuffer.push_back(entry);
    if (webLogBuffer.size() > MAX_LOG_ENTRIES) webLogBuffer.pop_front();
}

void handleApiStatus() {
    JsonDocument doc;
    JsonObject mqtt = doc["mqtt"].to<JsonObject>();
    mqtt["connected"] = mqttClient.connected();
    mqtt["server"] = settings.mqttHost + ":" + String(settings.mqttPort);
    mqtt["uptime"] = (mqttClient.connected() && mqttConnectedAt > 0) ? (millis() - mqttConnectedAt) : 0;
    mqtt["lastError"] = mqttLastError;

    JsonObject queue = doc["controlQueue"].to<JsonObject>();
    queue["pending"] = legacyTaskQueue.size();
    queue["inProgress"] = legacyTaskInProgress;
    queue["activeTag"] = legacyTaskInProgress ? activeLegacyTask.tag : "";
    
    JsonArray logs = doc["logs"].to<JsonArray>();
    for (auto it = webLogBuffer.rbegin(); it != webLogBuffer.rend(); ++it) {
        JsonObject logEntry = logs.add<JsonObject>();
        logEntry["timestamp"] = it->timestamp;
        logEntry["level"] = it->level;
        logEntry["message"] = it->message;
    }
    String payload;
    serializeJson(doc, payload);
    webServer.send(200, "application/json", payload);
}

void publishDiscoveryMessage() {
    JsonDocument doc;
    doc["deviceId"] = settings.deviceId;
    doc["deviceType"] = settings.deviceType;
    doc["classroomZone"] = settings.classroomZone; // Spec recommended camelCase
    doc["studentGroup"] = settings.studentGroup; // Spec recommended camelCase
    
    JsonArray capabilities = doc["capabilities"].to<JsonArray>();
    capabilities.add("controlComputer");
    capabilities.add("controlLifting");
    capabilities.add("controlLamp");
    
    JsonObject deviceInfo = doc["deviceInfo"].to<JsonObject>();
    deviceInfo["manufacturer"] = kManufacturerName;
    deviceInfo["model"] = kModelName;
    deviceInfo["firmwareVersion"] = kFirmwareVersion;
    deviceInfo["hardwareVersion"] = kHardwareVersion;
    deviceInfo["serialNumber"] = settings.deviceId;
    
    JsonObject network = doc["network"].to<JsonObject>();
    network["ipAddress"] = WiFi.localIP().toString();
    network["macAddress"] = getMacAddressString();
    network["signalStrength"] = currentSignalQuality();
    
    String payload;
    serializeJson(doc, payload);
    if (mqttClient.connected()) mqttClient.publish(kTopicDiscovery, 1, false, payload.c_str());
    // Serial.println removed: Discovery JSON 不再通过串口输出，避免污染 RS485 总线
}

void publishStateTelemetry() {
    JsonDocument doc;
    doc["deviceId"] = settings.deviceId;
    doc["deviceType"] = settings.deviceType;
    doc["timestamp"] = time(nullptr) * 1000LL; 
    doc["classroomZone"] = settings.classroomZone; // Spec recommended camelCase
    doc["studentGroup"] = settings.studentGroup; // Spec recommended camelCase
    
    // Heartbeat fields
    doc["status"] = "ONLINE";
    doc["uptime"] = millis() / 1000;
    doc["ipAddress"] = WiFi.localIP().toString();
    doc["signalQuality"] = currentSignalQuality();
    
    // Required by protocol v3.2
    doc["memoryUsage"] = (1.0f - (float)ESP.getFreeHeap() / 81920.0f) * 100.0f; // Approx for ESP8266
    doc["cpuUsage"] = 0; // Not supported on ESP8266

    doc["lampStatus"] = runtimeState.lampStatus;
    doc["computerStatus"] = runtimeState.computerStatus;
    doc["motorFwd"] = runtimeState.motorFwdStatus;
    doc["motorBwd"] = runtimeState.motorBwdStatus;
    doc["liftingState"] = runtimeState.liftingState;
    doc["deviceStatus"] = runtimeState.deviceStatus;
    
    String payload;
    serializeJson(doc, payload);
    if (mqttClient.connected()) mqttClient.publish(kTopicTelemetry, 1, false, payload.c_str());
    lastTelemetrySent = millis();
}

void subscribeToRpcTopics() {
    if (!mqttClient.connected()) return;
    String rpcTopic = String(kTopicRpcRequestPrefix) + settings.deviceId + "/+";
    mqttClient.subscribe(rpcTopic.c_str(), 1);
    addWebLog("INFO", "MQTT 订阅: " + rpcTopic);
}

/*
// TCP Connection disabled to save resources and avoid conflicts
void maintainTcpConnection() {
    if (WiFi.status() != WL_CONNECTED) return;
    if (!tcpClient.connected()) {
        unsigned long now = millis();
        if (now - lastTcpReconnectAttempt > 5000) {
            lastTcpReconnectAttempt = now;
            if (tcpClient.connect(settings.tcpServerHost.c_str(), settings.tcpServerPort)) {
                tcpClient.setNoDelay(true);
                addWebLog("INFO", "TCP 透传已连接 " + settings.tcpServerHost + ":" + String(settings.tcpServerPort));
            }
        }
    }
}
*/

// Non-blocking Serial Command Handler
void handleSerialCommand() {
    static String serialBuffer = "";
    static unsigned long lastSerialActivity = 0;

    while (Serial.available()) {
        char c = (char)Serial.read();
        lastSerialActivity = millis();
        
        if (c == '\n') {
            serialBuffer.trim();
            if (serialBuffer.length() > 0) {
                // Process the command
                JsonDocument doc;
                DeserializationError error = deserializeJson(doc, serialBuffer);
                
                if (!error) {
                    if (doc["method"].is<String>()) {
                        String method = doc["method"];
                        JsonObject params = doc["params"];
                        String requestId = doc["requestId"] | "serial_cmd";
                        
                        JsonDocument responseDoc;
                        responseDoc["deviceId"] = settings.deviceId;
                        responseDoc["requestId"] = requestId;
                        
                        protocolHandler.processRequest(requestId, method, params, responseDoc);
                        
                        String responsePayload;
                        serializeJson(responseDoc, responsePayload);
                        Serial.println(responsePayload);
                    }
                } else {
                    Serial.println(F("{\"error\":\"Invalid JSON\"}"));
                }
            }
            serialBuffer = ""; // Clear buffer
        } else {
            if (serialBuffer.length() < 512) { // Prevent buffer overflow
                serialBuffer += c;
            }
        }
    }

    // Clear buffer if timeout (e.g. noise or incomplete transmission)
    if (serialBuffer.length() > 0 && (millis() - lastSerialActivity > 2000)) {
        serialBuffer = "";
    }
}

String getMacAddressString() {
    uint8_t mac[6];
    wifi_get_macaddr(STATION_IF, mac);
    char macStr[18];
    snprintf(macStr, sizeof(macStr), "%02X:%02X:%02X:%02X:%02X:%02X", mac[0], mac[1], mac[2], mac[3], mac[4], mac[5]);
    return String(macStr);
}

void logMqttMessage(const char *direction, const String &topic, const String &payload) {
    (void)payload; // 不将 MQTT payload 输出到串口，防止污染 RS485
    addWebLog("DEBUG", String("MQTT ") + direction + ": " + topic);
}

void handleConfigButton() {
    // TODO: Implement button logic if needed
}

void updateStatusLedState(wl_status_t wifiStatus) {
    if (configPortalActive) {
        statusLedBlinkEnabled = true;
        statusLedBlinkIntervalMs = 100;
        return;
    }
    if (wifiStatus == WL_CONNECTED) {
        statusLedBlinkEnabled = false;
        digitalWrite(kStatusLedPin, kStatusLedActiveLow ? LOW : HIGH);
    } else {
        statusLedBlinkEnabled = true;
        statusLedBlinkIntervalMs = 500;
    }
}

void processStatusLedBlink() {
    if (!statusLedBlinkEnabled) return;
    unsigned long currentTime = millis();
    if (currentTime - lastStatusLedToggleAt >= statusLedBlinkIntervalMs) {
        statusLedCurrentlyOn = !statusLedCurrentlyOn;
        int level = (statusLedCurrentlyOn) ? (kStatusLedActiveLow ? LOW : HIGH) : (kStatusLedActiveLow ? HIGH : LOW);
        digitalWrite(kStatusLedPin, level);
        lastStatusLedToggleAt = currentTime;
    }
}

const char *decodeWifiDisconnectReason(uint8_t reason) {
    switch (reason) {
        case 1: return "Unspecified";
        case 2: return "Auth failed";
        case 3: return "Assoc failed";
        case 201: return "No AP found";
        case 202: return "Auth fail";
        default: return "Other";
    }
}

void clearWifiErrorState() {
    wifiLastDisconnectReason = "";
    wifiAuthFailureCount = 0;
}

String computeDeviceIdFromMac() {
    String mac = getMacAddressString();
    mac.replace(":", "");
    return "LD-" + mac.substring(mac.length() - 4);
}

bool isValidDeviceId(const String& id) {
    if (id.length() < 3 || id.length() > 32) return false;
    for (unsigned int i = 0; i < id.length(); i++) {
        char c = id.charAt(i);
        // Allow alphanumeric, hyphen, underscore
        if (!isalnum(c) && c != '-' && c != '_') return false;
    }
    return true;
}

void ensureDeviceIdFromMac(DeviceSettings &config, bool persistToFs) {
    // Reset if empty, contains colon (MAC format), or contains invalid chars
    if (config.deviceId.isEmpty() || config.deviceId.indexOf(':') != -1 || !isValidDeviceId(config.deviceId)) {
        String newId = computeDeviceIdFromMac();
        addWebLog("WARN", "设备ID重置为: " + newId);
        config.deviceId = newId;
        if (persistToFs) saveSettings(config);
    }
}

bool publishJson(const char *topic, JsonDocument &doc, uint8_t qos, bool retain, const char *logDirection) {
    String payload;
    serializeJson(doc, payload);
    bool success = mqttClient.publish(topic, qos, retain, payload.c_str());
    if (success) logMqttMessage(logDirection, topic, payload);
    return success;
}

bool mapLiftingValueToRelays(const String &value, bool &motorFwd, bool &motorBwd) {
    String lowered = value;
    lowered.toLowerCase();
    if (lowered == "up") {
        motorFwd = true;
        motorBwd = false;
        return true;
    }
    if (lowered == "down") {
        motorFwd = true;
        motorBwd = true;
        return true;
    }
    if (lowered == "stop") {
        motorFwd = false;
        motorBwd = false;
        return true;
    }
    return false;
}

String buildLegacyComputerPayload(bool status) {
    return String("{\"device1\": ") + (status ? "true" : "false") + "}\n";
}

String buildLegacyLiftingPayload(bool motorFwd, bool motorBwd) {
    return String("{\"motor_fwd\": ") + (motorFwd ? "true" : "false") +
           ", \"motor_bwd\": " + (motorBwd ? "true" : "false") + "}\n";
}

bool enqueueLegacyBroadcastTask(const String &payload, const String &tag, String &error) {
    if (legacyTaskQueue.size() >= kLegacyQueueMaxTasks) {
        error = "Legacy queue is full";
        return false;
    }
    LegacyBroadcastTask task;
    task.payload = payload;
    task.tag = tag;
    task.currentHost = settings.controlIpStart;
    legacyTaskQueue.push_back(task);
    return true;
}

bool sendLegacyPayloadToHost(uint8_t host, const String &payload) {
    WiFiClient client;
    IPAddress ip(192, 168, 0, host);
    bool connected = client.connect(ip, settings.tcpServerPort);
    if (!connected) return false;
    size_t bytesWritten = client.print(payload);
    client.stop();
    return bytesWritten == payload.length();
}

void processLegacyTcpQueue() {
    if (WiFi.status() != WL_CONNECTED) return;

    if (!legacyTaskInProgress) {
        if (legacyTaskQueue.empty()) return;
        activeLegacyTask = legacyTaskQueue.front();
        legacyTaskQueue.pop_front();
        activeLegacyTask.currentHost = settings.controlIpStart;
        activeLegacyTask.round = 0;
        activeLegacyTask.sentCount = 0;
        activeLegacyTask.successCount = 0;
        activeLegacyTask.failedCount = 0;
        legacyTaskInProgress = true;
        lastLegacyBatchSentAt = 0;
        addWebLog("INFO", "下发任务开始: " + activeLegacyTask.tag);
    }

    unsigned long now = millis();
    if (now - lastLegacyBatchSentAt < settings.controlBatchIntervalMs) return;
    lastLegacyBatchSentAt = now;

    for (uint8_t i = 0; i < settings.controlBatchSize && legacyTaskInProgress; ++i) {
        bool sent = sendLegacyPayloadToHost(activeLegacyTask.currentHost, activeLegacyTask.payload);
        ++activeLegacyTask.sentCount;
        if (sent) {
            ++activeLegacyTask.successCount;
        } else {
            ++activeLegacyTask.failedCount;
        }

        if (activeLegacyTask.currentHost >= settings.controlIpEnd) {
            activeLegacyTask.currentHost = settings.controlIpStart;
            ++activeLegacyTask.round;
            if (activeLegacyTask.round >= settings.controlSendRounds) {
                legacyTaskInProgress = false;
                addWebLog(
                    "INFO",
                    "下发任务完成: " + activeLegacyTask.tag +
                    " sent=" + String(activeLegacyTask.sentCount) +
                    " ok=" + String(activeLegacyTask.successCount) +
                    " fail=" + String(activeLegacyTask.failedCount));
            }
        } else {
            ++activeLegacyTask.currentHost;
        }
    }
}

bool executeComputerControl(bool status, JsonObject &result) {
    runtimeState.computerStatus = status;
    runtimeState.lastUpdateMs = millis();
    String error;
    bool queued = enqueueLegacyBroadcastTask(
        buildLegacyComputerPayload(status),
        String("COMPUTER:") + (status ? "ON" : "OFF"),
        error);
    if (!queued) {
        result["status"] = status;
        result["queued"] = false;
        result["error"] = error;
        return false;
    }

    addWebLog("INFO", String("电脑控制入队: ") + (status ? "ON" : "OFF"));
    result["status"] = status;
    result["queued"] = true;
    result["targetPort"] = settings.tcpServerPort;
    publishStateTelemetry();
    return true;
}

bool executeLiftingControl(const String &value, JsonObject &result) {
    bool motorFwd = false;
    bool motorBwd = false;
    if (!mapLiftingValueToRelays(value, motorFwd, motorBwd)) {
        result["value"] = value;
        result["queued"] = false;
        result["error"] = "Invalid lifting value";
        return false;
    }

    runtimeState.motorFwdStatus = motorFwd;
    runtimeState.motorBwdStatus = motorBwd;
    runtimeState.liftingState = value;
    runtimeState.lastUpdateMs = millis();

    String error;
    bool queued = enqueueLegacyBroadcastTask(
        buildLegacyLiftingPayload(motorFwd, motorBwd),
        "LIFTING:" + value,
        error);
    if (!queued) {
        result["value"] = value;
        result["motor_fwd"] = motorFwd;
        result["motor_bwd"] = motorBwd;
        result["queued"] = false;
        result["error"] = error;
        return false;
    }

    addWebLog("INFO", "升降控制入队: " + value);
    result["value"] = value;
    result["motor_fwd"] = motorFwd;
    result["motor_bwd"] = motorBwd;
    result["queued"] = true;
    result["targetPort"] = settings.tcpServerPort;
    publishStateTelemetry();
    return true;
}

void handleSimulationAction() {
    if (!webServer.hasArg("plain")) {
        webServer.send(400, "application/json", "{\"error\":\"Missing body\"}");
        return;
    }
    JsonDocument doc;
    deserializeJson(doc, webServer.arg("plain"));
    String action = doc["action"].as<String>();
    
    bool applied = false;
    JsonDocument resultDoc;
    JsonObject result = resultDoc.to<JsonObject>();

    if (action == "LIFT_UP") {
        applied = executeLiftingControl("up", result);
    }
    else if (action == "LIFT_DOWN") {
        applied = executeLiftingControl("down", result);
    }
    else if (action == "LIFT_STOP") {
        applied = executeLiftingControl("stop", result);
    }
    else if (action == "LAMP_TOGGLE") {
        runtimeState.lampStatus = !runtimeState.lampStatus;
        runtimeState.lastUpdateMs = millis();
        applied = true;
        result["status"] = runtimeState.lampStatus;
    }
    else if (action == "PC_TOGGLE") {
        applied = executeComputerControl(!runtimeState.computerStatus, result);
    }
    
    publishStateTelemetry();
    
    JsonDocument response;
    response["success"] = applied;
    response["action"] = action;
    response["result"] = resultDoc;
    String payload;
    serializeJson(response, payload);
    webServer.send(200, "application/json", payload);
}
