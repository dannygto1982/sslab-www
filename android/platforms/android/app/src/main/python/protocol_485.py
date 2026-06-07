import json
import struct
from typing import Dict, Any

from devices import DeviceProtocol, crc16_modbus


def build_computer_frame(is_on: bool) -> bytes:
    # Keep legacy JSON semantics while moving transport to RS485.
    return DeviceProtocol.legacy_json_cmd("device1", bool(is_on))


def build_lifting_frame(value: Any) -> bytes:
    s = str(value).lower() if value is not None else ""
    if s == "stop":
        payload = {"motor_fwd": False, "motor_bwd": False}
    elif value is True or s in ["up", "1", "on", "true"]:
        payload = {"motor_fwd": True, "motor_bwd": False}
    else:
        payload = {"motor_fwd": False, "motor_bwd": True}
    return json.dumps(payload).encode("utf-8") + b"\n"


def build_lowxstb_frame(state: Dict[str, Any], sync_on: bool) -> bytes:
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
    # Modbus RTU: Write Single Register (0x06)
    value = 0x0001 if is_on else 0x0000
    pdu = struct.pack(">BBHH", int(slave_id) & 0xFF, 0x06, int(reg_power) & 0xFFFF, value)
    return pdu + crc16_modbus(pdu)


def build_vfd_speed_frame(speed: Any, slave_id: int, reg_speed: int, speed_map: Dict[str, int]) -> bytes:
    # Modbus RTU: Write Single Register (0x06)
    key = str(speed)
    if key not in speed_map:
        try:
            key = str(int(float(speed)))
        except Exception:
            key = "1"

    value = int(speed_map.get(key, speed_map.get("1", 1))) & 0xFFFF
    pdu = struct.pack(">BBHH", int(slave_id) & 0xFF, 0x06, int(reg_speed) & 0xFFFF, value)
    return pdu + crc16_modbus(pdu)
