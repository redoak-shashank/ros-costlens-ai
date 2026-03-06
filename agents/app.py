"""
AgentCore Runtime Entry Point — Billing Intelligence System.

Uses raw http.server (stdlib) for instant cold start.
Implements the two endpoints AgentCore Runtime expects:
  - GET  /ping         → health check
  - POST /invocations  → agent logic
"""

import json
import logging
import os
import sys
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler

# ── Logging to STDOUT (AgentCore uses OTEL which captures stdout) ────────────
logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    stream=sys.stdout,        # OTEL captures stdout, not stderr
    force=True,               # Override any pre-configured handlers
)
# Also make all loggers propagate to root so everything hits stdout
logging.getLogger().handlers[0].stream = sys.stdout
logger = logging.getLogger("agentcore-billing")

PORT = int(os.environ.get("PORT", "8080"))

# Ensure the zip root is on sys.path so "src" package can be found
ZIP_ROOT = os.path.dirname(os.path.abspath(__file__))
if ZIP_ROOT not in sys.path:
    sys.path.insert(0, ZIP_ROOT)


def _log(msg: str):
    """Write to both logger AND print to stdout with flush.
    AgentCore OTEL collects stdout; this ensures logs appear in CloudWatch."""
    logger.info(msg)
    print(f"[agentcore-billing] {msg}", flush=True)


# ── Lazy-loaded handler ──────────────────────────────────────────────────────
_handler = None


def get_handler():
    """Lazy-load the business-logic handler on first invocation."""
    global _handler
    if _handler is None:
        _log("Loading billing intelligence handler...")
        from src.app import handler
        _handler = handler
        _log("Handler loaded successfully.")
    return _handler


# ── HTTP Server ──────────────────────────────────────────────────────────────

class AgentHandler(BaseHTTPRequestHandler):
    """Minimal HTTP handler for AgentCore Runtime protocol."""

    def do_GET(self):
        """Health check endpoint."""
        if self.path == "/ping":
            self._respond(200, {"status": "healthy"})
        else:
            self._respond(404, {"error": "not found"})

    def do_POST(self):
        """Invocation endpoint."""
        if self.path != "/invocations":
            self._respond(404, {"error": "not found"})
            return

        try:
            length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(length) if length else b""
            payload = json.loads(body) if body else {}

            _log("Invocation payload: %s" % str(payload)[:500])

            handler_fn = get_handler()
            result = handler_fn(payload)

            _log("Invocation result keys: %s" % list(result.keys()) if isinstance(result, dict) else "non-dict")
            self._respond(200, result)

        except Exception as e:
            tb = traceback.format_exc()
            _log("Invocation error: %s\n%s" % (e, tb))
            # Return 200 with error details so we can debug
            # (AgentCore swallows 500 response bodies)
            self._respond(200, {
                "status": "error",
                "error_type": type(e).__name__,
                "message": str(e),
                "traceback": tb,
            })

    def _respond(self, code: int, body: dict):
        """Send a JSON response."""
        data = json.dumps(body, default=str).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, fmt, *args):
        """Route access logs through our logger."""
        logger.debug(fmt, *args)


# ── Start server ─────────────────────────────────────────────────────────────
_log("Starting AgentCore billing server on port %d ..." % PORT)
_log("Working directory: %s" % os.getcwd())
_log("sys.path: %s" % sys.path[:5])
_log("Environment keys: %s" % [k for k in sorted(os.environ.keys()) if not k.startswith("_")])
server = HTTPServer(("0.0.0.0", PORT), AgentHandler)
_log("Server ready — listening on port %d" % PORT)
server.serve_forever()
