# TCP 透传协议对接指导

## 1. 概述

为了兼容不支持 MQTT 协议的第三方控制系统或旧版中控主机，SSLAB-HMI 提供了 **TCP 透传网关** 功能。
HMI 系统会在本地启动一系列 TCP 服务端端口，每个端口对应一种设备类型。外部系统可以通过连接相应的 TCP 端口，发送 JSON 指令来控制对应的设备。

HMI 系统作为网关，负责将 TCP 接收到的指令转换为 MQTT RPC 请求发送给终端设备，并将设备的响应透传回 TCP 客户端。

## 2. 端口分配表 (Port Mapping)

TCP 服务监听端口从 **9101** 开始分配，与设备类型一一对应。

| 端口号 | 设备类型 (DeviceType) | 说明 |
| :--- | :--- | :--- |
| **9101** | `STUDENT_POWER` | 学生电源 |
| **9102** | `TEACHER_POWER` | 教师电源 |
| **9103** | `LIFT_DEVICE` | 升降设备 |
| **9104** | `LIGHTING_DIMMER` | 调光灯具 |
| **9105** | `CURTAIN` | 窗帘 |
| **9106** | `AIR_CONDITIONER` | 空调 |
| **9107** | `ENVIRONMENT_MONITOR` | 环境监测 |
| **9108** | `DRAINAGE_CONTROLLER` | 排水控制 |
| **9109** | `ENERGY_MONITOR` | 能耗监测 |
| **9110** | `PROJECTOR` | 投影仪 |
| **9111** | `INTERACTIVE_TEACHING` | 互动学生终端 |
| **9112** | `INTERACTIVE_DISPLAY` | 互动显示设备 |
| **9113** | `INTERACTIVE_CONTROLLER` | 互动控制器 |
| **9114** | `BOT_SERVICE` | 机器人服务 |
| **9115** | `INTELLIGENT_BALANCE` | 智能天平 |
| **9116** | `HAZARDOUS_CABINET` | 危化品智能柜 |
| **9117** | `COMPUTER_CONTROL` | 电脑控制终端 |
| **9118** | `ACCESS_CONTROL` | 门禁控制 |
| **9119** | `ATTENDANCE_TERMINAL` | 考勤终端 |
| **9120** | `SMART_CONTROL_CENTER` | 智能控制中心 |
| **9121** | `LIGHTING_SWITCH` | 智能开关 |

## 3. 协议格式 (Protocol Format)

### 3.1 通信方式
*   **传输层**: TCP
*   **编码**: UTF-8
*   **数据包格式**: 行分隔 JSON (Line-delimited JSON)。每条指令必须以换行符 `\n` (0x0A) 结尾。

### 3.2 请求格式 (Client -> HMI)

发送给 HMI 的指令格式与 MQTT RPC 请求格式保持一致，但必须包含 `deviceId` 以便网关路由。

```json
{
  "deviceId": "设备ID",
  "method": "方法名",
  "params": {
    "参数名": "参数值"
  },
  "requestId": "请求ID (必需)"
}
```

*   **deviceId**: 目标设备的唯一标识符 (如 `LD-EE01`)。**必须提供**。
*   **method**: 调用的功能方法 (参考 [DEVICE_PROTOCOL.md](DEVICE_PROTOCOL.md))。**必须提供**。
*   **params**: 方法参数对象。**必须提供** (无参数时传空对象 `{}`)。
*   **requestId**: 客户端生成的唯一请求ID，用于匹配响应。**必须提供**。

### 3.3 响应格式 (HMI -> Client)

HMI 收到设备响应后，会将其转发给 TCP 客户端。响应格式严格遵循以下规范：

**成功响应**:
```json
{
  "deviceId": "设备ID",
  "requestId": "请求ID",
  "success": true,
  "result": {
    "执行结果": "..."
  }
}
```

**失败响应**:
```json
{
  "deviceId": "设备ID",
  "requestId": "请求ID",
  "success": false,
  "error": {
    "code": 400,
    "message": "错误描述"
  }
}
```

**字段说明**:
*   **deviceId**: (string, **必需**) 设备ID
*   **requestId**: (string, **必需**) 请求ID
*   **success**: (boolean, **必需**) 操作是否成功
*   **result**: (object, **条件必需**) 当 success=true 时必需
*   **error**: (object, **条件必需**) 当 success=false 时必需

## 4. 交互示例

### 示例 1: 控制调光灯具 (端口 9104)

**场景**: 打开 ID 为 `LD-EE01` 的调光灯具。

1.  **连接**: TCP Client 连接 HMI IP (例如 `192.168.0.110`) 的 **9104** 端口。
2.  **发送**:
    ```json
    {"deviceId": "LD-EE01", "method": "setLightStatus", "params": {"status": true}, "requestId": "tcp_001"}\n
    ```
3.  **接收**:
    ```json
    {"deviceId": "LD-EE01", "requestId": "tcp_001", "success": true, "result": {"message": "Light turned on"}}\n
    ```

### 示例 2: 控制智能开关 (端口 9121)

**场景**: 打开 ID 为 `SW-EE02` 的开关。

1.  **连接**: TCP Client 连接 HMI IP (例如 `192.168.0.110`) 的 **9121** 端口。
2.  **发送**:
    ```json
    {"deviceId": "SW-EE02", "method": "turnOn", "params": {}, "requestId": "tcp_002"}\n
    ```
3.  **接收**:
    ```json
    {"deviceId": "SW-EE02", "requestId": "tcp_002", "success": true, "result": {"message": "Switch turned on"}}\n
    ```

### 示例 3: 控制窗帘 (端口 9105)

**场景**: 将 ID 为 `CC-EE05` 的窗帘设置到 50% 位置。

1.  **连接**: TCP Client 连接 HMI IP 的 **9105** 端口。
2.  **发送**:
    ```json
    {"deviceId": "CC-EE05", "method": "setPosition", "params": {"position": 50}, "requestId": "tcp_003"}\n
    ```
3.  **接收**:
    ```json
    {"deviceId": "CC-EE05", "requestId": "tcp_003", "success": true, "result": {"currentPosition": 50}}\n
    ```

## 5. 注意事项

1.  **长连接**: 客户端**应**保持 TCP 长连接，避免频繁建立/断开连接。
2.  **并发处理**: HMI 网关支持多客户端同时连接，但对同一设备的控制**必须**串行化。
3.  **超时机制**: 如果设备在 5 秒内未响应，TCP 网关将返回超时错误。
4.  **错误处理**: 若 JSON 格式错误或 deviceId 不匹配当前端口类型，网关将返回错误信息。

```json
{
  "success": false,
  "error": {
    "code": 400,
    "message": "Invalid JSON format or Device Type mismatch"
  }
}
```
