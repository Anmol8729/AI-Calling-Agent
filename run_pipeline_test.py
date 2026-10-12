"""Integration diagnostic test runner for the Clarivo backend and WebSocket services.

Launches (or attaches to) the FastAPI backend, tests /health probe, runs test_websocket.py,
and reports full diagnostic health.

Usage:
    python run_pipeline_test.py
"""

import subprocess
import time
import os
import sys
import urllib.request
import urllib.error

HEALTH_URL = "http://127.0.0.1:8000/health"


def is_backend_healthy() -> bool:
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=3) as resp:
            return resp.status == 200
    except Exception:
        return False


def main():
    python_bin = sys.executable
    launched_subproc = None

    if is_backend_healthy():
        print("✅ Backend is already running and healthy at http://127.0.0.1:8000")
    else:
        print("Starting FastAPI backend process for integration testing...")
        launched_subproc = subprocess.Popen(
            [python_bin, "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1", "--port", "8000"],
            text=True,
            bufsize=1
        )
        # Give server time to boot up and connect to DB
        for attempt in range(10):
            time.sleep(1.0)
            if is_backend_healthy():
                print(f"✅ Backend booted and healthy after {attempt + 1}s!")
                break
            if launched_subproc.poll() is not None:
                print("❌ Backend crashed on startup!")
                return

        if not is_backend_healthy():
            print("❌ Backend did not become healthy in time.")
            if launched_subproc:
                launched_subproc.terminate()
            return

    print("\nRunning WebSocket integration & security test (test_websocket.py)...")
    test_proc = subprocess.run(
        [python_bin, "test_websocket.py"],
        capture_output=True,
        text=True
    )

    print("\n--- test_websocket.py Output ---")
    print(test_proc.stdout)
    if test_proc.stderr:
        print(test_proc.stderr)
    print("--------------------------------")

    if launched_subproc:
        print("Stopping temporary FastAPI backend process...")
        launched_subproc.terminate()
        try:
            launched_subproc.wait(timeout=3.0)
        except subprocess.TimeoutExpired:
            launched_subproc.kill()
            launched_subproc.wait()
        print("Backend process stopped.")


if __name__ == "__main__":
    main()
