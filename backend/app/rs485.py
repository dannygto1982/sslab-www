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
            return {"ok": False, "error": str(e)}
        finally:
            if ser is not None:
                try:
                    ser.close()
                except Exception:
                    pass


rs485_manager = RS485Manager()
