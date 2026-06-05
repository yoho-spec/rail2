"""
utils/keep_alive.py
Railway requires your app to bind to a PORT — otherwise it marks the
deploy as failed. This module:
  1. Starts a lightweight HTTP server on PORT so Railway sees a live service
  2. The separate Railway cron service pings /health every 10 minutes

Railway does NOT spin down paid services, but the free $5 credit tier
can sleep — the cron ping prevents that.
"""
import asyncio
import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger(__name__)

PORT = int(os.environ.get("PORT", 8080))


class HealthHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path in ("/", "/health"):
            self.send_response(200)
            self.send_header("Content-Type", "text/plain")
            self.end_headers()
            self.wfile.write(b"Archiver Bot is running OK")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress HTTP server logs


def _run_http_server():
    server = HTTPServer(("0.0.0.0", PORT), HealthHandler)
    logger.info(f"✅ Health server running on port {PORT}")
    server.serve_forever()


def start_keep_alive():
    """
    Start health server in a background daemon thread.
    Call this once from main() before app.run_polling().
    """
    thread = threading.Thread(target=_run_http_server, daemon=True)
    thread.start()
    logger.info("✅ Keep-alive thread started")
