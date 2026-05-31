# SSLAB 管理平台 - 技术文档

## 1. 系统概述

SSLAB 管理平台是一个远程固件分发、终端监控和命令测试系统，部署在云服务器上，用于管理教室现场的 Android 控制终端。

### 架构图

```
┌──────────────────────────────────────────────────┐
│              49.234.204.200 (云服务器)              │
│  ┌──────────┐    ┌──────────────────────────┐    │
│  │  Nginx   │───>│  FastAPI (8080)           │    │
│  │  (80)    │    │  - 固件管理 API            │    │
│  └──────────┘    │  - 终端心跳/日志 API       │    │
│                  │  - 命令下发/结果 API        │    │
│                  │  - Vue3 管理前端           │    │
│                  └───────────┬────────────────┘    │
│                              │                     │
│                  ┌───────────▼──────────┐          │
│                  │  SQLite Database     │          │
│                  │  /opt/sslab-admin/   │          │
│                  └─────────────────────┘          │
└──────────────────────────────────────────────────┘
                        ▲  ▲  ▲
          HTTP POST     │  │  │   HTTP GET
      (心跳/日志/结果)   │  │  │  (命令轮询/固件检查)
                        │  │  │
┌───────────────────────┴──┴──┴────────────────────┐
│           教室局域网 (192.168.0.x)                  │
│  ┌──────────────────────────────────────┐        │
│  │  Android 控制终端 (APP)               │        │
│  │  - FastAPI 本地服务 (1880)            │        │
│  │  - reporter.py (管理平台上报模块)      │        │
│  │  - 8887 TCP同步服务端                 │        │
│  │  - 设备扫描/控制                      │        │
│  └────────┬───────────┬──────────┬───────┘        │
│           │           │          │                 │
│    ┌──────▼──┐  ┌─────▼────┐  ┌─▼──────────┐    │
│    │8234 设备│  │8888 教师机│  │1053 电脑/升降│    │
│    └─────────┘  └──────────┘  └─────────────┘    │
└──────────────────────────────────────────────────┘
```

## 2. 服务器部署信息

| 项目 | 值 |
|------|------|
| 服务器 IP | 49.234.204.200 |
| 操作系统 | OpenCloudOS 9 (x86_64) |
| Python | 3.11.6 |
| Nginx | 1.26.3 |
| 部署路径 | /opt/sslab-admin/ |
| 服务名称 | sslab-admin.service |
| 内部端口 | 8080 |
| 外部端口 | 80 (Nginx 反代) |
| 数据库 | SQLite: /opt/sslab-admin/data/sslab_admin.db |
| APK存储 | /opt/sslab-admin/uploads/ |
| 前端 | /opt/sslab-admin/static/index.html |

### 管理后台登录
- 地址: http://49.234.204.200
- 用户名: `admin`
- 密码: `admin123`

## 3. 目录结构

### 服务端 (server/)
```
server/
├── main.py              # FastAPI 主应用
├── config.py            # 配置文件
├── models.py            # 数据库模型 (aiosqlite)
├── auth.py              # JWT 认证
├── requirements.txt     # Python 依赖
├── deploy.sh            # 一键部署脚本
├── sslab-admin.service  # systemd 服务文件
├── nginx_sslab_admin.conf # Nginx 配置
├── static/
│   └── index.html       # Vue3 SPA 管理前端
├── data/
│   └── sslab_admin.db   # SQLite 数据库
└── uploads/             # APK 固件存储
```

### APP端新增
```
android/.../python/
├── reporter.py          # 管理平台上报模块 (新增)
├── main.py              # 主应用 (已集成reporter)
├── scanner.py           # 设备扫描
├── devices.py           # 设备协议
└── server_main.py       # 入口
```

## 4. API 接口文档

### 4.1 认证

#### POST /api/auth/login
登录获取 JWT Token。
```json
Request: {"username": "admin", "password": "admin123"}
Response: {"token": "eyJ...", "username": "admin"}
```

后续请求需在 Header 中携带: `Authorization: Bearer <token>`

---

### 4.2 固件管理

#### POST /api/firmware/upload (需认证)
上传 APK 固件。
```
Content-Type: multipart/form-data
Fields: file (APK文件), version_code (int), version_name (string), changelog (string)
Response: {"id": 1, "filename": "com.lab.management_10003_1.0.3.apk", "size": 12345678}
```

#### GET /api/firmware/list (需认证)
获取固件列表。
```json
Response: {"firmware": [{"id":1, "version_code":10003, "version_name":"1.0.3", ...}]}
```

#### GET /api/firmware/latest (公开)
APP 检查最新版本。
```json
Response: {"update_available": true, "version_code": 10003, "version_name": "1.0.3", "download_url": "/api/firmware/download/1", ...}
```

#### GET /api/firmware/download/{id} (公开)
下载 APK 文件。

#### DELETE /api/firmware/{id} (需认证)
删除固件。

#### POST /api/firmware/{id}/toggle (需认证)
启用/停用固件。
```json
Request: {"active": true}
```

---

### 4.3 终端管理

#### POST /api/terminal/heartbeat (公开 - APP调用)
终端心跳上报。
```json
Request: {
  "device_id": "a1b2c3d4e5f6",
  "device_name": "SSLAB-Controller-e5f6",
  "app_version": "1.0.0",
  "version_code": 10002,
  "device_info": {"platform": "android", "sync_server": {...}},
  "current_state": {"LowKZ": false, "Temperature": 25.0, ...}
}
Response: {"status": "ok", "server_time": 1776502562.0}
```

#### POST /api/terminal/log (公开 - APP调用)
批量上传日志。
```json
Request: {
  "device_id": "a1b2c3d4e5f6",
  "logs": [
    {"level": "INFO", "message": "APP started", "timestamp": 1776502500.0},
    {"level": "ERROR", "message": "TCP timeout", "timestamp": 1776502510.0}
  ]
}
Response: {"status": "ok", "count": 2}
```

#### GET /api/terminal/list (需认证)
获取所有终端列表（含在线状态）。

#### GET /api/terminal/{device_id}/detail (需认证)
获取终端详情。

#### GET /api/terminal/{device_id}/logs (需认证)
查看终端日志。支持 `level` 和 `limit` 参数。

---

### 4.4 命令测试

#### POST /api/command/send (需认证)
向终端下发命令。
```json
Request: {
  "device_id": "a1b2c3d4e5f6",
  "command_type": "modbus_8234",
  "command_data": {"target_ip": "192.168.0.7", "register": 1, "value": 1}
}
Response: {"status": "ok", "command_id": 1}
```

**支持的命令类型:**

| command_type | 说明 | command_data 字段 |
|---|---|---|
| `tcp_send` | 原始TCP发送 | target_ip, target_port, data (HEX字符串或文本) |
| `modbus_8234` | Modbus TCP (8234端口) | target_ip, register, value |
| `modbus_8888` | 教师机电源 (8888端口) | target_ip, power_on, voltage, current, is_ac |
| `json_1053` | JSON广播 (1053端口) | key, value |
| `sync_8887` | 学生同步广播 | data (文本) |
| `custom` | 自定义 | 任意 |

#### GET /api/command/pending/{device_id} (公开 - APP调用)
APP 轮询待执行命令。

#### POST /api/command/result (公开 - APP调用)
APP 回报命令执行结果。
```json
Request: {"command_id": 1, "response": "Sent 10 bytes to 192.168.0.7:8234", "status": "done"}
```

#### GET /api/command/history (需认证)
查看命令历史。

---

### 4.5 统计

#### GET /api/stats (需认证)
仪表盘统计数据。
```json
Response: {
  "total_terminals": 1,
  "online_terminals": 1,
  "latest_firmware": {...},
  "total_firmware": 3
}
```

## 5. APP 上报模块 (reporter.py)

### 工作流程

```
APP 启动
  → 生成/读取设备唯一ID (.device_id 文件)
  → 初始化 reporter 模块
  → 注册命令执行器回调
  → 启动 reporter 后台循环
    → 每 5 分钟: 发送心跳 (设备状态 + current_state)
    → 每 10 分钟: 批量上传日志缓冲区
    → 每 30 秒: 轮询待执行命令 → 执行 → 回报结果
```

### 命令执行流程

```
管理平台 Web UI
  → POST /api/command/send (管理员点击"发送命令")
  → 写入 command_queue 表 (status=pending)
  → APP 轮询 GET /api/command/pending/{device_id}
  → APP 本地执行命令 (TCP发送到局域网设备)
  → APP 回报 POST /api/command/result
  → 管理平台显示执行结果
```

## 6. 运维操作

### 查看服务状态
```bash
systemctl status sslab-admin
journalctl -u sslab-admin -f  # 实时日志
```

### 重启服务
```bash
systemctl restart sslab-admin
```

### 更新代码
```bash
# 从本地上传更新文件
scp server/main.py server/models.py root@49.234.204.200:/opt/sslab-admin/
scp server/static/index.html root@49.234.204.200:/opt/sslab-admin/static/
ssh root@49.234.204.200 "systemctl restart sslab-admin"
```

### 查看数据库
```bash
ssh root@49.234.204.200
sqlite3 /opt/sslab-admin/data/sslab_admin.db
.tables
SELECT * FROM terminal;
SELECT * FROM firmware;
SELECT * FROM command_queue ORDER BY created_at DESC LIMIT 10;
```

### Nginx 配置
```bash
# 检查配置
nginx -t
# 重载
systemctl reload nginx
# 注意: yum.conf 中 exclude 了 nginx，安装需加 --disableexcludes=all
```

## 7. 数据库表结构

### firmware
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增ID |
| app_name | TEXT | 包名 (com.lab.management) |
| version_code | INTEGER | 版本号 |
| version_name | TEXT | 版本名 |
| file_path | TEXT | 文件路径 |
| file_size | INTEGER | 文件大小 |
| changelog | TEXT | 更新说明 |
| upload_time | REAL | 上传时间戳 |
| is_active | INTEGER | 是否激活 |

### terminal
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增ID |
| device_id | TEXT UNIQUE | 设备唯一标识 |
| device_name | TEXT | 设备名称 |
| app_version | TEXT | APP版本 |
| version_code | INTEGER | 版本号 |
| ip_address | TEXT | 上报IP |
| device_info | TEXT (JSON) | 设备信息 |
| current_state | TEXT (JSON) | 当前控制状态 |
| last_heartbeat | REAL | 最后心跳时间 |
| created_at | REAL | 首次注册时间 |

### terminal_log
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增ID |
| device_id | TEXT | 设备ID |
| log_level | TEXT | 日志级别 (INFO/WARN/ERROR) |
| message | TEXT | 日志内容 |
| timestamp | REAL | 日志时间戳 |

### command_queue
| 字段 | 类型 | 说明 |
|------|------|------|
| id | INTEGER PK | 自增ID |
| device_id | TEXT | 目标设备ID |
| command_type | TEXT | 命令类型 |
| command_data | TEXT (JSON) | 命令参数 |
| response | TEXT | 执行结果 |
| status | TEXT | 状态 (pending/done/error) |
| created_at | REAL | 创建时间 |
| executed_at | REAL | 执行时间 |

## 8. 安全说明

- 管理 API 使用 JWT 认证保护
- APP 上报接口 (heartbeat/log/command) 为公开接口，通过 device_id 标识终端
- 默认密码 `admin123`，生产环境应修改
- Nginx 限制上传文件大小 200MB
- 建议配置防火墙仅开放 80 端口
