"""
Android embedded Python server entry point.
Starts FastAPI backend on localhost:1880.
"""
import uvicorn
from main import app


def start_server(port=1880):
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=port,
        reload=False,
        log_level="info"
    )


if __name__ == "__main__":
    start_server()
