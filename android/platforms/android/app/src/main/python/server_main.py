"""
Android embedded Python server entry point.
Starts FastAPI backend with automatic port detection.
Returns actual port so Java can poll the correct address.
"""
import threading
import socket
import uvicorn
from main import app

_server_port = 0


def start_server(port=1880):
    """Find a free port in range, start uvicorn in daemon thread, return actual port."""
    global _server_port

    # Find first free port
    for attempt in range(6):
        p = port + attempt
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", p))
            s.close()
            _server_port = p
            break
        except OSError:
            continue

    if _server_port == 0:
        raise RuntimeError(
            f"No free port in range {port}-{port + 5}. "
            "Force-stop the app and try again."
        )

    print(f"[Server] Starting uvicorn on 127.0.0.1:{_server_port}")

    def _run():
        uvicorn.run(
            app,
            host="127.0.0.1",
            port=_server_port,
            reload=False,
            log_level="info",
        )

    t = threading.Thread(target=_run, daemon=True)
    t.start()

    return _server_port


def get_port():
    return _server_port
