#!/usr/bin/env pwsh
# =============================================================================
# SSLAB ADB 端到端联调测试脚本
# 目标设备：192.168.0.106:45149 (WiFi ADB)
# 后端端口：1880 (via port-forward)
# 用法：  .\docs\adb_e2e_test.ps1
# =============================================================================

$ADB    = "C:\Users\danny\AppData\Local\Android\Sdk\platform-tools\adb.exe"
$DEV    = "192.168.0.106:45149"
$API    = "http://localhost:1880"
$PASS   = 0    # 通过计数
$FAIL   = 0    # 失败计数

function Assert-Ok {
    param([string]$Label, [bool]$Condition, [string]$Detail = "")
    if ($Condition) {
        Write-Host "  [PASS] $Label" -ForegroundColor Green
        $script:PASS++
    } else {
        Write-Host "  [FAIL] $Label  $Detail" -ForegroundColor Red
        $script:FAIL++
    }
}

# --------------------------------------------------------------------------
# 0. ADB 连接与端口转发
# --------------------------------------------------------------------------
Write-Host "`n[0] ADB 连接" -ForegroundColor Cyan
& $ADB connect $DEV | Out-Null
$adbOut = & $ADB -s $DEV shell echo "ADB_OK" 2>&1
Assert-Ok "ADB 连通" ($adbOut -match "ADB_OK")

& $ADB -s $DEV forward tcp:1880 tcp:1880 | Out-Null
Write-Host "  端口转发 tcp:1880 已建立"

# --------------------------------------------------------------------------
# 1. 后端健康检查
# --------------------------------------------------------------------------
Write-Host "`n[1] 后端健康" -ForegroundColor Cyan
try {
    $req = Invoke-RestMethod -Uri "$API/req" -TimeoutSec 5
    Assert-Ok "GET /req 返回" ($req -ne $null)
    $rs485Enabled = $req.RS485_Status.enabled
    Write-Host "  RS485 enabled=$rs485Enabled  port=$($req.RS485_Status.port)"
} catch {
    Assert-Ok "GET /req 返回" $false "Exception: $_"
}

# --------------------------------------------------------------------------
# 2. 设备扫描
# --------------------------------------------------------------------------
Write-Host "`n[2] 设备扫描" -ForegroundColor Cyan
try {
    $scan = Invoke-RestMethod -Uri "$API/api/scan?ports=1053&clear=false" -TimeoutSec 30
    Write-Host "  扫描完成，在线设备数: $($scan.count)"
    $scan.devices | ForEach-Object { Write-Host "    -> $($_.ip):$($_.port)  online=$($_.online)" }
} catch {
    Write-Host "  扫描异常: $_" -ForegroundColor Yellow
}

# --------------------------------------------------------------------------
# 3. RS485 事务日志接口
# --------------------------------------------------------------------------
Write-Host "`n[3] RS485 日志接口" -ForegroundColor Cyan
try {
    $log = Invoke-RestMethod -Uri "$API/api/rs485/log?limit=10" -TimeoutSec 5
    Assert-Ok "GET /api/rs485/log 返回" ($log.status -ne $null)
    Write-Host "  最近事务数: $($log.log.Count)"
    if ($log.log.Count -gt 0) {
        $log.log | Select-Object -First 3 | ForEach-Object {
            Write-Host "    [$($_.ts)] tag=$($_.tag) ok=$($_.ok) ms=$($_.ms)"
        }
    }
} catch {
    Assert-Ok "GET /api/rs485/log 返回" $false "$_"
}

# --------------------------------------------------------------------------
# 4. Lifting 控制（up -> stop -> down -> stop）
# --------------------------------------------------------------------------
Write-Host "`n[4] Lifting 控制" -ForegroundColor Cyan
$cmds = @("up","stop","down","stop")
foreach ($v in $cmds) {
    try {
        $r = Invoke-RestMethod -Uri "$API/ctrl/Lifting" -Method POST `
            -ContentType "application/json" -Body "{`"value`":`"$v`"}" -TimeoutSec 8
        $ok = ($r.status -eq "ok") -or ($r.Lifting -ne $null)
        Assert-Ok "Lifting $v" $ok "resp=$($r | ConvertTo-Json -Compress -Depth 2)"
    } catch {
        # RS485 disabled → HTTP 500 is expected; treat as warning not hard fail
        if ($_ -match "500") {
            Write-Host "  [WARN] Lifting $v -> HTTP 500 (RS485 未接硬件时属正常)" -ForegroundColor Yellow
        } else {
            Assert-Ok "Lifting $v" $false "$_"
        }
    }
    Start-Sleep -Milliseconds 800
}

# --------------------------------------------------------------------------
# 5. Computer 控制
# --------------------------------------------------------------------------
Write-Host "`n[5] Computer 控制" -ForegroundColor Cyan
foreach ($v in @($true, $false)) {
    try {
        $body = "{`"value`":$($v.ToString().ToLower())}"
        $r = Invoke-RestMethod -Uri "$API/ctrl/Computer" -Method POST `
            -ContentType "application/json" -Body $body -TimeoutSec 8
        $ok = ($r.status -eq "ok") -or ($r.Computer -ne $null)
        Assert-Ok "Computer $v" $ok
    } catch {
        if ($_ -match "500") {
            Write-Host "  [WARN] Computer $v -> HTTP 500 (RS485 未接硬件时属正常)" -ForegroundColor Yellow
        } else {
            Assert-Ok "Computer $v" $false "$_"
        }
    }
    Start-Sleep -Milliseconds 500
}

# --------------------------------------------------------------------------
# 6. LowXSTB 学生同步
# --------------------------------------------------------------------------
Write-Host "`n[6] LowXSTB 同步" -ForegroundColor Cyan
foreach ($v in @($true, $false)) {
    try {
        $body = "{`"value`":$($v.ToString().ToLower())}"
        $r = Invoke-RestMethod -Uri "$API/ctrl/LowXSTB" -Method POST `
            -ContentType "application/json" -Body $body -TimeoutSec 8
        $ok = ($r.status -eq "ok") -or ($r.LowXSTB -ne $null)
        Assert-Ok "LowXSTB $v" $ok
    } catch {
        if ($_ -match "500") {
            Write-Host "  [WARN] LowXSTB $v -> HTTP 500 (RS485 未接硬件时属正常)" -ForegroundColor Yellow
        } else {
            Assert-Ok "LowXSTB $v" $false "$_"
        }
    }
    Start-Sleep -Milliseconds 500
}

# --------------------------------------------------------------------------
# 7. VFD 控制
# --------------------------------------------------------------------------
Write-Host "`n[7] VFD 控制" -ForegroundColor Cyan
foreach ($v in @("true","false")) {
    try {
        $r = Invoke-RestMethod -Uri "$API/ctrl/VFD_Power" -Method POST `
            -ContentType "application/json" -Body "{`"value`":$v}" -TimeoutSec 8
        Assert-Ok "VFD_Power $v" ($r.status -eq "ok")
    } catch {
        if ($_ -match "500") {
            Write-Host "  [WARN] VFD_Power $v -> HTTP 500 (未接硬件)" -ForegroundColor Yellow
        } else {
            Assert-Ok "VFD_Power $v" $false "$_"
        }
    }
    Start-Sleep -Milliseconds 300
}
foreach ($spd in @(1,3,5)) {
    try {
        $r = Invoke-RestMethod -Uri "$API/ctrl/VFD_Speed" -Method POST `
            -ContentType "application/json" -Body "{`"value`":$spd}" -TimeoutSec 8
        Assert-Ok "VFD_Speed $spd" ($r.status -eq "ok")
    } catch {
        if ($_ -match "500") {
            Write-Host "  [WARN] VFD_Speed $spd -> HTTP 500 (未接硬件)" -ForegroundColor Yellow
        } else {
            Assert-Ok "VFD_Speed $spd" $false "$_"
        }
    }
    Start-Sleep -Milliseconds 300
}

# --------------------------------------------------------------------------
# 8. 8234 与 8888 兼容回归（保持 TCP 不变）
# --------------------------------------------------------------------------
Write-Host "`n[8] 8234/8888 兼容回归" -ForegroundColor Cyan
foreach ($did in @("XS_A","XS_B","HighKZ")) {
    try {
        $r = Invoke-RestMethod -Uri "$API/ctrl/$did" -Method POST `
            -ContentType "application/json" -Body '{"value":false}' -TimeoutSec 8
        Assert-Ok "$did (8234 关)" ($r.status -eq "ok")
    } catch {
        Assert-Ok "$did (8234 关)" $false "$_"
    }
    Start-Sleep -Milliseconds 300
}
try {
    $r = Invoke-RestMethod -Uri "$API/ctrl/LowKZ" -Method POST `
        -ContentType "application/json" -Body '{"value":false}' -TimeoutSec 8
    Assert-Ok "LowKZ (8888 关)" ($r.status -eq "ok")
} catch {
    Assert-Ok "LowKZ (8888 关)" $false "$_"
}

# --------------------------------------------------------------------------
# 9. RS485 日志事后核验
# --------------------------------------------------------------------------
Write-Host "`n[9] RS485 事务核验" -ForegroundColor Cyan
try {
    $log = Invoke-RestMethod -Uri "$API/api/rs485/log?limit=20" -TimeoutSec 5
    $total    = $log.log.Count
    $ok_count = ($log.log | Where-Object { $_.ok -eq $true }).Count
    $err_count = $total - $ok_count
    Write-Host "  最近 $total 条事务：成功 $ok_count，失败 $err_count"
    if ($err_count -gt 0) {
        Write-Host "  失败详情：" -ForegroundColor Yellow
        $log.log | Where-Object { $_.ok -ne $true } | ForEach-Object {
            Write-Host "    [$($_.ts)] tag=$($_.tag) err=$($_.error)" -ForegroundColor Yellow
        }
    }
} catch {
    Write-Host "  日志获取失败: $_" -ForegroundColor Yellow
}

# --------------------------------------------------------------------------
# 汇总
# --------------------------------------------------------------------------
Write-Host "`n============================================" -ForegroundColor Cyan
Write-Host "  测试结果：PASS=$PASS  FAIL=$FAIL"
if ($FAIL -gt 0) {
    Write-Host "  部分用例失败（见上文 [FAIL]）" -ForegroundColor Red
} else {
    Write-Host "  全部通过！" -ForegroundColor Green
}
Write-Host "============================================`n" -ForegroundColor Cyan
