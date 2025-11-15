#!/usr/bin/env python3
"""
Cross-platform startup script for the Drone Swarm application.
Starts both the backend (FastAPI) and frontend (Vite) servers.
"""
import subprocess
import sys
import os
import time
import signal
from pathlib import Path

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent
BACKEND_DIR = PROJECT_ROOT / "backend"
FRONTEND_DIR = PROJECT_ROOT / "frontend"
VENV_DIR = PROJECT_ROOT / "venv"

def get_venv_python():
    """Get the Python executable from the virtual environment."""
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    else:
        return VENV_DIR / "bin" / "python"

def setup_venv():
    """Create and setup a virtual environment if it doesn't exist."""
    venv_python = get_venv_python()
    
    if not VENV_DIR.exists():
        print("Creating virtual environment...")
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)], check=True)
        print("✓ Virtual environment created")
    
    # Install/upgrade pip in venv
    print("Setting up virtual environment...")
    subprocess.run([str(venv_python), "-m", "pip", "install", "--upgrade", "pip"], 
                   check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    
    return venv_python

def check_dependencies():
    """Check if required dependencies are installed."""
    print("Checking dependencies...")
    
    # Check Python
    if sys.version_info < (3, 8):
        print("ERROR: Python 3.8 or higher is required")
        sys.exit(1)
    
    # Setup virtual environment
    venv_python = setup_venv()
    
    # Check if backend dependencies are installed in venv
    try:
        result = subprocess.run(
            [str(venv_python), "-c", "import fastapi; import uvicorn"],
            capture_output=True,
            check=True
        )
    except subprocess.CalledProcessError:
        print("Installing backend dependencies in virtual environment...")
        subprocess.run(
            [str(venv_python), "-m", "pip", "install", "-r", str(BACKEND_DIR / "requirements.txt")],
            check=True
        )
    
    # Check if Node.js is installed
    try:
        subprocess.run(["node", "--version"], capture_output=True, check=True)
    except (subprocess.CalledProcessError, FileNotFoundError):
        print("ERROR: Node.js is not installed. Please install Node.js from https://nodejs.org/")
        sys.exit(1)
    
    # Check if frontend dependencies are installed
    if not (FRONTEND_DIR / "node_modules").exists():
        print("Installing frontend dependencies...")
        subprocess.run(["npm", "install"], cwd=FRONTEND_DIR, check=True)
    
    print("✓ All dependencies are ready")
    print(f"✓ Using virtual environment: {VENV_DIR}\n")

def start_servers():
    """Start both backend and frontend servers."""
    processes = []
    venv_python = get_venv_python()
    
    try:
        # Start backend
        print("Starting backend server on http://localhost:8000...")
        backend_process = subprocess.Popen(
            [str(venv_python), "-m", "uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"],
            cwd=BACKEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        processes.append(backend_process)
        
        # Wait a bit for backend to start
        time.sleep(2)
        
        # Start frontend
        print("Starting frontend server on http://localhost:5173...")
        frontend_process = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=FRONTEND_DIR,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        processes.append(frontend_process)
        
        print("\n" + "="*60)
        print("✓ Both servers are running!")
        print("="*60)
        print("Backend API:  http://localhost:8000")
        print("Frontend UI:  http://localhost:5173")
        print("\nPress Ctrl+C to stop both servers")
        print("="*60 + "\n")
        
        # Wait for processes
        try:
            # Print output from both processes
            while True:
                for proc in processes:
                    if proc.poll() is not None:
                        print(f"\nProcess exited with code {proc.returncode}")
                        raise KeyboardInterrupt
                time.sleep(0.1)
        except KeyboardInterrupt:
            print("\n\nStopping servers...")
            for proc in processes:
                proc.terminate()
            time.sleep(1)
            for proc in processes:
                if proc.poll() is None:
                    proc.kill()
            print("✓ Servers stopped")
    
    except Exception as e:
        print(f"\nERROR: {e}")
        for proc in processes:
            if proc.poll() is None:
                proc.terminate()
        sys.exit(1)

if __name__ == "__main__":
    os.chdir(PROJECT_ROOT)
    check_dependencies()
    start_servers()

