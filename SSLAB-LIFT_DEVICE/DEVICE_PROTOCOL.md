# SSLAB HMI 设备通信协议规范

> **版本**: 3.2  
> **更新日期**: 2024年  
> **适用范围**: MQTT 协议下的所有设备类型  
> **协议标准**: ThingsBoard MQTT 协议

---

## ⚠️ 重要说明

本文档基于 **ThingsBoard MQTT 协议**，所有主题遵循 ThingsBoard 标准格式：

- **设备发现**: 通过 `v1/devices/me/attributes` 主题发布设备属性
- **遥测数据**: 通过 `v1/devices/me/telemetry` 主题发布
- **RPC 请求**: 平台发送到 `sslab/rpc/request/{deviceId}/{requestId}` 主题
- **RPC 响应**: 设备发送到 `v1/devices/me/rpc/response/{requestId}` 主题

**设备连接要求**:
- 使用 **Access Token** 作为 MQTT 用户名进行身份认证
- 订阅 `sslab/rpc/request/{自己的deviceId}/+` 主题以接收控制命令
- 所有主题中的 `me` 表示当前连接的设备（通过 Access Token 识别）

---

## 1. 概述

本文档规定了 SSLAB HMI 平台与各类教学实验设备的通信规范，包括设备发现、遥测上报、远程过程调用(RPC)等交互流程。

### 1.1 通信架构

**APP作为MQTT Broker服务端**，设备作为客户端连接：

```
设备固件 (MQTT客户端)
    ↓ 连接 (Access Token认证)
MQTT Broker (APP内置, ThingsBoard协议)
    ↓ 消息处理
HMI Platform (Android APP)
    ↓ UI更新
用户界面 (UI)
```

**关键点**：
- APP内置MQTT Broker（基于Moquette）
- 设备通过Access Token作为MQTT用户名连接
- **仅使用ThingsBoard协议**，主题格式：`v1/devices/me/*`
- 所有设备消息通过Broker转发给APP处理
- **TCP 透传支持**: 对于不支持 MQTT 的旧设备，平台提供 TCP 透传网关（详见 [TCP_PROTOCOL_GUIDE.md](TCP_PROTOCOL_GUIDE.md)）

### 1.2 MQTT 连接配置

**APP作为Broker服务端配置**：
- **Broker 地址**: APP所在设备的IP地址（局域网内）
- **Broker 端口**: 1883 (MQTT), 8083 (WebSocket), 8883 (SSL)
- **协议标准**: ThingsBoard MQTT 协议（基于标准 MQTT 3.1.1）
- **允许匿名连接**: 是（APP配置 `ALLOW_ANONYMOUS=true`）

**设备连接配置**：
- **连接方式**: 设备作为MQTT客户端连接到APP内置Broker
- **用户名 (Access Token)**: **必须提供**。设备连接时必须使用 Access Token 作为 MQTT 用户名。
- **客户端 ID**: **必须保证全局唯一**。推荐格式：`{deviceType}_{deviceId}`
  - **注意**：APP配置 `ALLOW_ZERO_BYTE_CLIENT_ID=false`，客户端ID不能为空
- **Keep-Alive**: 推荐值 60 秒
- **Clean Session**: 推荐值 true

### 1.3 关键概念

- **设备发现 (Discovery)**: 设备启动时发布自身信息到 MQTT
- **心跳检测 (Heartbeat)**: 通过遥测数据自动更新，无需单独发送心跳消息
- **遥测数据 (Telemetry)**: 设备定期上报状态和数值
- **远程过程调用 (RPC)**: HMI 向设备发送控制命令
- **Capabilities**: 设备支持的所有 RPC 方法列表（**关键字段**）

### 1.4 MQTT 主题架构

平台使用 **ThingsBoard MQTT 协议**，所有主题遵循 ThingsBoard 标准格式：

| 主题 | 方向 | 用途 | QoS | Retain |
|------|------|------|-----|--------|
| `v1/devices/me/attributes` | 设备→平台 | 设备属性/发现信息 | 1 | false |
| `v1/devices/me/telemetry` | 设备→平台 | 遥测数据上报 | 1 | false |
| `sslab/rpc/request/{deviceId}/{requestId}` | 平台→设备 | 定向 RPC 控制请求 | 1 | false |
| `v1/devices/me/rpc/response/{requestId}` | 设备→平台 | RPC 控制响应 | 1 | false |
| `v1/devices/me/attributes/request/{requestId}` | 设备→平台 | 请求共享属性 | 1 | false |
| `v1/devices/me/attributes/response/{requestId}` | 平台→设备 | 共享属性响应 | 1 | false |

**重要说明**: 
- 设备**必须订阅** `sslab/rpc/request/{自己的deviceId}/+` 主题以接收定向控制命令。
- 设备通过发布到 `v1/devices/me/attributes` 主题进行设备发现和注册
- 设备通过发布到 `v1/devices/me/telemetry` 主题上报遥测数据
- 所有主题中的 `me` 表示当前连接的设备（通过 Access Token 识别）

---

## 2. 设备发现协议 (Device Discovery)

### 2.1 发布规范

每个设备**必须**在以下时刻发布设备属性到 MQTT 主题 `v1/devices/me/attributes`:

- 设备启动并连接 MQTT Broker 后立即发布
- 每隔 60 秒定期发布一次（保持设备信息同步）
- 设备信息发生变化时发布（如固件升级、配置变更等）

**发布 QoS**: 1 (至少一次)  
**保留标志 (Retain)**: `false` (不保留消息)  
**主题**: `v1/devices/me/attributes`

**重要**：
- 设备**必须**在 attributes 消息中显式包含 `deviceId` 字段。
- `deviceId` 必须与 Access Token 绑定的设备一致。
- 严禁依赖隐式推断或临时 ID。

### 2.2 发现消息格式

设备通过发布 JSON 对象到 `v1/devices/me/attributes` 主题进行注册。消息格式**必须**严格遵循 camelCase 命名规范：

**标准格式（必须使用 camelCase）**:

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "capabilities": ["setLightStatus", "turnOn", "turnOff", "setBrightness", "setColorTemperature"],
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1",
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "LED Panel 2024",
    "firmwareVersion": "1.2.3",
    "hardwareVersion": "1.0",
    "serialNumber": "DIMMER-LD-EE01"
  },
  "network": {
    "ipAddress": "192.168.0.110",
    "macAddress": "AA:BB:CC:DD:EE:01",
    "signalStrength": 85
  },
  "transportMode": "thingsboard",
  "scenes": [
    {
      "sceneId": "reading",
      "name": "阅读模式",
      "brightness": 80,
      "colorTemperature": 4000
    }
  ]
}
```

**字段命名规范**：
- 必须严格使用 **camelCase** (小驼峰) 命名法。
- 不支持 snake_case 或其他别名。

**设备ID规则**：
- `deviceId` 字段必须与设备 MAC 地址后四位对应（格式：`{Prefix}-{MAC_Last_Four_Digits}`）
- `deviceId` 必须显式提供，且必须与 Access Token 绑定的设备一致。

**默认值处理**：
- **无默认值**。所有字段必须由设备显式提供。

### 2.3 字段说明

**核心字段**（**必需**）：

| 字段名 | 类型 | 要求 | 说明 |
|-------|------|------|------|
| `deviceId` | string | **必需** | 全局唯一设备标识符，格式：`{Prefix}-{MAC_Last_Four_Digits}` (e.g., "LD-EE01")。必须显式提供，严禁依赖 Access Token 推断。 |
| `deviceType` | string | **必需** | 设备类型，必须匹配 `DeviceType` 枚举值 (e.g., "LIGHTING_SWITCH", "STUDENT_POWER")。**必须显式声明，不支持推断**。 |
| `capabilities` | array | **必需** | 支持的 RPC 方法列表 (见 2.5 节)。必须显式列出所有支持的方法，若无控制功能请传空数组 `[]`。 |

**设备信息字段**（**必需**）：

| 字段名 | 类型 | 要求 | 说明 |
|-------|------|------|------|
| `deviceInfo` | object | **必需** | 设备信息对象，必须包含制造商、型号、固件版本等 |
| `deviceInfo.manufacturer` | string | **必需** | 制造商名称 |
| `deviceInfo.model` | string | **必需** | 设备型号 |
| `deviceInfo.firmwareVersion` | string | **必需** | 固件版本号 (semver 格式) |
| `deviceInfo.hardwareVersion` | string | **必需** | 硬件版本号 |
| `deviceInfo.serialNumber` | string | **必需** | 设备序列号 |

**位置和网络信息**（**必需**）：

| 字段名 | 类型 | 要求 | 说明 |
|-------|------|------|------|
| `classroomZone` | string | **必需** | 教室区域，必须匹配 `ClassroomZone` 枚举值。 |
| `studentGroup` | string | **特定设备必需** | 学生分组，仅 `STUDENT_POWER`, `LIFT_DEVICE` 等设备必需。 |
| `network` | object | **必需** | 网络连接信息 |
| `network.ipAddress` | string | **必需** | 设备 IP 地址 |
| `network.macAddress` | string | **必需** | MAC 地址 |
| `network.signalStrength` | number | **必需** | WiFi 信号强度 |

### 2.4 条件必需字段说明

| 字段名 | 类型 | 要求 | 说明 |
|-------|------|------|------|
| `studentGroup` | string | **条件必需** | 学生分组 (e.g., "GROUP_1")，`STUDENT_POWER`, `LIFT_DEVICE` 等设备**必需** |
| `transportMode` | string | **系统字段** | 传输模式，APP会设置为 "thingsboard"（设备无需提供此字段） |
| `scenes` | array | **条件必需** | 照明场景定义，仅 `LIGHTING_DIMMER` 设备**必需**。若无场景，必须返回空数组 `[]`。 |

### 2.5 设备类型声明机制

**严禁使用类型推断**。设备必须在 `v1/devices/me/attributes` 消息中显式包含 `deviceType` 字段。

如果 `deviceType` 字段缺失、为空或无效，HMI 平台将**拒绝注册该设备**。

**注意**：
- 必须严格按照 `DeviceType` 枚举值填写。
- `capabilities` 字段仅用于 UI 渲染控制按钮，**不用于** 推断设备类型。

### 2.6 Capabilities 字段 - 设备类型详解

HMI 平台根据 `capabilities` 数组的内容**决定是否渲染控制按钮**。

**关键规则**: 如果 `capabilities` 为空数组 `[]`，设备被视为**只读**（只显示状态，无控制选项）。

#### 智能开关 (LIGHTING_SWITCH)

```json
"capabilities": ["setLightStatus", "turnOn", "turnOff"]
```

#### 调光灯具 (LIGHTING_DIMMER)

```json
"capabilities": ["setLightStatus", "setBrightness", "setColorTemperature", "turnOn", "turnOff"]
```

#### 升降设备 (LIFT_DEVICE)

```json
"capabilities": ["controlComputer", "controlLamp", "setGroup"]
```

**说明**: 
- `controlComputer(status: boolean)` - 控制电脑电源
- `controlLamp(status: boolean)` - 控制台灯（开关）
- `setGroup(studentGroup: StudentGroup)` - 设置学生分组

#### 教学电源 (TEACHER_POWER)

```json
"capabilities": ["turnOn", "turnOff", "setVoltage", "setCurrent", "setDemoMode", "setLock"]
```

#### 学生电源 (STUDENT_POWER)

```json
"capabilities": ["setPower", "setVoltageLimit", "setCurrentLimit", "resetProtection", "controlSocket"]
```

#### 环境监测 (ENVIRONMENT_MONITOR)

```json
"capabilities": ["calibrate", "setDisplay", "setAlarmThreshold"]
```

#### 排水控制 (DRAINAGE_CONTROLLER)

```json
"capabilities": ["setDrainage", "setWaterSupply", "setVentilation", "setFanSpeed"]
```

#### 能源监测 (ENERGY_MONITOR)

```json
"capabilities": ["resetEnergy", "setUploadInterval"]
```

#### 窗帘控制 (CURTAIN)

```json
"capabilities": ["setPosition", "stop", "setMode"]
```

#### 投影仪 (PROJECTOR)

```json
"capabilities": ["setPower", "setInput", "setBrightness", "setVolume"]
```

#### 交互学生端 (INTERACTIVE_TEACHING)

```json
"capabilities": ["setDisplayContent", "setInteractionState"]
```

**说明**:
- `setDisplayContent(content: string)` - 设置显示内容
- `setInteractionState(active: boolean)` - 设置交互状态

#### 交互显示屏 (INTERACTIVE_DISPLAY)

```json
"capabilities": ["setDisplayMode", "setBrightness", "setTouchEnabled", "setVolume"]
```

#### 交互控制器 (INTERACTIVE_CONTROLLER)

```json
"capabilities": ["startSession", "stopSession", "setMode", "broadcastMessage"]
```

#### 空调设备 (AIR_CONDITIONER)

```json
"capabilities": ["controlAircon", "setSchedule", "setTemperature", "setFanSpeed", "setMode"]
```

#### 机器人服务 (BOT_SERVICE)

```json
"capabilities": ["dispatchTask", "cancelTask", "returnToBase", "setSpeedLimit"]
```

#### 智能天平 (INTELLIGENT_BALANCE)

```json
"capabilities": ["tare", "calibrate", "setUnit"]
```

#### 危险品柜 (HAZARDOUS_CABINET)

```json
"capabilities": ["unlock", "setVentilation", "setAlarmThreshold"]
```

#### 计算机控制 (COMPUTER_CONTROL)

```json
"capabilities": ["shutdown", "restart", "lockScreen", "sendMessage", "wakeOnLan"]
```

#### 门禁系统 (ACCESS_CONTROL)

```json
"capabilities": ["openDoor", "setLockMode", "syncUser"]
```

#### 考勤系统 (ATTENDANCE_TERMINAL)

```json
"capabilities": ["setMode", "displayMessage", "updateUserDb"]
```

#### 智能控制中心 (SMART_CONTROL_CENTER)

```json
"capabilities": ["setSystemMode", "activateScene", "broadcast", "emergencyStop"]
```

### 2.7 HMI 平台验证规则

HMI 接收设备发现消息后执行以下验证:

1. 检查必需字段 (deviceId, deviceType, capabilities)
2. 验证 deviceId 格式 (必须匹配 `^[A-Z]{2}-[0-9A-F]{4}$`)
3. 映射 deviceType 到内部模型
4. 解析 capabilities 数组
5. 决定 UI 控制渲染
   - 如果 capabilities 非空 → 显示所有控制按钮
   - 如果 capabilities 为空 → 只读模式（仅显示状态）

**关键验证错误处理**:

- `deviceId` 缺失或为空 → **拒绝注册**
- `capabilities` 缺失 → **拒绝注册**
- `capabilities` 为空数组 `[]` → 接受注册，标记为只读设备
- `deviceType` 无法识别 → **拒绝注册**

### 2.8 常见错误示例与修正

### ❌ 错误示例 1: 缺少 capabilities 字段

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "firmwareVersion": "1.0.0"
}
```

**问题**: 缺少必需字段 `capabilities`，HMI 拒绝注册

**修正**: 添加 `capabilities` 数组

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "firmwareVersion": "1.0.0",
  "capabilities": ["setLightStatus", "turnOn", "turnOff"]
}
```

### ❌ 错误示例 2: Capabilities 为空数组

```json
{
  "deviceId": "TP-EE03",
  "deviceType": "TEACHER_POWER",
  "capabilities": []
}
```

**问题**: HMI 记录警告 "Teaching zone RPC skip (no RPC capability): TP-001"

**修正**: 列举所有支持的 RPC 方法

```json
{
  "deviceId": "TP-EE03",
  "deviceType": "TEACHER_POWER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Teacher Power Supply",
    "firmwareVersion": "1.0.0",
    "hardwareVersion": "1.0",
    "serialNumber": "TEACHER_POWER-TP-001"
  },
  "capabilities": ["setPowerMode", "controlTerminal"]
}
```

### ❌ 错误示例 3: 缺少 timestamp 字段

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "classroomZone": "ZONE_A"
}
```

**问题**: HMI 无法确定消息时间，可能导致设备状态判断错误

**修正**: 添加 timestamp 字段

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "LED Panel",
    "firmwareVersion": "1.2.3",
    "hardwareVersion": "1.0",
    "serialNumber": "DIMMER-LD-6844"
  },
  "capabilities": ["setLightStatus", "turnOn", "turnOff"]
}
```

### ❌ 错误示例 4: firmwareVersion 位置错误

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067200000,
  "firmwareVersion": "1.2.3",
  "classroomZone": "ZONE_A"
}
```

**问题**: firmwareVersion 应在 deviceInfo 对象内，而不是顶层

**修正**: 将 firmwareVersion 移到 deviceInfo 内

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "LED Panel",
    "firmwareVersion": "1.2.3",
    "hardwareVersion": "1.0",
    "serialNumber": "DIMMER-LD-6844"
  },
  "capabilities": ["setLightStatus", "turnOn", "turnOff"]
}
```

---

## 3. 心跳检测协议 (Heartbeat)

### 3.1 心跳检测机制

**APP通过遥测数据自动检测设备在线状态**。每次设备发布遥测数据到 `v1/devices/me/telemetry` 主题时，APP会自动更新设备的心跳时间戳。

**心跳检测规则**:
- 设备通过定期发布遥测数据来维持在线状态（**无需单独的心跳主题**）
- APP在收到遥测数据时自动更新 `lastHeartbeat` 时间戳并调用 `notifyHeartbeat()`
- 如果超过 **60 秒**未收到任何遥测数据，设备将被标记为离线
- 设备**必须**每 **30-60 秒**发布一次遥测数据以维持在线状态（即使状态未变化，也必须发送空对象 `{}` 或状态数据）

**实现细节**：
- APP在 `onTelemetry()` 方法中自动更新心跳
- 心跳超时检查由 `MqttDiscoveryManager` 的离线扫描器执行（每5秒检查一次）

### 3.2 心跳数据格式（通过遥测数据携带）

设备可以在遥测数据中包含心跳相关信息，用于设备健康监控：

```json
{
  "status": "ONLINE",
  "uptime": 3600,
  "memoryUsage": 45.2,
  "cpuUsage": 12.5,
  "signalQuality": 85,
  "ipAddress": "192.168.0.110",
  "classroomZone": "ZONE_A"
}
```

### 3.3 字段说明

| 字段名 | 类型 | 要求 | 说明 |
|-------|------|------|------|
| `status` | string | **必需** | 设备状态 (ONLINE, OFFLINE, ERROR 等) |
| `uptime` | number | **必需** | 设备运行时间（秒） |
| `memoryUsage` | number | **必需** | 内存使用率 (%)，若不支持请返回 0 |
| `cpuUsage` | number | **必需** | CPU 使用率 (%)，若不支持请返回 0 |
| `signalQuality` | number | **必需** | 信号质量 (0-100)，若原始为 RSSI (dBm) 会自动换算 |
| `ipAddress` | string | **必需** | 设备 IP 地址（用于实时更新） |
| `classroomZone` | string | **必需** | 教室区域（用于实时更新） |

**注意**: 
- 心跳检测**不需要**单独的主题，通过遥测数据自动完成
- 即使遥测数据为空对象 `{}`，只要定期发布，平台也会更新心跳时间戳
- 如果设备长时间无状态变化，**必须**定期发送最小遥测数据（如 `{"status": "ONLINE"}`）以维持在线状态

---

## 4. 遥测数据规范 (Telemetry)

### 4.1 遥测数据通用要求

- **主题**: `v1/devices/me/telemetry`
- **发布频率**: 标准频率 5-30 秒，或状态变化时立即发布
- **发布 QoS**: 1 (至少一次)
- **保留标志 (Retain)**: `false`
- **消息格式**: JSON 对象或 JSON 数组（支持批量上报）

**单条遥测数据格式**（推荐）:

```json
{
  "isOn": true,
  "brightness": 80,
  "colorTemperature": 4000,
  "deviceStatus": "ONLINE"
}
```

**批量遥测数据格式**（ThingsBoard 标准，支持两种格式）:

**格式1：带时间戳和values对象**
```json
[
  {
    "ts": 1704067200000,
    "values": {
      "isOn": true,
      "brightness": 80
    }
  },
  {
    "ts": 1704067201000,
    "values": {
      "colorTemperature": 4000
    }
  }
]
```

**格式2：直接对象数组**
```json
[
  {
    "isOn": true,
    "brightness": 80
  },
  {
    "colorTemperature": 4000
  }
]
```

**APP处理逻辑**：
- APP会自动为每条遥测数据添加 `deviceId` 和 `timestamp` 字段
- 如果使用批量格式且包含 `ts` 字段，使用该时间戳；否则使用服务器当前时间
- 如果批量格式中元素包含 `values` 对象，从 `values` 中提取数据；否则直接使用元素对象
- 如果元素包含 `status` 字段，会映射为 `deviceStatus`
- **遥测数据发布时会自动更新设备心跳时间戳**

**实时属性更新**：
- 遥测数据中的 `ipAddress`、`classroomZone`、`signalQuality` 字段会自动更新到设备发现信息中
- 这些字段必须使用 camelCase 命名

### 4.2 智能开关 (LIGHTING_SWITCH) & 调光灯具 (LIGHTING_DIMMER)

**通用字段**:
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `isOn` | boolean | 开关状态 |
| `deviceStatus` | string | ONLINE, OFFLINE, ERROR |

**调光灯具 (LIGHTING_DIMMER) 专用字段**:
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `brightness` | number | 亮度 (0-100) |
| `colorTemperature` | number | 色温 (K) |
| `currentScene` | string | 当前场景ID |

### 4.3 升降设备 (LIFT_DEVICE)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `lampStatus` | boolean | 附属照明状态 |
| `computerStatus` | boolean | 电脑电源状态 |
| `deviceStatus` | string | IDLE, RUNNING, FAULT |

### 4.4 教学电源 (TEACHER_POWER)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `voltage` | number | 输出电压 (V) |
| `current` | number | 输出电流 (A) |
| `power` | number | 实时功率 (W) |
| `enabled` | boolean | 总电源开关 |
| `demoMode` | boolean | 演示模式状态 |
| `locked` | boolean | 面板锁定状态 |
| `deviceStatus` | string | NORMAL, OVERLOAD, ERROR |

### 4.5 学生电源 (STUDENT_POWER)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `powerMode` | string | DC 或 AC |
| `voltageSetting` | number | 设定电压 |
| `currentSetting` | number | 设定电流 |
| `socket1Status` | boolean | 插座1状态 |
| `socket2Status` | boolean | 插座2状态 |
| `socket3Status` | boolean | 插座3状态 |
| `socket4Status` | boolean | 插座4状态 |
| `isProtected` | boolean | 是否处于保护状态 |
| `deviceStatus` | string | NORMAL, OVERLOAD, ERROR |

### 4.6 环境监测 (ENVIRONMENT_MONITOR)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `temperature` | number | 温度 (°C) |
| `humidity` | number | 湿度 (%) |
| `co2` | number | CO2 浓度 (ppm) |
| `pm25` | number | PM2.5 浓度 (µg/m³) |
| `voc` | number | VOC 浓度 (ppb) |
| `illuminance` | number | 光照度 (lux) |
| `noise` | number | 噪音 (dB) |
| `deviceStatus` | string | NORMAL, WARNING, ERROR |

### 4.7 排水控制 (DRAINAGE_CONTROLLER)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `waterLevel` | number | 水位 (0-100) |
| `valveStatus` | boolean | 排水阀状态 |
| `pumpStatus` | boolean | 水泵状态 |
| `fanStatus` | boolean | 风扇状态 |
| `flowRate` | number | 流量 (L/min) |
| `deviceStatus` | string | NORMAL, WARNING, ERROR |

### 4.8 能源监测 (ENERGY_MONITOR)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `voltage` | number | 电压 (V) |
| `current` | number | 电流 (A) |
| `power` | number | 功率 (W) |
| `energy` | number | 累计能耗 (kWh) |
| `frequency` | number | 频率 (Hz) |
| `powerFactor` | number | 功率因数 |
| `deviceStatus` | string | NORMAL, ERROR |

### 4.9 窗帘控制 (CURTAIN)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `position` | number | 开合百分比 (0-100) |
| `isMoving` | boolean | 是否正在运动 |
| `mode` | string | MANUAL, AUTO |
| `deviceStatus` | string | IDLE, RUNNING, ERROR |

### 4.10 投影仪 (PROJECTOR)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `isOn` | boolean | 开关状态 |
| `source` | string | HDMI1, HDMI2, VGA |
| `lampHours` | number | 灯泡使用时长 (h) |
| `errorStatus` | string | 错误代码 |
| `deviceStatus` | string | STANDBY, ON, COOLING, ERROR |

### 4.11 交互学生端 (INTERACTIVE_TEACHING)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `screenState` | boolean | 屏幕开关 |
| `currentApp` | string | 当前运行应用 |
| `batteryLevel` | number | 电量 (0-100) |
| `isCharging` | boolean | 是否充电中 |
| `deviceStatus` | string | ONLINE, OFFLINE, LOCKED |

### 4.12 交互显示屏 (INTERACTIVE_DISPLAY)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `isOn` | boolean | 开关状态 |
| `brightness` | number | 亮度 (0-100) |
| `volume` | number | 音量 (0-100) |
| `source` | string | ANDROID, PC, HDMI |
| `touchEnabled` | boolean | 触摸功能是否启用 |
| `deviceStatus` | string | ONLINE, OFFLINE |

### 4.13 交互控制器 (INTERACTIVE_CONTROLLER)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `sessionActive` | boolean | 会话是否激活 |
| `connectedClients` | number | 连接客户端数量 |
| `currentMode` | string | BROADCAST, GROUP, INDIVIDUAL |
| `deviceStatus` | string | IDLE, ACTIVE, ERROR |

### 4.14 空调设备 (AIR_CONDITIONER)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `isOn` | boolean | 开关状态 |
| `mode` | string | COOL, HEAT, FAN, DRY |
| `temperature` | number | 设定温度 |
| `currentTemp` | number | 当前室温 |
| `fanSpeed` | string | LOW, MID, HIGH, AUTO |
| `swing` | boolean | 扫风状态 |
| `deviceStatus` | string | OFF, RUNNING, ERROR |

### 4.15 机器人服务 (BOT_SERVICE)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `batteryLevel` | number | 电量 (0-100) |
| `location` | string | 当前位置坐标或名称 |
| `taskStatus` | string | IDLE, MOVING, WORKING, CHARGING |
| `currentSpeed` | number | 当前速度 (m/s) |
| `deviceStatus` | string | ONLINE, OFFLINE, ERROR |

### 4.16 智能天平 (INTELLIGENT_BALANCE)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `weight` | number | 重量读数 |
| `unit` | string | g, kg, oz, lb |
| `isStable` | boolean | 读数是否稳定 |
| `isTare` | boolean | 是否已去皮 |
| `deviceStatus` | string | NORMAL, OVERLOAD, ERROR |

### 4.17 危险品柜 (HAZARDOUS_CABINET)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `doorStatus` | boolean | 柜门状态 (true=open) |
| `lockStatus` | boolean | 锁状态 (true=locked) |
| `temperature` | number | 柜内温度 |
| `humidity` | number | 柜内湿度 |
| `vocLevel` | number | VOC 浓度 |
| `deviceStatus` | string | NORMAL, ALARM, ERROR |

### 4.18 计算机控制 (COMPUTER_CONTROL)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `isOn` | boolean | 开机状态 |
| `cpuUsage` | number | CPU 使用率 (%) |
| `memoryUsage` | number | 内存使用率 (%) |
| `diskUsage` | number | 磁盘使用率 (%) |
| `currentApp` | string | 前台应用 |
| `deviceStatus` | string | ONLINE, OFFLINE, SLEEP |

### 4.19 门禁系统 (ACCESS_CONTROL)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `doorStatus` | boolean | 门状态 (true=open) |
| `lockStatus` | boolean | 锁状态 (true=locked) |
| `lastAccessUser` | string | 最后通行用户 |
| `lastAccessTime` | number | 最后通行时间戳 |
| `deviceStatus` | string | NORMAL, ALARM, ERROR |

### 4.20 考勤系统 (ATTENDANCE_TERMINAL)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `deviceStatus` | string | ONLINE, OFFLINE |
| `lastCheckInUser` | string | 最后打卡用户 |
| `lastCheckInTime` | number | 最后打卡时间戳 |
| `totalCount` | number | 今日总人数 |

### 4.21 智能控制中心 (SMART_CONTROL_CENTER)
| 字段名 | 类型 | 说明 |
|-------|------|------|
| `systemMode` | string | TEACHING, EXAM, SELF_STUDY |
| `activeScene` | string | 当前场景名称 |
| `cpuTemp` | number | CPU 温度 |
| `uptime` | number | 运行时间 (s) |
| `deviceStatus` | string | NORMAL, WARNING, ERROR |

---

## 5. RPC 命令规范 (Remote Procedure Call)

### 5.1 RPC 请求格式

**APP向特定设备发送RPC命令**到主题 `sslab/rpc/request/{deviceId}/{requestId}`：

- **主题**: `sslab/rpc/request/{deviceId}/{requestId}`
- **机制**: 只有订阅了该特定主题的设备才会收到消息，避免无关设备被唤醒处理。
- **设备端要求**: 设备**必须订阅** `sslab/rpc/request/{自己的deviceId}/+`。

#### 5.1.1 请求 Payload 格式

```json
{
  "deviceId": "LD-EE01",
  "method": "setLightStatus",
  "params": {
    "status": true
  }
}
```

**字段说明**:
- `deviceId` (string, 必需): 目标设备ID，设备应验证此字段是否匹配自身ID（用于多设备共享同一 Access Token 的场景）
- `method` (string, 必需): RPC 方法名称，必须与设备 capabilities 中声明的名称一致
- `params` (object, 必需): 方法参数，具体格式见各设备类型的 RPC 方法定义

**APP实现细节**：
- APP使用 `UUID.randomUUID().toString()` 生成唯一的 `requestId`
- APP向定向主题发布消息。
- 发布 QoS: 1 (至少一次)
- 保留标志 (Retain): `false`

**设备端适配指南**: 
1. **订阅主题**: 必须订阅 `sslab/rpc/request/{自己的deviceId}/+`。
2. **响应一致性**: 响应应发送到 `v1/devices/me/rpc/response/{requestId}`。

### 5.2 RPC 响应格式

**设备在主题 `v1/devices/me/rpc/response/{requestId}` 发送响应**（`{requestId}` 必须与请求主题中的 requestId 一致）:

**APP处理逻辑**：
- APP从主题路径中提取 `requestId`（`topic.substringAfterLast('/')`）
- APP将响应payload解析为Map，然后调用 `notifyRpcResponse(deviceId, requestId, responseMap)`
- 响应格式可以是任意JSON对象，APP会原样传递给监听器

**成功响应**:
```json
{
  "deviceId": "LD-EE01",
  "requestId": "req_12345",
  "timestamp": 1704067205000,
  "success": true,
  "result": {
    "message": "Operation successful"
  }
}
```

**失败响应**:
```json
{
  "deviceId": "LD-EE01",
  "requestId": "req_12345",
  "timestamp": 1704067205000,
  "success": false,
  "error": {
    "code": 400,
    "message": "Invalid parameter",
    "details": "Brightness value must be between 0 and 100"
  }
}
```

**响应格式说明**:
- APP会将响应payload解析为Map并传递给监听器
- 响应必须包含以下字段：
  - `deviceId` (string, **必需**): 设备ID
  - `requestId` (string, **必需**): 对应的请求ID（从主题路径中提取）
  - `success` (boolean, **必需**): 操作是否成功
  - `result` (object, **条件必需**): 当 `success` 为 `true` 时必需，包含结果数据
  - `error` (object, **条件必需**): 当 `success` 为 `false` 时必需，包含错误信息
    - `code` (number, **必需**): 错误代码
    - `message` (string, **必需**): 错误消息
    - `details` (string, **必需**): 详细错误信息（无详细信息时传空字符串 ""）

**发布 QoS**: 1 (至少一次)  
**保留标志 (Retain)**: `false`  
**主题格式**: `v1/devices/me/rpc/response/{requestId}`（`{requestId}` 必须与请求主题中的 requestId 完全一致）

**响应示例**（完整流程）:

1. **平台发送请求**到 `sslab/rpc/request/LD-EE01/abc123`:
```json
{
  "deviceId": "LD-EE01",
  "method": "setLightStatus",
  "params": {
    "status": true
  }
}
```

2. **设备响应**到 `v1/devices/me/rpc/response/abc123`:
```json
{
  "deviceId": "LD-EE01",
  "requestId": "abc123",
  "success": true,
  "result": {
    "message": "Light turned on successfully"
  }
}
```

### 5.3 常用 RPC 方法参数定义

#### 智能开关 (LIGHTING_SWITCH)

**setLightStatus**
```json
{
  "method": "setLightStatus",
  "params": {
    "status": true
  }
}
```

**turnOn / turnOff**
```json
{
  "method": "turnOn",
  "params": {}
}
```

#### 调光灯具 (LIGHTING_DIMMER)

**setLightStatus**
```json
{
  "method": "setLightStatus",
  "params": {
    "status": true
  }
}
```

**setBrightness**
```json
{
  "method": "setBrightness",
  "params": {
    "brightness": 80
  }
}
```
- `brightness`: 0-100 的整数

**setColorTemperature**
```json
{
  "method": "setColorTemperature",
  "params": {
    "temperature": 4000
  }
}
```
- `temperature`: 色温值 (K)，通常 2700-6500

#### LIFT_DEVICE (升降设备)

**controlComputer**
```json
{
  "method": "controlComputer",
  "params": {
    "status": true
  }
}
```

**controlLamp**
```json
{
  "method": "controlLamp",
  "params": {
    "status": true
  }
}
```

**setGroup**
```json
{
  "method": "setGroup",
  "params": {
    "studentGroup": "GROUP_1"
  }
}
```

#### TEACHER_POWER (教学电源)

**setPowerMode**
```json
{
  "method": "setPowerMode",
  "params": {
    "powerMode": "DC",
    "voltageSetting": 12.0,
    "currentSetting": 2.0
  }
}
```
- `powerMode`: "DC" 或 "AC"
- `voltageSetting`: 设定电压值
- `currentSetting`: 设定电流值

**controlTerminal**
```json
{
  "method": "controlTerminal",
  "params": {
    "terminalNumber": 1,
    "enabled": true
  }
}
```

#### STUDENT_POWER (学生电源)

**setPowerMode**
```json
{
  "method": "setPowerMode",
  "params": {
    "powerMode": "DC",
    "voltageSetting": 12.0,
    "currentSetting": 2.0
  }
}
```

**controlSocket**
```json
{
  "method": "controlSocket",
  "params": {
    "socketNumber": 1,
    "status": true
  }
}
```
- `socketNumber`: 1-4 的整数

**setGroupMode**
```json
{
  "method": "setGroupMode",
  "params": {
    "studentGroup": "GROUP_1"
  }
}
```

**emergencyStop**
```json
{
  "method": "emergencyStop",
  "params": {
    "reason": "Overload protection"
  }
}
```

#### AIR_CONDITIONER (空调设备)

**controlAircon**
```json
{
  "method": "controlAircon",
  "params": {
    "powerStatus": true,
    "mode": "COOL",
    "targetTemperature": 26.0,
    "fanSpeed": "AUTO"
  }
}
```
- `mode`: "COOL", "HEAT", "FAN", "DRY"
- `fanSpeed`: "LOW", "MID", "HIGH", "AUTO"

**setSchedule**
```json
{
  "method": "setSchedule",
  "params": {
    "scheduleEnabled": true,
    "onTime": "08:00",
    "offTime": "18:00"
  }
}
```

#### CURTAIN (窗帘控制)

**setPosition**
```json
{
  "method": "setPosition",
  "params": {
    "position": 50
  }
}
```
- `position`: 0-100 的整数（0=全开，100=全合）

**setMode**
```json
{
  "method": "setMode",
  "params": {
    "mode": "AUTO"
  }
}
```

**stop**
```json
{
  "method": "stop",
  "params": {}
}
```

#### ENVIRONMENT_MONITOR (环境监测)

**calibrate**
```json
{
  "method": "calibrate",
  "params": {
    "sensor": "temperature",
    "value": 25.0
  }
}
```

**setDisplay**
```json
{
  "method": "setDisplay",
  "params": {
    "on": true
  }
}
```

#### DRAINAGE_CONTROLLER (排水控制)

**setDrainage**
```json
{
  "method": "setDrainage",
  "params": {
    "enabled": true
  }
}
```

**setWaterSupply**
```json
{
  "method": "setWaterSupply",
  "params": {
    "enabled": true
  }
}
```

**setVentilation**
```json
{
  "method": "setVentilation",
  "params": {
    "enabled": true
  }
}
```

**setFanSpeed**
```json
{
  "method": "setFanSpeed",
  "params": {
    "speed": 80
  }
}
```
- `speed`: 0-100 的整数

#### ENERGY_MONITOR (能源监测)

**resetEnergy**
```json
{
  "method": "resetEnergy",
  "params": {}
}
```

**setUploadInterval**
```json
{
  "method": "setUploadInterval",
  "params": {
    "interval": 5
  }
}
```
- `interval`: 上传间隔（秒）

#### PROJECTOR (投影仪)

**setPower**
```json
{
  "method": "setPower",
  "params": {
    "enabled": true
  }
}
```

**setInput**
```json
{
  "method": "setInput",
  "params": {
    "input": "HDMI1"
  }
}
```

**setBrightness**
```json
{
  "method": "setBrightness",
  "params": {
    "brightness": 80
  }
}
```

#### INTERACTIVE_TEACHING (交互学生端)

**setDisplayContent**
```json
{
  "method": "setDisplayContent",
  "params": {
    "content": "Question 1: What is 2+2?"
  }
}
```

**setInteractionState**
```json
{
  "method": "setInteractionState",
  "params": {
    "active": true
  }
}
```

#### INTERACTIVE_DISPLAY (交互显示屏)

**setDisplayMode**
```json
{
  "method": "setDisplayMode",
  "params": {
    "mode": "ANDROID"
  }
}
```

**setBrightness**
```json
{
  "method": "setBrightness",
  "params": {
    "brightness": 80
  }
}
```

**setTouchEnabled**
```json
{
  "method": "setTouchEnabled",
  "params": {
    "enabled": true
  }
}
```

#### INTERACTIVE_CONTROLLER (交互控制器)

**startSession**
```json
{
  "method": "startSession",
  "params": {
    "courseId": "MATH_101"
  }
}
```

**stopSession**
```json
{
  "method": "stopSession",
  "params": {}
}
```

**setMode**
```json
{
  "method": "setMode",
  "params": {
    "mode": "BROADCAST"
  }
}
```

#### BOT_SERVICE (机器人服务)

**dispatchTask**
```json
{
  "method": "dispatchTask",
  "params": {
    "taskId": "TASK_001",
    "route": "A->B->C",
    "payload": 5.0
  }
}
```

**cancelTask**
```json
{
  "method": "cancelTask",
  "params": {
    "taskId": "TASK_001"
  }
}
```

**returnToBase**
```json
{
  "method": "returnToBase",
  "params": {
    "stationId": "BASE_01"
  }
}
```

**setSpeedLimit**
```json
{
  "method": "setSpeedLimit",
  "params": {
    "speed": 1.5
  }
}
```

#### INTELLIGENT_BALANCE (智能天平)

**tare**
```json
{
  "method": "tare",
  "params": {}
}
```

**calibrate**
```json
{
  "method": "calibrate",
  "params": {
    "weight": 100.0,
    "unit": "g"
  }
}
```

**setUnit**
```json
{
  "method": "setUnit",
  "params": {
    "unit": "kg"
  }
}
```

#### HAZARDOUS_CABINET (危险品柜)

**unlock**
```json
{
  "method": "unlock",
  "params": {
    "authCode": "AUTH_12345"
  }
}
```

**setVentilation**
```json
{
  "method": "setVentilation",
  "params": {
    "enabled": true
  }
}
```

**setAlarmThreshold**
```json
{
  "method": "setAlarmThreshold",
  "params": {
    "type": "temperature",
    "max": 30.0
  }
}
```

#### COMPUTER_CONTROL (计算机控制)

**shutdown**
```json
{
  "method": "shutdown",
  "params": {
    "force": false
  }
}
```

**restart**
```json
{
  "method": "restart",
  "params": {
    "force": false
  }
}
```

**lockScreen**
```json
{
  "method": "lockScreen",
  "params": {}
}
```

**sendMessage**
```json
{
  "method": "sendMessage",
  "params": {
    "message": "Please save your work"
  }
}
```

#### ACCESS_CONTROL (门禁系统)

**openDoor**
```json
{
  "method": "openDoor",
  "params": {
    "duration": 5
  }
}
```
- `duration`: 开门持续时间（秒）

**setLockMode**
```json
{
  "method": "setLockMode",
  "params": {
    "mode": "AUTO"
  }
}
```

**syncUser**
```json
{
  "method": "syncUser",
  "params": {
    "userId": "USER_001",
    "permission": "READ"
  }
}
```

#### ATTENDANCE_TERMINAL (考勤系统)

**setMode**
```json
{
  "method": "setMode",
  "params": {
    "mode": "CHECK_IN"
  }
}
```

**displayMessage**
```json
{
  "method": "displayMessage",
  "params": {
    "message": "Welcome"
  }
}
```

**updateUserDb**
```json
{
  "method": "updateUserDb",
  "params": {
    "url": "https://example.com/users.json"
  }
}
```

#### SMART_CONTROL_CENTER (智能控制中心)

**setSystemMode**
```json
{
  "method": "setSystemMode",
  "params": {
    "mode": "TEACHING"
  }
}
```

**activateScene**
```json
{
  "method": "activateScene",
  "params": {
    "sceneId": "SCENE_MORNING"
  }
}
```

**broadcast**
```json
{
  "method": "broadcast",
  "params": {
    "content": "Class will start in 5 minutes",
    "level": "INFO"
  }
}
```

**emergencyStop**
```json
{
  "method": "emergencyStop",
  "params": {}
}
```

---

## 6. 共享属性机制 (Shared Attributes)

共享属性是平台向设备推送的配置参数，设备可以主动请求或被动接收。

### 6.1 设备请求共享属性

**设备发布请求**到主题 `v1/devices/me/attributes/request/{requestId}`（`{requestId}` 为设备生成的唯一ID）：

```json
{}
```

**平台响应**到主题 `v1/devices/me/attributes/response/{requestId}`（`{requestId}` 必须与请求中的 requestId 一致）：

```json
{
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1",
  "autoSync": true,
  "updateInterval": 30
}
```

**字段说明**：
- 如果设备没有共享属性，平台返回空对象 `{}`
- 响应格式为任意JSON对象，具体字段由平台配置决定

**发布 QoS**: 1 (至少一次)  
**保留标志 (Retain)**: `false`

### 6.2 平台主动推送共享属性

平台可以通过 `updateSharedAttributes` API主动推送共享属性到设备：

**平台发布**到主题 `v1/devices/me/attributes`：

```json
{
  "classroomZone": "ZONE_B",
  "updateInterval": 60
}
```

**发布 QoS**: 1 (至少一次)  
**保留标志 (Retain)**: `false`

### 6.3 自动同步机制

当设备在遥测数据中包含以下字段时，平台会自动推送共享属性：

```json
{
  "syncSharedAttributes": true
}
```

平台检测到此字段为 `true` 时，会自动将存储的共享属性推送到 `v1/devices/me/attributes` 主题。

**注意**：此机制由平台内置规则引擎实现，设备无需额外处理。

---

## 7. 枚举值定义

### 6.1 DeviceType (设备类型)

**APP代码中定义的枚举值**（与 `MqttModels.kt` 完全一致）：
- `STUDENT_POWER` - 学生电源
- `TEACHER_POWER` - 教师电源
- `LIFT_DEVICE` - 升降设备
- `LIGHTING_SWITCH` - 智能开关
- `LIGHTING_DIMMER` - 调光灯具
- `CURTAIN` - 窗帘控制
- `AIR_CONDITIONER` - 空调设备
- `ENVIRONMENT_MONITOR` - 环境监测
- `DRAINAGE_CONTROLLER` - 排水控制器
- `ENERGY_MONITOR` - 能耗监测
- `PROJECTOR` - 投影设备
- `INTERACTIVE_TEACHING` - 互动学生终端
- `INTERACTIVE_DISPLAY` - 互动显示设备
- `INTERACTIVE_CONTROLLER` - 互动控制器
- `BOT_SERVICE` - 机器人服务
- `INTELLIGENT_BALANCE` - 智能天平
- `HAZARDOUS_CABINET` - 危化品智能柜
- `COMPUTER_CONTROL` - 电脑控制终端
- `ACCESS_CONTROL` - 门禁控制
- `ATTENDANCE_TERMINAL` - 考勤终端
- `SMART_CONTROL_CENTER` - 智能控制中心

### 6.2 ClassroomZone (教室区域)
- `ZONE_A` - 区域A
- `ZONE_B` - 区域B
- `ZONE_C` - 区域C
- `ZONE_D` - 区域D
- `ENTIRE_ROOM` - 整个教室
- `CONTROL_ROOM` - 控制室
- `MAIN_ENTRANCE` - 主入口
- `CHEMISTRY_LAB` - 化学实验室
- `CHEMISTRY_STORAGE` - 化学存储室

### 6.3 StudentGroup (学生分组)
- `GROUP_1` - 第1组
- `GROUP_2` - 第2组
- `GROUP_3` - 第3组
- `GROUP_4` - 第4组
- `GROUP_5` - 第5组
- `GROUP_6` - 第6组
- `ALL_GROUPS` - 所有组

### 6.4 DeviceStatus (设备状态)

**APP代码中定义的枚举值**：
- `ONLINE` - 在线
- `OFFLINE` - 离线
- `ERROR` - 错误
- `WARNING` - 警告
- `MAINTENANCE` - 维护中

**注意**：遥测数据中的 `deviceStatus` 字段**必须**使用上述枚举值或设备特定的标准状态值（如 `IDLE`、`RUNNING`、`FAULT`、`NORMAL`、`OVERLOAD`）。

---

## 8. 错误处理与最佳实践

### 7.1 错误处理

设备在以下情况应返回错误响应：

1. **方法不存在**: 如果请求的 method 不在 capabilities 列表中
   ```json
   {
     "success": false,
     "error": {
       "code": 404,
       "message": "Method not found",
       "details": "Method 'unknownMethod' is not supported"
     }
   }
   ```

2. **参数错误**: 如果参数格式不正确或超出范围
   ```json
   {
     "success": false,
     "error": {
       "code": 400,
       "message": "Invalid parameter",
       "details": "Brightness must be between 0 and 100"
     }
   }
   ```

3. **设备状态错误**: 如果设备当前状态不允许执行该操作
   ```json
   {
     "success": false,
     "error": {
       "code": 503,
       "message": "Device busy",
       "details": "Device is currently moving, cannot accept new commands"
     }
   }
   ```

### 7.2 最佳实践

1. **设备ID验证**: 设备应验证 RPC 请求中的 `deviceId` 是否匹配自身ID，忽略不匹配的请求
2. **超时处理**: 如果操作需要较长时间，设备应立即返回响应，然后通过遥测数据上报进度
3. **状态同步**: 执行 RPC 命令后，设备应在下次遥测数据中反映最新状态
4. **心跳保持**: 设备应定期发送心跳，即使没有状态变化
5. **重连机制**: 设备应实现自动重连机制，在网络断开后自动恢复连接

### 7.3 标准启动流程

设备启动后**必须**严格遵循以下顺序：

1. 设备启动 → 连接 MQTT Broker（使用 Access Token 作为用户名）
2. 发布 Discovery 消息到 `v1/devices/me/attributes`
3. 订阅 RPC 请求主题 `sslab/rpc/request/{自己的deviceId}/+`（使用通配符 `+`）
4. 开始定期发送遥测数据到 `v1/devices/me/telemetry`（每 5-30 秒，自动更新心跳）
5. 接收并处理 RPC 请求，发送响应到 `v1/devices/me/rpc/response/{requestId}`

---

## 附录 A: 快速参考

### A.1 MQTT 主题快速参考

| 操作 | 主题 | 方向 | QoS | Retain |
|------|------|------|-----|--------|
| 设备注册 | `v1/devices/me/attributes` | 设备→平台 | 1 | false |
| 状态上报 | `v1/devices/me/telemetry` | 设备→平台 | 1 | false |
| 接收控制 | `sslab/rpc/request/{自己的deviceId}/+` | 平台→设备 | 1 | false |
| 发送响应 | `v1/devices/me/rpc/response/{requestId}` | 设备→平台 | 1 | false |

**注意**: 
- 心跳检测通过遥测数据自动完成，无需单独主题
- RPC 请求主题使用通配符 `+` 订阅所有请求
- `{requestId}` 为平台生成的唯一请求ID

### A.2 消息发布频率规范

- **Discovery (Attributes)**: 启动时 + 每 60 秒 + 状态变化时
- **Telemetry**: 每 5-30 秒或状态变化时立即发布（**自动更新心跳**）
  - 即使没有状态变化，也应定期发送（可发送空对象`{}`）以维持在线状态
  - 如果超过60秒未发送遥测数据，设备将被标记为离线
- **RPC Response**: 收到请求后**必须**立即响应（超时时间 5 秒）

### A.3 必需字段检查清单

**Discovery 消息必需字段**:
- [ ] `deviceId`
- [ ] `deviceType`
- [ ] `timestamp`
- [ ] `classroom_zone`
- [ ] `deviceInfo.manufacturer`
- [ ] `deviceInfo.model`
- [ ] `deviceInfo.firmwareVersion`
- [ ] `deviceInfo.hardwareVersion`
- [ ] `deviceInfo.serialNumber`
- [ ] `capabilities` (可为空数组，但字段必须存在)

**Heartbeat 消息必需字段**:
- [ ] `deviceId`
- [ ] `deviceType`
- [ ] `timestamp`
- [ ] `status`
- [ ] `uptime`

**Telemetry 消息必需字段**:
- [ ] `deviceId`
- [ ] `deviceType`
- [ ] `timestamp`
- [ ] 设备特定的状态字段

**RPC Response 必需字段**:
- [ ] `deviceId`
- [ ] `requestId` (如果请求中包含)
- [ ] `timestamp`
- [ ] `success`
- [ ] `result` 或 `error` (根据 success 值)

---

## 附录 B: 设备 ID 前缀对照表

| 前缀 | 设备类型 (DeviceType) | 中文名称 |
|------|----------------------|---------|
| SW- | LIGHTING_SWITCH | 智能开关 |
| LD- | LIGHTING_DIMMER | 调光灯具 |
| LT- | LIFT_DEVICE | 升降 |
| TP- | TEACHER_POWER | 教学电源 |
| SP- | STUDENT_POWER | 学生电源 |
| EM- | ENVIRONMENT_MONITOR | 环境监测 |
| DC- | DRAINAGE_CONTROLLER | 排水控制 |
| PM- | ENERGY_MONITOR | 能源监测 |
| CC- | CURTAIN | 窗帘 |
| PC- | PROJECTOR | 投影仪 |
| IS- | INTERACTIVE_TEACHING | 交互学生端 |
| ID- | INTERACTIVE_DISPLAY | 交互显示屏 |
| IC- | INTERACTIVE_CONTROLLER | 交互控制器 |
| AC- | AIR_CONDITIONER | 空调 |
| BT- | BOT_SERVICE | 机器人 |
| IB- | INTELLIGENT_BALANCE | 智能天平 |
| HC- | HAZARDOUS_CABINET | 危险品柜 |
| DO- | ACCESS_CONTROL | 门禁 |
| AT- | ATTENDANCE_TERMINAL | 考勤 |
| CP- | COMPUTER_CONTROL | 计算机控制 |
| SC- | SMART_CONTROL_CENTER | 智能中控 |

---

## 附录 C: 设备ID命名规范

### C.1 设备ID格式规范

所有设备ID必须遵循以下格式：

**格式**: `{前缀}-{MAC后四位}`

**规则**:
- 前缀：2-3个大写字母，对应设备类型（见附录B）
- MAC后四位：设备MAC地址的最后4位十六进制字符（大写，无冒号）
- 示例：MAC地址为 `AA:BB:CC:DD:EE:01`，则设备ID为 `LD-EE01`

**设备ID前缀对照表**:

| 前缀 | 设备类型 | 示例（MAC: AA:BB:CC:DD:EE:01） |
|------|---------|----------------------------|
| SW- | LIGHTING_SWITCH | SW-EE01 |
| LD- | LIGHTING_DIMMER | LD-EE01 |
| LT- | LIFT_DEVICE | LT-EE02 |
| TP- | TEACHER_POWER | TP-EE03 |
| SP- | STUDENT_POWER | SP-EE04 |
| EM- | ENVIRONMENT_MONITOR | EM-EE05 |
| DC- | DRAINAGE_CONTROLLER | DC-EE06 |
| PM- | ENERGY_MONITOR | PM-EE07 |
| CC- | CURTAIN | CC-EE08 |
| PC- | PROJECTOR | PC-EE09 |
| IS- | INTERACTIVE_TEACHING | IS-EE10 |
| ID- | INTERACTIVE_DISPLAY | ID-EE11 |
| IC- | INTERACTIVE_CONTROLLER | IC-EE12 |
| AC- | AIR_CONDITIONER | AC-EE13 |
| BT- | BOT_SERVICE | BT-EE14 |
| IB- | INTELLIGENT_BALANCE | IB-EE15 |
| HC- | HAZARDOUS_CABINET | HC-EE16 |
| DO- | ACCESS_CONTROL | DO-EE17 |
| AT- | ATTENDANCE_TERMINAL | AT-EE18 |
| CP- | COMPUTER_CONTROL | CP-EE19 |
| SC- | SMART_CONTROL_CENTER | SC-EE20 |

**重要**: 设备ID必须与设备MAC地址后四位一致，确保全局唯一性。

---

## 附录 D: 各设备类型完整交互示例

以下为各设备类型的完整交互示例。**所有消息格式通用规则**：
- Discovery: 主题 `v1/devices/me/attributes`, QoS=1, Retain=false
- Telemetry: 主题 `v1/devices/me/telemetry`, QoS=1, Retain=false, 频率5-30秒（自动更新心跳）
- RPC Request: 主题 `sslab/rpc/request/{deviceId}/{requestId}`, QoS=1, Retain=false（设备订阅 `sslab/rpc/request/{自己的deviceId}/+`）
- RPC Response: 主题 `v1/devices/me/rpc/response/{requestId}`, QoS=1, Retain=false

**字段说明**: 各设备类型的必需字段和条件必需字段已在第2-5章详细说明，此处仅展示完整JSON示例。

---

### D.1 调光灯具 (LIGHTING_DIMMER) - 设备ID: LD-EE01 (MAC: AA:BB:CC:DD:EE:01)

**Discovery** (发布到 `v1/devices/me/attributes`):
```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["setLightStatus", "setBrightness", "setColorTemperature"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "LED Panel 2024",
    "firmwareVersion": "1.2.3",
    "hardwareVersion": "1.0",
    "serialNumber": "DIMMER-LD-EE01"
  },
  "network": {
    "ipAddress": "192.168.0.110",
    "macAddress": "AA:BB:CC:DD:EE:01",
    "signalStrength": -50
  },
  "transportMode": "thingsboard",
  "scenes": [
    {"sceneId": "reading", "name": "阅读模式", "brightness": 80, "colorTemperature": 4000}
  ]
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 3600,
  "memoryUsage": 45.2,
  "cpuUsage": 12.5,
  "classroomZone": "ZONE_A",
  "signalQuality": 85
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):LD-EE01`):
```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067270000,
  "isOn": true,
  "brightness": 80,
  "colorTemperature": 4000,
  "powerConsumption": 15.5,
  "deviceStatus": "ONLINE"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):LD-EE01`):
```json
{
  "deviceId": "LD-EE01",
  "method": "setBrightness",
  "params": {"brightness": 90}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):LD-EE01`):
```json
{
  "deviceId": "LD-EE01",
  "requestId": "req_abc123",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Brightness set to 90"}
}
```

---

### D.2 智能开关 (LIGHTING_SWITCH) - 设备ID: SW-EE02 (MAC: AA:BB:CC:DD:EE:02)

**Discovery** (发布到 `v1/devices/me/attributes`):
```json
{
  "deviceId": "SW-EE02",
  "deviceType": "LIGHTING_SWITCH",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["setLightStatus", "turnOn", "turnOff"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Smart Switch 2024",
    "firmwareVersion": "1.2.3",
    "hardwareVersion": "1.0",
    "serialNumber": "SWITCH-SW-EE02"
  },
  "network": {
    "ipAddress": "192.168.0.111",
    "macAddress": "AA:BB:CC:DD:EE:02",
    "signalStrength": -50
  }
}
```

### D.3 升降设备 (LIFT_DEVICE) - 设备ID: LT-EE02 (MAC: AA:BB:CC:DD:EE:02)

**Discovery** (发布到 `v1/devices/me/attributes`):
```json
{
  "deviceId": "LT-EE02",
  "deviceType": "LIFT_DEVICE",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1",
  "capabilities": ["controlComputer", "controlLamp", "setGroup"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Lift Table Pro",
    "firmwareVersion": "2.0.1",
    "hardwareVersion": "2.0",
    "serialNumber": "LIFT_DEVICE-LT-EE02"
  },
  "network": {
    "ipAddress": "192.168.0.111",
    "macAddress": "AA:BB:CC:DD:EE:02",
    "signalStrength": -55
  }
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "LT-EE02",
  "deviceType": "LIFT_DEVICE",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 3600,
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1"
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "LT-EE02",
  "deviceType": "LIFT_DEVICE",
  "timestamp": 1704067270000,
  "lampStatus": true,
  "computerStatus": false,
  "deviceStatus": "IDLE"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):
```json
{
  "deviceId": "LT-EE02",
  "method": "controlComputer",
  "params": {"status": true}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):
```json
{
  "deviceId": "LT-EE02",
  "requestId": "req_xyz789",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Computer power on"}
}
```

---

### D.3 教学电源 (TEACHER_POWER) - 设备ID: TP-EE03 (MAC: AA:BB:CC:DD:EE:03)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "TP-EE03",
  "deviceType": "TEACHER_POWER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["setPowerMode", "controlTerminal"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Teacher Power Supply Pro",
    "firmwareVersion": "3.1.0",
    "hardwareVersion": "3.0",
    "serialNumber": "TEACHER_POWER-TP-EE03"
  },
  "network": {
    "ipAddress": "192.168.0.112",
    "macAddress": "AA:BB:CC:DD:EE:03",
    "signalStrength": -48
  }
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):TP-EE03`):
```json
{
  "deviceId": "TP-EE03",
  "deviceType": "TEACHER_POWER",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 7200,
  "classroomZone": "ZONE_A"
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):TP-EE03`):
```json
{
  "deviceId": "TP-EE03",
  "deviceType": "TEACHER_POWER",
  "timestamp": 1704067270000,
  "powerMode": "DC",
  "voltageSetting": 24.0,
  "currentSetting": 5.0,
  "actualVoltage": 23.8,
  "actualCurrent": 4.9,
  "deviceStatus": "NORMAL"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):TP-EE03`):
```json
{
  "deviceId": "TP-EE03",
  "method": "setPowerMode",
  "params": {"powerMode": "DC", "voltageSetting": 24.0, "currentSetting": 5.0}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):TP-EE03`):
```json
{
  "deviceId": "TP-EE03",
  "requestId": "req_term001",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Terminal 1 enabled"}
}
```

---

### D.4 学生电源 (STUDENT_POWER) - 设备ID: SP-EE04 (MAC: AA:BB:CC:DD:EE:04)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "SP-EE04",
  "deviceType": "STUDENT_POWER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1",
  "capabilities": ["setPowerMode", "controlSocket", "setGroupMode", "emergencyStop"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Student Power Supply v2",
    "firmwareVersion": "2.1.0",
    "hardwareVersion": "2.0",
    "serialNumber": "STUDENT_POWER-SP-EE04"
  },
  "network": {
    "ipAddress": "192.168.0.113",
    "macAddress": "AA:BB:CC:DD:EE:04",
    "signalStrength": -52
  }
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):SP-EE04`):
```json
{
  "deviceId": "SP-EE04",
  "deviceType": "STUDENT_POWER",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 5400,
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1"
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):SP-EE04`):
```json
{
  "deviceId": "SP-EE04",
  "deviceType": "STUDENT_POWER",
  "timestamp": 1704067270000,
  "studentGroup": "GROUP_1",
  "powerMode": "DC",
  "voltageSetting": 12.0,
  "currentSetting": 2.0,
  "actualVoltage": 11.9,
  "actualCurrent": 1.8,
  "socket1Status": true,
  "socket2Status": false,
  "deviceStatus": "NORMAL"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):SP-EE04`):
```json
{
  "deviceId": "SP-EE04",
  "method": "controlSocket",
  "params": {"socketNumber": 2, "status": true}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):SP-EE04`):
```json
{
  "deviceId": "SP-EE04",
  "requestId": "req_socket002",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Socket 2 enabled"}
}
```

---

继续为剩余设备类型添加完整示例...
<｜tool▁calls▁begin｜><｜tool▁call▁begin｜>
read_file

**1. 设备启动 - 发布 Discovery 消息**

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["setLightStatus", "setBrightness", "setColorTemperature"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "LED Panel 2024",
    "firmwareVersion": "1.2.3",
    "hardwareVersion": "1.0",
    "serialNumber": "DIMMER-LD-6844"
  },
  "network": {
    "ipAddress": "192.168.0.110",
    "macAddress": "AA:BB:CC:DD:EE:FF",
    "signalStrength": -50
  }
}
```

**2. 定期发送心跳**

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 60,
  "classroomZone": "ZONE_A",
  "signalQuality": 85
}
```

**3. 定期发送遥测数据**

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067270000,
  "isOn": true,
  "brightness": 80,
  "colorTemperature": 4000,
  "deviceStatus": "ONLINE"
}
```

**4. 接收 RPC 控制命令**

平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`:
```json
{
  "deviceId": "LD-EE01",
  "method": "setBrightness",
  "params": {
    "brightness": 90
  }
}
```

**5. 发送 RPC 响应**

设备发送到 `v1/devices/me/rpc/response/{requestId}`:
```json
{
  "deviceId": "LD-EE01",
  "requestId": "req_12345",
  "timestamp": 1704067271000,
  "success": true,
  "result": {
    "message": "Brightness set to 90"
  }
}
```

**6. 更新遥测数据反映新状态**

```json
{
  "deviceId": "LD-EE01",
  "deviceType": "LIGHTING_DIMMER",
  "timestamp": 1704067272000,
  "isOn": true,
  "brightness": 90,
  "colorTemperature": 4000,
  "deviceStatus": "ONLINE"
}
```

### C.2 学生电源完整交互示例

**Discovery 消息**:
```json
{
  "deviceId": "SP-EE04",
  "deviceType": "STUDENT_POWER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1",
  "capabilities": ["setPowerMode", "controlSocket", "setGroupMode", "emergencyStop"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Student Power Supply v2",
    "firmwareVersion": "2.1.0",
    "hardwareVersion": "2.0",
    "serialNumber": "STUDENT_POWER-SP-001"
  }
}
```

**遥测数据**:
```json
{
  "deviceId": "SP-EE04",
  "deviceType": "STUDENT_POWER",
  "timestamp": 1704067270000,
  "powerMode": "DC",
  "voltageSetting": 12.0,
  "currentSetting": 2.0,
  "actualVoltage": 11.9,
  "actualCurrent": 1.8,
  "socket1Status": true,
  "socket2Status": false,
  "socket3Status": false,
  "socket4Status": false,
  "deviceStatus": "NORMAL"
}
```

**RPC 控制示例 - 控制插座**:
```json
{
  "deviceId": "SP-EE04",
  "method": "controlSocket",
  "params": {
    "socketNumber": 2,
    "status": true
  }
}
```

---

### D.5 环境监测 (ENVIRONMENT_MONITOR) - 设备ID: EM-EE05 (MAC: AA:BB:CC:DD:EE:05)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "EM-EE05",
  "deviceType": "ENVIRONMENT_MONITOR",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["calibrate", "setDisplay"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Environment Monitor Pro",
    "firmwareVersion": "1.5.2",
    "hardwareVersion": "1.0",
    "serialNumber": "ENVIRONMENT_MONITOR-EM-EE05"
  },
  "network": {
    "ipAddress": "192.168.0.114",
    "macAddress": "AA:BB:CC:DD:EE:05",
    "signalStrength": -45
  }
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):EM-EE05`):
```json
{
  "deviceId": "EM-EE05",
  "deviceType": "ENVIRONMENT_MONITOR",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 10800,
  "classroomZone": "ZONE_A"
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):EM-EE05`):
```json
{
  "deviceId": "EM-EE05",
  "deviceType": "ENVIRONMENT_MONITOR",
  "timestamp": 1704067270000,
  "temperature": 23.5,
  "humidity": 55.2,
  "co2": 450,
  "pm25": 35,
  "deviceStatus": "NORMAL"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):EM-EE05`):
```json
{
  "deviceId": "EM-EE05",
  "method": "calibrate",
  "params": {"sensor": "temperature", "value": 25.0}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):EM-EE05`):
```json
{
  "deviceId": "EM-EE05",
  "requestId": "req_cal001",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Temperature sensor calibrated"}
}
```

---

### D.6 排水控制 (DRAINAGE_CONTROLLER) - 设备ID: DC-EE06 (MAC: AA:BB:CC:DD:EE:06)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "DC-EE06",
  "deviceType": "DRAINAGE_CONTROLLER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1",
  "capabilities": ["setDrainage", "setWaterSupply", "setVentilation", "setFanSpeed"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Drainage Controller v2",
    "firmwareVersion": "2.0.3",
    "hardwareVersion": "2.0",
    "serialNumber": "DRAINAGE_CONTROLLER-DC-EE06"
  },
  "network": {
    "ipAddress": "192.168.0.115",
    "macAddress": "AA:BB:CC:DD:EE:06",
    "signalStrength": -50
  }
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):DC-EE06`):
```json
{
  "deviceId": "DC-EE06",
  "deviceType": "DRAINAGE_CONTROLLER",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 14400,
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1"
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):DC-EE06`):
```json
{
  "deviceId": "DC-EE06",
  "deviceType": "DRAINAGE_CONTROLLER",
  "timestamp": 1704067270000,
  "studentGroup": "GROUP_1",
  "drainageStatus": true,
  "ventilationStatus": true,
  "fanSpeed": 60,
  "deviceStatus": "NORMAL"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):DC-EE06`):
```json
{
  "deviceId": "DC-EE06",
  "method": "setFanSpeed",
  "params": {"speed": 80}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):DC-EE06`):
```json
{
  "deviceId": "DC-EE06",
  "requestId": "req_fan001",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Fan speed set to 80"}
}
```

---

### D.7 能源监测 (ENERGY_MONITOR) - 设备ID: PM-EE07 (MAC: AA:BB:CC:DD:EE:07)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "PM-EE07",
  "deviceType": "ENERGY_MONITOR",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["resetEnergy", "setUploadInterval"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Energy Monitor Pro",
    "firmwareVersion": "1.3.1",
    "hardwareVersion": "1.0",
    "serialNumber": "ENERGY_MONITOR-PM-EE07"
  },
  "network": {
    "ipAddress": "192.168.0.116",
    "macAddress": "AA:BB:CC:DD:EE:07",
    "signalStrength": -47
  }
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):PM-EE07`):
```json
{
  "deviceId": "PM-EE07",
  "deviceType": "ENERGY_MONITOR",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 18000,
  "classroomZone": "ZONE_A"
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):PM-EE07`):
```json
{
  "deviceId": "PM-EE07",
  "deviceType": "ENERGY_MONITOR",
  "timestamp": 1704067270000,
  "voltage": 220.5,
  "current": 5.2,
  "activePower": 1146.6,
  "energy": 1250.8,
  "frequency": 50.0
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):PM-EE07`):
```json
{
  "deviceId": "PM-EE07",
  "method": "resetEnergy",
  "params": {}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):PM-EE07`):
```json
{
  "deviceId": "PM-EE07",
  "requestId": "req_reset001",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Energy counter reset"}
}
```

---

### D.8 窗帘控制 (CURTAIN) - 设备ID: CC-EE08 (MAC: AA:BB:CC:DD:EE:08)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "CC-EE08",
  "deviceType": "CURTAIN",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["setPosition", "setMode", "stop"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Smart Curtain Controller",
    "firmwareVersion": "1.2.0",
    "hardwareVersion": "1.0",
    "serialNumber": "CURTAIN-CC-EE08"
  },
  "network": {
    "ipAddress": "192.168.0.117",
    "macAddress": "AA:BB:CC:DD:EE:08",
    "signalStrength": -49
  }
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):CC-EE08`):
```json
{
  "deviceId": "CC-EE08",
  "deviceType": "CURTAIN",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 21600,
  "classroomZone": "ZONE_A"
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):CC-EE08`):
```json
{
  "deviceId": "CC-EE08",
  "deviceType": "CURTAIN",
  "timestamp": 1704067270000,
  "curtainPosition": 50,
  "isMoving": false,
  "deviceStatus": "IDLE"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):CC-EE08`):
```json
{
  "deviceId": "CC-EE08",
  "method": "setPosition",
  "params": {"position": 75}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):CC-EE08`):
```json
{
  "deviceId": "CC-EE08",
  "requestId": "req_pos001",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Curtain position set to 75"}
}
```

---

### D.9 投影仪 (PROJECTOR) - 设备ID: PC-EE09 (MAC: AA:BB:CC:DD:EE:09)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "PC-EE09",
  "deviceType": "PROJECTOR",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["setPower", "setInput", "setBrightness"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "Projector Pro 4K",
    "firmwareVersion": "2.1.5",
    "hardwareVersion": "2.0",
    "serialNumber": "PROJECTOR-PC-EE09"
  },
  "network": {
    "ipAddress": "192.168.0.118",
    "macAddress": "AA:BB:CC:DD:EE:09",
    "signalStrength": -46
  }
}
```

**Heartbeat** (通过遥测数据自动更新，发布到 `v1/devices/me/telemetry`):PC-EE09`):
```json
{
  "deviceId": "PC-EE09",
  "deviceType": "PROJECTOR",
  "timestamp": 1704067260000,
  "status": "ONLINE",
  "uptime": 25200,
  "classroomZone": "ZONE_A"
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):PC-EE09`):
```json
{
  "deviceId": "PC-EE09",
  "deviceType": "PROJECTOR",
  "timestamp": 1704067270000,
  "powerStatus": true,
  "inputSource": "HDMI1",
  "brightness": 80,
  "lampHours": 1250,
  "deviceStatus": "ON"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/{deviceId}/{requestId}`, 设备订阅 `sslab/rpc/request/{自己的deviceId}/+`):PC-EE09`):
```json
{
  "deviceId": "PC-EE09",
  "method": "setPower",
  "params": {"enabled": true}
}
```

**RPC Response** (设备发送到 `v1/devices/me/rpc/response/{requestId}`):PC-EE09`):
```json
{
  "deviceId": "PC-EE09",
  "requestId": "req_pwr001",
  "timestamp": 1704067271000,
  "success": true,
  "result": {"message": "Projector powered on"}
}
```

---

### D.10 互动学生终端 (INTERACTIVE_TEACHING) - 设备ID: IS-EE10 (MAC: AA:BB:CC:DD:EE:10)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "IS-EE10",
  "deviceType": "INTERACTIVE_TEACHING",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "studentGroup": "GROUP_1",
  "capabilities": ["setDisplayContent", "setInteractionState"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "EduPad V2",
    "firmwareVersion": "1.2.0",
    "hardwareVersion": "1.0",
    "serialNumber": "IS-EE10-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "IS-EE10",
  "deviceType": "INTERACTIVE_TEACHING",
  "timestamp": 1704067270000,
  "isActive": true,
  "currentQuestion": "Q1024",
  "studentId": "STU2024001",
  "response": "A"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/IS-EE10/{requestId}`):
```json
{
  "deviceId": "IS-EE10",
  "method": "SetDisplayContent",
  "params": {"content": "Please answer Question 2"}
}
```

---

### D.11 互动显示设备 (INTERACTIVE_DISPLAY) - 设备ID: ID-EE11 (MAC: AA:BB:CC:DD:EE:11)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "ID-EE11",
  "deviceType": "INTERACTIVE_DISPLAY",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_FRONT",
  "capabilities": ["setDisplayMode", "setBrightness", "setTouchEnabled"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "SmartBoard X1",
    "firmwareVersion": "3.0.1",
    "hardwareVersion": "2.0",
    "serialNumber": "ID-EE11-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "ID-EE11",
  "deviceType": "INTERACTIVE_DISPLAY",
  "timestamp": 1704067270000,
  "displayMode": "PRESENTATION",
  "brightness": 90,
  "touchEnabled": true,
  "content": "Slide 5"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/ID-EE11/{requestId}`):
```json
{
  "deviceId": "ID-EE11",
  "method": "SetDisplayMode",
  "params": {"mode": "WHITEBOARD"}
}
```

---

### D.12 互动控制器 (INTERACTIVE_CONTROLLER) - 设备ID: IC-EE12 (MAC: AA:BB:CC:DD:EE:12)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "IC-EE12",
  "deviceType": "INTERACTIVE_CONTROLLER",
  "timestamp": 1704067200000,
  "classroomZone": "TEACHER_DESK",
  "capabilities": ["startSession", "stopSession", "setMode"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "ControlPad Pro",
    "firmwareVersion": "1.5.0",
    "hardwareVersion": "1.0",
    "serialNumber": "IC-EE12-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "IC-EE12",
  "deviceType": "INTERACTIVE_CONTROLLER",
  "timestamp": 1704067270000,
  "sessionActive": true,
  "connectedDevices": 45,
  "currentMode": "EXAM"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/IC-EE12/{requestId}`):
```json
{
  "deviceId": "IC-EE12",
  "method": "StartSession",
  "params": {"courseId": "CS101"}
}
```

---

### D.13 空调设备 (AIR_CONDITIONER) - 设备ID: AC-EE13 (MAC: AA:BB:CC:DD:EE:13)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "AC-EE13",
  "deviceType": "AIR_CONDITIONER",
  "timestamp": 1704067200000,
  "classroomZone": "ZONE_A",
  "capabilities": ["controlAircon", "setSchedule"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "CoolMaster 3000",
    "firmwareVersion": "2.0.0",
    "hardwareVersion": "1.5",
    "serialNumber": "AC-EE13-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "AC-EE13",
  "deviceType": "AIR_CONDITIONER",
  "timestamp": 1704067270000,
  "powerStatus": true,
  "mode": "COOL",
  "currentTemperature": 24.5,
  "targetTemperature": 22.0,
  "fanSpeed": "MEDIUM",
  "humidity": 45.0
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/AC-EE13/{requestId}`):
```json
{
  "deviceId": "AC-EE13",
  "method": "ControlAircon",
  "params": {
    "powerStatus": true,
    "mode": "COOL",
    "targetTemperature": 22.0,
    "fanSpeed": "HIGH"
  }
}
```

---

### D.14 机器人服务 (BOT_SERVICE) - 设备ID: BS-EE14 (MAC: AA:BB:CC:DD:EE:14)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "BS-EE14",
  "deviceType": "BOT_SERVICE",
  "timestamp": 1704067200000,
  "classroomZone": "CORRIDOR",
  "capabilities": ["dispatchTask", "cancelTask", "returnToBase", "setSpeedLimit"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "DeliveryBot X1",
    "firmwareVersion": "4.1.0",
    "hardwareVersion": "3.0",
    "serialNumber": "BS-EE14-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "BS-EE14",
  "deviceType": "BOT_SERVICE",
  "timestamp": 1704067270000,
  "botId": "BOT-001",
  "taskId": "TASK-998",
  "taskStatus": "IN_PROGRESS",
  "position": {"x": 12.5, "y": 34.2, "floor": 3.0},
  "batteryLevel": 85.5,
  "velocity": 0.8,
  "deviceStatus": "BUSY"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/BS-EE14/{requestId}`):
```json
{
  "deviceId": "BS-EE14",
  "method": "DispatchTask",
  "params": {
    "taskId": "TASK-999",
    "route": "LAB_TO_OFFICE",
    "payload": 5.0
  }
}
```

---

### D.15 智能天平 (INTELLIGENT_BALANCE) - 设备ID: IB-EE15 (MAC: AA:BB:CC:DD:EE:15)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "IB-EE15",
  "deviceType": "INTELLIGENT_BALANCE",
  "timestamp": 1704067200000,
  "classroomZone": "LAB_BENCH_1",
  "capabilities": ["tare", "calibrate", "setUnit"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "PrecisionScale 0.01g",
    "firmwareVersion": "1.0.5",
    "hardwareVersion": "1.0",
    "serialNumber": "IB-EE15-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "IB-EE15",
  "deviceType": "INTELLIGENT_BALANCE",
  "timestamp": 1704067270000,
  "weight": 125.45,
  "unit": "g",
  "isStable": true,
  "tare": 0.0,
  "range": "0-500g"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/IB-EE15/{requestId}`):
```json
{
  "deviceId": "IB-EE15",
  "method": "Tare",
  "params": {}
}
```

---

### D.16 危化品智能柜 (HAZARDOUS_CABINET) - 设备ID: HC-EE16 (MAC: AA:BB:CC:DD:EE:16)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "HC-EE16",
  "deviceType": "HAZARDOUS_CABINET",
  "timestamp": 1704067200000,
  "classroomZone": "STORAGE_ROOM",
  "capabilities": ["unlock", "setVentilation", "setAlarmThreshold"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "SafeStore 500",
    "firmwareVersion": "2.2.1",
    "hardwareVersion": "2.0",
    "serialNumber": "HC-EE16-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "HC-EE16",
  "deviceType": "HAZARDOUS_CABINET",
  "timestamp": 1704067270000,
  "temperature": 18.5,
  "humidity": 35.0,
  "vocLevel": 0.05,
  "doorStatus": false,
  "lockStatus": true,
  "alarmStatus": false
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/HC-EE16/{requestId}`):
```json
{
  "deviceId": "HC-EE16",
  "method": "Unlock",
  "params": {"authCode": "123456"}
}
```

---

### D.17 电脑控制终端 (COMPUTER_CONTROL) - 设备ID: CP-EE17 (MAC: AA:BB:CC:DD:EE:17)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "CP-EE17",
  "deviceType": "COMPUTER_CONTROL",
  "timestamp": 1704067200000,
  "classroomZone": "TEACHER_DESK",
  "capabilities": ["shutdown", "restart", "lockScreen", "sendMessage"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "ControlAgent Win11",
    "firmwareVersion": "1.0.0",
    "hardwareVersion": "N/A",
    "serialNumber": "CP-EE17-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "CP-EE17",
  "deviceType": "COMPUTER_CONTROL",
  "timestamp": 1704067270000,
  "pcStatus": "RUNNING",
  "cpuUsage": 15.5,
  "memoryUsage": 42.0,
  "currentUser": "teacher_admin",
  "appActive": "PowerPoint"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/CP-EE17/{requestId}`):
```json
{
  "deviceId": "CP-EE17",
  "method": "SendMessage",
  "params": {"message": "Class is over in 5 minutes"}
}
```

---

### D.18 门禁控制 (ACCESS_CONTROL) - 设备ID: DC-EE18 (MAC: AA:BB:CC:DD:EE:18)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "DC-EE18",
  "deviceType": "ACCESS_CONTROL",
  "timestamp": 1704067200000,
  "classroomZone": "ENTRANCE",
  "capabilities": ["openDoor", "setLockMode", "syncUser"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "SecureGate V3",
    "firmwareVersion": "3.1.0",
    "hardwareVersion": "2.0",
    "serialNumber": "DC-EE18-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "DC-EE18",
  "deviceType": "ACCESS_CONTROL",
  "timestamp": 1704067270000,
  "doorState": "CLOSED",
  "lastAccessUser": "STU2024001",
  "lastAccessTime": 1704067265000,
  "lastAccessType": "CARD"
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/DC-EE18/{requestId}`):
```json
{
  "deviceId": "DC-EE18",
  "method": "OpenDoor",
  "params": {"duration": 5000}
}
```

---

### D.19 考勤终端 (ATTENDANCE_TERMINAL) - 设备ID: AT-EE19 (MAC: AA:BB:CC:DD:EE:19)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "AT-EE19",
  "deviceType": "ATTENDANCE_TERMINAL",
  "timestamp": 1704067200000,
  "classroomZone": "ENTRANCE",
  "capabilities": ["setMode", "displayMessage", "updateUserDb"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "FaceID Pro",
    "firmwareVersion": "2.5.0",
    "hardwareVersion": "2.0",
    "serialNumber": "AT-EE19-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "AT-EE19",
  "deviceType": "ATTENDANCE_TERMINAL",
  "timestamp": 1704067270000,
  "deviceMode": "CHECK_IN",
  "todayCount": 45,
  "lastCheckIn": {"userId": "STU2024005", "time": "08:05:00"}
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/AT-EE19/{requestId}`):
```json
{
  "deviceId": "AT-EE19",
  "method": "DisplayMessage",
  "params": {"message": "Welcome to Lab 1"}
}
```

---

### D.20 智能控制中心 (SMART_CONTROL_CENTER) - 设备ID: SC-EE20 (MAC: AA:BB:CC:DD:EE:20)

**Discovery** (发布到 v1/devices/me/attributes):
```json
{
  "deviceId": "SC-EE20",
  "deviceType": "SMART_CONTROL_CENTER",
  "timestamp": 1704067200000,
  "classroomZone": "TEACHER_DESK",
  "capabilities": ["setSystemMode", "activateScene", "broadcast", "emergencyStop"],
  "deviceInfo": {
    "manufacturer": "SSLAB",
    "model": "CentralHub X",
    "firmwareVersion": "5.0.0",
    "hardwareVersion": "4.0",
    "serialNumber": "SC-EE20-001"
  }
}
```

**Telemetry** (发布到 `v1/devices/me/telemetry`):
```json
{
  "deviceId": "SC-EE20",
  "deviceType": "SMART_CONTROL_CENTER",
  "timestamp": 1704067270000,
  "systemMode": "TEACHING",
  "currentScene": "LECTURE",
  "activeAlerts": 0,
  "networkLoad": 12.5
}
```

**RPC Request** (平台发送到 `sslab/rpc/request/SC-EE20/{requestId}`):
```json
{
  "deviceId": "SC-EE20",
  "method": "ActivateScene",
  "params": {"sceneId": "LAB_EXPERIMENT"}
}
```

---

## 6. 调试与维护 (Debugging & Maintenance)

### 6.1 设备缓存清除

HMI 平台具备清除本地设备缓存的功能 (`clearLocalDiscoveredDevices`)，用于解决设备状态不一致或元数据过时的问题。

**清除范围**:
- 已连接设备列表
- 客户端会话映射 (Session Maps)
- 设备属性缓存 (Attributes Cache)
- 发现管理器中的设备数据

**设备端影响**:
- 当 HMI 执行清除操作时，可能会断开现有 MQTT 连接或重置会话。
- 设备应具备**自动重连**和**重新发布属性** (`v1/devices/me/attributes`) 的机制，以确保在 HMI 重置后能迅速恢复在线状态。

### 6.2 日志追踪

HMI 增强了日志输出，设备端开发人员在调试时可关注以下日志标签：
- `MqttBrokerService`: 查看连接、断开、RPC 路由日志
- `DeviceDiscovery`: 查看设备属性上报和发现日志

---

## 版本历史

| 版本 | 日期 | 更新内容 |
|------|------|---------|
| 3.3 | 2025-12-15 | 增加定向 RPC 主题支持，解决广播风暴问题；添加调试与维护章节 |
|------|------|---------|
| 3.1 | 2024 | 初始版本，统一 MQTT 主题架构 |
| 3.2 | 2024 | 修复主题名称、RPC格式、枚举值，添加心跳协议、完整RPC参数说明、错误处理指南 |

---

## 文档完整性检查

本文档已包含设备端开发所需的全部信息：

✅ **MQTT 连接配置** - 端口、QoS、Retain 标志  
✅ **主题架构** - 所有主题名称和用途  
✅ **设备发现协议** - 完整消息格式和字段说明  
✅ **心跳协议** - 心跳消息格式和频率  
✅ **遥测数据规范** - 所有设备类型的遥测字段  
✅ **RPC 命令规范** - 请求/响应格式和所有方法参数  
✅ **枚举值定义** - 设备类型、区域、分组、状态  
✅ **错误处理** - 错误响应格式和最佳实践  
✅ **完整示例** - 实际交互流程示例  
✅ **快速参考** - 便于查找的关键信息  

**设备端开发者可以仅凭本文档完成设备固件开发，无需查阅其他文档或代码。**
