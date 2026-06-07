# D3 — 教师端低压电源

> **端口：** TCP 8888  
> **固定 IP：** 192.168.0.211  
> **协议：** Modbus RTU over TCP（含 CRC16，无 MBAP Header）  
> **连接方式：** 短连接（发完即断）

---

## 一、硬件说明

教师端低压电源为可编程直流/交流电源，负责为教师演示台提供可调节的低压输出：

| 控制变量 | 含义 | 类型 | 范围 |
|---------|------|------|------|
| `LowKZ` | 电源总开关 | 布尔 | true / false |
| `LowDYSZ` | 输出电压设定值 | 浮点 | 0 ~ 30.0 V |
| `LowDLSZ` | 输出电流限制值 | 浮点 | 0.1 ~ 30.0 A（默认 2.5A） |
| `LowDC_AC` | 输出模式 | 整数 | 0 = DC，1 = AC |

---

## 二、通信协议

### Modbus RTU 帧结构（裸帧，含 CRC16）

**开启帧（写 4 个寄存器，功能码 0x10）：**
```
┌────────┬──────┬─────────┬──────────┬───────────┬─────────────────────────────────┬───────┐
│ Slave  │ Func │ Start   │ Quantity │ ByteCount │ Data (8 bytes)                  │ CRC16 │
│ 1 byte │ 0x10 │ 0x0003  │ 0x0004   │ 0x08      │ [Cur H/L][Vol H/L][01 00][00 00]│ 2 B   │
└────────┴──────┴─────────┴──────────┴───────────┴─────────────────────────────────┴───────┘
```

**关闭帧（写 2 个寄存器，功能码 0x10）：**
```
┌────────┬──────┬─────────┬──────────┬───────────┬──────────────┬───────┐
│ Slave  │ Func │ Start   │ Quantity │ ByteCount │ Data (4 B)   │ CRC16 │
│ 1 byte │ 0x10 │ 0x0004  │ 0x0002   │ 0x04      │ [00 00 00 00]│ 2 B   │
└────────┴──────┴─────────┴──────────┴───────────┴──────────────┴───────┘
```

### 寄存器地址表

| 寄存器 | 地址 | 说明 |
|--------|------|------|
| Reg 3 | 0x0003 | 输出电流（整数，单位 mA，x1000） |
| Reg 4 | 0x0004 | 输出电压（整数，单位 0.01V，x100） |
| Reg 5 | 0x0005 | 控制位（1=开，0=关） |
| Reg 6 | 0x0006 | 保留（始终 0x0000） |

### 从机地址（Slave Address）

| 模式 | 从机地址 |
|------|---------|
| DC 直流 | `0xA1` |
| AC 交流 | `0xA2` |

### 数值换算规则

| 参数 | Web 输入 | 协议值 | 换算公式 |
|------|---------|-------|---------|
| 电压 | 12.5 V | 1250 | `int(V × 100)` |
| 电流 | 2.5 A | 2500 | `int(A × 1000)` |

---

## 三、完整帧示例

### 示例：DC 模式，12.5V，2.5A，开启

- Slave = `0xA1`
- 电流 = 2500 = `0x09C4`
- 电压 = 1250 = `0x04E2`

```
A1 10 00 03 00 04 08  09 C4  04 E2  00 01  00 00  [CRC16-LE]
```

PDU 部分（CRC 前，共 13 字节）：
```
A1 10 00 03 00 04 08 09 C4 04 E2 00 01 00 00
```
CRC16-Modbus（小端）计算后追加 2 字节。

### 示例：关闭

- Slave = `0xA1`

```
A1 10 00 04 00 02 04  00 00  00 00  [CRC16-LE]
```

---

## 四、CRC16 Modbus 算法

```python
import struct

def crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if crc & 1:
                crc = (crc >> 1) ^ 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)  # 小端序
```

---

## 五、发送触发条件

后端仅在以下情况下向设备发送命令，不做无效发送：

| 触发变量 | 是否发送 | 条件 |
|---------|---------|------|
| `LowKZ` | **始终** | 开或关都发 |
| `LowDYSZ` | 仅当 `LowKZ=true` | 电源已开才发电压更新 |
| `LowDLSZ` | 仅当 `LowKZ=true` | 电源已开才发电流更新 |
| `LowDC_AC` | 仅当 `LowKZ=true` | 电源已开才发模式更新 |

---

## 六、API 调用方式

### 开启电源（12V DC，2A）
```bash
curl -X POST http://localhost:1880/ctrl/LowDYSZ -H "Content-Type: application/json" -d '{"value": 12}'
curl -X POST http://localhost:1880/ctrl/LowDLSZ -H "Content-Type: application/json" -d '{"value": 2.0}'
curl -X POST http://localhost:1880/ctrl/LowDC_AC -H "Content-Type: application/json" -d '{"value": 0}'
curl -X POST http://localhost:1880/ctrl/LowKZ    -H "Content-Type: application/json" -d '{"value": true}'
```

### 关闭电源
```bash
curl -X POST http://localhost:1880/ctrl/LowKZ -H "Content-Type: application/json" -d '{"value": false}'
```

### 切换为 AC 模式
```bash
curl -X POST http://localhost:1880/ctrl/LowDC_AC -H "Content-Type: application/json" -d '{"value": 1}'
```

---

## 七、IP 固定说明

IP `192.168.0.211` 已硬编码，不依赖扫描结果：
```python
devs_8888 = [{"ip": "192.168.0.211", "port": 8888, "type": "final_fixed"}]
```

---

## 八、故障排查

| 现象 | 可能原因 | 解决方法 |
|------|---------|---------|
| 电源无输出 | Slave 地址不匹配 | 确认设备 Slave 地址为 0xA1（DC）或 0xA2（AC） |
| 电压值异常 | 换算倍率错误 | 检查是否已乘 100（12V → 1200，不是 12） |
| 开关命令后无响应 | IP 不通 | `ping 192.168.0.211` 确认网络连通 |
| 电流限制不生效 | 默认 2.5A 过大 | 显式设置 `LowDLSZ` 后再开 `LowKZ` |
