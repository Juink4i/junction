"""Run a Starlette app in a background thread. Used by the demo and the tests."""

from __future__ import annotations

import socket
import threading
import time
from dataclasses import dataclass

import uvicorn


@dataclass
class Running:
    server: uvicorn.Server
    thread: threading.Thread
    port: int

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=5)


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def port_open(port: int, host: str = "127.0.0.1") -> bool:
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex((host, port)) == 0


def run_in_thread(app, port: int | None = None, host: str = "127.0.0.1") -> Running:
    port = port or free_port()
    config = uvicorn.Config(app, host=host, port=port, log_level="warning", lifespan="on")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.time() + 10
    while not server.started:
        if time.time() > deadline or not thread.is_alive():
            raise RuntimeError(f"Server on port {port} did not start.")
        time.sleep(0.05)
    return Running(server, thread, port)
