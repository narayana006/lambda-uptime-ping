"""A small local web server to point the checker at.

    python examples/demo_server.py            # listens on http://127.0.0.1:8808

Paths:  /          200
        /slow      200 after 0.8 seconds
        /broken    503
        /redirect  302
"""

from __future__ import annotations

import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer


class DemoServer:
    def __init__(self, port: int = 8808) -> None:
        demo = self
        self.outage = False  # when True, every path answers 503

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self):
                status = 200
                if demo.outage or self.path == "/broken":
                    status = 503
                elif self.path == "/slow":
                    time.sleep(0.8)
                elif self.path == "/redirect":
                    status = 302
                self.send_response(status)
                if status == 302:
                    self.send_header("Location", "/")
                self.send_header("Content-Length", "0")
                self.end_headers()

            def log_message(self, *args):
                pass

        self.httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        self.port = self.httpd.server_address[1]

    def start(self) -> "DemoServer":
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8808
    server = DemoServer(port)
    print(f"demo server on http://127.0.0.1:{server.port} (Ctrl-C to stop)")
    try:
        server.httpd.serve_forever()
    except KeyboardInterrupt:
        pass
