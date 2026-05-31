
import asyncio
import struct
import logging
from app.devices import DeviceProtocol

logger = logging.getLogger("server_8887")

class StudentSyncServer:
    def __init__(self):
        self.server = None
        self.clients = {}  # {addr: writer}

    async def start_server(self):
        try:
            self.server = await asyncio.start_server(
                self.handle_client, '0.0.0.0', 8887
            )
            addr = self.server.sockets[0].getsockname()
            print(f"[Server-8887] Listening on {addr}")
            
            async with self.server:
                await self.server.serve_forever()
        except Exception as e:
            print(f"[Server-8887] Start failed: {e}")

    async def handle_client(self, reader, writer):
        addr = writer.get_extra_info('peername')
        print(f"[Server-8887] Accepted connection from {addr}")
        self.clients[addr] = writer
        
        try:
            while True:
                # Keep connection alive, maybe read heartbeat if protocol has one
                # For now just wait for data or disconnect
                data = await reader.read(1024)
                if not data:
                    break
        except Exception as e:
            print(f"[Server-8887] Error with client {addr}: {e}")
        finally:
            print(f"[Server-8887] Closing connection {addr}")
            writer.close()
            if addr in self.clients:
                del self.clients[addr]

    async def broadcast_sync_cmd(self, cmd: bytes, target_ip="192.168.0.12"):
        """
        Send command to specific connected client or all
        The requirement specifically mentions waiting for 192.168.0.12
        """
        target_writer = None
        
        # Find the specific client
        for addr, writer in self.clients.items():
            if addr[0] == target_ip:
                target_writer = writer
                break
        
        if target_writer:
            try:
                print(f"[Server-8887] Sending Sync Cmd to {target_ip}")
                target_writer.write(cmd)
                await target_writer.drain()
            except Exception as e:
                print(f"[Server-8887] Send error to {target_ip}: {e}")
        else:
            print(f"[Server-8887] Target {target_ip} not connected.")

# Singleton instance
student_server = StudentSyncServer()
