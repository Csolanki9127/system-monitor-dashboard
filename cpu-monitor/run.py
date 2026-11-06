import socket
import threading
import time
import webbrowser

import uvicorn


def find_free_port(start=8000, end=8100):
    for port in range(start, end):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                return port
            except OSError:
                continue
    raise RuntimeError("Koi free port nathi malyo")


def open_browser_when_ready(port):
    # Server chalu thay tya sudhi rah jove, pachi browser khole
    for _ in range(50):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) == 0:
                webbrowser.open(f"http://localhost:{port}")
                return
        time.sleep(0.2)


if __name__ == "__main__":
    port = find_free_port()
    print(f"System Monitor chalu thay che: http://localhost:{port}")
    threading.Thread(target=open_browser_when_ready, args=(port,), daemon=True).start()
    uvicorn.run("app:app", host="127.0.0.1", port=port)