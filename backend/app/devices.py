import asyncio
import struct

def crc16_modbus(data: bytes) -> bytes:
    """计算 Modbus CRC16"""
    crc = 0xFFFF
    for pos in data:
        crc ^= pos
        for _ in range(8):
            if (crc & 1) != 0:
                crc >>= 1
                crc ^= 0xA001
            else:
                crc >>= 1
    return struct.pack('<H', crc)  # Little-endian

class DeviceProtocol:
    """协议生成工厂"""
    
    @staticmethod
    def legacy_json_cmd(key: str, val: bool) -> bytes:
        """Old JSON Protocol (e.g. {"device1": true})"""
        # Ensure bool is lower case in JSON if needed, or rely on Python json.dumps logic
        import json
        payload = {key: val}
        return json.dumps(payload).encode('utf-8') + b'\n'

    @staticmethod
    def student_sync_cmd(group_addr_hex: int, is_on: bool, mode_ac: bool = False, voltage_val: int = 850, current_val: int = 2500) -> bytes:
        """
        生成学生端同步指令 (Modbus RTU via TCP)
        参考数据包:
          ON (A2): A2 10 00 03 00 04 08 09 C4 03 52 00 01 00 00 FC 9E
        """
        slave_addr = group_addr_hex
        
        if is_on:
            # 开启指令: Write 4 Registers starting at 0x0003
            # Reg3: Current (current_val)
            # Reg4: Voltage (voltage_val)
            # Reg5: Control (1=On)
            
            start_addr = 0x0003
            quantity = 0x0004
            byte_count = 0x08
            
            # Payload: [CurHi, CurLo, VolHi, VolLo, CtrlHi, CtrlLo, ResHi, ResLo]
            # Fixed mapping based on analysis: Reg 3=Current, Reg 4=Voltage
            payload_data = struct.pack('>HHHH', current_val, voltage_val, 0x0001, 0x0000)
            
            # [Slave, Func(0x10), StartHi, StartLo, QtyHi, QtyLo, ByteCount, Data...]
            pdu = struct.pack('>BBHHB', slave_addr, 0x10, start_addr, quantity, byte_count) + payload_data
        else:
            # 关闭指令: Write 2 Registers starting at 0x0004
            # Reg4 & Reg5
            
            start_addr = 0x0004
            quantity = 0x0002
            byte_count = 0x04
            
            payload_data = struct.pack('>HH', 0x0000, 0x0000)
            
            pdu = struct.pack('>BBHHB', slave_addr, 0x10, start_addr, quantity, byte_count) + payload_data

        return pdu + crc16_modbus(pdu)

    @staticmethod
    def mingju_relay_cmd(relay_id: int, is_on: bool) -> bytes:
        """
        生成鸣驹继电器控制指令 (Modbus RTU)
        假设使用 功能码 0x05 (写单个线圈) 或 0x01 (自定义)
        鸣驹 MJ-E1S1 通常是: 
        打开第1路: 01 05 00 00 FF 00 8C 3A
        关闭第1路: 01 05 00 00 00 00 CD CA
        """
        slave_addr = 0x01 # 默认地址
        func_code = 0x05
        coil_addr = relay_id - 1 # 0-based
        data = 0xFF00 if is_on else 0x0000
        
        pdu = struct.pack('>BBHH', slave_addr, func_code, coil_addr, data)
        return pdu + crc16_modbus(pdu)

    @staticmethod
    def groups_modbus_tcp_cmd(addr: int, val: int) -> bytes:
        """
        Device D (Port 8234) Modbus TCP Cmd
        Func 0x06 Write Single Register
        """
        # Header: TransId(2) + Proto(2) + Len(2) + Unit(1)
        # PDU: Func(1) + Addr(2) + Val(2)
        trans_id = 0x0001
        proto = 0x0000
        length = 0x0006
        unit = 0x01
        func = 0x06
        
        header = struct.pack('>HHHB', trans_id, proto, length, unit)
        pdu = struct.pack('>BHH', func, addr, val)
        return header + pdu

    @staticmethod
    def teacher_power_cmd(val: bool, voltage_val: int = 0, current_val: int = 2000, is_ac: bool = False) -> bytes:
        """
        Device B (Port 8888) Teacher Power Control
        Logic: 
        LowKZ Trigger -> Send [Current, Voltage, Enable]
        If val (LowKZ) is True: Enable=1, Vol=UserVal, Cur=UserVal
        If val (LowKZ) is False: Enable=0
        
        Registers (Based on Student Protocol Reuse):
        Reg 3: Current (0.001A steps? 2.5A=2500 -> 2A=2000)
        Reg 4: Voltage (0.1V steps? 24.0V=2400? Or x100? Assuming x100 based on '850'=8.5V in old comment)
        Reg 5: Control (1=ON)
        """
        # Slave Address: 0x01 (Assuming Teacher Power is Slave 1, different from Student Groups)
        # OR using broadcast/specific ID if known. Typically single device on 8888 implies direct Modbus.
        # User didn't specify slave ID, assume 0x01 for Teacher Device.
        # UPDATE: User verified 192.168.0.211 uses A2/A1 protocol ID.
        slave = 0xA2 if is_ac else 0xA1
        
        # Adjust Values
        # Voltage: Web sends standard float (e.g. 12.5). Protocol expects int. 
        # Student logic used 850 for unknown V (maybe 8.5V?). Let's assume x100.
        # Current: Web sends float (e.g. 2.0). Logic used 2500 for 2.5A. So x1000.
        
        # However, caller passes processed ints? 
        # Let's ensure caller passes raw or processed. 
        # Looking at scanner '240' default. If 240V -> 24000? 
        # Actually Low Voltage is 0-30V. So 240 probably meant 24.0V if x10. Or 2.4V? 
        # Wait, previous default was 240. Maybe x10 = 24.0V? 
        # User just set default to 0. 
        
        # Let's assume caller handles main scaling or we verify here. 
        # Let's assume protocol is same as 'student_sync_cmd':
        # Reg3=Current, Reg4=Voltage, Reg5=1/0
        
        if val:
            # Turn ON
            ii = struct.pack('>H', int(current_val))
            vv = struct.pack('>H', int(voltage_val))
            
            # [Current(2), Voltage(2), 00 01, 00 00] -> Total 8 bytes data
            data_payload = ii + vv + b'\x00\x01\x00\x00'
            
            # Write 4 Regs starting at 0x0003
            pdu_head = struct.pack('>BBHHB', slave, 0x10, 0x0003, 0x0004, 0x08)
            pdu = pdu_head + data_payload
            return pdu + crc16_modbus(pdu)
        else:
            # Turn OFF (Write 0 to Reg 4, 5? Or just Reg 5?)
            # Student logic: Write 2 regs at 0x0004 (Voltage=0, Control=0)
            data_payload = b'\x00\x00\x00\x00'
            pdu_head = struct.pack('>BBHHB', slave, 0x10, 0x0004, 0x0002, 0x04)
            pdu = pdu_head + data_payload
            return pdu + crc16_modbus(pdu)

    @staticmethod
    def student_sync_broadcast_cmd(voltage_val: int, current_val: int, is_ac: bool, is_on: bool) -> list[bytes]:
        """
        Generate frames for Groups A, B, C, D
        """
        frames = []
        # Real Groups: A, B, C, D
        base_slaves_dc = [0xA1, 0xB1, 0xC1, 0xD1]
        base_slaves_ac = [0xA2, 0xB2, 0xC2, 0xD2]
        
        # Select slave IDs based on AC/DC mode
        target_slaves = base_slaves_ac if is_ac else base_slaves_dc

        # Prepare payload once
        if is_on:
             # User Correction: 
             # Reg 3 = Current (current_val)
             # Reg 4 = Voltage (voltage_val)
             
             ii = struct.pack('>H', current_val)
             vv = struct.pack('>H', voltage_val)
             
             data_payload = ii + vv + b'\x00\x01\x00\x00'
             
             # Head parts need slave insertion
             # Func 0x10, Addr 0x0003, Qty 0x0004, Bytes 0x08
             partial_head = struct.pack('>BHHB', 0x10, 0x0003, 0x0004, 0x08)
        else:
             data_payload = b'\x00\x00\x00\x00'
             partial_head = struct.pack('>BHHB', 0x10, 0x0004, 0x0002, 0x04)
        
        for slave in target_slaves:
            pdu = struct.pack('>B', slave) + partial_head + data_payload
            full_frame = pdu + crc16_modbus(pdu)
            frames.append(full_frame)
            
        return frames

class CommandExecutor:
    """执行器：负责 TCP 连接与发送"""
    
    @staticmethod
    async def send_one(ip: str, port: int, data: bytes, timeout: float = 1.0) -> bool:
        """短连接发送单条指令"""
        import socket
        writer = None
        try:
            print(f"DEBUG: Connecting to {ip}:{port}...")
            conn = asyncio.open_connection(ip, port)
            # 如果是 8234 端口，增加超时时间
            actual_timeout = 3.0 if port == 8234 else timeout
            reader, writer = await asyncio.wait_for(conn, timeout=actual_timeout)
            
            # 优化: 启用 TCP_NODELAY 以减少单条指令的延迟
            try:
                sock = writer.get_extra_info('socket')
                if sock:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except (OSError, AttributeError):
                pass  # 某些平台或 socket 类型不支持 TCP_NODELAY
                
            writer.write(data)
            await writer.drain()
            print(f"DEBUG: Sent {len(data)} bytes to {ip}:{port} -> {data.hex().upper()}")

            # 特殊处理：8888 教师电源端口也读取响应，方便调试
            if port == 8888 or port == 8234:
                try:
                    resp = await asyncio.wait_for(reader.read(1024), timeout=actual_timeout)
                    if resp:
                        print(f"DEBUG: Received {len(resp)} bytes from {ip}:{port} -> {resp.hex().upper()}")
                    else:
                        print(f"DEBUG: Received EMPTY response from {ip}:{port}")
                except asyncio.TimeoutError:
                    print(f"DEBUG: TIMEOUT waiting for response from {ip}:{port}")
                except Exception as e:
                     print(f"DEBUG: Error reading response from {ip}:{port}: {e}")

            # 特殊处理：8234 端口必须等待响应 (Handled above now)
            
            # 其它端口保持原样（不等待响应，或者如果之前被注释了就不读）
            # 注意：某些旧设备如果不读响应直接 Close 可能会 Drop 包
            
            try:
                writer.close()
                await writer.wait_closed()
            except Exception as close_err:
                # If close fails but write succeeded, consider it success (common in simple Modbus/TCP stacks)
                print(f"WARN: writer.close failed for {ip}:{port} - {close_err}")

            return True
        except Exception as e:
            print(f"ERROR: send_one failed to {ip}:{port} - {e}")
            if writer:
                try:
                    writer.close()
                except OSError:
                    pass
            return False

    @staticmethod
    async def send_batch_on_single_conn(ip: str, port: int, data_list: list[bytes], interval: float = 0.05) -> bool:
        """在一个 TCP 连接中发送多条指令"""
        import socket
        writer = None
        try:
            conn = asyncio.open_connection(ip, port)
            # 8234 端口增加超时
            actual_timeout = 3.0 if port == 8234 else 2.0
            reader, writer = await asyncio.wait_for(conn, timeout=actual_timeout)
            
            # 关键优化: 禁用 Nagle 算法 (TCP_NODELAY)
            try:
                sock = writer.get_extra_info('socket')
                if sock:
                    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            except (OSError, AttributeError):
                pass  # 某些平台或 socket 类型不支持 TCP_NODELAY

            for data in data_list:
                writer.write(data)
                await writer.drain()
                
                # 特殊处理：8234 端口必须同步等待响应
                if port == 8234:
                    try:
                        await asyncio.wait_for(reader.read(1024), timeout=2.0)
                    except (asyncio.TimeoutError, ConnectionError, OSError):
                        pass  # 响应超时或连接断开属正常情况
                
                if interval > 0:
                    await asyncio.sleep(interval)
            
            writer.close()
            await writer.wait_closed()
            return True
        except Exception as e:
            print(f"ERROR: send_batch failed to {ip}:{port} - {e}")
            if writer:
                try:
                    writer.close()
                except OSError:
                    pass
            return False

class StaggeredQueue:
    """错峰发送队列"""
    
    def __init__(self):
        self.queue = asyncio.Queue()
        self.is_running = False
        self.status_callback = None # 用于 WebSocket 回调
    
    async def add_task(self, ip, port, data_bytes):
        """
        Adapting to main.py usage: await queue_manager.add_task(dev["ip"], 8887, cmd)
        data_bytes can be bytes OR list[bytes]
        """
        task_info = {
            "ip": ip,
            "port": port,
            "data": data_bytes
        }
        await self.queue.put(task_info)
    
    async def start_worker(self, batch_size=5, delay_ms=100):
        self.is_running = True
        while self.is_running:
            # 尝试取出 batch_size 个任务
            batch = []
            try:
                # 阻塞等待第一个
                item = await self.queue.get()
                batch.append(item)
                
                # 非阻塞尝试取更多
                for _ in range(batch_size - 1):
                    if not self.queue.empty():
                        batch.append(self.queue.get_nowait())
                    else:
                        break
            except asyncio.CancelledError:
                break
            
            # 并发执行这一批
            if batch:
                asyncio.create_task(self._process_batch(batch))
                # 批次间延时
                await asyncio.sleep(delay_ms / 1000.0)

    async def _process_batch(self, batch):
        tasks = []
        for item in batch:
            tasks.append(self._execute_and_report(item))
        await asyncio.gather(*tasks)
        
    async def _execute_and_report(self, item):
        success = False
        data_payload = item['data']
        
        # Retry logic: Try up to 2 times
        for _ in range(2):
            if isinstance(data_payload, list):
                # 如果是命令列表，走批量发送(复用连接)
                success = await CommandExecutor.send_batch_on_single_conn(item['ip'], item['port'], data_payload, interval=0.02)
            else:
                # 单条发送
                success = await CommandExecutor.send_one(item['ip'], item['port'], data_payload, timeout=1.5)
            
            if success:
                break
            await asyncio.sleep(0.2)
            
        if self.status_callback:
            await self.status_callback(item['ip'], "success" if success else "error")

queue_manager = StaggeredQueue()
