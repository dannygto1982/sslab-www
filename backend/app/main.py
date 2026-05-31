from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.scanner import perform_network_scan
from app.devices import queue_manager, DeviceProtocol
from app.server_8887 import student_server
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
            
    # Start the Student Sync Server (Port 8887)
    asyncio.create_task(student_server.start_server())
    
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
    return current_state

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
    
    # --- HARDWARE CONTROL LOGIC ADAPTER ---
    config_path = os.path.join(BASE_DIR, "config.json")
    
    # SIMULATION: Pressure Test Multiplier
    # To simulate 14 devices / 28 students pressure, we repeat commands.
    SIMULATION_MULTIPLIER = 14

    if device_id in ["Computer", "Lifting"]:
        conf = load_config(config_path)
        # Port 1053 Devices (Legacy or Simulator)
        mj_devs = [d for d in conf.get("devices", []) if d.get("port") == 1053]
        
        # Determine protocol key based on device_id
        # Computer -> device1 | Lifting -> device2 (as per common legacy wiring, or use motor_fwd if it's motor)
        # Based on logs: Lifting behavior maps to "device2" or "motor_fwd". 
        # Referencing PROJECT_DEV_DOC.md 1.1: 
        #   {"device1": true} -> PC
        #   {"device2": true} -> Aux
        #   {"motor_fwd": true} -> Lifting
        
        if device_id == "Computer":
             # Computer Power (Device 1)
             key = "device1"
             cmd = DeviceProtocol.legacy_json_cmd(key, bool(val))
             
        elif device_id == "Lifting":
             # Support Up/Down/Stop
             # Values: True/'up' => UP, False/'down' => DOWN, 'stop' => STOP
             cmd_str = str(val).lower() if val is not None else ""
             
             if cmd_str == 'stop':
                 # Send both False to stop
                 cmd = json.dumps({"motor_fwd": False, "motor_bwd": False}).encode('utf-8') + b'\n'
             elif val is True or cmd_str in ['up', '1', 'on', 'true']:
                 cmd = DeviceProtocol.legacy_json_cmd("motor_fwd", True)
             else:
                 # Default to Down
                 cmd = DeviceProtocol.legacy_json_cmd("motor_bwd", True)

        # Optimization: Send to fixed range 192.168.0.100-130 as per user requirement
        # Send 2 set of commands (Same logic as LowXSTB)
        target_ips = [f"192.168.0.{i}" for i in range(100, 131)]
        
        # Send Twice
        for _ in range(2):
            for ip in target_ips:
                await queue_manager.add_task(ip, 1053, cmd)

        # Legacy simulation code removed to favor robust range broadcast
        # Logging for debug
        print(f"[1053_BROADCAST] Sent {device_id} command to {len(target_ips)} IPs (100-130) (x2 passes)")
    

    # --- GROUP A/B/C/D SWITCHES & HIGH VOLTAGE (Port 8234) ---
    elif device_id in ["XS_A", "XS_B", "XS_C", "XS_D", "HighKZ", "HighXZ", "HighCurrent", "BBLampKZ", "CRLampKZ", "PowerCZ"]:
        # Mapped to Device D (Port 8234)
        conf = load_config(config_path)
        devs_8234 = [d for d in conf.get("devices", []) if d.get("port") == 8234]

        # FORCE FIX: 192.168.0.7 must be included for 8234 control as per user requirement
        found_fixed = False
        for d in devs_8234:
             if d.get("ip") == "192.168.0.7":
                 found_fixed = True
                 break
        if not found_fixed:
             # Add fixed target
             devs_8234.append({"ip": "192.168.0.7", "port": 8234, "type": "fixed_8234"})

        reg_addr = 0x0000
        # Doc 1.2 Mappings - UPDATED based on Node-RED Archived Flow Analysis
        # Source: archived_v1/flows_modified_delay.json
        if device_id == "HighCurrent": reg_addr = 0x0000 
        elif device_id == "XS_D": reg_addr = 0x0001
        elif device_id == "XS_C": reg_addr = 0x0002
        elif device_id == "XS_B": reg_addr = 0x0003
        elif device_id == "XS_A": reg_addr = 0x0004
        elif device_id == "HighXZ": reg_addr = 0x0006  # HV Select
        elif device_id == "HighKZ": reg_addr = 0x0007  # HV Main (Confirmed by user also related to PFKZ/Exhaust logic context)
        elif device_id == "PowerCZ": reg_addr = 0x0005 # Power Socket (Mapped to Channel 6)
        elif device_id == "BBLampKZ": reg_addr = 0x0008 
        elif device_id == "CRLampKZ": reg_addr = 0x0009 
        
        print(f"[DEBUG_8234] ID={device_id} -> Addr={reg_addr} Val={val}")
        cmd = DeviceProtocol.groups_modbus_tcp_cmd(reg_addr, 1 if val else 0)

        
        for dev in devs_8234:
            await queue_manager.add_task(dev["ip"], 8234, cmd)

    # --- TEACHER POWER (Port 8888) ---
    elif device_id in ["LowKZ", "LowDYSZ", "LowDLSZ", "LowDC_AC"]:
        # Only send command if LowKZ is ON, OR if the trigger is LowKZ itself (turning ON/OFF)
        
        # Current switch state from updated state
        power_on = bool(current_state.get("LowKZ", False))
        
        # Condition to send:
        # 1. If LowKZ changed (device_id == "LowKZ") -> Always send (ON or OFF)
        # 2. If Param changed -> Only send if Power is currently ON.
        
        should_send = False
        if device_id == "LowKZ":
            should_send = True
        elif power_on:
             should_send = True
             
        if should_send:
            # Get State Params
            is_ac = (current_state.get("LowDC_AC", 0) == 1) # 1=AC, 0=DC
            
            # 1. Voltage Parsing (x100)
            # Log: {LowDYSZ: 10} -> 10V -> 1000
            raw_volts = current_state.get("LowDYSZ", 0)
            try:
                # Handle empty string or None
                if raw_volts == "": raw_volts = 0
                volts_int = int(float(raw_volts) * 100)
            except:
                volts_int = 0
                
            # 2. Current Parsing (x1000, Default 2.5A)
            # LowDLSZ (Current Setting). If empty/0 => 2.5A
            raw_amps = current_state.get("LowDLSZ", 2.5)
            try:
                 if raw_amps == "": raw_amps = 2.5
                 amps_float = float(raw_amps)
                 if amps_float <= 0: amps_float = 2.5
                 amps_int = int(amps_float * 1000)
            except:
                 amps_int = 2500 # Default 2.5A
                
            # Mapping LowKZ to Teacher Power Output
            # User requirement: FIXED IP 192.168.0.211 (NO Scanning, NO Config file)
            devs_8888 = [{"ip": "192.168.0.211", "port": 8888, "type": "final_fixed"}]
            
            print(f"[TEACHER_PWR] Send: ON={power_on} V={volts_int/100:.1f}V I={amps_int/1000:.1f}A AC={is_ac}")
            cmd = DeviceProtocol.teacher_power_cmd(power_on, volts_int, amps_int, is_ac)
            
            for dev in devs_8888:
                await queue_manager.add_task(dev["ip"], 8888, cmd)

    # --- STUDENT SYNC LOW POWER (Port 8887) ---
    elif device_id == "LowXSTB":
        # Group Sync Broadcast
        # Logic: Read Teacher Params -> Send via Server 8887 to 192.168.0.12
        
        is_ac = (current_state.get("LowDC_AC", 0) == 1)
        
        # Voltage
        raw_volts = current_state.get("LowDYSZ", 0)
        try:
            volts_int = int(float(raw_volts) * 100)
        except:
            volts_int = 0
            
        # Current
        raw_amps = current_state.get("LowDLSZ", 2.0)
        try:
             amps_float = float(raw_amps)
             if amps_float <= 0: amps_float = 2.0
             amps_int = int(amps_float * 1000)
        except:
             amps_int = 2000

        # Group A Slate ID: 0xA1 (DC) or 0xA2 (AC)
        # Force A1/A2 protocol for all students in range
        slave_a = 0xA2 if is_ac else 0xA1
        cmd = DeviceProtocol.student_sync_cmd(slave_a, bool(val), is_ac, volts_int, amps_int)

        # Send via Server 8887 to connected 192.168.0.12
        await student_server.broadcast_sync_cmd(cmd, "192.168.0.12")


    elif device_id in ["XS_A", "XS_B", "XS_C", "XS_D"]:
        target_group = device_id.split("_")[1] # A, B, C, D
        conf = load_config(config_path)
        
        # New Logic: Port 8887 (Device C) is the Sync Controller for ALL groups.
        # We find valid Sync devices (port 8887) and send the command with the correct Slave ID.
        sync_devs = [d for d in conf.get("devices", []) if d.get("port") == 8887]
        
        # Map Group to Slave ID (Logic from Doc 1.4)
        addr_map = {'A': 0xA1, 'B': 0xB1, 'C': 0xC1, 'D': 0xD1}
        modbus_addr = addr_map.get(target_group, 0xA1)
        
        cmd = DeviceProtocol.student_sync_cmd(modbus_addr, bool(val))
        
        print(f"[GROUP] {target_group} -> Found {len(sync_devs)} sync controllers. Sending ID {hex(modbus_addr)}")
        for dev in sync_devs:
            await queue_manager.add_task(dev["ip"], 8887, cmd)
    
    
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
