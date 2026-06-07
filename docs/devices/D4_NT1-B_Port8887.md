# D4 — 亿佰特 NT1-B 学生端同步器

> **端口：** TCP 8887  
> **固定 IP：** 192.168.0.12（NT1-B 设备 IP）  
> **协议：** Modbus RTU over TCP（含 CRC16，无 MBAP Header）  
> **连接方式：** ⚠️ **反向连接** — NT1-B 主动连接到 SSLAB 后端（后端作为 TCP Server 监听 8887 端口）

---

## 一、硬件说明

亿佰特 NT1-B 是一款串口转以太网模块，用于将 Modbus RTU 指令通过 TCP 传递给学生台低压电源（各组独立电源，共 4 组 A/B/C/D）。

| 控制变量 | 功能 |
|---------|------|
| `LowXSTB` | 将教师台当前参数同步广播到所有学生台 |

---

## 二、连接架构

```
SSLAB 后端 (192.168.0.x)          亿佰特 NT1-B (192.168.0.12)
┌─────────────────────────┐        ┌──────────────────────────┐
│  TCP Server             │◄──────│  TCP Client              │
│  监听 0.0.0.0:8887      │       │  主动连接到后端 8887      │
│  (StudentSyncServer)    │       │  串口侧连接学生台电源     │
└─────────────────────────┘        └──────────────────────────┘
        ↑ 后端向此连接写入 Modbus RTU 帧
```

> ⚠️ **与其他设备不同**：后端不主动连接 NT1-B，而是等待 NT1-B 来连接，连接建立后保持长连接，由后端在需要时写入命令。

---

## 三、通信协议

### Modbus RTU 帧结构（同 D3，含 CRC16）

**开启帧（写 4 个寄存器，功能码 0x10）：**
```
┌────────┬──────┬─────────┬──────────┬───────────┬─────────────────────────────────┬───────┐
│ Slave  │ Func │ Start   │ Quantity │ ByteCount │ Data (8 bytes)                  │ CRC16 │
│ 1 byte │ 0x10 │ 0x0003  │ 0x0004   │ 0x08      │ [Cur H/L][Vol H/L][00 01][00 00]│ 2 B   │
└────────┴──────┴─────────┴──────────┴───────────┴─────────────────────────────────┴───────┘
```

**关闭帧（写 2 个寄存器，功能码 0x10）：**
```
┌────────┬──────┬─────────┬──────────┬───────────┬──────────────┬───────┐
│ Slave  │ Func │ Start   │ Quantity │ ByteCount │ Data (4 B)   │ CRC16 │
│ 1 byte │ 0x10 │ 0x0004  │ 0x0002   │ 0x04      │ [00 00 00 00]│ 2 B   │
└────────┴──────┴─────────┴──────────┴───────────┴──────────────┴───────┘
```

---

## 四、从机地址（Slave Address）与分组映射

NT1-B 串口侧连接多台学生电源，通过 Slave 地址区分：

| 分组 | DC 模式地址 | AC 模式地址 | 说明 |
|------|-----------|-----------|------|
| A 组 | `0xA1` | `0xA2` | A 组全部学生台 |
| B 组 | `0xB1` | `0xB2` | B 组全部学生台 |
| C 组 | `0xC1` | `0xC2` | C 组全部学生台 |
| D 组 | `0xD1` | `0xD2` | D 组全部学生台 |

**`LowXSTB`（全组同步）使用 A1 或 A2 广播：**
```python
slave_a = 0xA2 if is_ac else 0xA1
cmd = student_sync_cmd(slave_a, bool(val), is_ac, volts_int, amps_int)
```

---

## 五、完整帧示例

### 示例：A1（DC），12.5V，2.5A，开启

- Slave = `0xA1`
- 电流 = 2500 = `0x09C4`
- 电压 = 1250 = `0x04E2`

**PDU（CRC 前，共 13 字节）：**
```
A1 10 00 03 00 04 08  09 C4  04 E2  00 01  00 00
```
加 CRC16-Modbus（小端）后完整帧共 15 字节。

参考已知正确帧（A2 组开启）：
```
A2 10 00 03 00 04 08 09 C4 03 52 00 01 00 00 FC 9E
```
- `03 52` = 850 = 8.5V（旧测试值）
- `FC 9E` = CRC16

### 示例：A1，关闭

```
A1 10 00 04 00 02 04  00 00  00 00  [CRC16]
```

---

## 六、数值换算规则

与 D3 教师端电源相同：

| 参数 | Web 输入 | 协议值 | 换算公式 |
|------|---------|-------|---------|
| 电压（`LowDYSZ`） | 12.5 V | 1250 | `int(V × 100)` |
| 电流（`LowDLSZ`） | 2.5 A | 2500 | `int(A × 1000)` |

---

## 七、API 调用方式

### 全组同步开启（LowXSTB）
```bash
# 前提：LowDYSZ / LowDLSZ / LowDC_AC 已设置
curl -X POST http://localhost:1880/ctrl/LowXSTB \
  -H "Content-Type: application/json" \
  -d '{"value": true}'
```

### 全组同步关闭
```bash
curl -X POST http://localhost:1880/ctrl/LowXSTB \
  -H "Content-Type: application/json" \
  -d '{"value": false}'
```

---

## 八、后端 TCP Server 实现要点

```python
# server_8887.py — StudentSyncServer
# 监听 0.0.0.0:8887，等待 NT1-B 主动连接
self.server = await asyncio.start_server(
    self.handle_client, '0.0.0.0', 8887
)

# 发送命令时找到已连接的 192.168.0.12 写入
async def broadcast_sync_cmd(self, cmd: bytes, target_ip="192.168.0.12"):
    for addr, writer in self.clients.items():
        if addr[0] == target_ip:
            writer.write(cmd)
            await writer.drain()
```

---

## 九、NT1-B 配置要求

NT1-B 需在设备 Web 管理界面做如下配置：

| 配置项 | 设定值 |
|-------|-------|
| 工作模式 | TCP Client |
| 服务器 IP | SSLAB 后端 IP（如 192.168.0.100） |
| 服务器端口 | 8887 |
| 串口波特率 | 9600（或与电源匹配） |
| 串口数据位 | 8 |
| 串口停止位 | 1 |
| 串口校验 | None |

---

## 十、故障排查

| 现象 | 可能原因 | 解决方法 |
|------|---------|---------|
| 发送后无响应 | NT1-B 未连接 | 检查 NT1-B 网络配置，确认其已连接到后端 8887 |
| 日志：`Target 192.168.0.12 not connected` | NT1-B 断线 | 重启 NT1-B 模块，等待重连 |
| 学生台无输出 | Slave 地址错误 | 确认学生台电源 Slave ID 配置（A=0xA1，B=0xB1…） |
| 部分组无响应 | 总线断线 | 检查 NT1-B 串口侧 RS485 接线 |
