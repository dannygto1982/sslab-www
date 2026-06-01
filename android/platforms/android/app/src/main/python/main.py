from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from scanner import perform_network_scan, get_online_devices, set_sync_server
from devices import queue_manager, DeviceProtocol, CommandExecutor
from typing import List, Optional, Dict, Any
from pydantic import BaseModel
import asyncio
import json
import os
import sys
import uuid
import urllib.request
import urllib.error
import reporter

app = FastAPI(title="Control System API")


# ===== 8887 学生同步 TCP 客户�?=====
class SyncTcpClient:
    """TCP 客户端，主动连接到学生同步服�?192.168.0.12:8887"""
    def __init__(self, host: str = "192.168.0.12", port: int = 8887):
        self.host = host
        self.port = port
        self._writer = None
        self._connected = False
        self._lock = asyncio.Lock()

    async def start(self):
        asyncio.create_task(self._reconnect_loop())
        print(f"[SyncClient] Started, target={self.host}:{self.port}")

    async def _reconnect_loop(self):
        while True:
            if not self._connected:
                try:
                    reader, writer = await asyncio.wait_for(
                        asyncio.open_connection(self.host, self.port), timeout=5.0
                    )
                    self._writer = writer
                    self._connected = True
                    print(f"[SyncClient] Connected to {self.host}:{self.port}")
                    try:
                        while True:
                            data = await reader.read(1024)
                            if not data:
                                break
                    except Exception:
                        pass
                    self._connected = False
                    self._writer = None
                    print(f"[SyncClient] Disconnected from {self.host}:{self.port}")
                except Exception as e:
                    self._connected = False
                    self._writer = None
                    print(f"[SyncClient] Connect failed: {e}")
            await asyncio.sleep(5)

    async def send(self, data: bytes) -> bool:
        if not self._connected or not self._writer:
            print("[SyncClient] Not connected, cannot send")
            return False
        async with self._lock:
            try:
                self._writer.write(data)
                await self._writer.drain()
                hex_str = ' '.join(f'{b:02X}' for b in data)
                print(f"[SyncClient] Sent {len(data)}B to {self.host}:{self.port} | {hex_str}")
                return True
            except Exception as e:
                print(f"[SyncClient] Send failed: {e}")
                self._connected = False
                self._writer = None
                return False

    async def broadcast(self, data: bytes) -> int:
        """兼容旧接口，向同步服务发送数�?""
        success = await self.send(data)
        return 1 if success else 0

    def get_client_count(self) -> int:
        return 1 if self._connected else 0

    def is_connected(self) -> bool:
        return self._connected

    def get_client_list(self) -> List[Dict]:
        if self._connected:
            return [{
                "ip": self.host,
                "port": self.port,
                "type": "SyncHub",
                "name": "SyncHub-8887",
                "online": True
            }]
        return []


sync_server = SyncTcpClient(host="192.168.0.12", port=8887)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 设备ID（startup时初始化�?
device_id: str = "unknown"

# State Storage (In-Memory)
current_state: Dict[str, Any] = {
    "LowKZ": False,
    "HighKZ": False,
    "HighCurrent": False,
    "Computer": False,
    "Lifting": False,
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
    "LowDYSZ": 12.5,
    "LowDLSZ": 2.5,
    "LowXSTB": False,
    "LowDC_AC": 0,
    "Temperature": None,
    "Humidity": None,
    "PM2_5": None,
    "PM10": None,
    "CO2": None,
    "TVOC": None,
    "CH2O": None,
    "Light": None
}

# 天气数据缓存
_weather_cache: Dict[str, Any] = {}


async def fetch_weather():
    """�?wttr.in 获取当地天气数据并更�?current_state"""
    global _weather_cache
    try:
        loop = asyncio.get_event_loop()
        def _req():
            url = "https://wttr.in/?format=j1"
            req = urllib.request.Request(url, headers={"User-Agent": "curl/7.0", "Accept-Language": "zh-CN"})
            with urllib.request.urlopen(req, timeout=10) as resp:
                return json.loads(resp.read().decode("utf-8"))
        data = await loop.run_in_executor(None, _req)

        cur = data.get("current_condition", [{}])[0]
        temp_c = cur.get("temp_C", "")
        humidity = cur.get("humidity", "")
        # wttr.in 没有 PM2.5 等室内数�? �?uvIndex/visibility 等替代不合�?
        # 只填充温度和湿度, 其他保持 None

        current_state["Temperature"] = float(temp_c) if temp_c else None
        current_state["Humidity"] = float(humidity) if humidity else None

        # 解析天气描述
        desc_list = cur.get("lang_zh", [{}])
        weather_desc = desc_list[0].get("value", "") if desc_list else cur.get("weatherDesc", [{}])[0].get("value", "")
        feels_like = cur.get("FeelsLikeC", "")
        wind_speed = cur.get("windspeedKmph", "")
        wind_dir = cur.get("winddir16Point", "")
        pressure = cur.get("pressure", "")
        visibility = cur.get("visibility", "")
        uv = cur.get("uvIndex", "")

        _weather_cache = {
            "temp": temp_c,
            "humidity": humidity,
            "desc": weather_desc,
            "feels_like": feels_like,
            "wind_speed": wind_speed,
            "wind_dir": wind_dir,
            "pressure": pressure,
            "visibility": visibility,
            "uv": uv
        }
        print(f"[Weather] Updated: {temp_c}°C, {humidity}%, {weather_desc}")
    except Exception as e:
        print(f"[Weather] Fetch failed: {e}")

@app.on_event("startup")
async def startup_event():
    print("Starting background tasks...")
    async def device_feedback_callback(ip: str, status: str):
        if status == "success":
            await manager.broadcast(json.dumps({
                "type": "cmd_result",
                "ip": ip,
                "status": status
            }))

    queue_manager.status_callback = device_feedback_callback
    asyncio.create_task(queue_manager.start_worker(batch_size=2, delay_ms=50))

    async def periodic_scan():
        await asyncio.sleep(1)
        print("[AutoScan] Initial ping scan...")
        await perform_network_scan()
        while queue_manager.is_running:
            await asyncio.sleep(60)
            if not queue_manager.is_running: break
            print("[AutoScan] Periodic ping scan...")
            await perform_network_scan()

    asyncio.create_task(periodic_scan())

    # 启动 8887 学生同步 TCP 客户端（连接�?192.168.0.12:8887�?
    await sync_server.start()
    set_sync_server(sync_server)

    async def periodic_weather():
        await asyncio.sleep(3)
        print("[Weather] Initial fetch...")
        await fetch_weather()
        while queue_manager.is_running:
            await asyncio.sleep(600)  # 10分钟更新一�?
            if not queue_manager.is_running: break
            await fetch_weather()

    asyncio.create_task(periodic_weather())

    # ===== 初始化管理平台上报模�?=====
    global device_id
    # 优先使用 Android ANDROID_ID（硬件级唯一标识，重�?重装不变�?
    device_id = None
    try:
        from java import jclass
        PythonApp = jclass("com.chaquo.python.Python")
        app_ctx = PythonApp.getInstance().getApplication()
        SecureSettings = jclass("android.provider.Settings$Secure")
        android_id = str(SecureSettings.getString(app_ctx.getContentResolver(), "android_id"))
        if android_id and android_id not in ("", "unknown", "None"):
            device_id = android_id[:12]
            print(f"[Main] Using ANDROID_ID as device_id: {device_id}")
    except Exception as e:
        print(f"[Main] ANDROID_ID unavailable: {e}")

    # 回退：持久化文件存储（使�?app files dir，比 HOME 更稳定）
    if not device_id:
        try:
            import tempfile
            from java import jclass
            PythonApp = jclass("com.chaquo.python.Python")
            files_dir = str(PythonApp.getInstance().getApplication().getFilesDir().getAbsolutePath())
        except:
            import tempfile
            files_dir = os.environ.get("HOME", tempfile.gettempdir())
        device_id_file = os.path.join(files_dir, ".sslab_device_id")
        if os.path.exists(device_id_file):
            with open(device_id_file, "r") as f:
                device_id = f.read().strip()
            print(f"[Main] Loaded device_id from file: {device_id}")
        else:
            device_id = uuid.uuid4().hex[:12]
            try:
                with open(device_id_file, "w") as f:
                    f.write(device_id)
            except:
                pass
            print(f"[Main] Generated new device_id: {device_id}")

    reporter.init_reporter(
        device_id=device_id,
        state_ref=current_state,
        sync_server_ref=sync_server,
        app_version="2.0.1",
        version_code=20002
    )

    async def execute_remote_command(cmd_type: str, cmd_data: dict) -> str:
        """执行管理平台下发的远程命�?""
        target_ip = cmd_data.get("target_ip", "")
        target_port = int(cmd_data.get("target_port", 0))
        data = cmd_data.get("data", "")

        if cmd_type == "tcp_send" and target_ip and target_port:
            if data.replace(" ", "").replace(":", "").isalnum() and all(c in "0123456789abcdefABCDEF " for c in data.replace(":", "")):
                payload = bytes.fromhex(data.replace(" ", "").replace(":", ""))
            else:
                payload = data.encode("utf-8")
            resp = await CommandExecutor.send_one(target_ip, target_port, payload)
            return f"Sent {len(payload)} bytes to {target_ip}:{target_port}, response: {resp}"

        elif cmd_type == "modbus_8234" and target_ip:
            addr = int(cmd_data.get("register", 0))
            val = int(cmd_data.get("value", 0))
            cmd = DeviceProtocol.groups_modbus_tcp_cmd(addr, val)
            await queue_manager.add_task(target_ip, 8234, cmd)
            return f"Modbus 8234 sent to {target_ip}: addr={addr}, val={val}"

        elif cmd_type == "modbus_8888" and target_ip:
            on = bool(cmd_data.get("power_on", False))
            volts = int(cmd_data.get("voltage", 0))
            amps = int(cmd_data.get("current", 2500))
            is_ac = bool(cmd_data.get("is_ac", False))
            cmd = DeviceProtocol.teacher_power_cmd(on, volts, amps, is_ac)
            await queue_manager.add_task(target_ip, 8888, cmd)
            return f"Modbus 8888 sent to {target_ip}: on={on}, V={volts}, A={amps}"

        elif cmd_type == "json_1053":
            key = cmd_data.get("key", "device1")
            val = cmd_data.get("value", True)
            cmd = DeviceProtocol.legacy_json_cmd(key, val)
            ips = [f"192.168.0.{i}" for i in range(100, 201)]
            for ip in ips:
                await queue_manager.add_task(ip, 1053, cmd)
            return f"JSON 1053 broadcast: {key}={val} to {len(ips)} IPs"

        elif cmd_type == "sync_8887":
            count = sync_server.get_client_count()
            if count > 0:
                msg = data.encode("utf-8") if data else b""
                if msg:
                    await sync_server.broadcast(msg)
                return f"Broadcast to {count} sync clients"
            return "No sync clients connected"

        elif cmd_type == "custom":
            return f"Custom command received: {json.dumps(cmd_data)}"

        return f"Unknown command type: {cmd_type}"

    reporter.set_command_executor(execute_remote_command)
    asyncio.create_task(reporter.reporter_loop())
    reporter.log_info("APP started, reporter initialized")

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

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
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

@app.get("/req")
async def get_state_endpoint():
    return {**current_state, "_device_id": device_id, "_version": "2.0.0"}

@app.get("/api/scan")
async def scan_network_endpoint(clear: bool = False, ports: str = None):
    print(f"[API] Scan requested. Clear existing cache: {clear}. Ports: {ports}")
    target_ports = None
    if ports:
        try:
            target_ports = [int(p) for p in ports.split(",")]
        except ValueError:
            pass
    results = await perform_network_scan(clear_cache=clear, target_ports=target_ports)
    await manager.broadcast(json.dumps({
        "type": "scan_complete",
        "data": results,
        "count": len(results)
    }))
    return {"status": "ok", "count": len(results), "devices": results}

@app.get("/api/devices")
async def get_devices_endpoint():
    return get_online_devices()

@app.get("/api/weather")
async def get_weather_endpoint():
    """返回天气缓存数据"""
    return _weather_cache

@app.get("/api/sync_clients")
async def get_sync_clients():
    """返回 8887 学生同步已连接客户端"""
    return {"count": sync_server.get_client_count(), "clients": sync_server.get_client_list()}

@app.post("/{domain}/{device_id}")
async def control_endpoint(domain: str, device_id: str, payload: Dict[str, Any]):
    val = payload.get("value")
    if val is None:
        if payload.get("bool") is not None: val = payload.get("bool")
        elif payload.get("state") is not None: val = (payload.get("state") == 1)

    if isinstance(val, str):
        if val.lower() in ["false", "0", "off", "no"]:
            val = False
        elif val.lower() in ["true", "1", "on", "yes"]:
            val = True

    current_state[device_id] = val
    print(f"[CTRL] {domain}/{device_id} -> {val}")

    config_path = os.path.join(BASE_DIR, "config.json")

    if device_id in ["Computer", "Lifting"]:
        conf = load_config(config_path)

        if device_id == "Computer":
             cmd = DeviceProtocol.legacy_json_cmd("device1", bool(val))
        elif device_id == "Lifting":
             if val:
                 cmd = b'{"motor_fwd":true,"motor_bwd":false}\n'
             else:
                 cmd = b'{"motor_fwd":false,"motor_bwd":true}\n'

        target_ips = [f"192.168.0.{i}" for i in range(100, 201)]
        for _ in range(2):
            for ip in target_ips:
                await queue_manager.add_task(ip, 1053, cmd)
        print(f"[1053_BROADCAST] Sent {device_id} command to {len(target_ips)} IPs (x2)")

    elif device_id in ["XS_A", "XS_B", "XS_C", "XS_D", "HighKZ", "HighXZ", "HighCurrent", "BBLampKZ", "CRLampKZ"]:
        conf = load_config(config_path)
        devs_8234 = [d for d in conf.get("devices", []) if d.get("port") == 8234]

        found_fixed = any(d.get("ip") == "192.168.0.7" for d in devs_8234)
        if not found_fixed:
             devs_8234.append({"ip": "192.168.0.7", "port": 8234, "type": "fixed_8234"})

        reg_addr = 0x0000
        if device_id == "HighCurrent": reg_addr = 0x0000
        elif device_id == "XS_D": reg_addr = 0x0001
        elif device_id == "XS_C": reg_addr = 0x0002
        elif device_id == "XS_B": reg_addr = 0x0003
        elif device_id == "XS_A": reg_addr = 0x0004
        elif device_id == "HighXZ": reg_addr = 0x0006
        elif device_id == "HighKZ": reg_addr = 0x0007
        elif device_id == "BBLampKZ": reg_addr = 0x0008
        elif device_id == "CRLampKZ": reg_addr = 0x0009

        cmd = DeviceProtocol.groups_modbus_tcp_cmd(reg_addr, 1 if val else 0)
        for dev in devs_8234:
            await queue_manager.add_task(dev["ip"], 8234, cmd)

    elif device_id in ["LowKZ", "LowDYSZ", "LowDLSZ", "LowDC_AC"]:
        power_on = bool(current_state.get("LowKZ", False))

        should_send = (device_id == "LowKZ") or power_on

        if should_send:
            is_ac = (current_state.get("LowDC_AC", 0) == 1)

            raw_volts = current_state.get("LowDYSZ", 0)
            try:
                if raw_volts == "": raw_volts = 0
                volts_int = int(float(raw_volts) * 100)
            except:
                volts_int = 0

            raw_amps = current_state.get("LowDLSZ", 2.5)
            try:
                 if raw_amps == "": raw_amps = 2.5
                 amps_float = float(raw_amps)
                 if amps_float <= 0: amps_float = 2.5
                 amps_int = int(amps_float * 1000)
            except:
                 amps_int = 2500

            conf = load_config(config_path)
            devs_8888 = [d for d in conf.get("devices", []) if d.get("port") == 8888]
            if not devs_8888:
                devs_8888 = [{"ip": "192.168.0.211", "port": 8888}]

            cmd = DeviceProtocol.teacher_power_cmd(power_on, volts_int, amps_int, is_ac)
            for dev in devs_8888:
                await queue_manager.add_task(dev["ip"], 8888, cmd)

    elif device_id == "LowXSTB":
        is_ac = (current_state.get("LowDC_AC", 0) == 1)

        raw_volts = current_state.get("LowDYSZ", 12.5)
        try:
            volts_int = int(float(raw_volts) * 100)
            if volts_int <= 0: volts_int = 1250
        except:
            volts_int = 1250

        raw_amps = current_state.get("LowDLSZ", 2.5)
        try:
             amps_float = float(raw_amps)
             if amps_float <= 0: amps_float = 2.5
             amps_int = int(amps_float * 1000)
        except:
             amps_int = 2500

        cmd = DeviceProtocol.teacher_power_cmd(bool(val), volts_int, amps_int, is_ac)
        client_count = sync_server.get_client_count()
        if client_count > 0:
            await sync_server.broadcast(cmd)
            print(f"[SYNC] Broadcast to {client_count} clients, on={val}, V={volts_int}, A={amps_int}, AC={is_ac}")
        else:
            print(f"[SYNC] No clients connected on 8887, command not sent")

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
