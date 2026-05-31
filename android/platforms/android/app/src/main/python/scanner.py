import asyncio
import subprocess
import platform
from typing import List, Dict

# ===== 固定设备表 =====
# 每个设备: ip, port, type, name
FIXED_DEVICES = [
    {"ip": "192.168.0.7",   "port": 8234, "type": "USR-IO808",    "name": "Device-D-8234"},
    {"ip": "192.168.0.211", "port": 8888, "type": "TeacherPower", "name": "Teacher-Power"},
]

# 8887 学生同步: APP 作为客户端连接到 192.168.0.12:8887，由 sync_client 提供连接状态
_sync_server_ref = None  # 由 main.py 设置

def set_sync_server(server):
    global _sync_server_ref
    _sync_server_ref = server

# 升降/电脑 1053 范围
LIFT_PORT = 1053
LIFT_IP_START = 100
LIFT_IP_END = 200
LIFT_SUBNET = "192.168.0."

# 在线设备列表 (内存)
_online_devices: List[Dict] = []


async def ping_host(ip: str, timeout: int = 1) -> bool:
    """ICMP ping 检测主机是否在线"""
    try:
        if platform.system().lower() == "windows":
            cmd = ["ping", "-n", "1", "-w", str(timeout * 1000), ip]
        else:
            cmd = ["ping", "-c", "1", "-W", str(timeout), ip]

        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL
        )
        await asyncio.wait_for(proc.wait(), timeout=timeout + 2)
        return proc.returncode == 0
    except Exception:
        return False


async def tcp_check(ip: str, port: int, timeout: float = 0.5) -> bool:
    """TCP 连接检测端口是否开放"""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(ip, port),
            timeout=timeout
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def scan_1053_range() -> List[Dict]:
    """并发 TCP 扫描 1053 端口范围, 返回在线设备列表"""
    tasks = {}
    for i in range(LIFT_IP_START, LIFT_IP_END + 1):
        ip = f"{LIFT_SUBNET}{i}"
        tasks[ip] = asyncio.create_task(tcp_check(ip, LIFT_PORT, timeout=0.5))

    results = []
    for ip, task in tasks.items():
        online = await task
        if online:
            results.append({
                "ip": ip,
                "port": LIFT_PORT,
                "type": "LiftComputer",
                "name": f"Desk-{ip.split('.')[-1]}",
                "online": True
            })
    return results


async def perform_network_scan(**kwargs) -> List[Dict]:
    """Ping 固定设备 + TCP扫描 1053 范围, 更新在线状态"""
    global _online_devices

    # 1) Ping 固定设备
    tasks = [(dev.copy(), ping_host(dev["ip"])) for dev in FIXED_DEVICES]

    results = []
    for dev, task in tasks:
        online = await task
        dev["online"] = online
        results.append(dev)
        status = "ONLINE" if online else "offline"
        print(f"[Ping] {dev['ip']}:{dev['port']} ({dev['name']}) -> {status}")

    # 2) TCP 扫描 1053 范围
    print(f"[1053] Scanning {LIFT_SUBNET}{LIFT_IP_START}-{LIFT_IP_END} port {LIFT_PORT}...")
    lift_devices = await scan_1053_range()
    results.extend(lift_devices)

    # 3) 8887 学生同步: 从 sync_server 获取已连接客户端
    if _sync_server_ref:
        sync_clients = _sync_server_ref.get_client_list()
        results.extend(sync_clients)
        print(f"[8887] SyncClient connected: {len(sync_clients)}")

    online_count = sum(1 for d in results if d.get("online"))
    fixed_count = len(FIXED_DEVICES)
    lift_count = len(lift_devices)
    print(f"[Ping] Fixed: {sum(1 for d in results[:fixed_count] if d.get('online'))}/{fixed_count} | [1053] Desks: {lift_count} online")

    _online_devices = results
    return results


def get_online_devices() -> List[Dict]:
    """返回当前已知设备列表(含在线状态)"""
    return _online_devices