"""
RS485 Manager v3.0 — TCP Socket 模式（通过以太网转485转换器通信）

架构:
  APK → TCP Socket → [Ethernet-RS485 转换器 IP:1053] → RS485 Bus → 固件 Serial RX

帧格式: JSON + '\n' (与固件 ProtocolHandler 对齐)
转换器只需透明转发 TCP 字节到 RS485，无需协议变更。

v3.0 改进:
  - 守护协程维持 TCP 连接状态缓存，消除每次 status() 调用的阻塞 socket 操作
  - converter_reachable 由后台 daemon 维护，零延迟读取
  - 10 秒保活间隔，确保 Android 网络波动下状态可靠

原 USB-Serial 模式备份: rs485_usb_backup.py
"""
import asyncio
import time as _time
from collections import deque
from typing import Optional, Dict, Any, List

_MAX_LOG = 100
_DAEMON_KEEPALIVE_INTERVAL = 10.0  # 守护协程保活间隔（秒）
_DAEMON_CONNECT_TIMEOUT = 2.0     # 守护协程连接超时（秒）


class RS485Manager:
    """通过以太网转485转换器发送 JSON-RPC 帧"""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._settings: Dict[str, Any] = {
            "enabled": False,
            "transport": "tcp",          # "tcp" = 以太网转485, "serial" = USB直连 (需 rs485_usb_backup.py)
            "tcp_host": "192.168.0.12",  # 以太网转485转换器 IP
            "tcp_port": 1053,            # 转换器 TCP 端口
            "timeout": 0.5,              # socket 连接超时(秒)
            "inter_frame_delay_ms": 20,
        }
        self._last_error: str = ""
        self._txlog: deque = deque(maxlen=_MAX_LOG)
        self._any_tx_ok: bool = False
        # ── v3.0 守护状态 ──
        self._converter_online: bool = False
        self._daemon_task: Optional[asyncio.Task] = None
        self._daemon_running: bool = False

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------
    def configure(self, settings: Dict[str, Any]) -> None:
        if not isinstance(settings, dict):
            return
        merged = dict(self._settings)
        merged.update(settings)
        self._settings = merged

    # ------------------------------------------------------------------
    # Daemon (v3.0) — 后台守护维持 TCP 连接状态缓存
    # ------------------------------------------------------------------
    def start_daemon(self) -> None:
        """启动守护协程，维持 converter_reachable 状态缓存（同步方法，必须在事件循环内调用）"""
        if self._daemon_running:
            return
        self._daemon_running = True
        self._daemon_task = asyncio.get_event_loop().create_task(self._daemon_loop())
        print("[RS485 Daemon] Started keepalive loop")

    async def stop_daemon(self) -> None:
        """停止守护协程"""
        self._daemon_running = False
        if self._daemon_task and not self._daemon_task.done():
            self._daemon_task.cancel()
            try:
                await self._daemon_task
            except asyncio.CancelledError:
                pass
        self._daemon_task = None
        self._converter_online = False
        print("[RS485 Daemon] Stopped")

    async def _daemon_loop(self) -> None:
        """守护循环：每10秒TCP连接到转换器并发送保活帧，维护 _converter_online 状态"""
        while self._daemon_running:
            if not self._settings.get("enabled", False):
                self._converter_online = False
                await asyncio.sleep(_DAEMON_KEEPALIVE_INTERVAL)
                continue

            host = str(self._settings.get("tcp_host", ""))
            port = int(self._settings.get("tcp_port", 1053))

            if not host:
                self._converter_online = False
                await asyncio.sleep(_DAEMON_KEEPALIVE_INTERVAL)
                continue

            was_online = self._converter_online
            try:
                reader, writer = await asyncio.wait_for(
                    asyncio.open_connection(host, port),
                    timeout=_DAEMON_CONNECT_TIMEOUT,
                )
                # 发送保活帧（空 JSON 对象，兼容协议格式）
                writer.write(b'{}\n')
                await writer.drain()
                try:
                    await asyncio.wait_for(reader.read(128), timeout=1.0)
                except (asyncio.TimeoutError, Exception):
                    pass
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
                self._converter_online = True
                self._last_error = ""
                if not was_online:
                    print(f"[RS485 Daemon] Converter {host}:{port} ONLINE")
            except Exception as e:
                self._converter_online = False
                if was_online:
                    print(f"[RS485 Daemon] Converter {host}:{port} OFFLINE: {e}")

            await asyncio.sleep(_DAEMON_KEEPALIVE_INTERVAL)

    # ------------------------------------------------------------------
    # Status / log access (v3.0 — 读取缓存，零延迟零阻塞)
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        converter_host = str(self._settings.get("tcp_host", ""))
        converter_port = int(self._settings.get("tcp_port", 1053))

        return {
            "enabled": bool(self._settings.get("enabled", False)),
            "transport": str(self._settings.get("transport", "tcp")),
            "tcp_host": converter_host,
            "tcp_port": converter_port,
            "converter_reachable": self._converter_online,
            "last_error": self._last_error,
            "recent_tx_ok": self._any_tx_ok,
        }

    def get_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        entries = list(self._txlog)
        entries.reverse()
        return entries[:limit]

    def _log_tx(
        self, tag: str, frame: bytes, ok: bool, elapsed_ms: float,
        error: str = "", response: str = "", attempts: int = 1,
        action: str = "", device: str = "", value: str = "",
    ) -> None:
        if ok:
            self._any_tx_ok = True
        self._txlog.append({
            "ts": _time.strftime("%H:%M:%S"),
            "_time": _time.time(),
            "tag": tag,
            "tx": frame.hex().upper(),
            "ok": ok,
            "ms": round(elapsed_ms, 1),
            "attempts": attempts,
            "rx": response,
            "error": error,
            "action": action,
            "device": device,
            "value": value,
            "protocol": "RS485/TCP",
        })

    # ------------------------------------------------------------------
    # Main send API (async, serialized, retry)
    # ------------------------------------------------------------------
    async def send_frame(
        self, frame: bytes,
        expect_response: bool = False,
        response_timeout: Optional[float] = None,
        retries: int = 2,
        tag: str = "",
        action: str = "", device: str = "", value: str = "",
    ) -> Dict[str, Any]:
        _tag = tag or "?"
        _frame = frame if isinstance(frame, bytes) else b""

        if not self._settings.get("enabled", False):
            self._last_error = "RS485 disabled"
            self._log_tx(_tag, _frame, False, 0.0, self._last_error,
                        action=action, device=device, value=value)
            return {"ok": False, "error": self._last_error}

        if not isinstance(frame, (bytes, bytearray)) or len(frame) == 0:
            self._last_error = "empty frame"
            self._log_tx(_tag, b"", False, 0.0, self._last_error,
                        action=action, device=device, value=value)
            return {"ok": False, "error": self._last_error}

        async with self._lock:
            last_error = ""
            attempts = 0
            t0 = _time.monotonic()
            for _ in range(max(1, retries)):
                attempts += 1
                result = await asyncio.to_thread(
                    self._send_frame_blocking,
                    bytes(frame), expect_response, response_timeout,
                )
                elapsed = (_time.monotonic() - t0) * 1000
                if result.get("ok"):
                    self._last_error = ""
                    self._log_tx(_tag, bytes(frame), True, elapsed,
                                response=result.get("response", ""), attempts=attempts,
                                action=action, device=device, value=value)
                    return result
                last_error = result.get("error", "unknown error")
                await asyncio.sleep(0.05)

            elapsed = (_time.monotonic() - t0) * 1000
            self._last_error = f"send failed after {attempts} attempts: {last_error}"
            self._log_tx(_tag, bytes(frame), False, elapsed, error=self._last_error,
                        attempts=attempts, action=action, device=device, value=value)
            return {"ok": False, "error": self._last_error}

    # ------------------------------------------------------------------
    # Blocking TCP send (runs in thread via asyncio.to_thread)
    # ------------------------------------------------------------------
    def _send_frame_blocking(
        self, frame: bytes,
        expect_response: bool,
        response_timeout: Optional[float],
    ) -> Dict[str, Any]:
        import socket

        host = str(self._settings.get("tcp_host", ""))
        port = int(self._settings.get("tcp_port", 1053))

        if not host:
            return {"ok": False, "error": "TCP host not configured"}

        timeout = (
            float(response_timeout)
            if response_timeout is not None
            else float(self._settings.get("timeout", 0.5))
        )

        sock = None
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect((host, port))
            sock.sendall(frame)

            if not expect_response:
                return {"ok": True}

            data = sock.recv(256)
            return {"ok": True, "response": data.hex().upper() if data else ""}
        except Exception as e:
            return {"ok": False, "error": str(e)}
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception:
                    pass


rs485_manager = RS485Manager()
