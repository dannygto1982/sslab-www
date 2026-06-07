# SSLAB 设备控制文档索引

> 本目录包含系统中每台硬件设备的独立对接说明。  
> 所有命令均通过后端 FastAPI（`http://localhost:1880`）发出，设备位于局域网 `192.168.0.0/24`。

---

## 设备总览

| 编号 | 设备型号 | IP 地址 | TCP 端口 | 协议 | 说明文档 |
|------|---------|---------|---------|------|---------|
| D1 | 鸣驹 MJ-E1S1-X-P | 192.168.0.100–130（广播） | **1053** | Legacy JSON / TCP | [D1_MJ-E1S1_Port1053.md](D1_MJ-E1S1_Port1053.md) |
| D2 | USR-IO808 综合控制器 | 192.168.0.7（固定） | **8234** | Modbus TCP | [D2_USR-IO808_Port8234.md](D2_USR-IO808_Port8234.md) |
| D3 | 教师端低压电源 | 192.168.0.211（固定） | **8888** | Modbus RTU over TCP | [D3_TeacherPower_Port8888.md](D3_TeacherPower_Port8888.md) |
| D4 | 亿佰特 NT1-B 学生同步器 | 192.168.0.12（固定） | **8887** | Modbus RTU over TCP（反向连接） | [D4_NT1-B_Port8887.md](D4_NT1-B_Port8887.md) |

---

## 控制变量与设备映射

| 前端变量 | 对应设备 | 端口 |
|---------|---------|------|
| `Computer` | 鸣驹 MJ-E1S1（PC 电源） | 1053 |
| `Lifting` | 鸣驹 MJ-E1S1（升降电机） | 1053 |
| `XS_A / XS_B / XS_C / XS_D` | USR-IO808 + 亿佰特 NT1-B | 8234 + 8887 |
| `HighKZ / HighXZ / HighCurrent` | USR-IO808 | 8234 |
| `BBLampKZ / CRLampKZ / PowerCZ` | USR-IO808 | 8234 |
| `LowKZ / LowDYSZ / LowDLSZ / LowDC_AC` | 教师端低压电源 | 8888 |
| `LowXSTB` | 亿佰特 NT1-B（广播同步） | 8887 |

---

## 网络扫描端口

系统启动后自动扫描 `192.168.0.0/24`，发现以下端口后记入 `config.json`：

| 端口 | 设备类型标记 |
|------|------------|
| 8887 | `student` |
| 1053 | `control` |
| 8888 | `teacher` |
| 8234 | `device_8234` |

---

*最后更新：2026-06-04*
