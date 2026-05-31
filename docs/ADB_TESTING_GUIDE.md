# SSLAB Android APP — ADB 全功能测试说明

> 适用版本：SSLAB-WWW Android（Cordova + 嵌入式 Python FastAPI）  
> 内嵌后端端口：`1880`（HTTP/WebSocket）、`8887`（学生端 TCP 同步服务器）  
> 测试日期：2026-05-30

---

## 一、环境准备

### 1.1 安装 ADB
```powershell
# 方式一：通过 winget（推荐）
winget install Google.PlatformTools

# 方式二：手动下载 platform-tools，解压后加入 PATH
# https://developer.android.com/tools/releases/platform-tools
```

### 1.2 手机开启开发者选项
1. 设置 → 关于手机 → 连续点击"版本号"7 次，解锁开发者选项
2. 设置 → 开发者选项 → 打开 **USB 调试**
3. 连接 USB 数据线，在手机弹窗中选择"允许 USB 调试"

### 1.3 验证连接
```powershell
adb devices
# 预期输出：
# List of devices attached
# XXXXXXXX    device
```

---

## 二、APK 安装

```powershell
# Debug 版（开发测试用）
adb install -r "D:\CODE\SSLAB-WWW\android\platforms\android\app\build\outputs\apk\debug\app-debug.apk"

# 强制降级安装（版本回退时使用）
adb install -r -d "D:\CODE\SSLAB-WWW\android\platforms\android\app\build\outputs\apk\debug\app-debug.apk"

# 确认安装成功
adb shell pm list packages | findstr sslab
```

---

## 三、端口转发（ADB Port Forward）

APP 内嵌的 FastAPI 服务运行在手机本地，需要通过 ADB 端口转发才能从 PC 访问：

```powershell
# 转发 HTTP/WebSocket 主端口
adb forward tcp:1880 tcp:1880

# 转发学生端 TCP 同步服务
adb forward tcp:8887 tcp:8887

# 查看已建立的转发列表
adb forward --list

# 测试转发是否生效（需先启动 APP）
curl http://localhost:1880/req
```

---

## 四、APP 启动与基础验证

### 4.1 通过 ADB 启动 APP
```powershell
# 替换 com.sslab.www 为实际包名（见 AndroidManifest.xml）
adb shell monkey -p com.sslab.www -c android.intent.category.LAUNCHER 1
```

### 4.2 等待后端就绪（约 3-5 秒）
```powershell
# 循环检测直到后端响应 200
:wait_loop
curl -s -o nul -w "%{http_code}" http://localhost:1880/req | findstr 200
if errorlevel 1 (
    timeout /t 1 >nul
    goto wait_loop
)
echo Backend is ready!
```

### 4.3 获取初始状态
```powershell
curl -s http://localhost:1880/req | python -m json.tool
```

预期响应示例：
```json
{
  "LowKZ": false, "HighKZ": false, "HighCurrent": false,
  "Computer": false, "Lifting": false,
  "XS_A": false, "XS_B": false, "XS_C": false, "XS_D": false,
  "GSKZ": false, "PFKZ": false,
  "BBLampKZ": false, "CRLampKZ": false,
  "CLQQ": false, "CLHQ": false,
  "VFD_Power": false, "VFD_Speed": 1,
  "LowDYSZ": 0, "LowDLSZ": 2.0, "LowXSTB": false, "LowDC_AC": 0
}
```

---

## 五、REST API 全端点测试

### 5.1 获取设备状态 `GET /req`
```powershell
curl -s http://localhost:1880/req
# 预期：返回完整 JSON 状态对象（21 个字段）
```

### 5.2 获取已发现设备列表 `GET /api/devices`
```powershell
curl -s http://localhost:1880/api/devices | python -m json.tool
# 预期：返回 JSON 数组，包含已缓存的局域网设备
```

### 5.3 触发网络扫描 `GET /api/scan`
```powershell
# 全端口扫描（8887/1053/8888/8234）
curl -s "http://localhost:1880/api/scan" | python -m json.tool

# 仅扫描学生端端口（8887）
curl -s "http://localhost:1880/api/scan?ports=8887" | python -m json.tool

# 清除缓存后重新扫描
curl -s "http://localhost:1880/api/scan?clear=true" | python -m json.tool

# 预期：{"status": "ok", "count": N, "devices": [...]}
```

### 5.4 设备控制端点 `POST /{domain}/{device_id}`

**布尔型开关控制：**

| 设备 ID | 说明 | 映射协议 |
|---------|------|---------|
| `Computer` | 学生台 PC 电源 | Port 1053 `{"device1": bool}` |
| `Lifting` | 升降台 | Port 1053 `{"motor_fwd": bool}` |
| `XS_A/B/C/D` | 学生分组开关 A-D | Port 8234 Modbus 线圈 |
| `HighKZ` | 高压主控开关 | Port 8234 线圈 0x0007 |
| `HighCurrent` | 高电流控制 | Port 8234 线圈 0x0000 |
| `BBLampKZ` | 白板灯控制 | Port 8234 线圈 0x0008 |
| `CRLampKZ` | 顶灯控制 | Port 8234 线圈 0x0009 |
| `LowKZ` | 低压总开关 | Port 8887 Modbus RTU |
| `GSKZ` | 高速控制 | Port 8887 |
| `PFKZ` | 排风控制 | Port 8887 |
| `VFD_Power` | 变频器电源 | Port 8887 |
| `CLQQ` | 车辆前进 | Port 8887 |
| `CLHQ` | 车辆后退 | Port 8887 |
| `LowXSTB` | 低压学生台广播 | Port 8887 批量 |

```powershell
# 开启 PC 电源
curl -s -X POST http://localhost:1880/ctrl/Computer `
  -H "Content-Type: application/json" `
  -d '{"value": true}'

# 关闭 PC 电源
curl -s -X POST http://localhost:1880/ctrl/Computer `
  -H "Content-Type: application/json" `
  -d '{"value": false}'

# 升降台上升
curl -s -X POST http://localhost:1880/ctrl/Lifting `
  -H "Content-Type: application/json" `
  -d '{"value": "up"}'

# 升降台下降
curl -s -X POST http://localhost:1880/ctrl/Lifting `
  -H "Content-Type: application/json" `
  -d '{"value": "down"}'

# 升降台停止
curl -s -X POST http://localhost:1880/ctrl/Lifting `
  -H "Content-Type: application/json" `
  -d '{"value": "stop"}'

# 开启高压
curl -s -X POST http://localhost:1880/ctrl/HighKZ `
  -H "Content-Type: application/json" `
  -d '{"value": true}'

# 开启学生分组 A
curl -s -X POST http://localhost:1880/ctrl/XS_A `
  -H "Content-Type: application/json" `
  -d '{"value": true}'

# 设置 VFD 变频速度（整数 1-50 Hz 等）
curl -s -X POST http://localhost:1880/ctrl/VFD_Speed `
  -H "Content-Type: application/json" `
  -d '{"value": 25}'

# 设置低压电压设定值
curl -s -X POST http://localhost:1880/ctrl/LowDYSZ `
  -H "Content-Type: application/json" `
  -d '{"value": 220}'
```

### 5.5 批量开关测试（全设备循环）
```powershell
# 使用 PowerShell 批量测试所有布尔开关
$switches = @("LowKZ","HighKZ","HighCurrent","Computer","GSKZ","PFKZ",
              "BBLampKZ","CRLampKZ","CLQQ","CLHQ","VFD_Power",
              "XS_A","XS_B","XS_C","XS_D","LowXSTB")

foreach ($sw in $switches) {
    Write-Host "=== Testing $sw ===" -ForegroundColor Cyan
    # ON
    $resp = Invoke-RestMethod -Uri "http://localhost:1880/ctrl/$sw" `
        -Method POST -ContentType "application/json" -Body '{"value":true}'
    Write-Host "ON: $resp"
    Start-Sleep -Milliseconds 200
    # OFF
    $resp = Invoke-RestMethod -Uri "http://localhost:1880/ctrl/$sw" `
        -Method POST -ContentType "application/json" -Body '{"value":false}'
    Write-Host "OFF: $resp"
    Start-Sleep -Milliseconds 200
}
Write-Host "All switch tests passed!" -ForegroundColor Green
```

---

## 六、WebSocket 实时推送测试

### 6.1 安装 wscat 工具
```powershell
npm install -g wscat
```

### 6.2 连接 WebSocket 并监听推送
```powershell
# 打开新终端窗口，连接 WebSocket
wscat -c ws://localhost:1880/ws
```

### 6.3 触发推送并验证
在另一个终端发送控制命令，观察 WebSocket 终端是否收到推送：
```powershell
# 控制操作后，WS 应收到：
# {"type": "cmd_result", "ip": "192.168.0.xxx", "status": "success"}
# 或扫描完成后：
# {"type": "scan_complete", "data": [...], "count": N}

curl -s -X POST http://localhost:1880/ctrl/Computer `
  -H "Content-Type: application/json" `
  -d '{"value": true}'
```

### 6.4 PowerShell WebSocket 测试脚本
```powershell
# 使用 .NET WebSocket 进行快速测试
$ws = [System.Net.WebSockets.ClientWebSocket]::new()
$uri = [System.Uri]::new("ws://localhost:1880/ws")
$task = $ws.ConnectAsync($uri, [System.Threading.CancellationToken]::None)
$task.Wait(5000)

if ($ws.State -eq "Open") {
    Write-Host "WebSocket connected successfully!" -ForegroundColor Green
    $ws.CloseAsync("NormalClosure", "Test done", [System.Threading.CancellationToken]::None).Wait(3000)
} else {
    Write-Host "WebSocket connection failed! State: $($ws.State)" -ForegroundColor Red
}
```

---

## 七、Logcat 日志监控

### 7.1 全量日志（过滤 SSLAB 相关）
```powershell
# 清除历史日志
adb logcat -c

# 实时监控 APP 日志（过滤 Python/FastAPI 输出）
adb logcat | findstr /i "sslab\|python\|fastapi\|server\|websocket\|uvicorn\|chaquopy"
```

### 7.2 关键日志标签过滤
```powershell
# 只看崩溃与错误
adb logcat *:E | findstr /i "sslab\|python\|chaquopy"

# 只看 Python 后端输出（Chaquopy 标签）
adb logcat -s python:V

# 监控并实时保存日志文件
adb logcat > "D:\CODE\SSLAB-WWW\docs\adb_test_log.txt"
```

### 7.3 关键启动日志验证
```
[预期出现的日志条目]
Python initialized successfully
Starting background tasks...
[Server-8887] Listening on ('0.0.0.0', 8887)
[AutoScan] Initial scan started...
INFO:     Uvicorn running on http://127.0.0.1:1880
```

---

## 八、UI 自动化测试（ADB Input）

### 8.1 屏幕截图与分析
```powershell
# 截图并拉取到 PC
adb shell screencap -p /sdcard/sslab_test.png
adb pull /sdcard/sslab_test.png "D:\CODE\SSLAB-WWW\docs\screenshots\sslab_test.png"
```

### 8.2 触摸操作模拟
```powershell
# 录制触摸操作序列
adb shell getevent -l   # 查看输入事件（先手动操作一遍获取坐标）

# 点击屏幕特定坐标（需根据实际分辨率调整）
adb shell input tap 540 960      # 点击屏幕中心
adb shell input swipe 540 1200 540 300 500  # 上滑

# 模拟按下返回键
adb shell input keyevent KEYCODE_BACK

# 模拟按下 HOME 键
adb shell input keyevent KEYCODE_HOME
```

### 8.3 WebView UI 状态验证
```powershell
# 检查 WebView 是否成功加载（通过 chrome://inspect 协议）
# 在 Chrome 浏览器地址栏输入：
# chrome://inspect/#devices
# 找到对应 WebView 并点击 inspect 进行调试
```

---

## 九、性能与稳定性测试

### 9.1 APP 启动时间
```powershell
# 测量冷启动时间
adb shell am start-activity -W -n com.sslab.www/.MainActivity 2>&1 | findstr "TotalTime"
# 预期：TotalTime < 5000ms（含 Python 初始化）
```

### 9.2 内存占用监控
```powershell
# 实时监控 APP 内存
adb shell while true; do dumpsys meminfo com.sslab.www | grep "TOTAL"; sleep 2; done

# 一次性快照
adb shell dumpsys meminfo com.sslab.www
```

### 9.3 CPU 占用
```powershell
adb shell top -n 1 | findstr com.sslab.www
```

### 9.4 压力测试（连续发送 100 次控制命令）
```powershell
$success = 0
$fail = 0
for ($i = 1; $i -le 100; $i++) {
    try {
        $val = if ($i % 2 -eq 0) { "true" } else { "false" }
        $null = Invoke-RestMethod -Uri "http://localhost:1880/ctrl/Computer" `
            -Method POST -ContentType "application/json" -Body "{`"value`": $val}" `
            -TimeoutSec 3
        $success++
    } catch {
        $fail++
        Write-Warning "Request $i failed: $_"
    }
}
Write-Host "Stress test: $success OK / $fail FAILED" -ForegroundColor $(if ($fail -eq 0) {"Green"} else {"Red"})
```

---

## 十、智能体自动化测试脚本

以下脚本可交给 AI 智能体（Copilot Agent / 自动化测试 Agent）执行，完整模拟 APP 全部功能：

```powershell
# ============================================================
# SSLAB APP 全功能智能体自动测试脚本
# 执行前提：
#   1. ADB 已连接手机并建立端口转发 (adb forward tcp:1880 tcp:1880)
#   2. APP 已启动，后端就绪
# ============================================================

$BASE_URL = "http://localhost:1880"
$PASS = 0; $FAIL = 0

function Test-API {
    param($Name, $Method, $Url, $Body=$null, $ExpectKey=$null, $ExpectVal=$null)
    try {
        $params = @{ Uri=$Url; Method=$Method; TimeoutSec=5 }
        if ($Body) { $params.Body = $Body; $params.ContentType = "application/json" }
        $resp = Invoke-RestMethod @params
        if ($ExpectKey -and $resp.$ExpectKey -ne $ExpectVal) {
            Write-Host "[FAIL] $Name - expected $ExpectKey=$ExpectVal got $($resp.$ExpectKey)" -ForegroundColor Red
            $script:FAIL++
        } else {
            Write-Host "[PASS] $Name" -ForegroundColor Green
            $script:PASS++
        }
    } catch {
        Write-Host "[FAIL] $Name - $($_.Exception.Message)" -ForegroundColor Red
        $script:FAIL++
    }
}

Write-Host "`n=== [1/6] 基础状态获取测试 ===" -ForegroundColor Yellow
Test-API "GET /req 状态" GET "$BASE_URL/req"
Test-API "GET /api/devices 设备列表" GET "$BASE_URL/api/devices"

Write-Host "`n=== [2/6] 网络扫描测试 ===" -ForegroundColor Yellow
Test-API "GET /api/scan 全扫描" GET "$BASE_URL/api/scan" -ExpectKey "status" -ExpectVal "ok"
Test-API "GET /api/scan?ports=8887 指定端口" GET "$BASE_URL/api/scan?ports=8887" -ExpectKey "status" -ExpectVal "ok"
Test-API "GET /api/scan?clear=true 清除缓存扫描" GET "$BASE_URL/api/scan?clear=true" -ExpectKey "status" -ExpectVal "ok"

Write-Host "`n=== [3/6] 布尔开关控制测试 ===" -ForegroundColor Yellow
$boolSwitches = @("LowKZ","HighKZ","HighCurrent","Computer",
                  "GSKZ","PFKZ","BBLampKZ","CRLampKZ",
                  "VFD_Power","XS_A","XS_B","XS_C","XS_D","LowXSTB")
foreach ($sw in $boolSwitches) {
    Test-API "POST /ctrl/$sw ON"  POST "$BASE_URL/ctrl/$sw" '{"value":true}'
    Start-Sleep -Milliseconds 100
    Test-API "POST /ctrl/$sw OFF" POST "$BASE_URL/ctrl/$sw" '{"value":false}'
    Start-Sleep -Milliseconds 100
}

Write-Host "`n=== [4/6] 升降台三态控制测试 ===" -ForegroundColor Yellow
Test-API "Lifting UP"   POST "$BASE_URL/ctrl/Lifting" '{"value":"up"}'
Start-Sleep -Milliseconds 500
Test-API "Lifting STOP" POST "$BASE_URL/ctrl/Lifting" '{"value":"stop"}'
Start-Sleep -Milliseconds 200
Test-API "Lifting DOWN" POST "$BASE_URL/ctrl/Lifting" '{"value":"down"}'
Start-Sleep -Milliseconds 500
Test-API "Lifting STOP" POST "$BASE_URL/ctrl/Lifting" '{"value":"stop"}'

Write-Host "`n=== [5/6] 数值型参数控制测试 ===" -ForegroundColor Yellow
Test-API "VFD_Speed=25"  POST "$BASE_URL/ctrl/VFD_Speed"  '{"value":25}'
Test-API "VFD_Speed=50"  POST "$BASE_URL/ctrl/VFD_Speed"  '{"value":50}'
Test-API "VFD_Speed=1"   POST "$BASE_URL/ctrl/VFD_Speed"  '{"value":1}'
Test-API "LowDYSZ=220"   POST "$BASE_URL/ctrl/LowDYSZ"    '{"value":220}'
Test-API "LowDLSZ=3.5"   POST "$BASE_URL/ctrl/LowDLSZ"   '{"value":3.5}'
Test-API "LowDC_AC=1"    POST "$BASE_URL/ctrl/LowDC_AC"   '{"value":1}'
Test-API "LowDC_AC=0"    POST "$BASE_URL/ctrl/LowDC_AC"   '{"value":0}'

Write-Host "`n=== [6/6] 最终状态验证 ===" -ForegroundColor Yellow
Test-API "最终状态 GET /req" GET "$BASE_URL/req"

# 截图留档
adb shell screencap -p /sdcard/sslab_autotest_result.png 2>$null
adb pull /sdcard/sslab_autotest_result.png "D:\CODE\SSLAB-WWW\docs\screenshots\autotest_$(Get-Date -f 'yyyyMMdd_HHmmss').png" 2>$null

Write-Host "`n=============================="
Write-Host "测试完成: PASS=$PASS  FAIL=$FAIL" -ForegroundColor $(if ($FAIL -eq 0) {"Green"} else {"Yellow"})
Write-Host "==============================`n"
```

---

## 十一、常见问题排查

| 现象 | 排查步骤 |
|------|---------|
| `adb devices` 无设备 | 检查 USB 调试是否开启；换数据线；重启 ADB（`adb kill-server; adb start-server`） |
| `curl localhost:1880` 超时 | 确认已执行 `adb forward tcp:1880 tcp:1880`；确认 APP 已启动并完成 Python 初始化 |
| Python 后端启动失败 | `adb logcat` 查看 Chaquopy 报错；通常是 APK 内 Python 依赖缺失 |
| WebSocket 连接断开 | 检查 APP 是否被系统杀掉后台；开启"禁止优化电池"权限 |
| 控制命令无响应 | 设备不在线是正常的（广播模式）；可通过模拟器模式(`mock_device_server.py`)验证协议 |
| APK 安装失败 INSTALL_FAILED_VERSION_DOWNGRADE | 使用 `-d` 参数强制降级：`adb install -r -d app.apk` |

---

## 十二、配合模拟器进行离线测试

在没有真实设备（鸣驹继电器/亿佰特模块）时，可先用项目内置模拟器验证逻辑：

```powershell
# 启动设备模拟器（PC 端）
cd D:\CODE\SSLAB-WWW
.\.venv\Scripts\python.exe backend\mock_device_server.py

# 同时运行测试脚本，所有命令将被模拟器接收并响应
```

---

*文档由 GitHub Copilot 生成 · 2026-05-30*
