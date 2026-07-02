"""
Entry point used by the PyInstaller-frozen api sidecar.

The source-mode workflow launches uvicorn via the CLI
(`uvicorn api:app --port 8000`), which discovers `api:app` at runtime by
string. That doesn't survive freezing — PyInstaller inlines exactly the
modules it can see at build time, and passing a module:name string means
uvicorn tries to re-import from the source tree at runtime and can't find
it. Handing uvicorn the imported `app` object directly avoids the
lookup entirely.

Port 8765 (not 8000) so a running packaged app doesn't collide with a dev
uvicorn on 8000.
"""

import uvicorn

from api import app


if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8765, log_level="warning")
