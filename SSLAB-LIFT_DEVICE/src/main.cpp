#include <Arduino.h>
#include <LittleFS.h>
#include <ESP8266WiFi.h>
#include <ESP8266WiFiMulti.h>
#include <ESP8266WebServer.h>
#include <ESP8266HTTPUpdateServer.h>
#include <ESP8266mDNS.h>
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

// =============================================================================
// 性能与稳定性优化常量 (v3.3)
// =============================================================================
// 注：ArduinoJson v7 的 JsonDocument 为动态分配，不支持构造函数容量参数。
// 以下容量值仅供参考文档用途（单位：字节预估）。
//   小型: ~512B (ping, status)  中型: ~1024B (telemetry, cmd_result)
//   大型: ~2048B (discovery)    配置: ~3072B (config save)

// 堆保护
constexpr uint32_t kMinFreeHeapBytes      = 8192;  // 低于此值进入降级模式
constexpr uint32_t kCriticalFreeHeapBytes = 4096;  // 低于此值只保留基本功能

// Loop 健康检查
constexpr unsigned long kMaxLoopDurationMs      = 3000;   // 单轮 loop 超过此值告警
constexpr unsigned long kMaxTcpTimeSliceMs       = 30;    // 每轮 TCP 广播最大时间片

// NTP
constexpr unsigned long kNtpSyncTimeoutMs = 15000;  // NTP 超时后不再重试 (直到 WiFi 重连)
constexpr unsigned long kNtpSyncStartGraceMs = 5000; // WiFi 连上后延迟 N s 再同步 (给 LWIP 稳定时间)

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
constexpr unsigned long kControlConnectTimeoutMs = 30;   // 单主机 TCP 连接超时 (缩短以加快广播)
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
    // 升降自动停止定时器
    bool liftAutoStopActive = false;
    unsigned long liftAutoStopStartedAt = 0;
    uint16_t liftAutoStopTimeoutSec = 0;
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
String lastSerialFrameHex;
size_t lastSerialFrameLen = 0;

// Forward declarations
String renderConfigPage();
uint8_t currentSignalQuality();
void handleRoot();
void handleConfigPost();
void handleStatus();
void handleApiStatus();
void handleSimulationAction();
void handleStyleCss();
void handleAppJs();
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
    mqttLastDisconnectedAt = millis();
    mqttLastError = "断开原因: " + String(static_cast<int>(reason));
    if (settings.mqttEnabled) {  // only log when MQTT is supposed to be on
        addWebLog("WARN", "MQTT 连接断开 (reason: " + String(static_cast<int>(reason)) + ")");
    }
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
        String ipStr = event.ip.toString();
        addWebLog("INFO", "WiFi 连接到 " + currentWifiSsid + " IP: " + ipStr);
        addWebLog("INFO", "网页: http://" + ipStr + "/  或  http://" + settings.deviceId + ".local/");
        Serial.println("STA CONNECTED: " + currentWifiSsid + " IP=" + ipStr);
        // 重启 mDNS 以发布 STA IP
        MDNS.end();
        MDNS.begin(settings.deviceId.c_str());
        MDNS.addService("http", "tcp", 80);
        updateStatusLedState(WL_CONNECTED);  // 立即亮灯
    });

    stationDisconnectedHandler = WiFi.onStationModeDisconnected([](const WiFiEventStationModeDisconnected &event) {
        wifiLastDisconnectReason = decodeWifiDisconnectReason(event.reason);
        runtimeState.lastErrorCode = wifiLastDisconnectReason;
        runtimeState.deviceStatus = "OFFLINE";
        addWebLog("WARN", "WiFi 断开: " + wifiLastDisconnectReason);
        updateStatusLedState(WL_DISCONNECTED);  // 立即慢闪

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
    // 告知用户 SoftAP 访问地址
    String apIp = WiFi.softAPIP().toString();
    addWebLog("INFO", "配置门户 AP: " + apName + " 密码: " + String(kConfigApPassword));
    addWebLog("INFO", "请连接 WiFi \"" + apName + "\" 后访问 http://" + apIp + "/");
    Serial.println("CONFIG PORTAL: SSID=" + apName + " IP=" + apIp);
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
    static unsigned long lastRunAttemptMs = 0;
    static unsigned long wifiDisconnectedSinceMs = 0;  // 断线计时器
    static unsigned long lastReconnectLogMs = 0;        // 重连日志限频
    static uint8_t reconnectAttempts = 0;               // 当前轮重连次数

    wl_status_t status = WiFi.status();

    if (status != WL_CONNECTED) {
        unsigned long now = millis();

        // 记录断线起始时间
        if (wifiDisconnectedSinceMs == 0) {
            wifiDisconnectedSinceMs = now;
            reconnectAttempts = 0;
        }

        // 超过 5 分钟未连接：自动重启
        if (now - wifiDisconnectedSinceMs > 300000UL) {
            addWebLog("ERROR", "WiFi 断线超过 5 分钟，自动重启");
            delay(500);
            ESP.restart();
            return;
        }

        // 每 60 秒输出一次重连日志
        if (now - lastReconnectLogMs > 60000UL) {
            lastReconnectLogMs = now;
            unsigned long downSec = (now - wifiDisconnectedSinceMs) / 1000;
            addWebLog("WARN", "WiFi 已断线 " + String(downSec) + "s，尝试重连(" + String(reconnectAttempts) + "次)");
        }

        // 每 3 秒尝试一次连接；连接期间置 IDLE 状态让 LED 快闪
        if (now - lastRunAttemptMs >= 3000) {
            lastRunAttemptMs = now;
            ++reconnectAttempts;
            updateStatusLedState(WL_IDLE_STATUS);  // 快闪：正在连接
            ESP.wdtFeed();  // wifiMulti.run 可阻塞 1s，提前喂狗
            status = wifiMulti.run(1000);           // 1s 超时，减少循环阻塞
        }
    } else {
        // 已连接：清除断线计时
        if (wifiDisconnectedSinceMs != 0) {
            addWebLog("INFO", "WiFi 重连成功 (尝试 " + String(reconnectAttempts) + " 次)");
            wifiDisconnectedSinceMs = 0;
            reconnectAttempts = 0;
        }
    }

    if (status == WL_CONNECTED) {
        if (lastWifiStatus != WL_CONNECTED) {
            wifiEverConnected = true;
        }
        wifiAttemptStartedAt = millis();
        if (configPortalActive && !configPortalSticky) {
            stopConfigPortal();
        }
    } else {
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
    webServer.on("/style.css", HTTP_GET, handleStyleCss);
    webServer.on("/app.js", HTTP_GET, handleAppJs);
    // 浏览器 favicon.ico 自动请求 → 204 No Content 减少流量
    webServer.on("/favicon.ico", HTTP_GET, [] {
        webServer.sendHeader("Cache-Control", "public, max-age=604800");
        webServer.send(204, "text/plain", "");
    });
    webServer.onNotFound([] {
        webServer.sendHeader("Connection", "close");
        webServer.send(404, "application/json", "{\"error\":\"Not Found\"}");
    });

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
    if (!settings.mqttEnabled) return;  // disabled — skip silently
    if (settings.mqttHost.isEmpty()) return;
    unsigned long now = millis();
    if (now - lastMqttReconnectAttempt < kMqttReconnectDelayMs) return;
    lastMqttReconnectAttempt = now;
    mqttClient.connect();
}

void setup() {
    Serial.setRxBufferSize(512);
    Serial.begin(9600);
    Serial.setDebugOutput(false); // 关闭框架debug输出，确保 Serial = UART0 GPIO1(TX)/GPIO3(RX)

    // === LittleFS 初始化（必须在 addWebLog 之前，因为 addWebLog 虽用内存 buffer，
    //     但后续 loadSettings 依赖 FS） ===
    bool fsOk = LittleFS.begin();
    if (!fsOk) {
        LittleFS.format();
        fsOk = LittleFS.begin();
        if (!fsOk) {
            // FS 彻底失败，无法持久化配置，但设备仍可运行（使用出厂默认）
            // 通过串口输出错误信息
            Serial.println("FATAL: LittleFS mount failed after format");
        }
    }

    if (loadSettings(settings)) {
        addWebLog("INFO", "配置已加载");
    } else {
        addWebLog("WARN", "使用出厂默认配置");
    }

    // === 串口回环自测（TX-RX短接验证）===
    // 移到 FS 初始化之后，确保 addWebLog 环境就绪
    delay(500);
    while (Serial.available()) Serial.read(); // 清空启动垃圾
    delay(50);

    Serial.print("LOOPBACK\n");
    Serial.flush();
    delay(200);

    char echoBuf[64] = {0};
    size_t echoLen = 0;
    unsigned long t = millis();
    while (millis() - t < 800) {
        if (Serial.available() && echoLen < sizeof(echoBuf) - 1) {
            echoBuf[echoLen++] = (char)Serial.read();
        }
        yield();
    }
    // trim trailing whitespace
    while (echoLen > 0 && (echoBuf[echoLen-1] == '\n' || echoBuf[echoLen-1] == '\r' || echoBuf[echoLen-1] == ' ')) {
        echoLen--;
    }
    echoBuf[echoLen] = '\0';

    if (strstr(echoBuf, "LOOPBACK") != nullptr) {
        addWebLog("RS485", String("回环自测 OK len=") + String(echoLen));
    } else {
        addWebLog("RS485", String("回环自测 FAIL len=") + String(echoLen));
    }
    // ===================================

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

    // WebServer 必须在 setupWiFiStation 之前初始化，
    // 因为 setupWiFiStation 可能在无凭据时立即启动配置门户 AP
    setupWebServer();
    setupOta();
    setupMqtt();
    setupWiFiStation();

    // mDNS: 设备可通过 http://{deviceId}.local 访问 (如 ld-dc4d.local)
    if (MDNS.begin(settings.deviceId.c_str())) {
        MDNS.addService("http", "tcp", 80);
        addWebLog("INFO", "mDNS 已启动: " + settings.deviceId + ".local");
    } else {
        addWebLog("WARN", "mDNS 启动失败");
    }
}

void updateHardwareOutputs() {
    digitalWrite(kLiftUpPin, (runtimeState.motorFwdStatus ^ kOutputsActiveLow) ? HIGH : LOW);
    digitalWrite(kLiftDownPin, (runtimeState.motorBwdStatus ^ kOutputsActiveLow) ? HIGH : LOW);
    digitalWrite(kComputerPowerPin, (runtimeState.computerStatus ^ kOutputsActiveLow) ? HIGH : LOW);
    digitalWrite(kLightingPin, (runtimeState.lampStatus ^ kOutputsActiveLow) ? HIGH : LOW);
}

void loop() {
    unsigned long loopEntryMs = millis();
    
    // === 软件看门狗喂养 (ESP8266 SDK 默认 3.2s 超时) ===
    ESP.wdtFeed();
    
    // === 堆保护 ===
    uint32_t freeHeap = ESP.getFreeHeap();
    bool criticalMemory = (freeHeap < kCriticalFreeHeapBytes);
    if (criticalMemory) {
        // 临界低内存：只保留 Web 服务 + 硬件输出 + WiFi 维护
        // 跳过 MQTT、TCP 广播、日志记录等非必要操作
        updateHardwareOutputs();
        handleConfigButton();
        maintainWiFi();
        webServer.handleClient();
        ArduinoOTA.handle();
        MDNS.update();
        processStatusLedBlink();
        if (shouldReboot && (millis() - rebootScheduledAt > 3000)) ESP.restart();
        yield();
        return;
    }
    
    updateHardwareOutputs();
    handleConfigButton();
    maintainWiFi();
    handleSerialCommand(); // Handle JSON commands via Serial

    // 升降自动停止检查
    if (runtimeState.liftAutoStopActive) {
        unsigned long elapsed = millis() - runtimeState.liftAutoStopStartedAt;
        if (elapsed >= runtimeState.liftAutoStopTimeoutSec * 1000UL) {
            runtimeState.motorFwdStatus = false;
            runtimeState.motorBwdStatus = false;
            runtimeState.liftingState = "stop";
            runtimeState.liftAutoStopActive = false;
            runtimeState.lastUpdateMs = millis();
            addWebLog("INFO", "升降自动停止 (超时" + String(runtimeState.liftAutoStopTimeoutSec) + "s)");
            publishStateTelemetry();
        }
    }

    // === Web 服务器优先处理（避免浏览器超时） ===
    webServer.handleClient();

    // Legacy TCP 队列处理 — 限时执行，防止阻塞 web 服务
    {
        unsigned long tcpStartMs = millis();
        while (millis() - tcpStartMs < kMaxTcpTimeSliceMs) {
            if (WiFi.status() != WL_CONNECTED) break;
            if (!legacyTaskInProgress && legacyTaskQueue.empty()) break;
            processLegacyTcpQueue();
            if (legacyTaskInProgress) {
                webServer.handleClient();
                ESP.wdtFeed(); // 广播期间喂养 WDT
            }
        }
    }

    if (WiFi.status() == WL_CONNECTED) {
        // NTP 同步：延迟启动 + 超时保护
        {
            static unsigned long wifiStableSince = 0;
            if (wifiStableSince == 0) wifiStableSince = millis();

            if (!ntpConfigured) {
                if (millis() - wifiStableSince > kNtpSyncStartGraceMs) {
                    configTime(8 * 3600, 0, "cn.pool.ntp.org", "pool.ntp.org");
                    ntpConfigured = true;
                }
            } else {
                // 超时检查：如果 NTP 长时间不响应，强制标记完成
                // time(nullptr)==0 比无限等待好（telemetry 会用 0 作为时间戳）
                static unsigned long ntpDeadlineMs = 0;
                if (time(nullptr) < 1000000000UL) {  // NTP 尚未同步
                    if (ntpDeadlineMs == 0) ntpDeadlineMs = millis() + kNtpSyncTimeoutMs;
                    // 不做二次 configTime，只记录日志
                    if (millis() > ntpDeadlineMs) {
                        ntpDeadlineMs = 0;  // 静默接受，不再重试
                    }
                }
            }
        }
        if (!mqttClient.connected()) {
            attemptMqttReconnect();
        }
    } else {
        if (ntpConfigured && lastWifiStatus == WL_CONNECTED) {
            ntpConfigured = false;
        }
    }

    ArduinoOTA.handle();
    MDNS.update();
    
    // 再次处理 web 请求（OTA 可能阻塞了一小段时间）
    if (millis() - loopEntryMs > 100) {
        webServer.handleClient();
    }
    
    processStatusLedBlink();

    unsigned long now = millis();
    // 低堆时跳过 MQTT publish（消息可能分配失败导致崩溃）
    bool lowMemory = (freeHeap < kMinFreeHeapBytes);
    if (!lowMemory) {
        if (now - lastDiscoverySent >= settings.discoveryIntervalMs) {
            publishDiscoveryMessage();
            lastDiscoverySent = now;
        }
        if (now - lastTelemetrySent >= settings.telemetryIntervalMs) {
            publishStateTelemetry();
        }
    }

    if (shouldReboot && (millis() - rebootScheduledAt > 3000)) {
        ESP.restart();
    }
    
    // 空闲 yield 给 ESP8266 WiFi 栈（LWIP 需要定时处理）
    yield();
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
    // 预分配 ~4.5KB 避免 30+ 次 String::+= 导致的堆碎片链
    String page = WebPageAssets::getHeader("升降设备 (LIFT_DEVICE)");
    page.reserve(4600);
    
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

    // OTA 升级状态区块
    page += F("<section class=\"card\"><h2>OTA 升级</h2>");
    page += F("<div class=\"status-grid\">");
    page += F("<div class=\"status-pill\"><strong>固件版本</strong><span>");
    page += kFirmwareVersion;
    page += F("</span></div>");
    page += F("<div class=\"status-pill\"><strong>mDNS 地址</strong><span>http://");
    page += settings.deviceId;
    page += F(".local/</span></div>");
    page += F("<div class=\"status-pill\"><strong>OTA 端点</strong><span>/update (admin)</span></div>");
    page += F("<div class=\"status-pill\"><strong>OTA 密码</strong><span>");
    page += settings.otaPassword;
    page += F("</span></div>");
    page += F("</div>");
    page += F("<p class=\"hint\" style=\"margin-top:1rem;\">OTA 烧录: PlatformIO 使用 espota 协议，目标 IP 192.168.0.112，<br>或通过 http://");
    page += WiFi.localIP().toString();
    page += F("/update 上传固件 (.bin)</p>");
    page += F("</section>");

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
    page += F("<label>MQTT 启用<input type=\"checkbox\" name=\"mqttEnabled\" value=\"1\"");
    if (settings.mqttEnabled) page += F(" checked");
    page += F("> 启用 MQTT 上报</label>");
    page += F("<label>MQTT Host<input name=\"mqttHost\" value=\"");
    page += settings.mqttHost;
    page += F("\"></label>");
    page += F("<label>MQTT Port<input type=\"number\" name=\"mqttPort\" value=\"");
    page += settings.mqttPort;
    page += F("\"></label>");
    page += F("<label>TCP Server Port<input type=\"number\" name=\"tcpServerPort\" value=\"");
    page += settings.tcpServerPort;
    page += F("\"></label>");
    page += F("<label>升降自动停止 (秒, 0=不自动停)<input type=\"number\" name=\"liftTimeoutSec\" value=\"");
    page += settings.liftTimeoutSec;
    page += F("\" min=\"0\" max=\"120\"></label></div>");
    
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
    // 设备实时状态（由 JS 轮询 /api/status 填充）
    page += F("<div id=\"devStateGrid\" class=\"status-grid\" style=\"margin-bottom:1rem;\">");
    page += F("<div class=\"status-pill\"><strong>电脑</strong><span>○ 加载中…</span></div>");
    page += F("<div class=\"status-pill\"><strong>升降</strong><span>■ 加载中…</span></div>");
    page += F("<div class=\"status-pill\"><strong>灯光</strong><span>🌑 加载中…</span></div>");
    page += F("<div class=\"status-pill\"><strong>最后更新</strong><span>--</span></div></div>");
    // RS485 最后帧
    page += F("<div id=\"rs485Info\" style=\"margin-bottom:0.5rem;\"><span style=\"font-size:12px;color:var(--muted);\">RS485: 等待数据…</span></div>");
    page += F("<div style=\"max-height:300px;overflow-y:auto;padding:1rem;border-radius:12px;background:#f8fafc;border:1px solid var(--border);\">");
    page += F("<div id=\"logContainer\">正在加载日志...</div></div></section>");

    page += WebPageAssets::getFooter();
    return page;
}

void handleRoot() {
    webServer.sendHeader("Cache-Control", "no-cache, must-revalidate");
    webServer.sendHeader("X-Content-Type-Options", "nosniff");
    webServer.sendHeader("X-Frame-Options", "DENY");
    webServer.sendHeader("Connection", "close");
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
    // checkbox: present = checked, absent = unchecked
    newSettings.mqttEnabled = webServer.hasArg("mqttEnabled");
    if (webServer.hasArg("tcpServerPort")) newSettings.tcpServerPort = webServer.arg("tcpServerPort").toInt();
    if (webServer.hasArg("liftTimeoutSec")) newSettings.liftTimeoutSec = webServer.arg("liftTimeoutSec").toInt();

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
    char tsBuf[12];
    snprintf(tsBuf, sizeof(tsBuf), "%lu:%02lu:%02lu",
             seconds / 3600, (seconds % 3600) / 60, seconds % 60);
    entry.timestamp = tsBuf;
    entry.level = level;
    entry.message = message;
    webLogBuffer.push_back(entry);
    if (webLogBuffer.size() > MAX_LOG_ENTRIES) webLogBuffer.pop_front();
}

void handleApiStatus() {
    JsonDocument doc;
    JsonObject device = doc["device"].to<JsonObject>();
    device["computer"] = runtimeState.computerStatus;
    device["lifting"] = runtimeState.liftingState;
    device["lamp"] = runtimeState.lampStatus;
    device["lastUpdateMs"] = runtimeState.lastUpdateMs;
    device["liftTimeoutSec"] = settings.liftTimeoutSec;

    JsonObject wifi = doc["wifi"].to<JsonObject>();
    wifi["connected"] = (WiFi.status() == WL_CONNECTED);
    wifi["signalPct"] = currentSignalQuality();

    JsonObject mqtt = doc["mqtt"].to<JsonObject>();
    mqtt["connected"] = mqttClient.connected();
    mqtt["uptime"] = (mqttClient.connected() && mqttConnectedAt > 0) ? (millis() - mqttConnectedAt) : 0;

    JsonObject rs485 = doc["rs485"].to<JsonObject>();
    rs485["lastFrameHex"] = lastSerialFrameHex;
    rs485["lastFrameLen"] = lastSerialFrameLen;

    JsonArray logs = doc["logs"].to<JsonArray>();
    int logCount = 0;
    for (auto it = webLogBuffer.rbegin(); it != webLogBuffer.rend() && logCount < 5; ++it, ++logCount) {
        JsonObject logEntry = logs.add<JsonObject>();
        logEntry["timestamp"] = it->timestamp;
        logEntry["level"] = it->level;
        logEntry["message"] = it->message;
    }
    String payload;
    serializeJson(doc, payload);
    webServer.send(200, "application/json", payload);
}

void handleStyleCss() {
    webServer.sendHeader("Cache-Control", "public, max-age=86400, immutable");
    webServer.sendHeader("ETag", "\"v2-css\"");
    webServer.sendHeader("Connection", "close");
    webServer.send(200, "text/css", WebPageAssets::getCssContent());
}

void handleAppJs() {
    webServer.sendHeader("Cache-Control", "public, max-age=86400, immutable");
    webServer.sendHeader("ETag", "\"v2-js\"");
    webServer.sendHeader("Connection", "close");
    webServer.send(200, "application/javascript", WebPageAssets::getJsContent());
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
    doc["memoryUsage"] = ESP.getHeapFragmentation(); // 堆碎片率，比估算的总内存更准确
    doc["freeHeap"] = ESP.getFreeHeap();
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

// Non-blocking Serial Command Handler (with debug logging)
// 使用固定缓冲区替代 String 拼接，避免堆碎片
void handleSerialCommand() {
    static char serialBuffer[512] = {0};
    static size_t serialBufferLen = 0;
    static unsigned long lastSerialActivity = 0;

    while (Serial.available()) {
        char c = (char)Serial.read();
        lastSerialActivity = millis();
        
        if (c == '\n') {
            // trim trailing \r
            if (serialBufferLen > 0 && serialBuffer[serialBufferLen - 1] == '\r') {
                serialBufferLen--;
            }
            serialBuffer[serialBufferLen] = '\0';
            
            if (serialBufferLen > 0) {
                // Log received command with hex dump for diagnostics
                String hexDump;
                hexDump.reserve(serialBufferLen * 2 + 4);
                for (size_t i = 0; i < serialBufferLen; i++) {
                    if (hexDump.length() > 0) hexDump += ' ';
                    char hex[3];
                    snprintf(hex, sizeof(hex), "%02X", (unsigned char)serialBuffer[i]);
                    hexDump += hex;
                }
                lastSerialFrameHex = hexDump;
                lastSerialFrameLen = serialBufferLen;
                {
                    char logBuf[20];
                    snprintf(logBuf, sizeof(logBuf), "RX[%uB]", (unsigned)serialBufferLen);
                    addWebLog("RS485", String(logBuf) + ": " + hexDump);
                }
                {
                    // RX 原文日志 — 如果 serialBuffer 本身比 String("RX: ") + serialBuffer 小，直接合并
                    String rxMsg;
                    rxMsg.reserve(serialBufferLen + 5);
                    rxMsg = F("RX: ");
                    rxMsg += serialBuffer;
                    addWebLog("RS485", rxMsg);
                }
                
                // Process the command
                JsonDocument doc;
                DeserializationError error = deserializeJson(doc, serialBuffer);
                
                if (!error) {
                    if (doc["method"].is<String>()) {
                        String method = doc["method"];
                        JsonObject params = doc["params"];
                        String requestId = doc["requestId"] | "rs485_cmd";
                        
                        JsonDocument responseDoc;
                        responseDoc["deviceId"] = settings.deviceId;
                        responseDoc["requestId"] = requestId;
                        
                        protocolHandler.processRequest(requestId, method, params, responseDoc);
                        
                        // DO NOT write back to Serial — RS485 bus is receive-only here
                        bool success = responseDoc["success"] | false;
                        addWebLog("RS485", success ? "OK: " + method + " [" + requestId + "]" : "FAIL: " + method + " - " + (responseDoc["error"] | ""));
                    } else {
                        addWebLog("RS485", "ERR: Missing method field");
                    }
                } else {
                    addWebLog("RS485", String("ERR: Invalid JSON - ") + serialBuffer);
                }
            }
            serialBufferLen = 0;
            serialBuffer[0] = '\0';
        } else {
            if (serialBufferLen < sizeof(serialBuffer) - 1) {
                serialBuffer[serialBufferLen++] = c;
            }
        }
    }

    // Clear buffer if timeout (e.g. noise or incomplete transmission)
    if (serialBufferLen > 0 && (millis() - lastSerialActivity > 2000)) {
        addWebLog("RS485", String("TIMEOUT: Clearing partial buffer: ") + serialBuffer);
        serialBufferLen = 0;
        serialBuffer[0] = '\0';
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

// LED 状态说明（kStatusLedActiveLow=true，低电平亮）
// 长亮           = WiFi 已连接，正常运行
// 慢闪 800ms     = WiFi 已断开，等待重连
// 快闪 150ms     = WiFi 正在连接中（wifiMulti.run 执行期间）
// 极速闪 80ms    = 配置门户已激活
void updateStatusLedState(wl_status_t wifiStatus) {
    if (configPortalActive) {
        statusLedBlinkEnabled = true;
        statusLedBlinkIntervalMs = 80;
        return;
    }
    if (wifiStatus == WL_CONNECTED) {
        // 长亮：已连接
        statusLedBlinkEnabled = false;
        digitalWrite(kStatusLedPin, kStatusLedActiveLow ? LOW : HIGH);
    } else if (wifiStatus == WL_IDLE_STATUS) {
        // 快闪：正在连接中
        statusLedBlinkEnabled = true;
        statusLedBlinkIntervalMs = 150;
    } else {
        // 慢闪：已断开，等待重连
        statusLedBlinkEnabled = true;
        statusLedBlinkIntervalMs = 800;
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
    client.setTimeout(kControlConnectTimeoutMs);  // 缩短默认超时，避免阻塞循环
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
                {
                    char statBuf[96];
                    snprintf(statBuf, sizeof(statBuf), "%s sent=%u ok=%u fail=%u",
                             activeLegacyTask.tag.c_str(),
                             activeLegacyTask.sentCount,
                             activeLegacyTask.successCount,
                             activeLegacyTask.failedCount);
                    addWebLog("INFO", "下发任务完成: " + String(statBuf));
                }
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

    // 上升/下降启动自动停止定时器
    String valLower = value;
    valLower.toLowerCase();
    if (valLower == "up" || valLower == "down") {
        if (settings.liftTimeoutSec > 0) {
            runtimeState.liftAutoStopActive = true;
            runtimeState.liftAutoStopStartedAt = millis();
            runtimeState.liftAutoStopTimeoutSec = settings.liftTimeoutSec;
        }
    } else {
        runtimeState.liftAutoStopActive = false;
    }

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
