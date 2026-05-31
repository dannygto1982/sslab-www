import sys
import os
import uvicorn
import multiprocessing

# Add backend to path so imports work
current_dir = os.path.dirname(os.path.abspath(__file__))
backend_path = os.path.join(current_dir, 'backend')
if os.path.exists(backend_path):
    sys.path.insert(0, backend_path)

# For PyInstaller: import needs to be resolvable relative to this script or bundled
if getattr(sys, 'frozen', False):
    # If frozen, the backend code is likely bundled.
    # We might not need path insertion if analysis found it.
    pass

if __name__ == "__main__":
    multiprocessing.freeze_support() # Needed for win exe
    
    # Set proper asyncio loop policy for Windows to avoid issues with sockets/subprocesses
    import asyncio
    import platform
    if platform.system() == 'Windows':
        # On Python 3.8+, Proactor is default, but Selector is often more stable for 
        # complex socket ops in some tools. However, for connect calls, Proactor is fine.
        # But if we encountered 10048 or other weirdness, explicit Selector might help.
        # Given debug_real_scan worked with Selector, let's use it.
        try:
            asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
        except Exception:
            pass

    try:
        from app.main import app
    except ImportError:
        # Fallback if structure is flat in dist
        import app.main
        app = app.main.app

    print("Starting Control System Server...")
    # Bind to 0.0.0.0:1880
    uvicorn.run(app, host="0.0.0.0", port=1880, log_level="info")
