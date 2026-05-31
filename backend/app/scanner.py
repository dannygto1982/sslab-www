import asyncio
import json
import os
import ipaddress
from typing import List, Dict, Optional

# 配置
SUBNET = "192.168.0.0/24"
PORT_STUDENT = 8887  # 亿佰特 NT1-B
PORT_CONTROL = 1053  # 鸣驹 MJ-E1S1-X-P
PORT_TEACHER = 8888  # 教师端电源
PORT_DEVICE_D = 8234 # 综合控制 D
TIMEOUT = 3.0        # 增加超时以防止漏扫

import sys

# 路径
if getattr(sys, 'frozen', False):
    # Running in PyInstaller Bundle
    # Config should be next to executable
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

CONFIG_PATH = os.path.join(BASE_DIR, "config.json")

async def check_port(ip: str, port: int) -> bool:
    """尝试连接指定IP的端口，判断是否开放"""
    try:
        conn = asyncio.open_connection(ip, port)
        reader, writer = await asyncio.wait_for(conn, timeout=TIMEOUT)
        writer.close()
        await writer.wait_closed()
        return True
    except (asyncio.TimeoutError, ConnectionRefusedError, OSError):
        return False
    except Exception as e:
        return False

async def scan_single_ip(ip: str, target_ports: List[int] = None) -> Optional[Dict]:
    """扫描单个IP，并发检查多个端口
    :param target_ports: 如果提供，则只扫描这些端口。如果未提供，扫描所有默认端口。
    """
    
    # 定义端口与类型的映射
    # Port -> (Type string, Name prefix)
    port_map = {
        PORT_STUDENT: ("student", "Student"),
        PORT_CONTROL: ("control", "Control"),
        PORT_TEACHER: ("teacher", "Teacher-Power"),
        PORT_DEVICE_D: ("device_8234", "Device-D-8234")
    }

    # 确定要扫描的端口列表
    if target_ports:
        ports_to_scan = [p for p in target_ports if p in port_map]
    else:
        ports_to_scan = list(port_map.keys())

    if not ports_to_scan:
        return None

    # 创建检查任务
    tasks = [check_port(ip, p) for p in ports_to_scan]
    results = await asyncio.gather(*tasks)
    
    # 结果分析 (按顺序)
    for port, is_open in zip(ports_to_scan, results):
        if is_open:
            # 找到开放端口，立即返回 (优先级取决于 ports_to_scan 的顺序，或者调用者意图)
            # 这里简单返回第一个发现的，因为逻辑上目前一个IP对应一个角色
            type_str, name_prefix = port_map[port]
            
            # 特殊名称处理
            if port == PORT_STUDENT or port == PORT_CONTROL:
                final_name = f"{name_prefix}-{ip.split('.')[-1]}"
            else:
                final_name = name_prefix

            if port == PORT_CONTROL:
                print(f"[+] Found Control Device at {ip}:1053")
                
            return {
                "ip": ip,
                "type": type_str,
                "port": port,
                "name": final_name
            }
    
    return None

import socket

def get_all_subnets():
    """获取所有本机非回环网卡的子网前缀"""
    subnets = set()
    try:
        hostname = socket.gethostname()
        ips = socket.gethostbyname_ex(hostname)[2]
        print(f"[DEBUG] gethostbyname_ex found IPs: {ips}")
        for ip in ips:
            if not ip.startswith("127."):
                subnets.add(".".join(ip.split('.')[:-1]))
    except Exception as e:
        print(f"[Warn] gethostbyname_ex failed: {e}")

    # Fallback
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 80))
        ip = s.getsockname()[0]
        s.close()
        print(f"[DEBUG] UDP fallback found IP: {ip}")
        if not ip.startswith("127."):
            subnets.add(".".join(ip.split('.')[:-1]))
    except Exception as e:
         print(f"[Warn] UDP fallback failed: {e}")
            
    return list(subnets)

async def perform_network_scan(clear_cache: bool = False, target_ports: List[int] = None):
    """执行全网段扫描 (支持多网卡)
    :param target_ports: 指定扫描端口列表，None 则扫描全部
    """
    
    # Force REAL mode effectively if not strictly SIMULATION
    env_mode = os.getenv("ENV_MODE", "REAL").upper()
    print(f"[DEBUG] Start Scan. Mode: {env_mode}. Clear Cache: {clear_cache}. Target Ports: {target_ports}")
    
    scan_results = []
    
    # ---------------------------
    # SIMULATION / MOCK LOGIC
    # ---------------------------
    if env_mode == "SIMULATION":
        # ... (Same Sim Logic)
        print("[*] SIMULATION MODE active.")
        all_sim_ports = [
            (1053, "lifting", "Sim-Lifting-Dev1"),
            (8234, "student_master", "Sim-Student-Groups"),
            (8888, "teacher", "Sim-Teacher-Power")
            # REMOVED Sim-Student-Sync (8887) by user request: "Student should be 0"
        ]
        
        # Filter simulation ports
        ports_to_check = []
        if target_ports:
            ports_to_check = [x for x in all_sim_ports if x[0] in target_ports]
        else:
            ports_to_check = all_sim_ports

        for p, t, n in ports_to_check:
            if await check_port('127.0.0.1', p):
                scan_results.append({"ip": "127.0.0.1", "port": p, "type": t, "name": n})
                
        if not scan_results and not target_ports:
             print("[-] Local Simulator not found.")

    # ---------------------------
    # REAL SCAN LOGIC
    # ---------------------------
    else:
        target_subnets = get_all_subnets()
        print(f"[*] REAL MODE: Detected Subnets: {target_subnets}")
        
        tasks = []

        # 1. 192.168.0.x Special Handling for Control Device (1053)
        # Requirement: 1053 only scan 192.168.0.100-130
        should_scan_control = (not target_ports) or (PORT_CONTROL in target_ports)
        
        # 2. Other Ports Scan Range
        should_scan_others = True # By default scan others 1-254
        if target_ports and PORT_CONTROL in target_ports and len(target_ports) == 1:
            should_scan_others = False # If ONLY scanning 1053, don't scan others
            
        for subnet in target_subnets:
            print(f"[*] Queueing scan for subnet: {subnet}")
            
            # Logic:
            # If scanning 1053: Only check .100-.130
            # If scanning others: Check .1-.254 (excluding special handling if mixed? No, mixed is fine)
            
            # Simplified Loop
            for i in range(1, 255):
                target_ip = f"{subnet}.{i}"
                
                # Filter ports for this IP
                current_target_ports = []
                if target_ports:
                    current_target_ports = list(target_ports)
                else:
                    current_target_ports = [PORT_STUDENT, PORT_CONTROL, PORT_TEACHER, PORT_DEVICE_D]
                
                # Apply 1053 Constraint
                if PORT_CONTROL in current_target_ports:
                     # Remove 1053 if IP is NOT in range 100-130
                     if not (100 <= i <= 130):
                         current_target_ports.remove(PORT_CONTROL)
                
                if current_target_ports:
                    tasks.append(scan_single_ip(target_ip, current_target_ports))
        
        if not tasks:
            print("[!] No network interfaces found to scan.")
            return []

        # Use Semaphore to limit concurrency (Windows limit)
        sem = asyncio.Semaphore(60)
        async def sem_task(task):
            async with sem:
                return await task

        print(f"[*] Starting concurrent scan of {len(tasks)} IPs with semaphore...")
        results = await asyncio.gather(*(sem_task(t) for t in tasks))
        
        # Filter None results
        scan_results = [r for r in results if r is not None]
        
        # Deduplicate current scan results
        unique_results = {}
        for r in scan_results:
            key = f"{r['ip']}:{r['port']}"
            unique_results[key] = r
            
        print(f"[DEBUG] Raw scan results count: {len(unique_results)}")

        # User Request: 不保存和读取历史设备 - 每次实时扫描
        # Load existing config to merge ONLY IF not clearing cache
        existing_devices = []
        # if not clear_cache and os.path.exists(CONFIG_PATH):
        #     try:
        #         with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
        #             existing = json.load(f).get("devices", [])
        #             existing_devices = existing
        #     except:
        #         pass
        
        # Merge Strategy
        # 1. Create map of existing
        merged_map = {f"{d['ip']}:{d['port']}": d for d in existing_devices}
        
        # 2. If Partial Scan: We basically want to refresh the scanned ports.
        #    If a device WAS in config but is NOT found now, should we remove it?
        #    "Fill the pits" implies we add new ones. 
        #    However, if we re-scan students and student A is gone, it should probably be removed?
        #    Current logic: "Update/Add new results". It does NOT delete missing ones unless clear_cache=True.
        #    This matches "Accumulate" behavior.
        
        for key, dev in unique_results.items():
            merged_map[key] = dev
            
        final_list = list(merged_map.values())

        # Apply Grouping Logic
        for dev in final_list:
            dev_ip = dev['ip']
            # Only print NEWLY found ones or just summary?
            # print(f"[+] Device in list: {dev_ip} Port:{dev['port']}")
            try:
                last_octet = int(dev_ip.split('.')[-1])
                if 102 <= last_octet <= 108: dev['group'] = 'A'
                elif 109 <= last_octet <= 115: dev['group'] = 'B'
                elif 116 <= last_octet <= 122: dev['group'] = 'C'
                elif 123 <= last_octet <= 129: dev['group'] = 'D'
                else: dev['group'] = 'Unknown'
            except:
                dev['group'] = 'Unknown'

        # Sort by IP for consistent list
        def ip_key(d):
            try:
                return tuple(map(int, d['ip'].split('.')))
            except:
                return (0,0,0,0)
        
        final_list.sort(key=ip_key)

        print(f"[*] Update finished. Total known devices: {len(final_list)}")
        # Log discovered IPs for debugging
        # found_ips = [d['ip'] for d in final_list]
        # print(f"[*] Discovered: {found_ips}")

    # write_config(final_list)  # 禁用保存功能 - 不保存IP，每次实时扫描
    return final_list


def write_config(devices: List[Dict]):
    """保存配置到文件"""
    # 读取旧配置以保留人工修改过的部分（如别名）? 
    # 暂时策略：全覆盖，但如果以后有元数据需要合并逻辑
    
    data = {"devices": devices, "last_scan": "now"} # 时间戳暂略
    
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"[*] 配置已保存至 {CONFIG_PATH}")

if __name__ == "__main__":
    if os.name == 'nt':
        # Windows下asyncio policy调整
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        
    asyncio.run(perform_network_scan())
