"""Start the demo screens.

    uv run python -m web                 # http://localhost:8080 , phones on the same Wi-Fi too
    uv run python -m web --local         # this computer only
"""

from __future__ import annotations

import argparse
import os
import socket

import uvicorn

from web.app import create_app


def lan_ip() -> str | None:
    """This computer's address on the local network, for phones on the same Wi-Fi."""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # no packet is sent
            ip = s.getsockname()[0]
        return None if ip.startswith("127.") else ip
    except OSError:
        return None


def phone_url(port: int, local: bool) -> str:
    ip = None if local else lan_ip()
    return f"http://{ip or 'localhost'}:{port}/approvals"


def main() -> None:
    ap = argparse.ArgumentParser(description="Approval, log and chat pages.")
    ap.add_argument("--port", type=int, default=int(os.environ.get("WEB_PORT", 8080)))
    ap.add_argument("--trade", default=os.environ.get("TRADE_HTTP_URL", "http://localhost:8000"),
                    help="Trade server base URL (Contract B HTTP endpoints).")
    ap.add_argument("--local", action="store_true", help="Only accept connections from this computer.")
    args = ap.parse_args()

    os.environ.setdefault("PHONE_URL", phone_url(args.port, args.local))
    print(f"Stage view:  http://localhost:{args.port}/")
    print(f"Approvals:   {os.environ['PHONE_URL']}   (open this on the phone)")
    print(f"Log:         http://localhost:{args.port}/log")
    print(f"Trade server: {args.trade}")
    uvicorn.run(create_app(args.trade), host="127.0.0.1" if args.local else "0.0.0.0", port=args.port,
                log_level="warning", timeout_graceful_shutdown=2)


if __name__ == "__main__":
    main()
