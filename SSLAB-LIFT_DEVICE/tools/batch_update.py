import argparse
import requests
import ipaddress
import concurrent.futures
import sys
import os
import time

# Configuration
DEFAULT_TIMEOUT = 2  # 连接超时时间 (秒)
DEFAULT_USER = "admin" # ESP8266HTTPUpdateServer 默认用户名

def scan_and_update(ip, target_type, firmware_path, password):
    status_url = f"http://{ip}/status"
    update_url = f"http://{ip}/update"
    
    try:
        # 1. 检查设备状态 (Check Device Status)
        try:
            response = requests.get(status_url, timeout=DEFAULT_TIMEOUT)
        except requests.exceptions.RequestException:
            return None # 设备不可达或不是 HTTP 服务器

        if response.status_code != 200:
            return None

        try:
            data = response.json()
        except ValueError:
            return None # 返回的不是 JSON

        device_type = data.get("deviceType")
        device_id = data.get("deviceId")
        current_version = data.get("firmwareVersion", "unknown")
        
        if not device_type:
            return None

        print(f"[发现] IP: {ip} | 类型: {device_type} | ID: {device_id} | 版本: {current_version}")

        # 2. 检查类型是否匹配 (Check if Type Matches)
        if device_type != target_type:
            print(f"[跳过] 设备 {ip} 类型为 '{device_type}'，目标类型为 '{target_type}'")
            return False

        # 3. 执行更新 (Perform Update)
        print(f"[更新] 正在为 {device_id} ({ip}) 上传固件...")
        
        with open(firmware_path, 'rb') as f:
            # ESP8266HTTPUpdateServer 接受 multipart/form-data 上传
            # 字段名通常为 'image' 或 'update'
            files = {'image': (os.path.basename(firmware_path), f, 'application/octet-stream')}
            
            try:
                update_response = requests.post(
                    update_url, 
                    files=files, 
                    auth=(DEFAULT_USER, password),
                    timeout=60 # 固件上传和刷写需要时间
                )
                
                if update_response.status_code == 200:
                    # 通常返回 "Update Success! Rebooting..."
                    if "Success" in update_response.text:
                        print(f"[成功] {device_id} ({ip}) 更新成功！设备正在重启...")
                        return True
                    else:
                        print(f"[警告] {device_id} ({ip}) 更新响应: {update_response.text}")
                        return True
                elif update_response.status_code == 401:
                    print(f"[失败] {device_id} ({ip}) 认证失败。请检查 OTA 密码。")
                    return False
                else:
                    print(f"[失败] {device_id} ({ip}) 更新失败: {update_response.status_code} {update_response.text}")
                    return False
            except requests.exceptions.RequestException as e:
                print(f"[错误] {device_id} ({ip}) 连接中断: {e}")
                return False

    except Exception as e:
        print(f"[异常] IP {ip} 处理出错: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description="SSLAB 设备批量更新工具")
    parser.add_argument("--firmware", required=True, help="固件文件路径 (.bin)")
    parser.add_argument("--type", required=True, help="目标设备类型 (例如: LIFT_DEVICE)")
    parser.add_argument("--subnet", required=True, help="扫描网段 (例如: 192.168.1.0/24)")
    parser.add_argument("--password", default="changemeOTA", help="OTA 密码 (默认: changemeOTA)")
    parser.add_argument("--workers", type=int, default=50, help="并发扫描线程数 (默认: 50)")

    args = parser.parse_args()

    if not os.path.exists(args.firmware):
        print(f"错误: 固件文件 '{args.firmware}' 不存在。")
        sys.exit(1)

    print(f"--- 开始批量更新任务 ---")
    print(f"目标网段: {args.subnet}")
    print(f"目标类型: {args.type}")
    print(f"固件文件: {args.firmware}")
    print(f"------------------------")
    
    try:
        network = ipaddress.ip_network(args.subnet, strict=False)
    except ValueError:
        print("错误: 网段格式无效。请使用 CIDR 格式，例如 192.168.1.0/24")
        sys.exit(1)

    # 获取所有主机 IP (排除网络地址和广播地址)
    hosts = list(network.hosts())
    print(f"正在扫描 {len(hosts)} 个 IP 地址...")
    
    success_count = 0
    fail_count = 0
    
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(scan_and_update, str(ip), args.type, args.firmware, args.password): ip for ip in hosts}
        
        for future in concurrent.futures.as_completed(futures):
            result = future.result()
            if result is True:
                success_count += 1
            elif result is False:
                fail_count += 1
            # result is None means no device found, ignore

    print(f"------------------------")
    print(f"任务完成。")
    print(f"成功更新: {success_count} 台")
    print(f"更新失败/跳过: {fail_count} 台")

if __name__ == "__main__":
    main()
