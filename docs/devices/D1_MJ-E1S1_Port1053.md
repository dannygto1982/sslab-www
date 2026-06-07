# D1 — 鸣驹 MJ-E1S1-X-P 学生台控制器

> **端口：** TCP 1053  
> **目标IP：** 192.168.0.100 ~ 192.168.0.130（固定范围广播）  
> **协议：** Legacy JSON over TCP（明文 JSON，`\n` 结尾）  
> **连接方式：** 短连接（发完即断）

---

## 一、硬件说明

鸣驹 MJ-E1S1-X-P 是一款以太网继电器控制器，每台控制一个学生工位：

| 继电器通道 | 功能 | 变量名 |
|-----------|------|-------|
| `device1` | 学生台 PC 电源开关 | `Computer` |
| `motor_fwd` | 升降台电机正转（上升） | `Lifting` 上升 |
| `motor_bwd` | 升降台电机反转（下降） | `Lifting` 下降 |

---

## 二、通信协议

### 格式
```
{"<key>": <bool>}\n
```
- 编码：UTF-8，无 BOM
- 结尾：`\n`（0x0A 换行符）
- 连接：TCP 短连接，发送后立即关闭

### 命令列表

#### PC 电源开（Computer ON）
```json
{"device1": true}
```
字节序列：
```
7B 22 64 65 76 69 63 65 31 22 3A 20 74 72 75 65 7D 0A
```

#### PC 电源关（Computer OFF）
```json
{"device1": false}
```
字节序列：
```
7B 22 64 65 76 69 63 65 31 22 3A 20 66 61 6C 73 65 7D 0A
```

#### 升降台上升（Lifting UP）
```json
{"motor_fwd": true, "motor_bwd": false}
```
字节序列：
```
7B 22 6D 6F 74 6F 72 5F 66 77 64 22 3A 20 74 72 75 65 2C 20 22 6D 6F 74 6F 72 5F 62 77 64 22 3A 20 66 61 6C 73 65 7D 0A
```

#### 升降台下降（Lifting DOWN）
```json
{"motor_fwd": false, "motor_bwd": true}
```

#### 升降台停止（Lifting STOP）
```json
{"motor_fwd": false, "motor_bwd": false}
```

> ⚠️ **注意**：上升和下降命令必须同时设置两个键（双键模式），单键命令会导致电机不响应。

---

## 三、发送范围与策略

- **目标 IP 范围：** `192.168.0.100` ~ `192.168.0.130`（共 31 个 IP）
- **发送次数：** 每次控制操作发送 **2 轮**（共发送 62 次）
- **原因：** 广播范围内设备数量不确定，重复发送防止丢包
- **并发控制：** 后端使用队列管理器，批量大小 = 2，批间延迟 = 50ms

```python
target_ips = [f"192.168.0.{i}" for i in range(100, 131)]
for _ in range(2):
    for ip in target_ips:
        await queue_manager.add_task(ip, 1053, cmd)
```

---

## 四、API 调用方式

### PC 电源控制
```http
POST /ctrl/Computer
Content-Type: application/json

{"value": true}   # 开
{"value": false}  # 关
```

### 升降台控制
```http
POST /ctrl/Lifting
Content-Type: application/json

{"value": "up"}    # 上升
{"value": "down"}  # 下降
{"value": "stop"}  # 停止
{"value": true}    # 等同于 up
{"value": false}   # 等同于 down
```

---

## 五、响应

设备无应答帧，后端采用"发送即成功"策略。

---

## 六、设备发现

系统启动时自动扫描，发现 192.168.0.100-130 中响应 1053 端口的设备，记录到 `config.json`：
```json
{"ip": "192.168.0.101", "port": 1053, "type": "control", "name": "Control-101"}
```

---

## 七、故障排查

| 现象 | 可能原因 | 解决方法 |
|------|---------|---------|
| PC 不开机 | IP 不在 100-130 范围 | 检查设备 IP 配置 |
| 升降台不动 | 发送了单键命令（旧版本 bug） | 确认使用双键格式 |
| 升降台不停 | 没有发送 STOP 命令 | 操作后补发 `{"value": "stop"}` |
| 部分设备无响应 | 正常（范围广播，允许部分离线） | 无需处理 |
