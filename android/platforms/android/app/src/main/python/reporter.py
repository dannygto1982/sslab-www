"""SSLAB Admin Reporter - APP端管理平台上报模块
自动向远程管理平台上报心跳、日志和拉取待执行命令，并支持OTA自动更新
"""
import asyncio
import json
import os
import time
import traceback
import urllib.request
import urllib.error
from typing import Dict, Any, List
from collections import deque

# 管理平台地址
ADMIN_SERVER = "http://49.234.204.200"

# 设备唯一ID (首次启动时生成)
_device_id = ""
_app_version = "2.0.1"
_version_code = 20002

# 日志缓冲区
_log_buffer: deque = deque(maxlen=500)

# 命令执行回调
_command_executor = None

# 引用主模块的 current_state
_state_ref = None
_sync_server_ref = None


def init_reporter(device_id: str, state_ref: dict, sync_server_ref=None,
                  app_version: str = "2.0.1", version_code: int = 20002):
    """初始化上报模块"""
    global _device_id, _state_ref, _sync_server_ref, _app_version, _version_code
    _device_id = device_id
    _state_ref = state_ref
    _sync_server_ref = sync_server_ref
    _app_version = app_version
    _version_code = version_code
    print(f"[Reporter] Initialized: device_id={device_id}, server={ADMIN_SERVER}")


def log(level: str, message: str):
    """记录日志到缓冲区"""
    entry = {
        "level": level,
        "message": message,
        "timestamp": time.time()
    }
    _log_buffer.append(entry)


def log_info(msg: str):
    log("INFO", msg)


def log_warn(msg: str):
    log("WARN", msg)


def log_error(msg: str):
    log("ERROR", msg)


def set_command_executor(executor_func):
    """设置命令执行器回调: async def executor(cmd_type, cmd_data) -> str"""
    global _command_executor
    _command_executor = executor_func


def _http_post(path: str, data: dict, timeout: int = 10) -> dict:
    """同步 HTTP POST"""
    url = ADMIN_SERVER + path
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


def _http_get(path: str, timeout: int = 10) -> dict:
    """同步 HTTP GET"""
    url = ADMIN_SERVER + path
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return {"error": str(e)}


async def _send_heartbeat():
    """发送心跳"""
    if not _device_id:
        print("[Reporter] Heartbeat skipped: no device_id")
        return
    try:
        state = dict(_state_ref) if _state_ref else {}
        # 添加同步服务客户端信息
        sync_info = {}
        if _sync_server_ref:
            try:
                sync_info = {
                    "sync_clients": _sync_server_ref.get_client_count(),
                    "sync_client_list": _sync_server_ref.get_client_list()
                }
            except:
                pass

        data = {
            "device_id": _device_id,
            "device_name": f"SSLAB-Controller-{_device_id[-4:]}",
            "app_version": _app_version,
            "version_code": _version_code,
            "device_info": {
                "platform": "android",
                "sync_server": sync_info
            },
            "current_state": state
        }
        print(f"[Reporter] Sending heartbeat to {ADMIN_SERVER}...")
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _http_post, "/api/terminal/heartbeat", data)
        if "error" not in result:
            print(f"[Reporter] Heartbeat OK")
        else:
            print(f"[Reporter] Heartbeat failed: {result['error']}")
    except Exception as e:
        print(f"[Reporter] Heartbeat error: {e}")


async def _send_logs():
    """批量上传日志"""
    if not _device_id or not _log_buffer:
        return
    try:
        logs = []
        while _log_buffer and len(logs) < 100:
            logs.append(_log_buffer.popleft())
        if not logs:
            return
        data = {"device_id": _device_id, "logs": logs}
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _http_post, "/api/terminal/log", data)
        if "error" not in result:
            print(f"[Reporter] Uploaded {len(logs)} logs")
        else:
            # 上传失败，放回缓冲区
            for l in reversed(logs):
                _log_buffer.appendleft(l)
            print(f"[Reporter] Log upload failed: {result['error']}")
    except Exception as e:
        print(f"[Reporter] Log upload error: {e}")


async def _poll_commands():
    """拉取并执行待执行命令"""
    if not _device_id:
        return
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _http_get, f"/api/command/pending/{_device_id}")
        commands = result.get("commands", [])
        for cmd in commands:
            cmd_id = cmd.get("id")
            cmd_type = cmd.get("command_type", "")
            cmd_data_str = cmd.get("command_data", "{}")
            try:
                cmd_data = json.loads(cmd_data_str) if isinstance(cmd_data_str, str) else cmd_data_str
            except:
                cmd_data = {"raw": cmd_data_str}

            print(f"[Reporter] Executing command #{cmd_id}: {cmd_type}")
            log_info(f"Executing command #{cmd_id}: {cmd_type} -> {json.dumps(cmd_data)}")

            response = "no executor"
            status = "error"

            # 特殊处理: force_update 命令
            if cmd_type == "force_update":
                try:
                    response = await _handle_force_update(cmd_data)
                    status = "done"
                except Exception as e:
                    response = f"Force update error: {e}"
                    status = "error"
            elif cmd_type == "self_uninstall":
                try:
                    from java import jclass
                    UpdateHelper = jclass("com.lab.management.UpdateHelper")
                    ok = bool(UpdateHelper.uninstallSelf())
                    response = "Uninstall intent launched" if ok else "Uninstall intent failed"
                    status = "done"
                    log_info(f"[CMD] self_uninstall triggered: {response}")
                except Exception as e:
                    response = f"Uninstall error: {e}"
                    status = "error"
            elif _command_executor:
                try:
                    response = await _command_executor(cmd_type, cmd_data)
                    status = "done"
                except Exception as e:
                    response = f"Error: {traceback.format_exc()}"
                    status = "error"
            else:
                response = "No command executor registered"

            # 回报结果
            report_data = {
                "command_id": cmd_id,
                "response": str(response)[:1000],
                "status": status
            }
            await loop.run_in_executor(None, _http_post, "/api/command/result", report_data)
            print(f"[Reporter] Command #{cmd_id} result: {status}")
    except Exception as e:
        print(f"[Reporter] Command poll error: {e}")


def _download_file(url: str, dest_path: str, timeout: int = 300) -> bool:
    """下载文件到指定路径"""
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            total = int(resp.headers.get("Content-Length", 0))
            downloaded = 0
            with open(dest_path, "wb") as f:
                while True:
                    chunk = resp.read(65536)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
            print(f"[Reporter] Downloaded {downloaded} bytes to {dest_path}")
            return downloaded > 0
    except Exception as e:
        print(f"[Reporter] Download error: {e}")
        try:
            os.remove(dest_path)
        except:
            pass
        return False


async def _handle_force_update(cmd_data: dict) -> str:
    """处理管理员推送的强制更新命令"""
    version_code = cmd_data.get("version_code", 0)
    version_name = cmd_data.get("version_name", "")
    download_url = cmd_data.get("download_url", "")

    if not download_url:
        return "No download_url in command data"

    if version_code <= _version_code:
        return f"Already up to date (local={_version_code}, remote={version_code})"

    log_info(f"Force update received: v{version_code} ({version_name})")
    _report_update_status_sync(version_code, "downloading")

    # 获取下载目录
    try:
        from java import jclass
        UpdateHelper = jclass("com.lab.management.UpdateHelper")
        update_dir = str(UpdateHelper.getUpdateDir())
    except Exception:
        update_dir = os.path.join(os.environ.get("HOME", "/tmp"), "updates")
        os.makedirs(update_dir, exist_ok=True)

    apk_path = os.path.join(update_dir, f"update_{version_code}.apk")
    loop = asyncio.get_running_loop()

    # 下载
    if not (os.path.exists(apk_path) and os.path.getsize(apk_path) > 1000000):
        full_url = ADMIN_SERVER + download_url
        log_info(f"Downloading firmware v{version_code}...")
        success = await loop.run_in_executor(None, _download_file, full_url, apk_path)
        if not success:
            _report_update_status_sync(version_code, "failed")
            return f"Download failed for v{version_code}"

    _report_update_status_sync(version_code, "downloaded")
    log_info(f"Firmware v{version_code} downloaded, installing...")
    _report_update_status_sync(version_code, "installing")

    # 安装
    try:
        from java import jclass
        UpdateHelper = jclass("com.lab.management.UpdateHelper")
        installed = bool(UpdateHelper.installApk(apk_path))
        if installed:
            _report_update_status_sync(version_code, "installed")
            return f"Install intent launched for v{version_code}"
        else:
            _report_update_status_sync(version_code, "failed")
            return f"Install intent failed for v{version_code}"
    except Exception as e:
        _report_update_status_sync(version_code, "failed")
        return f"Install error: {e}"


def _report_update_status_sync(version_code: int, status: str):
    """同步回报更新状态到服务器"""
    try:
        data = {"device_id": _device_id, "version_code": version_code, "status": status}
        _http_post("/api/firmware/update-status", data)
    except Exception as e:
        print(f"[Reporter] Report update status error: {e}")


async def _check_update():
    """检查并执行OTA固件更新"""
    if not _device_id:
        return
    try:
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, _http_get, f"/api/firmware/latest?current_version_code={_version_code}")

        if result.get("error"):
            print(f"[Reporter] Update check failed: {result['error']}")
            return

        if not result.get("update_available"):
            print(f"[Reporter] No update available")
            return

        remote_version_code = result.get("version_code", 0)
        remote_version_name = result.get("version_name", "")
        download_url = result.get("download_url", "")

        if remote_version_code <= _version_code:
            print(f"[Reporter] Already up to date (local={_version_code}, remote={remote_version_code})")
            return

        print(f"[Reporter] Update available: {_version_code} -> {remote_version_code} ({remote_version_name})")
        log_info(f"OTA update found: v{remote_version_code} ({remote_version_name})")
        _report_update_status_sync(remote_version_code, "downloading")

        # 获取下载目录 (通过Java UpdateHelper)
        try:
            from java import jclass
            UpdateHelper = jclass("com.lab.management.UpdateHelper")
            update_dir = str(UpdateHelper.getUpdateDir())
        except Exception:
            update_dir = os.path.join(os.environ.get("HOME", "/tmp"), "updates")
            os.makedirs(update_dir, exist_ok=True)

        apk_path = os.path.join(update_dir, f"update_{remote_version_code}.apk")

        # 如果已下载过就跳过下载
        if os.path.exists(apk_path) and os.path.getsize(apk_path) > 1000000:
            print(f"[Reporter] APK already downloaded: {apk_path}")
        else:
            # 下载APK
            full_url = ADMIN_SERVER + download_url
            print(f"[Reporter] Downloading APK from {full_url}...")
            log_info(f"Downloading firmware v{remote_version_code}...")
            success = await loop.run_in_executor(None, _download_file, full_url, apk_path)
            if not success:
                log_error(f"Failed to download firmware v{remote_version_code}")
                _report_update_status_sync(remote_version_code, "failed")
                return
            log_info(f"Firmware v{remote_version_code} downloaded ({os.path.getsize(apk_path)} bytes)")

        _report_update_status_sync(remote_version_code, "downloaded")

        # 清理旧的下载文件
        try:
            for f in os.listdir(update_dir):
                if f.startswith("update_") and f.endswith(".apk") and f != os.path.basename(apk_path):
                    os.remove(os.path.join(update_dir, f))
        except:
            pass

        # 触发安装
        print(f"[Reporter] Triggering APK install: {apk_path}")
        log_info(f"Installing firmware v{remote_version_code}...")
        _report_update_status_sync(remote_version_code, "installing")
        try:
            from java import jclass
            UpdateHelper = jclass("com.lab.management.UpdateHelper")
            installed = bool(UpdateHelper.installApk(apk_path))
            if installed:
                print(f"[Reporter] Install intent launched successfully")
                log_info(f"OTA install intent launched for v{remote_version_code}")
                _report_update_status_sync(remote_version_code, "installed")
            else:
                print(f"[Reporter] Install intent failed")
                log_error(f"OTA install intent failed for v{remote_version_code}")
                _report_update_status_sync(remote_version_code, "failed")
        except Exception as e:
            print(f"[Reporter] Java install call error: {e}")
            log_error(f"OTA install error: {e}")

    except Exception as e:
        print(f"[Reporter] Update check error: {e}")
        traceback.print_exc()


async def reporter_loop():
    """后台循环：心跳 + 日志 + 命令轮询 + OTA检查"""
    print(f"[Reporter] Waiting 10s before starting loop... server={ADMIN_SERVER}, device={_device_id}")
    await asyncio.sleep(10)  # 启动后等待10秒再开始
    print("[Reporter] Background loop started")
    log_info("Reporter started")

    heartbeat_interval = 60    # 1 分钟心跳
    log_interval = 600         # 10 分钟上传日志
    command_interval = 15      # 15 秒轮询命令
    update_interval = 600      # 10 分钟检查更新

    last_heartbeat = 0
    last_log_upload = 0
    last_command_poll = 0
    last_update_check = 0

    while True:
        try:
            now = time.time()

            if now - last_heartbeat >= heartbeat_interval:
                await _send_heartbeat()
                last_heartbeat = now

            if now - last_log_upload >= log_interval:
                await _send_logs()
                last_log_upload = now

            if now - last_command_poll >= command_interval:
                await _poll_commands()
                last_command_poll = now

            if now - last_update_check >= update_interval:
                await _check_update()
                last_update_check = now

            await asyncio.sleep(5)
        except Exception as e:
            print(f"[Reporter] Loop error: {e}")
            await asyncio.sleep(30)
