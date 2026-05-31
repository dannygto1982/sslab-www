# SSLAB-WWW — 智慧实验室控制系统

控制柜 Android APP + 局域网后端控制服务 + 远程管理平台（OTA/命令推送）的完整源码。

---

## 项目结构

```
SSLAB-WWW/
├── android/                        # Android 控制柜 APP（Cordova + Chaquopy）
│   └── platforms/android/app/
│       └── src/main/
│           ├── java/com/lab/management/
│           │   ├── MainActivity.java       # APP 主入口，WebView + Chaquopy 启动
│           │   └── UpdateHelper.java       # APK 安装 / 自卸载工具类
│           ├── python/
│           │   ├── main.py                 # 局域网控制后端（FastAPI，127.0.0.1:1880）
│           │   ├── reporter.py             # ⭐ 远程管理上报 + OTA 自动更新（关键文件）
│           │   ├── scanner.py              # 局域网设备扫描
│           │   ├── server_main.py          # 学生同步 TCP 服务（8887 端口）
│           │   └── devices.py             # 设备协议 / 队列管理
│           └── assets/www/
│               └── index.html              # WebView 前端页面（内嵌于 APK）
│
├── backend/                        # PC 端模拟后端（开发/测试用，与 android/python 同构）
│   └── app/
│       ├── main.py
│       ├── scanner.py
│       ├── devices.py
│       └── server_8887.py
│
├── server/                         # 远程管理平台后端（部署于 49.234.204.200）
│   ├── main.py                     # FastAPI 主应用（OTA 上传、命令下发、心跳接收）
│   ├── models.py                   # SQLite 数据模型（terminal / firmware / command 表）
│   ├── auth.py                     # JWT 鉴权
│   ├── config.py                   # 配置
│   └── static/index.html           # 管理后台 Web 界面
│
├── frontend/                       # 局域网前端页面（浏览器访问 localhost:1880）
│   └── index.html
│
├── docs/                           # 开发文档
├── upload_firmware.py              # 上传 APK 固件到管理平台的工具脚本
├── run_backend.py                  # 启动本地 backend/ 服务的入口
└── requirements.txt
```

---

## 各模块说明

### Android APP（`android/`）

- **运行环境**：RK3568/RK3576 Android 设备，全屏 Kiosk 模式
- **技术栈**：Cordova WebView + Chaquopy（在 APP 内运行 Python）
- **内嵌 Python 服务**：FastAPI 监听 `127.0.0.1:1880`，WebView 通过 HTTP 与之通信
- **当前版本**：`v2.0.1`（versionCode=20002）

#### ⭐ reporter.py — OTA 与远程命令核心

`android/platforms/android/app/src/main/python/reporter.py`

此文件运行在 Android 设备内部（通过 Chaquopy），**不能在 PC 上直接运行**。功能包括：

- 每 30 秒向管理平台（`49.234.204.200`）发送心跳
- 轮询待执行命令（OTA 更新、`self_uninstall` 自卸载等）
- 自动下载并安装新版 APK（OTA 更新）
- 支持 `min_version_code` 过滤，确保 V1 设备不收到 V2 固件推送

### 局域网后端（`backend/`）

PC 端开发/模拟用，与 android/python 目录功能同构，可通过 `run_backend.py` 在 PC 上启动：

```bash
python run_backend.py
# 访问 http://localhost:1880
```

### 远程管理平台（`server/`）

部署在 `49.234.204.200`，systemd 服务 `sslab-admin`，路径 `/opt/sslab-admin/`。

```bash
# 部署后启动
systemctl restart sslab-admin
```

主要 API：

| 接口 | 说明 |
|------|------|
| `POST /api/auth/login` | 获取 JWT token |
| `GET /api/terminals` | 查看所有在线设备 |
| `POST /api/commands/send` | 向设备推送命令 |
| `POST /api/firmware/upload` | 上传 APK 固件 |
| `GET /api/firmware/latest?current_version_code=N` | 设备查询最新固件（含版本隔离） |

---

## 固件版本隔离

`firmware` 表中的 `min_version_code` 字段用于隔离 V1/V2 设备：

| 固件 | min_version_code | 说明 |
|------|-----------------|------|
| v2.0.1 (20002) | 20000 | 仅 V2 设备（versionCode ≥ 20000）收到推送 |
| v1.x.x | 0 | 所有设备均可收到 |

---

## 上传固件

```bash
python upload_firmware.py
# 默认上传 android/...apk 为 v2.0.1，min_version_code=20000
```

---

## 开发环境

- Python 3.10+
- Android SDK / Gradle（构建 APK）
- `pip install -r requirements.txt`

```bash
# 构建 APK
cd android/platforms/android
.\app\gradlew assembleDebug
# 输出：android/platforms/android/app/build/outputs/apk/debug/app-debug.apk
```
