"""Local demo server: the web UI plus two API routes that drive the real agent.

    python3 server/app.py            # http://127.0.0.1:8787

GET  /api/state              -> live mandate state, invoices, on-chain events
POST /api/run/<caseId>       -> the agent evaluates and acts: {"approve": bool}
POST /api/reset-invoices     -> re-issue the signed invoices (no chain writes)
"""
from __future__ import annotations

import json
import os
import sys
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web"
sys.path.insert(0, str(ROOT / "agent"))

from mandate import cli, config  # noqa: E402

LOCK = threading.Lock()
PORT = int(os.environ.get("PORT", "8787"))


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):  # quieter logs
        if "/api/" in (args[0] if args else ""):
            super().log_message(fmt, *args)

    def _json(self, payload, status=200):
        body = json.dumps(payload, default=str).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        self.send_header("cache-control", "no-store")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/api/state":
            try:
                with LOCK:
                    self._json(cli.build_payload())
            except Exception as exc:  # surfaced to the UI instead of a blank page
                self._json({"error": str(exc)}, 500)
            return
        if path == "/api/health":
            self._json({"ok": True})
            return
        return super().do_GET()

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("content-length") or 0)
        body = json.loads(self.rfile.read(length) or b"{}")
        try:
            if path.startswith("/api/run/"):
                case_id = path.rsplit("/", 1)[-1]
                with LOCK:
                    self._json(cli.run_case(case_id, approve=bool(body.get("approve"))))
                return
            if path == "/api/invoices":
                with LOCK:
                    cli.cmd_invoices(None)
                self._json({"ok": True})
                return
        except SystemExit as exc:
            self._json({"error": str(exc)}, 400)
            return
        except Exception as exc:
            self._json({"error": f"{type(exc).__name__}: {exc}"}, 500)
            return
        self._json({"error": "not found"}, 404)


def main():
    config.load_env()
    server = ThreadingHTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Aevum Mandate demo on http://127.0.0.1:{PORT}  (web root {WEB})")
    server.serve_forever()


if __name__ == "__main__":
    main()
