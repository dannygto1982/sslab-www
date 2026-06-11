from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.scanner import perform_network_scan
from app.devices import queue_manager, DeviceProtocol
from app.rs485 import rs485_manager
from app.config_manager import ConfigManager
from app.protocol_485 import (
    build_computer_frame,
    build_lifting_frame,
    build_lowxstb_frame,
    build_vfd_power_frame,
    build_vfd_speed_frame,
)
from app.handlers import (
    handle_computer_lifting,
    handle_group_switches,
    handle_teacher_power,
    handle_low_xstb,
    handle_vfd,
)
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import asyncio
import json
import os
import sys

app = FastAPI(title="Control System API")

# Path Configuration
if getattr(sys, 'frozen', False):
    # Running in PyInstaller Bundle
    if hasattr(sys, '_MEIPASS'):
        # OneFile mode
        Bundle_Dir = sys._MEIPASS
    else:
        # OneDir mode (PyInstaller 6+ uses _internal by default)
        exe_dir = os.path.dirname(sys.executable)
        internal_dir = os.path.join(exe_dir, '_internal')
        if os.path.exists(internal_dir):
             Bundle_Dir = internal_dir
        else:
             Bundle_Dir = exe_dir
    
    # Frontend is bundled inside
    FRONTEND_DIR = os.path.join(Bundle_Dir, "frontend")
    
    # Config/Backend dir: Prefer directory next to Executable for Config
    BASE_DIR = os.path.dirname(sys.executable)
else:
    # Running in Dev
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__))) # back to backend/
    ROOT_DIR = os.path.dirname(BASE_DIR) # back to www/
    FRONTEND_DIR = os.path.join(ROOT_DIR, "frontend")

# Ensure frontend dir exists to avoid errors on startup
if not os.path.exists(FRONTEND_DIR):
    os.makedirs(FRONTEND_DIR, exist_ok=True)
    os.makedirs(os.path.join(FRONTEND_DIR, "css"), exist_ok=True)
    os.makedirs(os.path.join(FRONTEND_DIR, "js"), exist_ok=True)

# State Storage (In-Memory)
current_state: Dict[str, Any] = {
    "LowKZ": False,
    "HighKZ": False,
    "HighCurrent": False,
    "Computer": False, # PC
    "Lifting": False,  # Lift
    "XS_A": False,
    "XS_B": False,
    "XS_C": False,
    "XS_D": False,
    "GSKZ": False,
    "PFKZ": False,
    "BBLampKZ": False,
    "CRLampKZ": False,
    "CLQQ": False,
    "CLHQ": False,
    "VFD_Power": False,
    "VFD_Speed": 1,
    "LowDYSZ": 0,
    "LowDLSZ": 2.0,
    "LowXSTB": False,
    "LowDC_AC": 0
}


# Initialise ConfigManager singleton (sync, safe before event loop)
_cfg_mgr = ConfigManager.init(BASE_DIR)


def load_runtime_config() -> Dict[str, Any]:
    return _cfg_mgr.full()

@app.on_event("startup")
async def startup_event():
    print("Starting background tasks...")
    # Setup callback for command results
    async def device_feedback_callback(ip: str, status: str):
        # Broadcast the result to all connected clients
        # Optimization: Only broadcast SUCCESS to avoid flooding frontend with errors from offline devices during range scan
        if status == "success": # or status == "error":
            await manager.broadcast(json.dumps({
                "type": "cmd_result",
                "ip": ip,
                "status": status
            }))

    # Start the staggered queue worker
    queue_manager.status_callback = device_feedback_callback
    # Tuning: 
    # Batch=2 (Conservative concurrency to prevent router packet loss)
    # Delay=50ms (Launch next batch quickly)
    asyncio.create_task(queue_manager.start_worker(batch_size=2, delay_ms=50))

    rs485_manager.configure(_cfg_mgr.get_section("rs485", {}))

    # Start Periodic Auto-Scan Task (Every 60s)
    async def periodic_scan():
        # Initial wait to let server start
        await asyncio.sleep(2)
        print("[AutoScan] Initial scan started...")
        await perform_network_scan()
        
        while queue_manager.is_running:
            await asyncio.sleep(60)
            if not queue_manager.is_running: break
            print("[AutoScan] Periodic scan started...")
            await perform_network_scan()
            
    asyncio.create_task(periodic_scan())

@app.on_event("shutdown")
async def shutdown_event():
    print("Shutting down background tasks...")
    queue_manager.is_running = False

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Static Files
app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")
if os.path.exists(os.path.join(FRONTEND_DIR, "images")):
    app.mount("/images", StaticFiles(directory=os.path.join(FRONTEND_DIR, "images")), name="images")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    # Return a 1x1 transparent user_provided icon or a placeholder
    return HTMLResponse("")


def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        return {}
    for encoding in ["utf-8", "utf-16", "gbk", "cp1252"]:
        try:
            with open(path, "r", encoding=encoding) as f:
                return json.load(f)
        except Exception:
            continue
    return {}

@app.get("/", response_class=HTMLResponse)
async def read_root():
    idx_path = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(idx_path):
        for encoding in ["utf-8", "utf-16", "gbk", "cp1252"]:
            try:
                with open(idx_path, "r", encoding=encoding) as f:
                    return f.read()
            except Exception:
                continue
        # Fallback
        with open(idx_path, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
            
    return "Frontend not found. Please place index.html in frontend folder."

@app.get("/req")
async def get_state_endpoint():
    payload = dict(current_state)
    payload["RS485_Status"] = rs485_manager.status()
    return payload

@app.get("/api/scan")
async def scan_network_endpoint(clear: bool = False, ports: str = None):
    """
    Trigger a network scan
    If clear=true, it wipes the existing config before scanning.
    If ports is provided (comma separated), scans only those ports.
    """
    print(f"[API] Scan requested. Clear existing cache: {clear}. Ports: {ports}")
    
    target_ports = None
    if ports:
        try:
            target_ports = [int(p) for p in ports.split(",")]
        except ValueError:
            pass # Ignore invalid format

    results = await perform_network_scan(clear_cache=clear, target_ports=target_ports)
    # Broadcast update via WS
    await manager.broadcast(json.dumps({
        "type": "scan_complete",
        "data": results,
        "count": len(results)
    }))
    return {"status": "ok", "count": len(results), "devices": results}

@app.get("/api/devices")
async def get_devices_endpoint():
    """Get current device list"""
    config_path = os.path.join(BASE_DIR, "config.json")
    conf = load_config(config_path)
    return conf.get("devices", [])

@app.get("/api/rs485/log")
async def rs485_log_endpoint(limit: int = 50):
    """Return recent RS485 transaction log entries (newest first)."""
    limit = max(1, min(limit, 100))
    return {
        "status": rs485_manager.status(),
        "log": rs485_manager.get_log(limit),
    }


# ─────────────────────────────────────────────────────────────
# Admin API  (/api/admin/*)
# ─────────────────────────────────────────────────────────────

@app.get("/api/admin/config")
async def admin_get_config():
    """Return full config.json contents."""
    return _cfg_mgr.full()


@app.put("/api/admin/config")
async def admin_put_config(body: Dict[str, Any]):
    """Overwrite the entire config.json. Returns saved config."""
    for key, val in body.items():
        _cfg_mgr.set_section(key, val)
    rs485_manager.configure(_cfg_mgr.get_section("rs485", {}))
    return {"ok": True, "config": _cfg_mgr.full()}


@app.get("/api/admin/rs485")
async def admin_get_rs485():
    """Return rs485 config section + live status."""
    return {
        "config": _cfg_mgr.get_section("rs485", {}),
        "status": rs485_manager.status(),
    }


@app.put("/api/admin/rs485")
async def admin_put_rs485(body: Dict[str, Any]):
    """Update rs485 section (merged). Hot-applies to rs485_manager."""
    _cfg_mgr.update_section("rs485", body)
    rs485_manager.configure(_cfg_mgr.get_section("rs485", {}))
    return {"ok": True, "rs485": _cfg_mgr.get_section("rs485", {})}


@app.get("/api/admin/devices")
async def admin_get_devices():
    """Return devices list from config.json."""
    return _cfg_mgr.get_section("devices", [])


@app.post("/api/admin/devices")
async def admin_add_device(body: Dict[str, Any]):
    """Add a new device entry."""
    devices = list(_cfg_mgr.get_section("devices", []))
    devices.append(body)
    _cfg_mgr.set_section("devices", devices)
    return {"ok": True, "devices": devices}


@app.put("/api/admin/devices/{idx}")
async def admin_update_device(idx: int, body: Dict[str, Any]):
    """Update device at index *idx*."""
    devices = list(_cfg_mgr.get_section("devices", []))
    if idx < 0 or idx >= len(devices):
        return JSONResponse(status_code=404, content={"error": "index out of range"})
    devices[idx] = body
    _cfg_mgr.set_section("devices", devices)
    return {"ok": True, "devices": devices}


@app.delete("/api/admin/devices/{idx}")
async def admin_delete_device(idx: int):
    """Delete device at index *idx*."""
    devices = list(_cfg_mgr.get_section("devices", []))
    if idx < 0 or idx >= len(devices):
        return JSONResponse(status_code=404, content={"error": "index out of range"})
    removed = devices.pop(idx)
    _cfg_mgr.set_section("devices", devices)
    return {"ok": True, "removed": removed, "devices": devices}


@app.post("/api/admin/reload")
async def admin_reload_config():
    """Hot-reload config.json from disk."""
    ok = _cfg_mgr.reload()
    return {"ok": ok, "loaded_at": _cfg_mgr.loaded_at}


@app.post("/api/admin/rs485/test")
async def admin_rs485_send_raw(body: Dict[str, Any]):
    """Send a raw hex frame for diagnostics. body: {hex: '...', tag: '...'}."""
    hex_str = str(body.get("hex", "")).replace(" ", "")
    tag = str(body.get("tag", "manual"))
    try:
        frame = bytes.fromhex(hex_str)
    except ValueError as e:
        return JSONResponse(status_code=400, content={"error": f"invalid hex: {e}"})
    result = await rs485_manager.send_frame(
        frame,
        expect_response=bool(body.get("expect_response", True)),
        response_timeout=float(body.get("timeout", 0.5)),
        retries=1,
        tag=tag,
    )
    return result


@app.get("/api/admin/health")
async def admin_health():
    """Check connectivity of fixed-IP devices and RS485 port."""
    import asyncio as _aio

    async def tcp_ping(ip: str, port: int, timeout: float = 1.0) -> Dict[str, Any]:
        t0 = __import__('time').monotonic()
        try:
            r, w = await _aio.wait_for(_aio.open_connection(ip, port), timeout=timeout)
            w.close()
            try:
                await w.wait_closed()
            except Exception:
                pass
            ms = round((__import__('time').monotonic() - t0) * 1000, 1)
            return {"ip": ip, "port": port, "ok": True, "ms": ms}
        except Exception as e:
            return {"ip": ip, "port": port, "ok": False, "error": str(e)}

    targets = [
        ("192.168.0.7", 8234),
        ("192.168.0.211", 8888),
        ("192.168.0.12", 8887),
    ]
    pings = await _aio.gather(*[tcp_ping(ip, p) for ip, p in targets])
    return {
        "rs485": rs485_manager.status(),
        "devices": list(pings),
        "state_keys": len(current_state),
    }


@app.get("/admin", response_class=HTMLResponse)
async def admin_page():
    """Serve the Admin UI page."""
    admin_path = os.path.join(FRONTEND_DIR, "admin.html")
    if os.path.exists(admin_path):
        with open(admin_path, "r", encoding="utf-8") as f:
            return f.read()
    return HTMLResponse("<h2>admin.html not found in frontend/</h2>", status_code=404)

@app.post("/{domain}/{device_id}")
async def control_endpoint(domain: str, device_id: str, payload: Dict[str, Any]):
    val = payload.get("value")
    if val is None:
        if payload.get("bool") is not None: val = payload.get("bool")
        elif payload.get("state") is not None: val = (payload.get("state") == 1)
    
    # Robust Boolean Parsing (Handle "false", "0" strings)
    if isinstance(val, str):
        if val.lower() in ["false", "0", "off", "no"]:
            val = False
        elif val.lower() in ["true", "1", "on", "yes"]:
            val = True
    
    current_state[device_id] = val
    print(f"[CTRL] {domain}/{device_id} -> {val}")
    
    # Load runtime config for handlers
    config = _cfg_mgr.full()
    rs485_cfg = config.get("rs485", {})
    
    if device_id in ["Computer", "Lifting"]:
        error = await handle_computer_lifting(device_id, val, current_state, rs485_cfg, queue_manager, rs485_manager)
    elif device_id in ["XS_A", "XS_B", "XS_C", "XS_D", "HighKZ", "HighXZ", "HighCurrent", "BBLampKZ", "CRLampKZ", "PowerCZ"]:
        error = await handle_group_switches(device_id, val, current_state, rs485_cfg, queue_manager, rs485_manager, config)
    elif device_id in ["LowKZ", "LowDYSZ", "LowDLSZ", "LowDC_AC"]:
        error = await handle_teacher_power(device_id, val, current_state, rs485_cfg, queue_manager, rs485_manager)
    elif device_id == "LowXSTB":
        error = await handle_low_xstb(device_id, val, current_state, rs485_cfg, queue_manager, rs485_manager)
    elif device_id in ["VFD_Power", "VFD_Speed"]:
        error = await handle_vfd(device_id, val, current_state, rs485_cfg, queue_manager, rs485_manager)
    else:
        error = None
    
    if error:
        return error
    
    return {"status": "ok", "state": current_state}


# WebSocket for status updates
class ConnectionManager:
    def __init__(self):
        self.active_connections: List[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)

    async def broadcast(self, message: str):
        for connection in self.active_connections[:]:
            try:
                await connection.send_text(message)
            except:
                self.disconnect(connection)

manager = ConnectionManager()

@app.websocket("/ws") 
async def websocket_endpoint(websocket: WebSocket):
    await manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket)
    except Exception:
        manager.disconnect(websocket)
