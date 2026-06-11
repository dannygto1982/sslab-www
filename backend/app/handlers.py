"""
Device control handlers extracted from backend/app/main.py control_endpoint.

Each handler receives:
- val: parsed control value (bool/int)
- current_state: mutable dict of all device states (updated in place)
- rs485_cfg: rs485 section from config.json
- queue_manager: StaggeredQueue singleton for TCP commands
- rs485_manager: RS485Manager singleton for RS485 commands

Returns JSONResponse on error, or None on success.
"""
import json
import asyncio
from typing import Any, Dict, Optional
from fastapi.responses import JSONResponse

from app.devices import DeviceProtocol
from app.protocol_485 import (
    build_computer_frame,
    build_lifting_frame,
    build_lowxstb_frame,
    build_vfd_power_frame,
    build_vfd_speed_frame,
)


# ─────────────────────────────────────────────
# Helper
# ─────────────────────────────────────────────

def _parse_bool(val: Any) -> bool:
    """Robust boolean parsing: handle strings, ints, bools."""
    if isinstance(val, str):
        return val.lower() not in ("false", "0", "off", "no")
    if val is None:
        return False
    return bool(val)


# ─────────────────────────────────────────────
# Computer / Lifting (RS485 primary, TCP 1053 fallback)
# ─────────────────────────────────────────────

async def handle_computer_lifting(
    device_id: str,
    val: Any,
    current_state: Dict[str, Any],
    rs485_cfg: Dict[str, Any],
    queue_manager,
    rs485_manager,
) -> Optional[JSONResponse]:
    if device_id == "Computer":
        cmd = build_computer_frame(_parse_bool(val))
    else:  # Lifting
        cmd = build_lifting_frame(val)

    rs485_on = bool(rs485_cfg.get("enabled", False))
    legacy_on = bool(rs485_cfg.get("legacy_1053_enabled", False))

    if rs485_on:
        result = await rs485_manager.send_frame(
            cmd,
            expect_response=bool(rs485_cfg.get("expect_response", False)),
            response_timeout=float(rs485_cfg.get("timeout", 0.25)),
            retries=int(rs485_cfg.get("retries", 2)),
            tag=device_id,
        )
        if not result.get("ok") and not legacy_on:
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": result.get("error", "rs485 send failed"),
                    "state": current_state,
                },
            )

    if legacy_on or not rs485_on:
        # Fallback: broadcast via legacy TCP 1053
        target_ips = [f"192.168.0.{i}" for i in range(100, 131)]
        for _ in range(2):
            for ip in target_ips:
                await queue_manager.add_task(ip, 1053, cmd)
        print(f"[FALLBACK_1053] {device_id} sent to 31 IPs x2")

    return None


# ─────────────────────────────────────────────
# Group Switches (Port 8234 via USR-IO808)
# ─────────────────────────────────────────────

# Register address mappings (Doc 1.2)
_GROUP_REG_ADDRS: Dict[str, int] = {
    "HighCurrent": 0x0000,
    "XS_D": 0x0001,
    "XS_C": 0x0002,
    "XS_B": 0x0003,
    "XS_A": 0x0004,
    "PowerCZ": 0x0005,
    "HighXZ": 0x0006,
    "HighKZ": 0x0007,
    "BBLampKZ": 0x0008,
    "CRLampKZ": 0x0009,
}

_GROUP_DEVICE_IDS = set(_GROUP_REG_ADDRS.keys())

async def handle_group_switches(
    device_id: str,
    val: Any,
    current_state: Dict[str, Any],
    rs485_cfg: Dict[str, Any],
    queue_manager,
    rs485_manager,
    conf: Dict[str, Any],
) -> Optional[JSONResponse]:
    devs_8234 = [d for d in conf.get("devices", []) if d.get("port") == 8234]

    # Force-include fixed IP 192.168.0.7 for 8234 control
    found_fixed = any(d.get("ip") == "192.168.0.7" for d in devs_8234)
    if not found_fixed:
        devs_8234.append({"ip": "192.168.0.7", "port": 8234, "type": "fixed_8234"})

    reg_addr = _GROUP_REG_ADDRS.get(device_id, 0x0000)
    print(f"[DEBUG_8234] ID={device_id} -> Addr={reg_addr} Val={val}")
    cmd = DeviceProtocol.groups_modbus_tcp_cmd(reg_addr, 1 if _parse_bool(val) else 0)

    for dev in devs_8234:
        await queue_manager.add_task(dev["ip"], 8234, cmd)

    return None


# ─────────────────────────────────────────────
# Teacher Power (Port 8888)
# ─────────────────────────────────────────────

async def handle_teacher_power(
    device_id: str,
    val: Any,
    current_state: Dict[str, Any],
    rs485_cfg: Dict[str, Any],
    queue_manager,
    rs485_manager,
) -> Optional[JSONResponse]:
    power_on = bool(current_state.get("LowKZ", False))

    # Determine if we should send
    should_send = False
    if device_id == "LowKZ":
        should_send = True
    elif power_on:
        should_send = True

    if not should_send:
        return None

    is_ac = current_state.get("LowDC_AC", 0) == 1

    # Voltage parsing (x100)
    raw_volts = current_state.get("LowDYSZ", 0)
    try:
        if raw_volts == "":
            raw_volts = 0
        volts_int = int(float(raw_volts) * 100)
    except (ValueError, TypeError):
        volts_int = 0

    # Current parsing (x1000, default 2.5A)
    raw_amps = current_state.get("LowDLSZ", 2.5)
    try:
        if raw_amps == "":
            raw_amps = 2.5
        amps_float = float(raw_amps)
        if amps_float <= 0:
            amps_float = 2.5
        amps_int = int(amps_float * 1000)
    except (ValueError, TypeError):
        amps_int = 2500

    # Fixed IP 192.168.0.211 for Teacher Power
    devs_8888 = [{"ip": "192.168.0.211", "port": 8888, "type": "final_fixed"}]

    print(
        f"[TEACHER_PWR] Send: ON={power_on} "
        f"V={volts_int / 100:.1f}V I={amps_int / 1000:.1f}A AC={is_ac}"
    )
    cmd = DeviceProtocol.teacher_power_cmd(power_on, volts_int, amps_int, is_ac)

    for dev in devs_8888:
        await queue_manager.add_task(dev["ip"], 8888, cmd)

    return None


# ─────────────────────────────────────────────
# Student Sync (LowXSTB) — RS485 primary, 8887 fallback
# ─────────────────────────────────────────────

async def handle_low_xstb(
    device_id: str,
    val: Any,
    current_state: Dict[str, Any],
    rs485_cfg: Dict[str, Any],
    queue_manager,
    rs485_manager,
) -> Optional[JSONResponse]:
    cmd = build_lowxstb_frame(current_state, _parse_bool(val))
    rs485_on = bool(rs485_cfg.get("enabled", False))
    legacy_on = bool(rs485_cfg.get("legacy_8887_enabled", False))

    if rs485_on:
        result = await rs485_manager.send_frame(
            cmd,
            expect_response=bool(rs485_cfg.get("expect_response", False)),
            response_timeout=float(rs485_cfg.get("timeout", 0.25)),
            retries=int(rs485_cfg.get("retries", 2)),
            tag="LowXSTB",
        )
        if not result.get("ok") and not legacy_on:
            return JSONResponse(
                status_code=500,
                content={
                    "status": "error",
                    "message": result.get("error", "rs485 send failed"),
                    "state": current_state,
                },
            )

    if legacy_on or not rs485_on:
        try:
            from app.server_8887 import student_server

            await student_server.broadcast_sync_cmd(cmd, "192.168.0.12")
            print("[FALLBACK_8887] LowXSTB sent via legacy TCP server")
        except Exception as _e:
            print(f"[FALLBACK_8887] failed: {_e}")

    return None


# ─────────────────────────────────────────────
# VFD (Modbus RS485)
# ─────────────────────────────────────────────

async def handle_vfd(
    device_id: str,
    val: Any,
    current_state: Dict[str, Any],
    rs485_cfg: Dict[str, Any],
    queue_manager,
    rs485_manager,
) -> Optional[JSONResponse]:
    vfd_cfg = rs485_cfg.get("vfd", {}) if isinstance(rs485_cfg, dict) else {}
    slave_id = int(vfd_cfg.get("slave_id", 1))
    reg_power = int(vfd_cfg.get("reg_power", 0x2000))
    reg_speed = int(vfd_cfg.get("reg_speed", 0x2001))
    speed_map = vfd_cfg.get("speed_map", {"1": 10, "2": 20, "3": 30})
    if not isinstance(speed_map, dict):
        speed_map = {"1": 10, "2": 20, "3": 30}

    if device_id == "VFD_Power":
        cmd = build_vfd_power_frame(_parse_bool(val), slave_id, reg_power)
    else:
        cmd = build_vfd_speed_frame(val, slave_id, reg_speed, speed_map)

    result = await rs485_manager.send_frame(
        cmd,
        expect_response=bool(rs485_cfg.get("expect_response", False)),
        response_timeout=float(rs485_cfg.get("timeout", 0.25)),
        retries=int(rs485_cfg.get("retries", 2)),
        tag=device_id,
    )
    if not result.get("ok"):
        return JSONResponse(
            status_code=500,
            content={
                "status": "error",
                "message": result.get("error", "rs485 send failed"),
                "state": current_state,
            },
        )

    return None


# ─────────────────────────────────────────────
# Dispatcher — maps device_id to handler
# ─────────────────────────────────────────────

_HANDLER_GROUPS = [
    (lambda did: did in ("Computer", "Lifting"), handle_computer_lifting),
    (lambda did: did in _GROUP_DEVICE_IDS, handle_group_switches),
    (lambda did: did in ("LowKZ", "LowDYSZ", "LowDLSZ", "LowDC_AC"), handle_teacher_power),
    (lambda did: did == "LowXSTB", handle_low_xstb),
    (lambda did: did in ("VFD_Power", "VFD_Speed"), handle_vfd),
]


async def dispatch(
    device_id: str,
    val: Any,
    current_state: Dict[str, Any],
    rs485_cfg: Dict[str, Any],
    queue_manager,
    rs485_manager,
    conf: Dict[str, Any],
) -> Optional[JSONResponse]:
    """Dispatch device control to the appropriate handler. Returns error response or None."""
    for predicate, handler in _HANDLER_GROUPS:
        if predicate(device_id):
            return await handler(
                device_id, val, current_state,
                rs485_cfg, queue_manager, rs485_manager,
                conf=conf if handler is handle_group_switches else None,
            )
    return None
