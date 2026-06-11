# SSLAB 设备批量更新工具

这是一个用于批量更新局域网内 SSLAB 设备的 Python 脚本。它会自动扫描指定网段，识别设备类型，并仅对匹配类型的设备进行固件更新。

## 功能特点

*   **自动发现**: 扫描指定网段内的所有 IP。
*   **类型安全**: 通过检查 `/status` 接口返回的 `deviceType`，确保只更新正确类型的设备。
*   **并发处理**: 使用多线程进行快速扫描和更新。
*   **身份验证**: 支持 OTA 密码认证。

## 依赖环境

需要 Python 3 和 `requests` 库。

```bash
pip install requests
```

## 使用方法

在终端中运行脚本：

```bash
python batch_update.py --firmware <固件路径> --type <设备类型> --subnet <网段> [选项]
```

### 参数说明

*   `--firmware`: **(必填)** 编译好的固件文件路径 (`.bin` 文件)。
*   `--type`: **(必填)** 目标设备类型，必须与设备代码中的 `deviceType` 一致 (例如 `LIFT_DEVICE`)。
*   `--subnet`: **(必填)** 要扫描的局域网网段 (CIDR 格式，例如 `192.168.1.0/24`)。
*   `--password`: OTA 更新密码 (默认为 `changemeOTA`)。
*   `--workers`: 并发线程数 (默认为 50)。

### 示例

更新局域网 `192.168.0.x` 内所有 `LIFT_DEVICE` 设备：

```bash
python tools/batch_update.py --firmware .pio/build/d1_mini/firmware.bin --type LIFT_DEVICE --subnet 192.168.0.0/24
```

更新局域网 `10.0.0.x` 内所有 `LIGHTING` 设备，并指定密码：

```bash
python tools/batch_update.py --firmware firmware.bin --type LIGHTING --subnet 10.0.0.0/24 --password mySecretPass
```

## 注意事项

1.  请确保运行脚本的电脑与设备在同一局域网内。
2.  更新过程中请勿断开电源或网络。
3.  脚本会忽略网络地址和广播地址。
