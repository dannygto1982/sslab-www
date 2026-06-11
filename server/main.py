"""SSLAB Admin Platform - Main Application"""
from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional
import json
import time
import os
import shutil
import logging
from logging.handlers import RotatingFileHandler

import config
import models
from auth import verify_password, create_token, decode_token
from rate_limit import public_limiter, auth_limiter, admin_limiter

app = FastAPI(title="SSLAB Admin Platform", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ============ Auth Dependency ============

async def require_auth(request: Request):
    auth = request.headers.get("Authorization", "")
    if auth.startswith("Bearer "):
        token = auth[7:]
        payload = decode_token(token)
        if payload:
            return payload
    raise HTTPException(status_code=401, detail="Unauthorized")


# ============ Startup ============

@app.on_event("startup")
async def startup():
    # Log rotation: 10 MB per file, 5 backups
    log_dir = os.path.join(config.BASE_DIR, "logs")
    os.makedirs(log_dir, exist_ok=True)
    handler = RotatingFileHandler(
        os.path.join(log_dir, "sslab-admin.log"),
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    ))
    logging.getLogger().addHandler(handler)
    logging.getLogger().setLevel(logging.INFO)

    await models.init_db()
    logging.info(f"Server started on {config.HOST}:{config.PORT}")


# ============ Auth Endpoints ============

@app.post("/api/auth/login")
async def login(request: Request):
    body = await request.json()
    username = body.get("username", "")
    password = body.get("password", "")
    if username != config.ADMIN_USERNAME or not verify_password(password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    token = create_token(username)
    return {"token": token, "username": username}


# ============ Firmware Endpoints ============

@app.post("/api/firmware/upload")
async def upload_firmware(
    file: UploadFile = File(...),
    app_name: str = Form("com.lab.management"),
    version_code: int = Form(...),
    version_name: str = Form(...),
    changelog: str = Form(""),
    min_version_code: int = Form(0),
    _auth=Depends(require_auth)
):
    # Save file
    filename = f"{app_name}_{version_code}_{version_name}.apk"
    file_path = os.path.join(config.UPLOAD_DIR, filename)
    with open(file_path, "wb") as f:
        shutil.copyfileobj(file.file, f)

    file_size = os.path.getsize(file_path)
    fw_id = await models.create_firmware(
        app_name, version_code, version_name, file_path, file_size, changelog, min_version_code
    )
    return {"id": fw_id, "filename": filename, "size": file_size}


@app.get("/api/firmware/list")
async def list_firmware(app_name: Optional[str] = None, _auth=Depends(require_auth)):
    items = await models.list_firmware(app_name)
    for item in items:
        item.pop("file_path", None)
    return {"firmware": items}


@app.get("/api/firmware/latest")
async def latest_firmware(app_name: str = "com.lab.management", current_version_code: int = 0, _rate=Depends(public_limiter)):
    """Public endpoint - APP calls this to check for updates"""
    fw = await models.get_latest_firmware(app_name, current_version_code)
    if not fw:
        return {"update_available": False}
    return {
        "update_available": True,
        "version_code": fw["version_code"],
        "version_name": fw["version_name"],
        "file_size": fw["file_size"],
        "changelog": fw["changelog"],
        "download_url": f"/api/firmware/download/{fw['id']}",
        "firmware_id": fw["id"]
    }


@app.get("/api/firmware/download/{firmware_id}")
async def download_firmware(firmware_id: int):
    fw = await models.get_firmware_by_id(firmware_id)
    if not fw or not os.path.exists(fw["file_path"]):
        raise HTTPException(status_code=404, detail="Firmware not found")
    filename = os.path.basename(fw["file_path"])
    return FileResponse(fw["file_path"], filename=filename, media_type="application/vnd.android.package-archive")


@app.delete("/api/firmware/{firmware_id}")
async def delete_firmware(firmware_id: int, _auth=Depends(require_auth)):
    fw = await models.get_firmware_by_id(firmware_id)
    if not fw:
        raise HTTPException(status_code=404, detail="Not found")
    if os.path.exists(fw["file_path"]):
        os.remove(fw["file_path"])
    await models.delete_firmware(firmware_id)
    return {"status": "ok"}


@app.post("/api/firmware/{firmware_id}/toggle")
async def toggle_firmware(firmware_id: int, request: Request, _auth=Depends(require_auth)):
    body = await request.json()
    await models.toggle_firmware(firmware_id, 1 if body.get("active") else 0)
    return {"status": "ok"}


@app.post("/api/firmware/push-update")
async def push_firmware_update(request: Request, _auth=Depends(require_auth)):
    """管理员向指定终端推送固件更新命令"""
    body = await request.json()
    device_ids = body.get("device_ids", [])
    firmware_id = body.get("firmware_id")
    if not device_ids or not firmware_id:
        raise HTTPException(status_code=400, detail="device_ids and firmware_id required")

    fw = await models.get_firmware_by_id(firmware_id)
    if not fw:
        raise HTTPException(status_code=404, detail="Firmware not found")

    results = []
    for device_id in device_ids:
        terminal = await models.get_terminal(device_id)
        from_vc = terminal["version_code"] if terminal else 0
        # Create update history record
        rec_id = await models.create_update_record(
            device_id, firmware_id, from_vc, fw["version_code"], fw["version_name"]
        )
        # Enqueue force_update command
        cmd_data = json.dumps({
            "firmware_id": firmware_id,
            "version_code": fw["version_code"],
            "version_name": fw["version_name"],
            "download_url": f"/api/firmware/download/{firmware_id}"
        })
        cmd_id = await models.enqueue_command(device_id, "force_update", cmd_data)
        results.append({"device_id": device_id, "command_id": cmd_id, "update_record_id": rec_id})

    return {"status": "ok", "results": results}


@app.post("/api/firmware/update-status")
async def report_update_status(request: Request):
    """APP回报固件更新状态 - Public endpoint"""
    body = await request.json()
    device_id = body.get("device_id", "")
    version_code = body.get("version_code", 0)
    status = body.get("status", "")  # downloading, downloaded, installing, installed, failed
    if not device_id or not version_code or not status:
        raise HTTPException(status_code=400, detail="device_id, version_code, status required")
    await models.update_update_status(device_id, version_code, status)
    return {"status": "ok"}


@app.get("/api/firmware/update-history")
async def get_update_history(device_id: Optional[str] = None, _auth=Depends(require_auth)):
    history = await models.get_update_history(device_id=device_id)
    return {"history": history}


# ============ Terminal Endpoints (APP calls these) ============

@app.post("/api/terminal/heartbeat")
async def terminal_heartbeat(request: Request, _rate=Depends(public_limiter)):
    """APP定时上报心跳 - Public endpoint"""
    body = await request.json()
    device_id = body.get("device_id", "")
    if not device_id:
        raise HTTPException(status_code=400, detail="device_id required")

    await models.upsert_terminal(
        device_id=device_id,
        device_name=body.get("device_name", ""),
        app_version=body.get("app_version", ""),
        version_code=body.get("version_code", 0),
        ip_address=request.client.host if request.client else "",
        device_info=json.dumps(body.get("device_info", {}), ensure_ascii=False),
        current_state=json.dumps(body.get("current_state", {}), ensure_ascii=False)
    )
    return {"status": "ok", "server_time": time.time()}


@app.post("/api/terminal/log")
async def terminal_log(request: Request, _rate=Depends(public_limiter)):
    """APP批量上报日志 - Public endpoint"""
    body = await request.json()
    device_id = body.get("device_id", "")
    logs = body.get("logs", [])
    if not device_id or not logs:
        raise HTTPException(status_code=400, detail="device_id and logs required")
    await models.insert_logs(device_id, logs)
    return {"status": "ok", "count": len(logs)}


@app.get("/api/command/pending/{device_id}")
async def get_pending_commands(device_id: str, _rate=Depends(public_limiter)):
    """APP轮询待执行命令 - Public endpoint"""
    cmds = await models.get_pending_commands(device_id)
    return {"commands": cmds}


@app.post("/api/command/result")
async def report_command_result(request: Request, _rate=Depends(public_limiter)):
    """APP回报命令执行结果 - Public endpoint"""
    body = await request.json()
    cmd_id = body.get("command_id")
    response = body.get("response", "")
    status = body.get("status", "done")
    if not cmd_id:
        raise HTTPException(status_code=400, detail="command_id required")
    await models.update_command_result(cmd_id, response, status)
    return {"status": "ok"}


# ============ Admin Terminal Endpoints ============

@app.get("/api/terminal/list")
async def list_terminals(_auth=Depends(require_auth)):
    terminals = await models.list_terminals()
    now = time.time()
    for t in terminals:
        t["online"] = (now - t.get("last_heartbeat", 0)) < config.HEARTBEAT_TIMEOUT
        try:
            t["device_info"] = json.loads(t.get("device_info", "{}"))
        except:
            t["device_info"] = {}
        try:
            t["current_state"] = json.loads(t.get("current_state", "{}"))
        except:
            t["current_state"] = {}
    return {"terminals": terminals}


@app.get("/api/terminal/{device_id}/detail")
async def terminal_detail(device_id: str, _auth=Depends(require_auth)):
    t = await models.get_terminal(device_id)
    if not t:
        raise HTTPException(status_code=404, detail="Terminal not found")
    now = time.time()
    t["online"] = (now - t.get("last_heartbeat", 0)) < config.HEARTBEAT_TIMEOUT
    try:
        t["device_info"] = json.loads(t.get("device_info", "{}"))
    except:
        t["device_info"] = {}
    try:
        t["current_state"] = json.loads(t.get("current_state", "{}"))
    except:
        t["current_state"] = {}
    return t


@app.get("/api/terminal/{device_id}/logs")
async def terminal_logs(device_id: str, level: Optional[str] = None,
                        limit: int = 200, offset: int = 0, _auth=Depends(require_auth)):
    logs = await models.get_logs(device_id=device_id, level=level, limit=limit, offset=offset)
    return {"logs": logs}


# ============ Command Endpoints ============

@app.post("/api/command/send")
async def send_command(request: Request, _auth=Depends(require_auth)):
    body = await request.json()
    device_id = body.get("device_id", "")
    command_type = body.get("command_type", "")
    command_data = body.get("command_data", {})
    if not device_id or not command_type:
        raise HTTPException(status_code=400, detail="device_id and command_type required")
    cmd_id = await models.enqueue_command(device_id, command_type, json.dumps(command_data, ensure_ascii=False))
    return {"status": "ok", "command_id": cmd_id}


@app.get("/api/command/history")
async def command_history(device_id: Optional[str] = None, limit: int = 100,
                          _auth=Depends(require_auth)):
    cmds = await models.get_command_history(device_id=device_id, limit=limit)
    for c in cmds:
        try:
            c["command_data"] = json.loads(c.get("command_data", "{}"))
        except:
            pass
    return {"commands": cmds}


# ============ Stats ============

@app.get("/api/stats")
async def get_stats(_auth=Depends(require_auth)):
    terminals = await models.list_terminals()
    firmware = await models.list_firmware(limit=1)
    now = time.time()
    online_count = sum(1 for t in terminals if (now - t.get("last_heartbeat", 0)) < config.HEARTBEAT_TIMEOUT)
    return {
        "total_terminals": len(terminals),
        "online_terminals": online_count,
        "latest_firmware": firmware[0] if firmware else None,
        "total_firmware": len(await models.list_firmware(limit=999)),
    }


# ============ Health Check ============

_start_time = time.time()


@app.get("/api/health")
async def health_check():
    """Enhanced health check — no auth required, limited rate."""
    try:
        terminals = await models.list_terminals()
        db_ok = True
    except Exception:
        terminals = []
        db_ok = False

    now = time.time()
    online = sum(1 for t in terminals if (now - t.get("last_heartbeat", 0)) < config.HEARTBEAT_TIMEOUT)

    return {
        "status": "ok" if db_ok else "degraded",
        "uptime_seconds": round(now - _start_time, 1),
        "db_connected": db_ok,
        "terminals_total": len(terminals),
        "terminals_online": online,
        "server_time": now,
    }


# ============ Frontend SPA ============

@app.get("/", response_class=HTMLResponse)
async def serve_index():
    index_path = os.path.join(config.STATIC_DIR, "index.html")
    if os.path.exists(index_path):
        with open(index_path, "r", encoding="utf-8") as f:
            return HTMLResponse(f.read())
    return HTMLResponse("<h1>SSLAB Admin Platform</h1><p>Frontend not deployed yet.</p>")


# Mount static files last
if os.path.exists(config.STATIC_DIR):
    app.mount("/static", StaticFiles(directory=config.STATIC_DIR), name="static")


# ============ Entry Point ============

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT, log_level="info")
