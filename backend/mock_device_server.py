import asyncio
import socket

async def handle_client(reader, writer):
    addr = writer.get_extra_info('peername')
    print(f"Connection from {addr}")

    try:
        data = await reader.read(1024)
        if data:
            # 简单的 Modbus 响应模拟
            # 无论什么请求，都回复一个简单的 Mock 响应
            print(f"Received {len(data)} bytes from {addr}")
            
            # 模拟处理延时
            await asyncio.sleep(0.05) 
            
            # 回复 (随意构造几个字节)
            writer.write(b'\x01\x10\x00\x04\x00\x02\xE1\xCD') # Mock Response
            await writer.drain()
    except Exception as e:
        print(f"Error handling {addr}: {e}")
    finally:
        writer.close()
        await writer.wait_closed()

async def start_mock_server(port, name="Device"):
    server = await asyncio.start_server(handle_client, '127.0.0.1', port)
    addr = server.sockets[0].getsockname()
    print(f"[*] Mock {name} serving on {addr}")
    async with server:
        await server.serve_forever()

async def main():
    # 本地模拟:
    # 模拟一个学生端 (Port 8887)
    # 模拟一个控制端 (Port 1053)
    # 注意: 真实的 Scanner 是扫 10.168.1.x 的，
    # 为了让 Scanner 能扫到本地模拟器，我们需要临时修改 scanner.py 
    # 让它去扫 127.0.0.1 这里的端口。
    
    t1 = asyncio.create_task(start_mock_server(8887, "Student (Ebyte)"))
    t2 = asyncio.create_task(start_mock_server(1053, "Control (Mingju)"))
    
    await asyncio.gather(t1, t2)

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
