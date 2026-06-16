from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.middleware.cors import CORSMiddleware
from scanner import perform_network_scan, get_online_devices, set_sync_server
from devices import queue_manager, DeviceProtocol, CommandExecutor
from rs485 import rs485_manager
from protocol_485 import (
    build_computer_frame,
    build_lamp_frame,
    build_lifting_frame,
    build_lowxstb_frame,
    build_vfd_power_frame,
    build_vfd_speed_frame,
)
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
from datetime import datetime

app = FastAPI(title="Control System API")

# 辅助光源最后状态记录
_lamp_last_state = {"on": False}

# 升降自动停止定时器（APK 侧镜像固件逻辑）
_lift_auto_stop_task: Optional[asyncio.Task] = None
LIFT_DEFAULT_TIMEOUT_SEC = 20


def _describe_action(device_id: str, val) -> str:
    """构建人类可读的操作描述，用于 RS485 日志"""
    on_off = {True: "ON", False: "OFF", "up": "UP", "down": "DOWN", "stop": "STOP"}
    labels = {
        "Computer": "电脑", "Lifting": "升降", "Lamp": "辅助灯光",
        "VFD_Power": "变频器电源", "VFD_Speed": "变频器速度",
        "LowXSTB": "学生电源同步",
        "HighKZ": "高压开关", "HighCurrent": "大电流",
        "BBLampKZ": "黑板灯", "CRLampKZ": "教室灯",
    }
    dev_label = labels.get(device_id, device_id)
    if device_id == "VFD_Speed":
        spd_labels = {"1": "低速", "2": "中速", "3": "高速"}
        return f"{dev_label}→{spd_labels.get(str(val), str(val))}"
    if device_id == "Lifting":
        return f"{dev_label}→{on_off.get(str(val).lower(), str(val))}"
    if isinstance(val, bool) or str(val).lower() in ("true", "false", "on", "off"):
        v = bool(val) if not isinstance(val, bool) else val
        return f"{dev_label}→{'开' if v else '关'}"
    return f"{dev_label}→{val}"


# ===== 8887 学生同步 TCP 客户端 =====
class SyncTcpClient:
    """TCP 客户端，主动连接到学生同步服务 192.168.0.12:8887"""
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
        """兼容旧接口，向同步服务发送数据"""
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

# Frontend directory resolution for Chaquopy (Android)
# Try multiple candidate paths to locate www assets
_FRONTEND_CANDIDATES = [
    os.path.join(BASE_DIR, "www"),                             # alongside Python source
    os.path.join(BASE_DIR, "..", "assets", "www"),             # relative to python dir
    os.path.join(BASE_DIR, "..", "..", "assets", "www"),       # deeper relative
    os.path.join(os.getcwd(), "www"),                           # CWD
]
FRONTEND_DIR = ""
for _c in _FRONTEND_CANDIDATES:
    if os.path.isdir(_c):
        FRONTEND_DIR = _c
        break
if not FRONTEND_DIR:
    FRONTEND_DIR = _FRONTEND_CANDIDATES[0]  # default, will 404 gracefully

# 设备ID（startup时初始化）
device_id: str = "unknown"

# State Storage (In-Memory)
current_state: Dict[str, Any] = {
    "LowKZ": False,
    "HighKZ": False,
    "HighCurrent": False,
    "Computer": False,
    "Lifting": False,
    "Lamp": False,
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

# 最后一次扫描结果缓存
_last_scan_devices: List[Dict[str, Any]] = []


async def fetch_weather():
    """从 wttr.in 获取当地天气数据并更新 current_state"""
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
        # wttr.in 没有 PM2.5 等室内数据, 用 uvIndex/visibility 等替代不合适
        # 只填充温度和湿度, 其他保持 None

        current_state["Temperature"] = float(temp_c) if temp_c else None
        current_state["Humidity"] = float(humidity) if humidity else None

        # 提取实际位置名称 (配置覆盖优先)
        loc_name = ""
        try:
            cfg = load_config(os.path.join(BASE_DIR, "config.json"))
            loc_name = str(cfg.get("weather_location", "") or "").strip()
        except Exception:
            pass
        if not loc_name:
            try:
                nearest = data.get("nearest_area", [{}])[0]
                area_names = nearest.get("areaName", [])
                area = area_names[0].get("value", "") if area_names else ""
                loc_name = area or ""
            except Exception:
                pass

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
            "uv": uv,
            "location": loc_name
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
        global _last_scan_devices
        await asyncio.sleep(1)
        print("[AutoScan] Initial ping scan...")
        _last_scan_devices = await perform_network_scan()
        while queue_manager.is_running:
            await asyncio.sleep(60)
            if not queue_manager.is_running: break
            print("[AutoScan] Periodic ping scan...")
            _last_scan_devices = await perform_network_scan()

    asyncio.create_task(periodic_scan())

    # RS485 初始化：读取配置并启用 TCP 转换器通信
    _rs485_cfg = load_config(os.path.join(BASE_DIR, "config.json")).get("rs485", {})
    if not _rs485_cfg:
        _rs485_cfg = {
            "enabled": True,
            "transport": "tcp",
            "tcp_host": "192.168.0.12",   # 以太网转485转换器 IP
            "tcp_port": 1053,             # 转换器 TCP 端口
            "timeout": 0.5,
            "retries": 2,
            "expect_response": False,
            "inter_frame_delay_ms": 20,
        }
    rs485_manager.configure(_rs485_cfg)
    rs485_manager.start_daemon()  # v3.0 TCP 连接守护 — 维持 converter_reachable 缓存

    async def periodic_weather():
        await asyncio.sleep(3)
        print("[Weather] Initial fetch...")
        await fetch_weather()
        while queue_manager.is_running:
            await asyncio.sleep(600)  # 10分钟更新一次
            if not queue_manager.is_running: break
            await fetch_weather()

    asyncio.create_task(periodic_weather())

    # ===== 初始化管理平台上报模块 =====
    global device_id
    # 优先使用 Android ANDROID_ID（硬件级唯一标识，重启/重装不变）
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

    # 回退：持久化文件存储（使用 app files dir，比 HOME 更稳定）
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

    # ── 启动诊断日志 ──
    import os as _os

    _tcp_host = _rs485_cfg.get('tcp_host', '?')
    _tcp_port = _rs485_cfg.get('tcp_port', 1053)
    _transport = _rs485_cfg.get('transport', 'tcp')

    print("=" * 50)
    print("[INIT] SSLAB Control System Starting...")
    print(f"[INIT] Device ID: {device_id}")
    print(f"[INIT] BASE_DIR: {BASE_DIR}")
    print(f"[INIT] Frontend: {'OK' if _os.path.isdir(FRONTEND_DIR) else 'MISSING'} ({FRONTEND_DIR})")
    print("-" * 50)
    print("[INIT] === RS485 / TCP Converter ===")
    print(f"[INIT]   Enabled: {_rs485_cfg.get('enabled', False)}")
    print(f"[INIT]   Transport: {_transport}")
    print(f"[INIT]   TCP Host: {_tcp_host}:{_tcp_port}")
    print("-" * 50)
    print("[INIT] === USB Devices ===")
    print("[INIT]   (TCP mode - not using USB serial)")
    print("-" * 50)
    _status = rs485_manager.status()
    if _status.get("converter_reachable", False):
        print(f"[INIT] RS485 READY via TCP {_tcp_host}:{_tcp_port}")
    else:
        print(f"[INIT] WARNING: TCP converter {_tcp_host}:{_tcp_port} not reachable")
    print("=" * 50)

    # Store init status for API
    _init_status = {
        "device_id": device_id,
        "frontend_ok": _os.path.isdir(FRONTEND_DIR),
        "rs485_enabled": _rs485_cfg.get("enabled", False),
        "rs485_transport": _transport,
        "rs485_tcp_host": _tcp_host,
        "rs485_tcp_port": _tcp_port,
        "timestamp": __import__("time").strftime("%Y-%m-%d %H:%M:%S"),
    }

    async def execute_remote_command(cmd_type: str, cmd_data: dict) -> str:
        """执行管理平台下发的远程命令"""
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
            result = await rs485_manager.send_frame(cmd, tag="json_1053_test", device=key, value=str(val))
            return f"JSON via TCP-RS485: {key}={val}, ok={result.get('ok', False)}"

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

# ── Frontend Static Serving (for LAN access from other computers) ──
if os.path.isdir(os.path.join(FRONTEND_DIR, "css")):
    app.mount("/css", StaticFiles(directory=os.path.join(FRONTEND_DIR, "css")), name="css")
if os.path.isdir(os.path.join(FRONTEND_DIR, "js")):
    app.mount("/js", StaticFiles(directory=os.path.join(FRONTEND_DIR, "js")), name="js")
if os.path.isdir(os.path.join(FRONTEND_DIR, "images")):
    app.mount("/images", StaticFiles(directory=os.path.join(FRONTEND_DIR, "images")), name="images")

@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return HTMLResponse("")

@app.get("/", response_class=HTMLResponse)
async def read_root():
    idx = os.path.join(FRONTEND_DIR, "index.html")
    if os.path.exists(idx):
        for enc in ("utf-8", "utf-16", "gbk", "cp1252"):
            try:
                with open(idx, "r", encoding=enc) as f:
                    return f.read()
            except Exception:
                continue
        with open(idx, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return HTMLResponse("<h2>Frontend not found</h2><p>Place index.html in the www folder.</p>", status_code=404)

@app.get("/admin", response_class=HTMLResponse)
async def read_admin():
    idx = os.path.join(FRONTEND_DIR, "admin.html")
    if os.path.exists(idx):
        for enc in ("utf-8", "utf-16", "gbk", "cp1252"):
            try:
                with open(idx, "r", encoding=enc) as f:
                    return f.read()
            except Exception:
                continue
        with open(idx, "r", encoding="utf-8", errors="ignore") as f:
            return f.read()
    return HTMLResponse("<h2>admin.html not found</h2>", status_code=404)

# ── RS485 Status (TCP mode) ──
@app.get("/api/usb")
async def get_rs485_status():
    """Return RS485 TCP converter status."""
    try:
        status = rs485_manager.status()
        return {
            "transport": status.get("transport", "tcp"),
            "tcp_host": status.get("tcp_host", ""),
            "tcp_port": status.get("tcp_port", 1053),
            "enabled": status.get("enabled", False),
            "converter_reachable": status.get("converter_reachable", False),
            "recent_tx_ok": status.get("recent_tx_ok", False),
        }
    except Exception as e:
        return {"devices": [], "error": str(e)}
@app.get("/api/init")
async def get_init_status():
    """返回启动初始化诊断信息"""
    try:
        return _init_status
    except NameError:
        return {"error": "Not initialized", "timestamp": __import__("time").strftime("%Y-%m-%d %H:%M:%S")}



# ── RS485 Self-Test Suite ──
@app.get("/api/test/rs485/health")
async def rs485_health_check():
    """全面 RS485 健康检查：TCP转换器状态、配置"""
    from rs485 import rs485_manager
    import os
    status = rs485_manager.status()
    recent_tx = status.get("recent_tx_ok", False)
    converter_reachable = status.get("converter_reachable", False)
    rs485_connected = status["enabled"] and (recent_tx or converter_reachable)

    return {
        "timestamp": __import__("time").strftime("%H:%M:%S"),
        "rs485": {
            "enabled": status["enabled"],
            "transport": status.get("transport", "tcp"),
            "tcp_host": status.get("tcp_host", ""),
            "tcp_port": status.get("tcp_port", 1053),
            "converter_reachable": converter_reachable,
            "last_error": status["last_error"],
        },
        "rs485_connected": rs485_connected,
        # 兼容旧前端字段
        "rs485_status": {
            "enabled": status["enabled"],
            "transport": "TCP",
            "host": status.get("tcp_host", ""),
            "port": status.get("tcp_port", 1053),
            "connected": rs485_connected,
        },
        # 各卡片通信协议指示
        "tcp_8888": sync_server.is_connected(),
        "tcp_8234": False,
        "rs485_8887": rs485_connected,
        "tcp_8887": sync_server.is_connected(),
        "rs485_8891": rs485_connected,
        # 1053 是独立 TCP 端口，converter_reachable 即表示 1053 TCP 可连接
        "tcp_1053": converter_reachable,
        "overall": "OK" if rs485_connected else "FAIL"
    }

@app.post("/api/test/ping")
async def rs485_ping_test():
    """发送 ping 帧到 RS485 总线，测试 TCP-RS485 通信"""
    from protocol_485 import build_ping_frame
    from rs485 import rs485_manager
    cfg = load_config(os.path.join(BASE_DIR, "config.json")).get("rs485", {})
    # Temporarily enable if disabled for testing
    was_enabled = rs485_manager._settings.get("enabled", False)
    if not was_enabled:
        rs485_manager._settings["enabled"] = True
    try:
        frame = build_ping_frame()
        result = await rs485_manager.send_frame(
            frame, expect_response=True, response_timeout=1.0,
            retries=1, tag="PING_TEST"
        )
        return {
            "test": "ping",
            "frame_hex": frame.hex().upper(),
            "ok": result.get("ok", False),
            "response": result.get("response", ""),
            "error": result.get("error", ""),
        }
    finally:
        if not was_enabled:
            rs485_manager._settings["enabled"] = was_enabled

@app.post("/api/test/computer")
async def rs485_computer_test(action: str = "toggle"):
    """测试电脑开关控制 (controlComputer)"""
    from protocol_485 import build_computer_frame
    from rs485 import rs485_manager
    is_on = True if action in ("on", "true", "1") else False
    frame = build_computer_frame(is_on)
    result = await rs485_manager.send_frame(
        frame, expect_response=True, response_timeout=1.0,
        retries=2, tag="COMPUTER_TEST"
    )
    return {
        "test": "controlComputer",
        "action": "ON" if is_on else "OFF",
        "frame_hex": frame.hex().upper(),
        "ok": result.get("ok", False),
        "response": result.get("response", ""),
        "error": result.get("error", ""),
    }

@app.post("/api/test/lifting")
async def rs485_lifting_test(action: str = "up"):
    """测试升降控制 (controlLifting)"""
    from protocol_485 import build_lifting_frame
    from rs485 import rs485_manager
    if action not in ("up", "down", "stop"):
        return {"error": "action must be up/down/stop"}
    frame = build_lifting_frame(action)
    result = await rs485_manager.send_frame(
        frame, expect_response=True, response_timeout=1.5,
        retries=2, tag="LIFT_TEST"
    )
    return {
        "test": "controlLifting",
        "action": action.upper(),
        "frame_hex": frame.hex().upper(),
        "ok": result.get("ok", False),
        "response": result.get("response", ""),
        "error": result.get("error", ""),
    }

@app.post("/api/rs485/lamp")
async def rs485_lamp_control():
    """辅助光源控制 → controlLamp (toggle)"""
    from protocol_485 import build_lamp_frame
    from rs485 import rs485_manager
    try:
        body = await request.json()
    except Exception:
        body = {}
    status_val = body.get("status", None)
    # toggle if not specified
    if status_val is None:
        status_val = not _lamp_last_state.get("on", False)
    frame = build_lamp_frame(status_val)
    result = await rs485_manager.send_frame(
        frame, expect_response=True, response_timeout=1.5,
        retries=2, tag="LAMP"
    )
    if result.get("ok"):
        _lamp_last_state["on"] = bool(status_val)
    return {
        "device": "lamp",
        "status": bool(status_val),
        "ok": result.get("ok", False),
        "frame_hex": frame.hex().upper(),
        "response": result.get("response", ""),
        "error": result.get("error", ""),
    }

@app.post("/api/test/auto")
async def rs485_auto_test():
    """全自动端到端测试：ping → 电脑开关 → 升降 → 灯光"""
    from protocol_485 import build_ping_frame, build_computer_frame, build_lifting_frame, build_lamp_frame
    from rs485 import rs485_manager
    import time as _t
    
    results = []
    cfg = load_config(os.path.join(BASE_DIR, "config.json")).get("rs485", {})
    
    # Enable RS485 for test
    was_enabled = rs485_manager._settings.get("enabled", False)
    if not was_enabled:
        rs485_manager._settings["enabled"] = True
    
    try:
        # Test 1: Ping
        r = await rs485_manager.send_frame(build_ping_frame(), expect_response=True, response_timeout=1.0, retries=1, tag="AUTO_PING")
        results.append({"step": 1, "name": "PING", "ok": r.get("ok", False), "detail": r.get("response", r.get("error", ""))})
        
        # Test 2: Computer ON
        r = await rs485_manager.send_frame(build_computer_frame(True), expect_response=True, response_timeout=1.0, retries=1, tag="AUTO_COMP_ON")
        results.append({"step": 2, "name": "Computer ON", "ok": r.get("ok", False), "detail": r.get("response", r.get("error", ""))})
        await asyncio.sleep(0.3)
        
        # Test 3: Computer OFF
        r = await rs485_manager.send_frame(build_computer_frame(False), expect_response=True, response_timeout=1.0, retries=1, tag="AUTO_COMP_OFF")
        results.append({"step": 3, "name": "Computer OFF", "ok": r.get("ok", False), "detail": r.get("response", r.get("error", ""))})
        await asyncio.sleep(0.3)
        
        # Test 4: Lifting UP
        r = await rs485_manager.send_frame(build_lifting_frame("up"), expect_response=True, response_timeout=1.5, retries=1, tag="AUTO_LIFT_UP")
        results.append({"step": 4, "name": "Lifting UP", "ok": r.get("ok", False), "detail": r.get("response", r.get("error", ""))})
        await asyncio.sleep(0.5)
        
        # Test 5: Lifting STOP
        r = await rs485_manager.send_frame(build_lifting_frame("stop"), expect_response=True, response_timeout=1.0, retries=1, tag="AUTO_LIFT_STOP")
        results.append({"step": 5, "name": "Lifting STOP", "ok": r.get("ok", False), "detail": r.get("response", r.get("error", ""))})
        
        # Test 6: Lamp ON
        r = await rs485_manager.send_frame(build_lamp_frame(True, 50), expect_response=True, response_timeout=1.0, retries=1, tag="AUTO_LAMP_ON")
        results.append({"step": 6, "name": "Lamp ON(50%)", "ok": r.get("ok", False), "detail": r.get("response", r.get("error", ""))})
        await asyncio.sleep(0.3)
        
        # Test 7: Lamp OFF
        r = await rs485_manager.send_frame(build_lamp_frame(False), expect_response=True, response_timeout=1.0, retries=1, tag="AUTO_LAMP_OFF")
        results.append({"step": 7, "name": "Lamp OFF", "ok": r.get("ok", False), "detail": r.get("response", r.get("error", ""))})
        
    finally:
        if not was_enabled:
            rs485_manager._settings["enabled"] = was_enabled
    
    passed = sum(1 for r in results if r["ok"])
    return {
        "total": len(results),
        "passed": passed,
        "failed": len(results) - passed,
        "results": results,
        "verdict": "ALL PASSED" if passed == len(results) else f"{passed}/{len(results)} PASSED"
    }

@app.get("/api/test/rs485/log")
async def rs485_log(limit: int = 50):
    """返回 RS485 通信日志"""
    from rs485 import rs485_manager
    return {"log": rs485_manager.get_log(limit)}

# 兼容别名：前端 api.js 调用此端点
@app.get("/api/rs485/log")
async def rs485_log_alias(limit: int = 50):
    """RS485 通信日志 (别名)"""
    from rs485 import rs485_manager
    return {"log": rs485_manager.get_log(limit)}


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

def save_config(path: str, data: Dict[str, Any]) -> None:
    """Atomically write config.json with pretty-print."""
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, path)

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
    _last_scan_devices = results
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

@app.get("/api/admin/weather")
async def get_weather_config():
    """获取天气位置配置"""
    try:
        cfg = load_config(os.path.join(BASE_DIR, "config.json"))
        return {"weather_location": cfg.get("weather_location", "") or ""}
    except Exception:
        return {"weather_location": ""}

@app.put("/api/admin/weather")
async def set_weather_config(body: Dict[str, Any]):
    """设置天气位置配置"""
    loc = str(body.get("weather_location", "") or "").strip()
    cfg_path = os.path.join(BASE_DIR, "config.json")
    try:
        cfg = load_config(cfg_path)
        cfg["weather_location"] = loc
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(cfg, f, indent=2, ensure_ascii=False)
        # 立即更新缓存中的位置
        global _weather_cache
        if _weather_cache:
            _weather_cache["location"] = loc
        # 后台异步刷新天气数据（下次 API 调用即可拿到新位置）
        asyncio.create_task(fetch_weather())
        return {"ok": True, "weather_location": loc}
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/api/sync_clients")
async def get_sync_clients():
    """返回 8887 学生同步已连接客户端"""
    return {"count": sync_server.get_client_count(), "clients": sync_server.get_client_list()}

# ═══════════════════════════════════════════════════════════════
# Admin API  — /api/admin/*  (v3.2 重构：PC→Android 统一)
# ═══════════════════════════════════════════════════════════════

def _admin_config_path() -> str:
    return os.path.join(BASE_DIR, "config.json")

def _admin_load() -> Dict[str, Any]:
    return load_config(_admin_config_path())

def _admin_save(data: Dict[str, Any]) -> None:
    save_config(_admin_config_path(), data)

@app.get("/api/admin/health")
async def admin_health():
    """通道健康状态：固定IP TCP ping + RS485转换器状态"""
    async def tcp_ping(ip: str, port: int, timeout: float = 1.0) -> Dict[str, Any]:
        t0 = __import__('time').monotonic()
        try:
            r, w = await asyncio.wait_for(asyncio.open_connection(ip, port), timeout=timeout)
            w.close()
            try: await w.wait_closed()
            except Exception: pass
            ms = round((__import__('time').monotonic() - t0) * 1000, 1)
            return {"ip": ip, "port": port, "ok": True, "ms": ms}
        except Exception as e:
            return {"ip": ip, "port": port, "ok": False, "error": str(e)}

    targets = [
        ("192.168.0.7", 8234),
        ("192.168.0.211", 8888),
        ("192.168.0.12", 8887),
    ]
    pings = await asyncio.gather(*[tcp_ping(ip, p) for ip, p in targets])
    rs_status = rs485_manager.status()
    return {
        "rs485": rs_status,
        "tcp_ping": {
            "8234": next((p["ms"] if p["ok"] else -1 for p in pings if p["port"] == 8234), -1),
            "8888": next((p["ms"] if p["ok"] else -1 for p in pings if p["port"] == 8888), -1),
            "8887": next((p["ms"] if p["ok"] else -1 for p in pings if p["port"] == 8887), -1),
        },
        "online_1053": 1 if rs_status.get("converter_reachable") else 0,
        "devices": list(pings),
        "state_keys": len(current_state),
    }

@app.get("/api/admin/devices")
async def admin_get_devices():
    return _admin_load().get("devices", [])

@app.post("/api/admin/devices")
async def admin_add_device(body: Dict[str, Any]):
    cfg = _admin_load()
    devices = list(cfg.get("devices", []))
    devices.append(body)
    cfg["devices"] = devices
    _admin_save(cfg)
    return {"ok": True, "devices": devices}

@app.put("/api/admin/devices/{idx}")
async def admin_update_device(idx: int, body: Dict[str, Any]):
    cfg = _admin_load()
    devices = list(cfg.get("devices", []))
    if idx < 0 or idx >= len(devices):
        return JSONResponse(status_code=404, content={"error": "index out of range"})
    devices[idx] = body
    cfg["devices"] = devices
    _admin_save(cfg)
    return {"ok": True, "devices": devices}

@app.delete("/api/admin/devices/{idx}")
async def admin_delete_device(idx: int):
    cfg = _admin_load()
    devices = list(cfg.get("devices", []))
    if idx < 0 or idx >= len(devices):
        return JSONResponse(status_code=404, content={"error": "index out of range"})
    removed = devices.pop(idx)
    cfg["devices"] = devices
    _admin_save(cfg)
    return {"ok": True, "removed": removed, "devices": devices}

@app.get("/api/admin/rs485")
async def admin_get_rs485():
    cfg = _admin_load()
    rs485_cfg = cfg.get("rs485", {})
    return {
        "port": rs485_cfg.get("tcp_host", "192.168.0.12"),
        "baudrate": rs485_cfg.get("baudrate", 9600),
        "timeout": rs485_cfg.get("timeout", 0.5),
        "retries": rs485_cfg.get("retries", 2),
        "inter_frame_delay_ms": rs485_cfg.get("inter_frame_delay_ms", 20),
        "enabled": rs485_cfg.get("enabled", False),
        "legacy_1053_enabled": rs485_cfg.get("legacy_1053_enabled", False),
        "legacy_8887_enabled": rs485_cfg.get("legacy_8887_enabled", False),
        "transport": rs485_cfg.get("transport", "tcp"),
        "tcp_host": rs485_cfg.get("tcp_host", "192.168.0.12"),
        "tcp_port": rs485_cfg.get("tcp_port", 1053),
        "vfd": rs485_cfg.get("vfd", {}),
        "device_map": rs485_cfg.get("device_map", {}),
        "status": rs485_manager.status(),
    }

@app.put("/api/admin/rs485")
async def admin_put_rs485(body: Dict[str, Any]):
    cfg = _admin_load()
    rs485_cfg = dict(cfg.get("rs485", {}))
    # 合并更新
    if "device_map_update" in body:
        upd = body.pop("device_map_update")
        dm = dict(rs485_cfg.get("device_map", {}))
        dm[upd["key"]] = {"slave_id": upd.get("slave_id"), "note": upd.get("note", "")}
        rs485_cfg["device_map"] = dm
    if "vfd" in body:
        vfd = dict(rs485_cfg.get("vfd", {}))
        vfd.update(body.pop("vfd"))
        rs485_cfg["vfd"] = vfd
    rs485_cfg.update(body)
    cfg["rs485"] = rs485_cfg
    _admin_save(cfg)
    rs485_manager.configure(rs485_cfg)
    return {"ok": True, "rs485": rs485_cfg}

@app.get("/api/admin/config")
async def admin_get_config():
    return _admin_load()

@app.post("/api/admin/reload")
async def admin_reload_config():
    cfg = _admin_load()
    rs485_cfg = cfg.get("rs485", {})
    rs485_manager.configure(rs485_cfg)
    return {"ok": True}

@app.post("/api/admin/rs485/test")
async def admin_rs485_send_raw(body: Dict[str, Any]):
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
    # 构建人类可读的操作描述
    _action_desc = _describe_action(device_id, val)
    print(f"[CTRL] {domain}/{device_id} -> {val}   [{_action_desc}]")

    config_path = os.path.join(BASE_DIR, "config.json")

    if device_id in ["Computer", "Lifting"]:
        _rs485_cfg = load_config(config_path).get("rs485", {})
        rs485_on = rs485_manager._settings.get("enabled", False)

        if device_id == "Computer":
            cmd = build_computer_frame(bool(val))
        else:
            cmd = build_lifting_frame(val)

        if rs485_on:
            result = await rs485_manager.send_frame(
                cmd,
                expect_response=bool(_rs485_cfg.get("expect_response", False)),
                response_timeout=float(_rs485_cfg.get("timeout", 0.5)),
                retries=int(_rs485_cfg.get("retries", 2)),
                tag=device_id,
                action=_action_desc,
                device=device_id,
                value=str(val),
            )
            if not result.get("ok"):
                return JSONResponse(status_code=500,
                    content={"status":"error","message":result.get("error","rs485 tcp failed"),"state":current_state})

        # 升降自动停止定时器（APK 侧镜像固件逻辑）
        if device_id == "Lifting":
            global _lift_auto_stop_task
            if _lift_auto_stop_task and not _lift_auto_stop_task.done():
                _lift_auto_stop_task.cancel()
                _lift_auto_stop_task = None
            val_str = str(val).lower()
            if val_str in ("up", "down"):
                async def _auto_stop_lift():
                    await asyncio.sleep(LIFT_DEFAULT_TIMEOUT_SEC)
                    current_state["Lifting"] = "stop"
                    print(f"[LIFT] Auto-stop after {LIFT_DEFAULT_TIMEOUT_SEC}s")
                _lift_auto_stop_task = asyncio.create_task(_auto_stop_lift())
            elif val_str == "stop":
                pass  # 已在上面取消定时器

    elif device_id == "Lamp":
        _rs485_cfg = load_config(config_path).get("rs485", {})
        rs485_on = rs485_manager._settings.get("enabled", False)

        cmd = build_lamp_frame(bool(val))

        if rs485_on:
            result = await rs485_manager.send_frame(
                cmd,
                expect_response=bool(_rs485_cfg.get("expect_response", False)),
                response_timeout=float(_rs485_cfg.get("timeout", 0.5)),
                retries=int(_rs485_cfg.get("retries", 2)),
                tag=device_id,
                action=_action_desc,
                device=device_id,
                value=str(val),
            )
            if not result.get("ok"):
                return JSONResponse(status_code=500,
                    content={"status":"error","message":result.get("error","rs485 tcp failed"),"state":current_state})

        _lamp_last_state["on"] = bool(val)

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
        _rs485_cfg = load_config(config_path).get("rs485", {})
        rs485_on = rs485_manager._settings.get("enabled", False)

        cmd = build_lowxstb_frame(current_state, bool(val))

        if rs485_on:
            result = await rs485_manager.send_frame(
                cmd,
                expect_response=bool(_rs485_cfg.get("expect_response", False)),
                response_timeout=float(_rs485_cfg.get("timeout", 0.5)),
                retries=int(_rs485_cfg.get("retries", 2)),
                tag="LowXSTB",
                action=_action_desc,
                device=device_id,
                value=str(val),
            )
            if not result.get("ok"):
                return JSONResponse(status_code=500,
                    content={"status":"error","message":result.get("error","rs485 tcp failed"),"state":current_state})

    elif device_id in ["VFD_Power", "VFD_Speed"]:
        _rs485_cfg = load_config(config_path).get("rs485", {})
        vfd_cfg  = _rs485_cfg.get("vfd", {}) if isinstance(_rs485_cfg, dict) else {}
        slave_id  = int(vfd_cfg.get("slave_id", 1))
        reg_power = int(vfd_cfg.get("reg_power", 0x2000))
        reg_speed = int(vfd_cfg.get("reg_speed", 0x2001))
        speed_map = vfd_cfg.get("speed_map", {"1": 10, "2": 20, "3": 30})
        if not isinstance(speed_map, dict):
            speed_map = {"1": 10, "2": 20, "3": 30}

        if device_id == "VFD_Power":
            cmd = build_vfd_power_frame(bool(val), slave_id, reg_power)
        else:
            cmd = build_vfd_speed_frame(val, slave_id, reg_speed, speed_map)

        result = await rs485_manager.send_frame(
            cmd,
            expect_response=bool(_rs485_cfg.get("expect_response", False)),
            response_timeout=float(_rs485_cfg.get("timeout", 0.5)),
            retries=int(_rs485_cfg.get("retries", 2)),
            tag=device_id,
            action=_action_desc,
            device=device_id,
            value=str(val),
        )
        if not result.get("ok"):
            return JSONResponse(status_code=500,
                content={"status":"error","message":result.get("error","rs485 tcp failed"),"state":current_state})

    return {"status": "ok", "state": current_state}


# ═══════════════════════════════════════════════════════════════
# 固件管理 API  — /api/firmware/*  (v3.2)
# ═══════════════════════════════════════════════════════════════

_FW_DIR = os.path.join(BASE_DIR, "firmware")
os.makedirs(_FW_DIR, exist_ok=True)

def _get_current_firmware_path() -> Optional[str]:
    """返回当前固件 .bin 文件路径，不存在则 None"""
    fw = os.path.join(_FW_DIR, "firmware.bin")
    return fw if os.path.isfile(fw) else None

@app.get("/api/firmware/status")
async def firmware_status():
    """查询固件设备状态 + 当前可用固件版本信息"""
    fw_path = _get_current_firmware_path()
    fw_size = os.path.getsize(fw_path) if fw_path else 0
    fw_mtime = datetime.fromtimestamp(os.path.getmtime(fw_path)).isoformat() if fw_path else None

    # 尝试从固件设备获取 telemetry
    firmware_ip = "192.168.0.112"  # 默认 OTA IP
    device_state = {}
    wifi_info = {}
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(firmware_ip, 80), timeout=1.5)
        req = b"GET /state HTTP/1.1\r\nHost: " + firmware_ip.encode() + b"\r\nConnection: close\r\n\r\n"
        w.write(req)
        await w.drain()
        resp = b""
        try:
            while True:
                chunk = await asyncio.wait_for(r.read(4096), timeout=1.0)
                if not chunk: break
                resp += chunk
        except Exception:
            pass
        w.close()
        try: await w.wait_closed()
        except Exception: pass
        body = resp.decode("utf-8", errors="replace").split("\r\n\r\n", 1)[-1]
        device_state = json.loads(body) if body.strip() else {}
        wifi_info = {"ssid": device_state.get("ssid", ""), "rssi": device_state.get("rssi", "")}
    except Exception:
        pass

    return {
        "firmware_available": fw_path is not None,
        "firmware_size": fw_size,
        "firmware_path": fw_path,
        "firmware_modified": fw_mtime,
        "firmware_ip": firmware_ip,
        "device_state": device_state,
        "wifi": wifi_info,
        "timestamp": datetime.now().isoformat(),
    }

@app.post("/api/firmware/upload")
async def firmware_upload(request: Request):
    """上传新固件 .bin 文件 (无需 python-multipart，直接读 body)"""
    content = await request.body()
    if len(content) < 1000 or len(content) > 4 * 1024 * 1024:
        return JSONResponse(status_code=400, content={"error": "固件大小无效 (1KB - 4MB)"})
    fw_path = os.path.join(_FW_DIR, "firmware.bin")
    with open(fw_path, "wb") as f:
        f.write(content)
    return {"ok": True, "size": len(content)}

@app.post("/api/firmware/flash")
async def firmware_flash(body: Dict[str, Any]):
    """通过 HTTP Update 推送固件到 ESP8266 设备"""
    device_ip = str(body.get("device_ip", "192.168.0.112"))
    ota_pwd = str(body.get("ota_password", "changemeOTA"))

    fw_path = _get_current_firmware_path()
    if not fw_path:
        return JSONResponse(status_code=400, content={"error": "无可用固件，请先上传或编译"})

    fw_size = os.path.getsize(fw_path)
    print(f"[OTA] Flashing {fw_path} ({fw_size} bytes) → {device_ip}")

    try:
        import aiohttp
        url = f"http://{device_ip}/update"
        auth = aiohttp.BasicAuth("admin", ota_pwd)
        async with aiohttp.ClientSession() as session:
            async with session.post(url, data=open(fw_path, "rb"), auth=auth,
                                    headers={"Content-Type": "application/octet-stream"}) as resp:
                if resp.status == 200:
                    body_text = await resp.text()
                    print(f"[OTA] Success: {resp.status} {body_text}")
                    return {"ok": True, "device_ip": device_ip, "size": fw_size,
                            "http_status": resp.status, "response": body_text}
                else:
                    body_text = await resp.text()
                    print(f"[OTA] Failed: {resp.status} {body_text}")
                    return JSONResponse(status_code=502,
                        content={"error": f"OTA failed HTTP {resp.status}", "detail": body_text})
    except ImportError:
        # aiohttp 不可用时使用 socket 回退
        try:
            import socket
            with open(fw_path, "rb") as f:
                data = f.read()
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(30)
            s.connect((device_ip, 80))
            auth_b64 = __import__("base64").b64encode(f"admin:{ota_pwd}".encode()).decode()
            req = (
                f"POST /update HTTP/1.1\r\n"
                f"Host: {device_ip}\r\n"
                f"Authorization: Basic {auth_b64}\r\n"
                f"Content-Type: application/octet-stream\r\n"
                f"Content-Length: {len(data)}\r\n"
                f"Connection: close\r\n\r\n"
            ).encode() + data
            s.sendall(req)
            resp = b""
            while True:
                try:
                    chunk = s.recv(4096)
                    if not chunk: break
                    resp += chunk
                except socket.timeout:
                    break
            s.close()
            resp_text = resp.decode("utf-8", errors="replace")
            if "200 OK" in resp_text.split("\r\n")[0] if resp_text else False:
                return {"ok": True, "device_ip": device_ip, "size": fw_size, "response": resp_text[:500]}
            else:
                code = resp_text.split("\r\n")[0] if resp_text else "no response"
                return JSONResponse(status_code=502, content={"error": f"OTA failed: {code}", "detail": resp_text[:500]})
        except Exception as se:
            return JSONResponse(status_code=502, content={"error": f"OTA socket error: {se}"})
    except Exception as e:
        return JSONResponse(status_code=502, content={"error": f"OTA connection failed: {e}"})


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
