"""
Entry point: starts API server and optionally the web dashboard.
  - API server    → port 5000
  - Web dashboard → port 5001 (if DASHBOARD=true)
"""

import logging
import multiprocessing
import os
import sys
import time

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("run")

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def run_api():
    sys.path.insert(0, BASE_DIR)
    from api.server import app
    logger.info("Starting API server on http://0.0.0.0:5000 …")
    app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)


def run_web():
    sys.path.insert(0, BASE_DIR)
    from web.app import app
    logger.info("Starting Web dashboard on http://0.0.0.0:5001 …")
    app.run(host="0.0.0.0", port=5001, debug=False, use_reloader=False)


if __name__ == "__main__":
    os.makedirs(os.path.join(BASE_DIR, "uploads"), exist_ok=True)

    dashboard_enabled = os.environ.get("DASHBOARD", "true").lower() == "true"
    debug_enabled = os.environ.get("DEBUG", "false").lower() == "true"

    processes = []

    api_proc = multiprocessing.Process(target=run_api, name="api-server", daemon=True)
    api_proc.start()
    processes.append(api_proc)
    logger.info("API server process started (PID %d).", api_proc.pid)

    if dashboard_enabled:
        time.sleep(1)
        web_proc = multiprocessing.Process(target=run_web, name="web-dashboard", daemon=True)
        web_proc.start()
        processes.append(web_proc)
        logger.info("Web dashboard process started (PID %d).", web_proc.pid)

    print("\n" + "=" * 56)
    print("  TikTok Uploader is running!")
    print(f"  API server:    http://127.0.0.1:5000")
    if dashboard_enabled:
        print(f"  Web dashboard: http://127.0.0.1:5001")
    else:
        print("  Web dashboard: DISABLED")
    print(f"  VNC:           {'ENABLED' if debug_enabled else 'DISABLED'}")
    print("  Press Ctrl+C to stop.")
    print("=" * 56 + "\n")

    try:
        for p in processes:
            p.join()
    except KeyboardInterrupt:
        logger.info("Shutting down…")
        for p in processes:
            p.terminate()
        for p in processes:
            p.join(timeout=5)
        logger.info("All processes stopped.")
        sys.exit(0)
