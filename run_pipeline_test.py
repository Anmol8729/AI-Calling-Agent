import subprocess
import time
import os
import sys

def main():
    print("Starting FastAPI backend...")
    # Use python executable from current virtualenv if active
    python_bin = sys.executable
    
    # Start backend server
    backend_proc = subprocess.Popen(
        [python_bin, "-m", "backend.app"],
        text=True,
        bufsize=1
    )
    
    # Give server 4 seconds to boot up and connect to DB
    time.sleep(4.0)
    
    # Check if backend crashed immediately
    if backend_proc.poll() is not None:
        print("❌ Backend crashed on startup!")
        return
        
    print("Backend server is running. Running test_websocket.py...")
    
    # Run test script
    test_proc = subprocess.run(
        [python_bin, "test_websocket.py"],
        capture_output=True,
        text=True
    )
    
    print("\n--- test_websocket.py Output ---")
    print(test_proc.stdout)
    print(test_proc.stderr)
    print("--------------------------------")
    
    # Terminate backend
    print("Stopping FastAPI backend...")
    backend_proc.terminate()
    try:
        backend_proc.wait(timeout=2.0)
    except subprocess.TimeoutExpired:
        backend_proc.kill()
        backend_proc.wait()

if __name__ == "__main__":
    main()
