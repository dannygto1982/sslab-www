# SSLAB 设备协议测试文档

> 网段：`192.168.0.x`  
> 工具推荐：`nc`（netcat）、`socat`、Modbus Poll、Packet Sender  

---

## 1. 教师电源  `192.168.0.211:8888`

**协议**：Modbus RTU over TCP（无 MBAP Header，原始 RTU 帧直接走 TCP）  
**响应**：设备回 Echo 帧（功能码 0x10 ACK，6 字节）

### Slave 地址

| 模式 | Slave ID |
|------|----------|
| DC   | `0xA1`   |
| AC   | `0xA2`   |

### 寄存器映射

| 寄存器 | 含义 | 单位 |
|--------|------|------|
| 0x0003 | 电流上限 | 0.001A（2500 = 2.5A）|
| 0x0004 | 电压设定 | 0.01V（1200 = 12.00V，850 = 8.50V）|
| 0x0005 | 使能控制 | 1=ON，0=OFF |

### 测试帧

```
# DC ON  (12.00V / 2.5A)
A1 10 00 03 00 04 08 09 C4 04 B0 00 01 00 00 46 3E

# DC OFF
A1 10 00 04 00 02 04 00 00 00 00 F0 5E

# AC ON  (12.00V / 2.5A)
A2 10 00 03 00 04 08 09 C4 04 B0 00 01 00 00 05 3F

# AC OFF
A2 10 00 04 00 02 04 00 00 00 00 FF 1A
```

**帧结构（ON 为例）**：
```
A1        ← Slave ID (DC=A1, AC=A2)
10        ← Func 0x10 Write Multiple Registers
00 03     ← 起始寄存器 0x0003
00 04     ← 寄存器数量 4
08        ← 数据字节数 8
09 C4     ← Reg3: 电流 2500 = 0x09C4
04 B0     ← Reg4: 电压 1200 = 0x04B0
00 01     ← Reg5: 使能 ON
00 00     ← Reg6: 预留
46 3E     ← CRC16-Modbus (Little-Endian)
```

**nc 测试**：
```bash
echo -ne '\xA1\x10\x00\x03\x00\x04\x08\x09\xC4\x04\xB0\x00\x01\x00\x00\x46\x3E' | nc 192.168.0.211 8888 | xxd
```

---

## 2. USR-IO808  `192.168.0.7:8234`

**协议**：Modbus TCP（标准 MBAP Header + PDU，无 CRC）  
**响应**：设备回 Modbus TCP ACK（12 字节）

### 帧结构

```
00 01     ← Transaction ID
00 00     ← Protocol ID (固定 0x0000)
00 06     ← 剩余长度 6
01        ← Unit ID (固定 0x01)
06        ← Func 0x06 Write Single Register
00 00     ← 寄存器地址 (0-based)
00 01     ← 写入值
```

### 测试帧

```
# 写 Reg0 = 1 (输出1 ON)
00 01 00 00 00 06 01 06 00 00 00 01

# 写 Reg0 = 0 (输出1 OFF)
00 01 00 00 00 06 01 06 00 00 00 00

# 写 Reg1 = 1 (输出2 ON)
00 01 00 00 00 06 01 06 00 01 00 01

# 写 Reg1 = 0 (输出2 OFF)
00 01 00 00 00 06 01 06 00 01 00 00
```

**nc 测试**：
```bash
echo -ne '\x00\x01\x00\x00\x00\x06\x01\x06\x00\x00\x00\x01' | nc 192.168.0.7 8234 | xxd
```

---

## 3. 学生同步端  `192.168.0.x:8887`

**角色**：**APP 是 TCP Server（监听 8887）**，学生设备主动连入  
**协议**：Modbus RTU over TCP（同 Port 8888，无 MBAP Header）  
**无需主动连接**，通过 SyncServer 获取已连接客户端列表

### Slave 地址（各组）

| 组 | DC Slave | AC Slave |
|----|----------|----------|
| A  | `0xA1`   | `0xA2`   |
| B  | `0xB1`   | `0xB2`   |
| C  | `0xC1`   | `0xC2`   |
| D  | `0xD1`   | `0xD2`   |

### 测试帧（Group-A）

```
# Group-A DC ON  (8.50V / 2.5A) — 参考包
A1 10 00 03 00 04 08 09 C4 03 52 00 01 00 00 BF 9F

# Group-A DC OFF
A1 10 00 04 00 02 04 00 00 00 00 F0 5E

# Group-A AC ON  (8.50V / 2.5A)
A2 10 00 03 00 04 08 09 C4 03 52 00 01 00 00 FC 9E

# Group-A AC OFF
A2 10 00 04 00 02 04 00 00 00 00 FF 1A
```

> 电压字段：850 (0x0352) = 8.50V，1200 (0x04B0) = 12.00V

**模拟学生设备连入 APP（从 Android 调试）**：
```bash
nc <APP_IP> 8887
# 连上后 APP 会将其列为 client，发送上述帧即可触发控制
```

---

## 4. 升降台 / 电脑桌  `192.168.0.100~200:1053`

**协议**：Legacy JSON over TCP，每条指令以 `\n` 结尾  
**扫描范围**：`192.168.0.100` ~ `192.168.0.200`（TCP connect 探测）

### 测试帧

```json
{"lift_up": true}\n
{"lift_down": true}\n
{"lift_stop": true}\n
{"power": true}\n
{"power": false}\n
```

**nc 测试（假设 IP 为 192.168.0.120）**：
```bash
echo '{"lift_up": true}' | nc 192.168.0.120 1053
echo '{"power": true}'   | nc 192.168.0.120 1053
echo '{"lift_stop": true}' | nc 192.168.0.120 1053
```

---

## 5. 鸣驹继电器（Modbus RTU，接在串口/TCP转换）

**协议**：Modbus RTU，Func 0x05 Write Single Coil

### 测试帧

```
# 路1 ON  (Coil 0 = 0xFF00)
01 05 00 00 FF 00 8C 3A

# 路1 OFF (Coil 0 = 0x0000)
01 05 00 00 00 00 CD CA

# 路2 ON  (Coil 1)
01 05 00 01 FF 00 DD FA

# 路2 OFF
01 05 00 01 00 00 9C 0A
```

**帧结构**：
```
01     ← Slave 0x01
05     ← Func 0x05 Write Single Coil
00 00  ← Coil 地址 (0-based，路1=0x0000)
FF 00  ← ON=0xFF00 / OFF=0x0000
8C 3A  ← CRC16-Modbus
```

---

## 快速测试脚本（Windows PowerShell）

```powershell
# 测试 8888 教师电源 DC ON
$bytes = [byte[]](0xA1,0x10,0x00,0x03,0x00,0x04,0x08,0x09,0xC4,0x04,0xB0,0x00,0x01,0x00,0x00,0x46,0x3E)
$tcp = New-Object System.Net.Sockets.TcpClient("192.168.0.211", 8888)
$stream = $tcp.GetStream()
$stream.Write($bytes, 0, $bytes.Length)
$buf = New-Object byte[] 256; $n = $stream.Read($buf, 0, 256)
[BitConverter]::ToString($buf[0..($n-1)]); $tcp.Close()

# 测试 8234 Reg0=1
$bytes = [byte[]](0x00,0x01,0x00,0x00,0x00,0x06,0x01,0x06,0x00,0x00,0x00,0x01)
$tcp = New-Object System.Net.Sockets.TcpClient("192.168.0.7", 8234)
$stream = $tcp.GetStream()
$stream.Write($bytes, 0, $bytes.Length)
$buf = New-Object byte[] 256; $n = $stream.Read($buf, 0, 256)
[BitConverter]::ToString($buf[0..($n-1)]); $tcp.Close()

# 测试 1053 升降台
$tcp = New-Object System.Net.Sockets.TcpClient("192.168.0.120", 1053)
$stream = $tcp.GetStream()
$data = [System.Text.Encoding]::UTF8.GetBytes("{`"lift_up`": true}`n")
$stream.Write($data, 0, $data.Length); $tcp.Close()
```
