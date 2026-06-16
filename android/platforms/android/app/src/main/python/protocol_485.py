"""
485 协议帧构建器 — JSON-RPC 格式（与 ESP8266 固件 v1.0.0+ 协议对齐）

固件支持的 method:
  controlComputer → {"status": bool}          → GPIO14 (电脑开关)
  controlLamp      → {"status": bool, "brightness": int} → GPIO5 (灯光)
  controlLifting   → {"value": "up"/"down"/"stop"}       → GPIO12/13 (升降)
  setGroup         → {"studentGroup": "A"/"B"/"C"/"D"}    → 分组设置
  ping             → {}                                    → 心跳检测

帧格式: JSON + '\n' (newline-terminated), 9600-8N1, RS485
"""
import json
import struct
from typing import Dict, Any

from devices import DeviceProtocol, crc16_modbus


def _json_frame(method: str, params: Dict[str, Any], request_id: str = "") -> bytes:
    """构建标准 JSON-RPC 请求帧"""
    payload = {"method": method, "params": params}
    if request_id:
        payload["requestId"] = request_id
    return json.dumps(payload, ensure_ascii=False).encode("utf-8") + b"\n"


def build_computer_frame(is_on: bool) -> bytes:
    """电脑开关控制 → controlComputer"""
    return _json_frame("controlComputer", {"status": bool(is_on)}, "computer")


def build_lifting_frame(value: Any) -> bytes:
    """升降控制 → controlLifting"""
    s = str(value).lower() if value is not None else ""
    if s in ["up", "1", "on", "true"]:
        lift_val = "up"
    elif s in ["down", "0", "off", "false"]:
        lift_val = "down"
    else:
        lift_val = "stop"
    return _json_frame("controlLifting", {"value": lift_val}, "lifting")


def build_lamp_frame(is_on: bool, brightness: int = 100) -> bytes:
    """灯光控制 → controlLamp"""
    return _json_frame("controlLamp", {"status": bool(is_on), "brightness": brightness}, "lamp")


def build_ping_frame() -> bytes:
    """心跳检测 → ping"""
    return _json_frame("ping", {}, "ping")


def build_lowxstb_frame(state: Dict[str, Any], sync_on: bool) -> bytes:
    """低压学生同步（保持 Modbus RTU 格式不变）"""
    is_ac = state.get("LowDC_AC", 0) == 1
    raw_volts = state.get("LowDYSZ", 0)
    raw_amps = state.get("LowDLSZ", 2.0)

    try:
        volts_int = int(float(raw_volts) * 100)
    except Exception:
        volts_int = 0

    try:
        amps_float = float(raw_amps)
        if amps_float <= 0:
            amps_float = 2.0
        amps_int = int(amps_float * 1000)
    except Exception:
        amps_int = 2000

    slave = 0xA2 if is_ac else 0xA1
    return DeviceProtocol.student_sync_cmd(slave, bool(sync_on), is_ac, volts_int, amps_int)


def build_vfd_power_frame(is_on: bool, slave_id: int, reg_power: int) -> bytes:
    """变频器启停 → Modbus RTU"""
    value = 0x0001 if is_on else 0x0000
    pdu = struct.pack(">BBHH", int(slave_id) & 0xFF, 0x06, int(reg_power) & 0xFFFF, value)
    return pdu + crc16_modbus(pdu)


def build_vfd_speed_frame(speed: Any, slave_id: int, reg_speed: int, speed_map: Dict[str, int]) -> bytes:
    """变频器频率 → Modbus RTU"""
    key = str(speed)
    if key not in speed_map:
        try:
            key = str(int(float(speed)))
        except Exception:
            key = "1"
    value = int(speed_map.get(key, speed_map.get("1", 1))) & 0xFFFF
    pdu = struct.pack(">BBHH", int(slave_id) & 0xFF, 0x06, int(reg_speed) & 0xFFFF, value)
    return pdu + crc16_modbus(pdu)
