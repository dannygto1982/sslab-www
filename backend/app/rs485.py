import asyncio
import time as _time
from collections import deque
from typing import Optional, Dict, Any, List

_MAX_LOG = 100


class RS485Manager:
    """Single-channel RS485 sender with serialized access, retry support,
    per-transaction logging and graceful rollback flags."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self._settings: Dict[str, Any] = {
            "enabled": False,
            "port": "COM3",
            "baudrate": 9600,
            "bytesize": 8,
            "parity": "N",
            "stopbits": 1,
            "timeout": 0.25,
            "inter_frame_delay_ms": 20,
        }
        self._last_error: str = ""
        self._txlog: deque = deque(maxlen=_MAX_LOG)
        # Auto-redetect flag: set when port fails with an access/not-found error
        self._needs_redetect: bool = False

    @property
    def needs_redetect(self) -> bool:
        return self._needs_redetect

    def clear_redetect(self) -> None:
        self._needs_redetect = False

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
    # Status / log access
    # ------------------------------------------------------------------
    def status(self) -> Dict[str, Any]:
        return {
            "enabled": bool(self._settings.get("enabled", False)),
            "port": str(self._settings.get("port", "")),
            "baudrate": int(self._settings.get("baudrate", 9600)),
            "last_error": self._last_error,
        }

    def get_log(self, limit: int = 50) -> List[Dict[str, Any]]:
        """Return the most recent *limit* transaction records (newest first)."""
        entries = list(self._txlog)
        entries.reverse()
        return entries[:limit]

    def _log_tx(
        self,
        tag: str,
        frame: bytes,
        ok: bool,
        elapsed_ms: float,
        error: str = "",
        response: str = "",
        attempts: int = 1,
    ) -> None:
        self._txlog.append(
            {
                "ts": _time.strftime("%H:%M:%S"),
                "tag": tag,
                "tx": frame.hex().upper(),
                "ok": ok,
                "ms": round(elapsed_ms, 1),
                "attempts": attempts,
                "rx": response,
                "error": error,
            }
        )

    async def send_frame(
        self,
        frame: bytes,
        expect_response: bool = False,
        response_timeout: Optional[float] = None,
        retries: int = 2,
        tag: str = "",
    ) -> Dict[str, Any]:
        if not self._settings.get("enabled", False):
            self._last_error = "RS485 disabled"
            self._log_tx(tag or "?", frame if isinstance(frame, bytes) else b"", False, 0.0, self._last_error)
            return {"ok": False, "error": self._last_error}

        if not isinstance(frame, (bytes, bytearray)) or len(frame) == 0:
            self._last_error = "empty frame"
            self._log_tx(tag or "?", b"", False, 0.0, self._last_error)
            return {"ok": False, "error": self._last_error}

        async with self._lock:
            last_error = ""
            attempts = 0
            t0 = _time.monotonic()
            for _ in range(max(1, retries)):
                attempts += 1
                result = await asyncio.to_thread(
                    self._send_frame_blocking,
                    bytes(frame),
                    expect_response,
                    response_timeout,
                )
                elapsed = (_time.monotonic() - t0) * 1000
                if result.get("ok"):
                    self._last_error = ""
                    self._log_tx(tag or "?", bytes(frame), True, elapsed, response=result.get("response", ""), attempts=attempts)
                    return result

                last_error = result.get("error", "unknown error")
                await asyncio.sleep(0.05)

            elapsed = (_time.monotonic() - t0) * 1000
            self._last_error = f"send failed after {attempts} attempts: {last_error}"
            self._log_tx(tag or "?", bytes(frame), False, elapsed, error=self._last_error, attempts=attempts)
            return {"ok": False, "error": self._last_error}

    def _send_frame_blocking(
        self,
        frame: bytes,
        expect_response: bool,
        response_timeout: Optional[float],
    ) -> Dict[str, Any]:
        try:
            import serial  # type: ignore
        except Exception as e:
            return {"ok": False, "error": f"pyserial not available: {e}"}

        parity_map = {
            "N": serial.PARITY_NONE,
            "E": serial.PARITY_EVEN,
            "O": serial.PARITY_ODD,
        }
        stopbits_map = {
            1: serial.STOPBITS_ONE,
            2: serial.STOPBITS_TWO,
        }

        timeout = (
            float(response_timeout)
            if response_timeout is not None
            else float(self._settings.get("timeout", 0.25))
        )

        ser = None
        try:
            ser = serial.Serial(
                port=str(self._settings.get("port", "COM3")),
                baudrate=int(self._settings.get("baudrate", 9600)),
                bytesize=int(self._settings.get("bytesize", 8)),
                parity=parity_map.get(str(self._settings.get("parity", "N")).upper(), serial.PARITY_NONE),
                stopbits=stopbits_map.get(int(self._settings.get("stopbits", 1)), serial.STOPBITS_ONE),
                timeout=timeout,
                write_timeout=timeout,
            )

            ser.reset_input_buffer()
            ser.write(frame)
            ser.flush()

            delay = float(self._settings.get("inter_frame_delay_ms", 20)) / 1000.0
            if delay > 0:
                import time

                time.sleep(delay)

            if not expect_response:
                return {"ok": True}

            data = ser.read(256)
            return {"ok": True, "response": data.hex().upper() if data else ""}
        except Exception as e:
            err_str = str(e).lower()
            # Port not accessible → request automatic re-detection
            _PORT_ERRS = (
                "cannot open", "could not open", "access is denied",
                "no such file", "filenotfound", "winerror 2", "winerror 5",
                "permission denied", "device or resource busy",
                "the system cannot find", "port not found",
            )
            if any(x in err_str for x in _PORT_ERRS):
                self._needs_redetect = True
            return {"ok": False, "error": str(e)}
        finally:
            if ser is not None:
                try:
                    ser.close()
                except OSError:
                    pass  # Serial port close may fail if already disconnected


    # ------------------------------------------------------------------
    # COM Port Discovery
    # ------------------------------------------------------------------
    def list_ports(self):
        """Return a list of available serial ports with description and hwid."""
        try:
            from serial.tools import list_ports  # type: ignore
            ports = []
            for p in sorted(list_ports.comports(), key=lambda x: x.device):
                ports.append({
                    "port": p.device,
                    "description": p.description or "",
                    "hwid": p.hwid or "",
                })
            return {"ok": True, "ports": ports}
        except Exception as e:
            return {"ok": False, "ports": [], "error": str(e)}

    def auto_detect_port(self, baudrate: int = 9600, test_frame: bytes = b"",
                          exclude: list = None) -> Dict[str, Any]:
        """Scan all available COM ports and return the first one that opens
        successfully at the given baud rate.  Ports in the *exclude* list and
        ports matching Bluetooth patterns are skipped automatically.

        A lifting 'stop' frame is sent as a no-op probe; we only check that the
        port opens without raising SerialException.
        """
        try:
            import serial  # type: ignore
            from serial.tools import list_ports  # type: ignore
        except Exception as e:
            return {"ok": False, "error": f"pyserial not available: {e}", "port": None}

        # Build a safe test frame if caller didn't provide one
        if not test_frame:
            try:
                from app.protocol_485 import build_lifting_frame
                test_frame = build_lifting_frame("stop")
            except Exception:
                test_frame = b""

        # Skip-patterns: lowercase substrings in description or hwid
        _SKIP = ("bluetooth", "bth")
        _EXCL = {e.upper() for e in (exclude or [])}

        candidates = sorted(list_ports.comports(), key=lambda x: x.device)
        tried = []
        for p in candidates:
            # Exclusion list (e.g. COM5=Android monitor, COM16=firmware DL)
            if p.device.upper() in _EXCL:
                tried.append({"port": p.device, "skipped": True, "reason": "excluded"})
                continue
            desc_lower = (p.description or "").lower()
            hwid_lower = (p.hwid or "").lower()
            if any(s in desc_lower or s in hwid_lower for s in _SKIP):
                tried.append({"port": p.device, "skipped": True, "reason": "bluetooth"})
                continue
            try:
                ser = serial.Serial(
                    port=p.device,
                    baudrate=baudrate,
                    bytesize=8,
                    parity=serial.PARITY_NONE,
                    stopbits=serial.STOPBITS_ONE,
                    timeout=0.2,
                    write_timeout=0.2,
                )
                if test_frame:
                    ser.reset_input_buffer()
                    ser.write(test_frame)
                    ser.flush()
                ser.close()
                tried.append({"port": p.device, "skipped": False, "ok": True})
                return {"ok": True, "port": p.device, "tried": tried,
                        "description": p.description or ""}
            except Exception as ex:
                tried.append({"port": p.device, "skipped": False, "ok": False, "error": str(ex)})
                continue

        return {"ok": False, "port": None, "tried": tried,
                "error": "no suitable COM port found"}


rs485_manager = RS485Manager()
