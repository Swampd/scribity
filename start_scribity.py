"""
Start Scribity without relying on macOS .command executable permissions.

Run this with Python 3 from the Scribity folder. On macOS, opening this file
with Python Launcher avoids the Git executable-bit problem that can affect
scribity.command.
"""

import os
import subprocess
import sys
import threading
import time
import webbrowser


PORT = 8000
URL = f"http://localhost:{PORT}"


def open_browser():
    time.sleep(2)
    webbrowser.open(URL)


def main():
    app_dir = os.path.dirname(os.path.abspath(__file__))
    os.chdir(app_dir)

    print("============================================")
    print("       SCRIBITY - Starting Up...")
    print("============================================")
    print()
    print(f"Starting server at {URL}")
    print("Press Ctrl+C to stop the server.")
    print()

    threading.Thread(target=open_browser, daemon=True).start()

    server_path = os.path.join(app_dir, "scribity_server.py")
    try:
        subprocess.run([sys.executable, server_path], check=False)
    except KeyboardInterrupt:
        print("\nScribity stopped.")


if __name__ == "__main__":
    main()
