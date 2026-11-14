import os

import uvicorn

from server.app import build_http_app

if __name__ == "__main__":
    uvicorn.run(
        build_http_app(),
        host=os.environ.get("SERVER_HOST", "127.0.0.1"),
        port=int(os.environ.get("SERVER_PORT", "8000")),
    )
