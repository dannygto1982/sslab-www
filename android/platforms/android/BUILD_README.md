# Android独立APP构建说明

## 项目结构改造

已完成以下改造，使APP成为独立运行的应用（无需外部服务器）：

### 1. 添加Chaquopy支持
- 在`build.gradle`中添加Chaquopy插件
- 配置Python 3.9运行环境
- 自动安装Python依赖：fastapi, uvicorn, websockets

### 2. 嵌入后端代码
- 后端代码位置：`app/src/main/python/`
- 包含所有Python模块：main.py, scanner.py, devices.py
- 服务器启动脚本：`server_main.py`

### 3. 嵌入前端资源
- 前端资源位置：`app/src/main/assets/www/`
- 包含完整的HTML/CSS/JS和图片资源

### 4. MainActivity改造
- 启动时自动初始化Python环境
- 后台线程运行FastAPI服务器（端口1880）
- WebView加载本地服务器：http://127.0.0.1:1880

## 构建步骤

### 前置要求
- Android Studio Arctic Fox或更高版本
- JDK 11+
- Android SDK (API 21+)

### 构建命令
```bash
cd D:\CODE\www\android\platforms\android
gradlew assembleDebug   # 构建Debug版本
gradlew assembleRelease # 构建Release版本
```

### 生成的APK位置
- Debug: `app/build/outputs/apk/debug/app-debug.apk`
- Release: `app/build/outputs/apk/release/app-release.apk`

## 运行机制

1. **APP启动** → MainActivity.onCreate()
2. **初始化Python** → Python.start(AndroidPlatform)
3. **启动服务器** → 后台线程运行server_main.py
4. **等待就绪** → 延迟2秒确保服务器启动
5. **加载UI** → WebView打开http://127.0.0.1:1880
6. **完全独立运行** → 所有功能在本地完成

## 特性

✅ **完全离线运行** - 无需外部服务器或网络连接
✅ **自包含** - Python环境和所有依赖都打包在APK中
✅ **原生性能** - 使用Chaquopy运行原生Python代码
✅ **完整功能** - 保留所有电源控制、设备扫描功能
✅ **WebSocket支持** - 实时数据更新正常工作

## 注意事项

1. **APK大小** - 由于包含Python环境，APK约40-60MB
2. **首次启动** - 初始化Python环境需要几秒钟
3. **权限** - 需要网络权限（用于localhost通信）
4. **设备扫描** - 在Android上扫描局域网设备需要WiFi权限

## 更新代码

如需更新后端或前端代码：

```bash
# 更新后端
Copy-Item -Path "D:\CODE\www\backend\app\*" -Destination "app\src\main\python\" -Recurse -Force

# 更新前端  
Copy-Item -Path "D:\CODE\www\frontend\*" -Destination "app\src\main\assets\www\" -Recurse -Force

# 重新构建
gradlew assembleDebug
```

## 故障排除

### 服务器启动失败
- 检查Logcat中的Python错误日志
- 确认所有Python依赖已正确安装

### WebView空白
- 检查服务器是否在2秒内启动成功
- 增加MainActivity中的等待时间

### 网络扫描不工作
- 确认APP有WiFi和网络状态权限
- 检查设备是否连接到正确的WiFi网络
